"""Bounded Q1/G1 pilot. Development and one-time reused-test evaluation are separate."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

from castguard.data import attach_roles, check_features, digest, read_inputs, validate
from castguard.experiment import environment
from castguard.models import build_model
from castguard.storage import write_json
from experiment_integrity import capacity, budget_fraction, binary_labels, gate_inputs, identifiers, candidate_matrix

ROOT = Path(__file__).resolve().parent
FOLD_KEYS = ["scheme", "fold"]
TARGETS = ["Short_Shot", "Bubble", "Exfoliation", "Blow_Hole"]


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(root):
    files = [root / "oct03_research.py", root / "experiment_integrity.py", root / "configs/oct03_pilot.json", root / "configs/oct02.json",
             root / "reports/oct02/model_selection.csv", root / "reports/oct02/provenance.json"]
    files += list((root / "castguard").glob("*.py")) + list((root / "data/processed").glob("*"))
    return {"hashes": {p.relative_to(root).as_posix(): digest(p) for p in files if p.is_file()},
            "environment": environment()}


def read_configs(root):
    return tuple(json.loads((root / name).read_text(encoding="utf-8"))
                 for name in ["configs/oct03_pilot.json", "configs/oct02.json", "reports/oct02/provenance.json"])


def cached_prediction(root, provenance, dataset, scheme, fold, model, seed, role):
    experiment = "A" if dataset == "q42" else "Gate"
    task = dict(zip(["dataset", "population", "scheme", "fold", "experiment", "model", "seed"],
                    [dataset, "all", scheme, str(fold), experiment, model, int(seed)]))
    directory = root / provenance["cache"] / "__".join(map(str, task.values()))
    receipt = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
    if receipt["task"] != task or digest(directory / "predictions.parquet") != receipt["sha256"]["predictions.parquet"]:
        raise ValueError("Unverified baseline prediction cache")
    # Predicate filtering keeps test predictions out of development computations.
    pred = pq.read_table(directory / "predictions.parquet", filters=[("role", "=", role)]).to_pandas()
    if pred.empty or not pred.role.eq(role).all() or pred.row_id.duplicated().any():
        raise ValueError("Invalid cached role/IDs")
    return pred


def with_prediction(part, pred):
    if set(part.row_id) != set(pred.row_id) or pred.row_id.duplicated().any():
        raise ValueError("Prediction population does not equal fixed evaluation partition")
    return part.merge(pred[["row_id", "probability"]], on="row_id", validate="one_to_one")


def selected_baseline(selection, dataset, scheme, fold):
    rows = selection.loc[selection.selected & selection.dataset.eq(dataset) & selection.population.eq("all")
                         & selection.scheme.eq(scheme) & selection.fold.eq(str(fold))]
    if len(rows) != 1:
        raise ValueError("Expected exactly one baseline model for this population/fold")
    return str(rows.model.iloc[0])


def inspection_mask(row_ids, scores, budget):
    if np.asarray(row_ids).ndim!=1 or np.asarray(scores).ndim!=1:
        raise ValueError("Inspection arrays must be one-dimensional")
    identifiers(pd.Series(row_ids),'inspection row_id')
    ids, scores = np.asarray(row_ids, dtype=str), np.asarray(scores, dtype=float)
    if len(ids) != len(scores) or len(set(ids)) != len(ids) or not np.isfinite(scores).all():
        raise ValueError("Inspection requires unique IDs and finite aligned scores")
    k=capacity(len(ids),budget)
    mask = np.zeros(len(ids), dtype=bool)
    mask[np.lexsort((ids, -scores))[:k]] = True
    return mask


def inspection_metrics(frame, target, budget):
    if frame.empty:raise ValueError('Inspection metrics require a population')
    binary_labels(frame[target],target);binary_labels(frame.y_defect,'y_defect')
    selected = inspection_mask(frame.row_id, frame.probability, budget)
    n, k = len(frame), int(selected.sum())
    y, overall = frame[target].to_numpy(), frame.y_defect.to_numpy()
    positives, all_positives = int(y.sum()), int(overall.sum())
    capture = float(y[selected].sum() / positives) if positives else np.nan
    capture_all = float(overall[selected].sum() / all_positives) if all_positives else np.nan
    return {"n": n, "inspected": k, "actual_budget": k / n, "positive": positives,
            "captured": int(y[selected].sum()), "capture": capture, "miss_rate": 1 - capture,
            "lift": capture / (k / n) if k else np.nan,
            "overall_positive": all_positives, "overall_captured": int(overall[selected].sum()),
            "overall_capture": capture_all, "overall_miss_rate": 1 - capture_all,
            "average_precision": float(average_precision_score(y, frame.probability)) if 0 < positives < n else np.nan,
            "roc_auc": float(roc_auc_score(y, frame.probability)) if 0 < positives < n else np.nan}


def sample_support(q, folds, cfg):
    records = []
    for (scheme, fold), assignments in folds.loc[folds.dataset == "q42"].groupby(FOLD_KEYS):
        dev = assignments.loc[assignments.role.isin(["train", "validation"]), ["row_id", "role"]].merge(q, on="row_id", validate="one_to_one")
        for target in TARGETS:
            row = {"scheme": scheme, "fold": fold, "target": "y_type_" + target}
            row["eligible"] = True
            for role in ["train", "validation"]:
                labels = dev.loc[dev.role == role, row["target"]]
                positive, negative = int(labels.sum()), int(len(labels) - labels.sum())
                row.update({role + "_positive": positive, role + "_negative": negative, role + "_n": len(labels)})
                row["eligible"] &= min(positive, negative) >= cfg[role + "_min_per_class"]
            records.append(row)
    return pd.DataFrame(records)


def timeline_partition(q, m, folds, scheme, fold, role):
    """Restore missing-input rows without dropping fully unobservable episodes."""
    assignment = attach_roles(q, folds, "q42", scheme, fold)
    valid_runs = q.groupby("run_id").size().loc[lambda x: x >= 20].index
    if scheme != "within_run":
        runs = assignment.loc[assignment.role == role, "run_id"].unique()
        return m.loc[m.run_id.isin(runs)].copy()
    mask = pd.Series(False, index=m.index)
    for run in valid_runs:
        train_end = assignment.loc[(assignment.run_id == run) & (assignment.role == "train"), "Shot"].max()
        val_end = assignment.loc[(assignment.run_id == run) & (assignment.role == "validation"), "Shot"].max()
        mask |= m.run_id.eq(run) & (m.Shot.le(train_end) if role == "train" else
                 ((m.Shot.gt(train_end) & m.Shot.le(val_end)) if role == "validation" else m.Shot.gt(val_end)))
    return m.loc[mask].copy()


def gate_statistics(timeline, scores, threshold, disabled=False):
    gate_inputs(timeline,scores)
    if not disabled and (threshold is None or isinstance(threshold,(bool,np.bool_)) or not np.isfinite(threshold)):
        raise ValueError('Enabled Gate requires a finite threshold')
    if scores.row_id.duplicated().any() or not set(scores.row_id).issubset(set(timeline.row_id)):
        raise ValueError("Gate score coverage invalid")
    expected = set(timeline.loc[timeline.gate_eligible, "row_id"])
    if set(scores.row_id) != expected:
        raise ValueError("Gate predictions omit eligible rows or include ineligible rows")
    merged = timeline.merge(scores[["row_id", "probability"]], how="left", on="row_id", validate="one_to_one")
    available = merged.probability.notna()
    alarm = available & (merged.probability.ge(threshold) if not disabled else False)
    normal, warm = merged.Machine_Status.eq(0), merged.Machine_Status.eq(1)
    episodes, per_run = [], []
    for episode, rows in merged.loc[warm].groupby("episode_id"):
        hits = rows.loc[alarm.loc[rows.index]]
        observed = rows.probability.notna().any()
        episodes.append({"episode_id": episode, "run_id": int(rows.run_id.iloc[0]),
                         "total_shots": len(rows), "observable_shots": int(rows.probability.notna().sum()),
                         "observable": bool(observed), "detected": not hits.empty,
                         "delay_shots": int(hits.Shot.min() - rows.Shot.min()) if len(hits) else np.nan})
    for run, rows in merged.groupby("run_id"):
        denominator = int((available & normal).loc[rows.index].sum())
        false = int((alarm & normal).loc[rows.index].sum())
        per_run.append({"run_id": int(run), "normal": denominator, "false_alarms": false,
                        "fpr": false / denominator if denominator else np.nan})
    observed = sum(e["observable"] for e in episodes)
    detected = sum(e["detected"] for e in episodes)
    delays = [e["delay_shots"] for e in episodes if e["detected"]]
    normal_n, false_n = int((available & normal).sum()), int((alarm & normal).sum())
    result = {"n_timeline": len(timeline), "available": int(available.sum()), "held": int((~available).sum()),
              "normal": normal_n, "false_alarms": false_n, "fpr": false_n / normal_n if normal_n else np.nan,
              "worst_run_fpr": max(r["fpr"] for r in per_run) if per_run and all(np.isfinite(r['fpr']) for r in per_run) else np.nan,
              "warm_total": int(warm.sum()), "warm_observable": int((warm & available).sum()),
              "warm_detected": int((warm & alarm).sum()), "warm_passed": int((warm & available & ~alarm).sum()),
              "episodes_total": len(episodes), "episodes_observable": observed, "episodes_detected": detected,
              "episode_recall": detected / observed if observed else np.nan,
              "mean_delay": float(np.mean(delays)) if delays else np.nan,
              "delay_sum": sum(delays), "disabled": bool(disabled)}
    merged["alarm"] = alarm
    return result, episodes, per_run, merged


def constrained_threshold(timeline, scores, max_fpr, min_episodes=2):
    gate_inputs(timeline,scores)
    budget_fraction(max_fpr)
    if isinstance(min_episodes,(bool,np.bool_)) or not isinstance(min_episodes,(int,np.integer)) or min_episodes<1:
        raise ValueError('Minimum episodes must be a positive integer')
    merged = timeline.merge(scores, on="row_id", validate="one_to_one", how="inner")
    if not np.isfinite(merged.probability).all():
        raise ValueError("Gate scores must be finite")
    bounds = []
    for _, rows in merged.groupby("run_id"):
        negatives = np.sort(rows.loc[rows.Machine_Status.eq(0), "probability"].to_numpy())[::-1]
        if not len(negatives):
            return None, True, "normal_evidence_missing"
        allowed=capacity(len(negatives),max_fpr)
        bounds.append(float(np.nextafter(negatives[allowed],np.inf)) if allowed<len(negatives)
                      else float(merged.probability.min()))
    if merged.loc[merged.Machine_Status.eq(1), "episode_id"].nunique() < min_episodes:
        return None, True, "insufficient_validation_episodes"
    lower = max(bounds)
    if not np.isfinite(lower):return None,True,'no_detection_under_constraint'
    warm_scores = merged.loc[merged.Machine_Status.eq(1), "probability"].unique()
    candidates = sorted(set([lower] + [float(x) for x in warm_scores if x >= lower]))
    choices = []
    for threshold in candidates:
        result, _, per_run, _ = gate_statistics(timeline, scores, threshold)
        if any(not np.isfinite(r["fpr"]) or r["fpr"] > max_fpr + 1e-12 for r in per_run):
            continue
        choices.append(((-result["episodes_detected"], result["mean_delay"] if result["episodes_detected"] else np.inf,
                         -threshold), threshold, result))
    if not choices or min(choices, key=lambda x: x[0])[2]["episodes_detected"] == 0:
        return None, True, "no_detection_under_constraint"
    return min(choices, key=lambda x: x[0])[1], False, "eligible"


def train_rule(train, features):
    candidates = []
    for feature in sorted(features):
        values = train[feature].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            continue
        auc = roc_auc_score(train.Machine_Status.astype(int), values)
        for direction in [1, -1]:
            candidates.append((-(auc if direction == 1 else 1 - auc), feature, -direction))
    if not candidates:
        raise ValueError("No valid simple-rule features")
    negative_auc, feature, negative_direction = min(candidates)
    return {"feature": feature, "direction": -negative_direction, "train_auc": -negative_auc}


def rule_scores(part, rule):
    return pd.DataFrame({"row_id": part.row_id, "probability": part[rule["feature"]] * rule["direction"]})


def choose_q1_family(metrics,expected_models=None,expected_seeds=None,expected_budgets=None):
    if not metrics.role.eq("validation").all():
        raise ValueError("Model selection may use validation only")
    candidate_matrix(metrics,expected_models,expected_seeds,expected_budgets)
    if not np.isfinite(metrics[['capture','average_precision']].to_numpy(dtype=float)).all():
        raise ValueError('Missing candidate quality metric')
    grouped = metrics.loc[metrics.budget == .2].groupby("model", as_index=False).agg(
        capture=("capture", "mean"), ap=("average_precision", "mean"))
    return grouped.sort_values(["capture", "ap", "model"], ascending=[False, False, True]).model.iloc[0]


def choose_gate_family(records,expected_models=None,expected_seeds=None):
    frame = pd.DataFrame(records)
    if not frame.role.eq("validation").all():
        raise ValueError("Gate selection may use validation only")
    candidate_matrix(frame,expected_models,expected_seeds)
    grouped = frame.groupby("model", as_index=False).agg(recall=("episode_recall", "mean"),
        delay=("mean_delay", "mean"), threshold=("threshold", "mean"))
    return grouped.sort_values(["recall", "delay", "threshold", "model"],
                                ascending=[False, True, False, True], na_position="last").model.iloc[0]


def conditional_interval(paired, cfg):
    """Paired blocks of fixed selected-policy decisions, not independent five-seed trials."""
    grouped = paired.groupby(["row_id", "run_id", "Shot", "y"], as_index=False)[["special_inspect", "base_inspect"]].mean()
    grouped = grouped.sort_values(["run_id", "Shot", "row_id"]).reset_index(drop=True)
    y = grouped.y.to_numpy()
    contribution = y * (grouped.special_inspect - grouped.base_inspect).to_numpy()
    rng = np.random.default_rng(cfg["bootstrap_seed"])
    runs = [rows.index.to_numpy() for _, rows in grouped.groupby("run_id")]
    sampled = []
    for _ in range(cfg["bootstrap_repetitions"]):
        if len(runs) >= 2:
            idx = np.concatenate([runs[i] for i in rng.integers(0, len(runs), len(runs))])
        else:
            n, block = len(grouped), min(cfg["bootstrap_block_shots"], len(grouped))
            starts = rng.integers(0, n - block + 1, int(np.ceil(n / block)))
            idx = np.concatenate([np.arange(start, start + block) for start in starts])[:n]
        if y[idx].sum():
            sampled.append(contribution[idx].sum() / y[idx].sum())
    interval = np.quantile(sampled, [.025, .975]) if sampled else [np.nan, np.nan]
    return {"lower95": interval[0], "upper95": interval[1], "valid_bootstraps": len(sampled),
            "resampling": "run_blocks" if len(runs) >= 2 else "moving_20_row_blocks",
            "scope": "conditional_validation_selected_policy_not_independent_confirmation"}


def q1_decision(comparison, intervals, cfg):
    if 'role' not in comparison or comparison.empty or not comparison.role.eq('validation').all():
        raise ValueError('Development decision requires validation metrics only')
    required=['gain','capture','actual_budget','overall_gain']
    if not np.isfinite(comparison[required].to_numpy(dtype=float)).all():
        raise ValueError('Development decision cannot silently omit missing metrics')
    means = comparison.loc[comparison.budget == .2].groupby(FOLD_KEYS, as_index=False).agg(
        gain=("gain", "mean"), capture=("capture", "mean"), random_capture=("actual_budget", "mean"),
        overall_gain=("overall_gain", "mean"))
    forward = means.loc[means.scheme == "forward_run"]
    passed = (len(forward) >= cfg["q1_min_forward_folds"] and means.gain.mean() >= cfg["q1_min_gain"]
              and forward.gain.mean() >= cfg["q1_min_gain"] and forward.gain.ge(0).all()
              and means.capture.mean() > means.random_capture.mean()
              and forward.capture.mean() > forward.random_capture.mean())
    fw_ci = intervals.loc[intervals.scheme == "forward_run"]
    strong = passed and len(fw_ci) >= 2 and fw_ci.lower95.gt(0).all()
    return {"numeric_development_gate_passed": bool(passed), "status": "development_support" if strong else
            ("partial_evidence" if passed else "failed_development_gate"), "eligible_forward_folds": len(forward),
            "mean_validation_gain": means.gain.mean(), "mean_forward_validation_gain": forward.gain.mean(),
            "forward_nonnegative": bool(forward.gain.ge(0).all()), "test_allowed": bool(passed),
            "warning": "Validation used for selection; historical test already seen. No independent confirmation."}, means


def develop(root, out):
    cfg, base_cfg, provenance = read_configs(root)
    if out.exists():
        raise ValueError("Development output already exists; choose a new empty run path")
    out.mkdir(parents=True)
    write_json(out / "run_status.json", {"status": "running", "started_at": now(), "stage": "development"})
    original_identity = identity(root)
    write_json(out / "registration.json", {"registered_at": now(), "config": cfg, "identity": original_identity,
                                           "test_opened": False})
    try:
        validate(root)
        frames, folds, contract = read_inputs(root)
        q, m = frames["q42"], frames["m41"]
        support = sample_support(q, folds, cfg)
        support.to_csv(out / "sample_support.csv", index=False)
        eligible = support.loc[support.target.eq(cfg["target"]) & support.eligible]
        chosen_old = pd.read_csv(root / "reports/oct02/model_selection.csv", dtype={"fold": str})
        features = contract[cfg["q1_features"]]
        check_features(features, contract)
        metrics, q_predictions, q_choices, paired_frames = [], [], [], []
        fits = 0
        for row in eligible.itertuples(index=False):
            scheme, fold = row.scheme, row.fold
            part = attach_roles(q, folds, "q42", scheme, fold)
            train, val = part.loc[part.role == "train"], part.loc[part.role == "validation"]
            baseline = selected_baseline(chosen_old, "q42", scheme, fold)
            for model_name in cfg["q1_models"]:
                for seed in cfg["seeds"]:
                    model = build_model(model_name, seed, base_cfg["models"][model_name])
                    with threadpool_limits(limits=1):
                        model.fit(train[features], train[cfg["target"]].astype(int))
                        probability = model.predict_proba(val[features])[:, 1]
                    key = f"{scheme}__{fold}__{model_name}__{seed}"
                    artifact = out / "models" / (key + ".joblib")
                    artifact.parent.mkdir(exist_ok=True)
                    joblib.dump({"pipeline": model, "features": features, "target": cfg["target"],
                                 "scheme": scheme, "fold": fold, "seed": seed}, artifact, compress=3)
                    result = val.copy()
                    result["probability"] = probability
                    meta = {"scheme": scheme, "fold": fold, "model": model_name, "seed": seed,
                            "variant": "specialist", "role": "validation"}
                    for budget in cfg["budgets"]:
                        metrics.append({**meta, "budget": budget, **inspection_metrics(result, cfg["target"], budget)})
                    pred = result[["row_id", "run_id", "Shot", cfg["target"], "y_defect", "Product_Type", "probability"]].copy()
                    q_predictions.append(pred.assign(**meta))
                    fits += 1
            family = choose_q1_family(pd.DataFrame([r for r in metrics if r["scheme"] == scheme and r["fold"] == fold]),
                cfg['q1_models'],cfg['seeds'],cfg['budgets'])
            q_choices.append({"scheme": scheme, "fold": fold, "model": family, "baseline_model": baseline})
            for seed in cfg["seeds"]:
                old = cached_prediction(root, provenance, "q42", scheme, fold, baseline, seed, "validation")
                result = with_prediction(val, old)
                meta = {"scheme": scheme, "fold": fold, "model": baseline, "seed": seed,
                        "variant": "baseline", "role": "validation"}
                for budget in cfg["budgets"]:
                    metrics.append({**meta, "budget": budget, **inspection_metrics(result, cfg["target"], budget)})
                q_predictions.append(result[["row_id", "run_id", "Shot", cfg["target"], "y_defect", "Product_Type", "probability"]].assign(**meta))
                specialist = next(p for p in q_predictions if p.model.iloc[0] == family and p.variant.iloc[0] == "specialist"
                                  and p.scheme.iloc[0] == scheme and p.fold.iloc[0] == fold and p.seed.iloc[0] == seed)
                ordered = specialist.set_index("row_id").loc[result.row_id]
                paired_frames.append(result[["row_id", "run_id", "Shot"]].assign(scheme=scheme, fold=fold, seed=seed,
                    y=result[cfg["target"]].to_numpy(), base_inspect=inspection_mask(result.row_id, result.probability, .2),
                    special_inspect=inspection_mask(result.row_id, ordered.probability, .2)))
            print(f"Q1 {scheme}/{fold}: {fits}/{len(eligible)*10} fits; selected {family}", flush=True)
        metric_frame = pd.DataFrame(metrics)
        metric_frame.to_csv(out / "q1_candidate_validation.csv", index=False)
        predictions = pd.concat(q_predictions, ignore_index=True)
        predictions.to_parquet(out / "q1_validation_predictions.parquet", index=False)
        paired = pd.concat(paired_frames, ignore_index=True)
        paired.to_parquet(out / "q1_paired_inspections.parquet", index=False)
        ci = pd.DataFrame([{**dict(zip(FOLD_KEYS, key)), **conditional_interval(group, cfg)}
                           for key, group in paired.groupby(FOLD_KEYS)])
        ci.to_csv(out / "q1_conditional_intervals.csv", index=False)
        selection = pd.DataFrame(q_choices)
        selected = metric_frame.merge(selection.rename(columns={"model": "selected_model"}), on=FOLD_KEYS, validate="many_to_one")
        special = selected.loc[selected.variant.eq("specialist") & selected.model.eq(selected.selected_model)]
        baseline = selected.loc[selected.variant.eq("baseline")]
        compare = special.merge(baseline[FOLD_KEYS + ["seed", "budget", "capture", "overall_capture"]],
                                on=FOLD_KEYS + ["seed", "budget"], suffixes=("", "_base"), validate="one_to_one")
        compare["gain"], compare["overall_gain"] = compare.capture - compare.capture_base, compare.overall_capture - compare.overall_capture_base
        compare.to_csv(out / "q1_comparison.csv", index=False)
        qdecision, fold_means = q1_decision(compare, ci, cfg)
        fold_means.to_csv(out / "q1_fold_summary.csv", index=False)

        gate_candidates, gate_choices, gate_prediction_frames, gate_episode_rows, gate_run_rows = [], [], [], [], []
        for scheme, fold in folds.loc[folds.dataset == "m41", FOLD_KEYS].drop_duplicates().itertuples(index=False, name=None):
            part = attach_roles(m, folds, "m41", scheme, fold)
            train, val = part.loc[part.role == "train"], part.loc[part.role == "validation"]
            timeline = timeline_partition(q, m, folds, scheme, fold, "validation")
            baseline = selected_baseline(chosen_old, "m41", scheme, fold)
            candidate_records, frozen_candidates, cached = [], {}, {}
            for model_name in base_cfg["models"]:
                for seed in cfg["seeds"]:
                    pred = cached_prediction(root, provenance, "m41", scheme, fold, model_name, seed, "validation")
                    scores = with_prediction(val, pred)[["row_id", "probability"]]
                    cached[model_name, seed] = (scores, float(pred.threshold.iloc[0]))
                    threshold, disabled, reason = constrained_threshold(timeline, scores, cfg["gate_fpr"], cfg["gate_min_validation_episodes"])
                    result, _, _, _ = gate_statistics(timeline, scores, threshold, disabled)
                    meta = {"scheme": scheme, "fold": fold, "model": model_name, "seed": seed,
                            "role": "validation", "policy": "constrained", "threshold": threshold, "reason": reason}
                    candidate_records.append({**meta, **result})
                    frozen_candidates[model_name, seed] = {**meta, "disabled": disabled}
            family = choose_gate_family(candidate_records,list(base_cfg['models']),cfg['seeds'])
            gate_candidates.extend(candidate_records)
            rule = train_rule(train, contract["q42_A0"])
            raw_scores = rule_scores(val, rule)
            rt, rd, rr = constrained_threshold(timeline, raw_scores, cfg["gate_fpr"], cfg["gate_min_validation_episodes"])
            for seed in cfg["seeds"]:
                frozen = [frozen_candidates[family, seed], {"scheme": scheme, "fold": fold, "model": baseline, "seed": seed,
                    "policy": "baseline", "threshold": cached[baseline, seed][1], "disabled": False},
                    {"scheme": scheme, "fold": fold, "model": "simple_rule", "seed": seed,
                     "policy": "simple_rule", "threshold": rt, "disabled": rd, "reason": rr, "rule": rule}]
                for choice in frozen:
                    choice["role"] = "validation"
                    gate_choices.append(choice)
                    scores = raw_scores if choice["policy"] == "simple_rule" else cached[choice["model"], seed][0]
                    stats, eps, runs, pred = gate_statistics(timeline, scores, choice["threshold"], choice["disabled"])
                    meta = {k: choice[k] for k in ["scheme", "fold", "model", "seed", "policy", "role", "threshold"]}
                    gate_prediction_frames.append(pred.assign(**meta))
                    gate_episode_rows.extend([{**meta, **e} for e in eps])
                    gate_run_rows.extend([{**meta, **r} for r in runs])
                    if choice["policy"] != "constrained":
                        gate_candidates.append({**meta, **stats})
            print(f"G1 {scheme}/{fold}: selected {family}; train rule {rule['feature']} direction {rule['direction']}", flush=True)
        gm = pd.DataFrame(gate_candidates)
        gm.to_csv(out / "g1_candidate_validation.csv", index=False)
        frozen_frame = pd.DataFrame(gate_choices)
        selected_gm = gm.merge(frozen_frame[FOLD_KEYS + ["seed", "policy", "model"]], on=FOLD_KEYS + ["seed", "policy", "model"], validate="one_to_one")
        selected_gm.to_csv(out / "g1_selected_validation.csv", index=False)
        pd.concat(gate_prediction_frames, ignore_index=True).to_parquet(out / "g1_validation_predictions.parquet", index=False)
        pd.DataFrame(gate_episode_rows).to_csv(out / "g1_validation_episodes.csv", index=False)
        pd.DataFrame(gate_run_rows).to_csv(out / "g1_validation_runs.csv", index=False)
        write_json(out / "selection.json", {"frozen_at": now(), "q1": q_choices, "q1_decision": qdecision,
                    "g1": gate_choices, "config": cfg, "test_used": False})
        if identity(root) != original_identity:
            raise ValueError("Inputs/code changed during development")
        write_json(out / "run_status.json", {"status": "complete", "stage": "development", "finished_at": now(),
                   "q1_fits": fits, "g1_cached_candidates": 220, "test_opened": False})
        hashes = {p.relative_to(out).as_posix(): digest(p) for p in out.rglob("*") if p.is_file()}
        write_json(out / "manifest.json", {"identity": original_identity, "outputs": hashes})
        print(json.dumps(qdecision, default=str), flush=True)
    except BaseException as exc:
        write_json(out / "run_status.json", {"status": "failed", "stage": "development", "error": str(exc), "time": now()})
        raise


def verify_development(root, out, allow_historical=False):
    receipt = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if allow_historical:
        from historical_sources import resolve_historical_source
        if receipt['identity']['environment']!=environment():
            raise ValueError('Environment differs from frozen development')
        for name,expected in receipt['identity']['hashes'].items():
            resolve_historical_source(root,name,expected)
    elif receipt["identity"] != identity(root):
        raise ValueError("Source/config/input/environment changed since selection")
    if any(digest(out / name) != expected for name, expected in receipt["outputs"].items()):
        raise ValueError("Development outputs changed after selection")
    return json.loads((out / "selection.json").read_text(encoding="utf-8"))


def evaluate(root, out):
    frozen = verify_development(root, out)
    test_out = out / "reused_test"
    if test_out.exists():
        raise ValueError("Reused-test evaluation has already been attempted; refusing a repeated evaluation")
    test_out.mkdir()
    write_json(test_out / "run_status.json", {"status": "running", "started_at": now(), "selection_sha256": digest(out / "selection.json")})
    try:
        cfg, base_cfg, provenance = read_configs(root)
        frames, folds, _ = read_inputs(root)
        q, m = frames["q42"], frames["m41"]
        qm, qp, gm, gp, ge, gr = [], [], [], [], [], []
        if frozen["q1_decision"]["test_allowed"]:
            for choice in frozen["q1"]:
                scheme, fold = choice["scheme"], choice["fold"]
                frame = attach_roles(q, folds, "q42", scheme, fold)
                part = frame.loc[frame.role == "test"]
                for seed in cfg["seeds"]:
                    name = f"{scheme}__{fold}__{choice['model']}__{seed}.joblib"
                    artifact = joblib.load(out / "models" / name)
                    with threadpool_limits(limits=1):
                        probability = artifact["pipeline"].predict_proba(part[artifact["features"]])[:, 1]
                    base = cached_prediction(root, provenance, "q42", scheme, fold, choice["baseline_model"], seed, "test")
                    baseline = with_prediction(part, base)
                    for variant, evaluated, model in [("specialist", part.assign(probability=probability), choice["model"]),
                                                      ("baseline", baseline, choice["baseline_model"])]:
                        meta = {"scheme": scheme, "fold": fold, "seed": seed, "model": model, "variant": variant, "role": "test"}
                        for budget in cfg["budgets"]:
                            qm.append({**meta, "budget": budget, **inspection_metrics(evaluated, cfg["target"], budget)})
                        qp.append(evaluated[["row_id", "run_id", "Shot", cfg["target"], "y_defect", "Product_Type", "probability"]].assign(**meta))
            pd.DataFrame(qm).to_csv(test_out / "q1_metrics.csv", index=False)
            pd.concat(qp, ignore_index=True).to_parquet(test_out / "q1_predictions.parquet", index=False)
        for choice in frozen["g1"]:
            scheme, fold = choice["scheme"], choice["fold"]
            frame = attach_roles(m, folds, "m41", scheme, fold)
            part = frame.loc[frame.role == "test"]
            timeline = timeline_partition(q, m, folds, scheme, fold, "test")
            if choice["policy"] == "simple_rule":
                scores = rule_scores(part, choice["rule"])
            else:
                pred = cached_prediction(root, provenance, "m41", scheme, fold, choice["model"], choice["seed"], "test")
                scores = with_prediction(part, pred)[["row_id", "probability"]]
            stats, episodes, runs, predictions = gate_statistics(timeline, scores, choice["threshold"], choice["disabled"])
            meta = {k: choice[k] for k in ["scheme", "fold", "seed", "model", "policy", "threshold"]}
            meta["role"] = "test"
            gm.append({**meta, **stats})
            ge.extend([{**meta, **e} for e in episodes])
            gr.extend([{**meta, **r} for r in runs])
            gp.append(predictions.assign(**meta))
        gate_metrics = pd.DataFrame(gm)
        gate_metrics.to_csv(test_out / "g1_metrics.csv", index=False)
        pd.DataFrame(ge).to_csv(test_out / "g1_episodes.csv", index=False)
        pd.DataFrame(gr).to_csv(test_out / "g1_runs.csv", index=False)
        pd.concat(gp, ignore_index=True).to_parquet(test_out / "g1_predictions.parquet", index=False)
        totals = gate_metrics.loc[gate_metrics.scheme == "run_holdout"].groupby(["policy", "seed"], as_index=False).agg(
            normal=("normal", "sum"), false_alarms=("false_alarms", "sum"), total=("episodes_total", "sum"),
            observable=("episodes_observable", "sum"), detected=("episodes_detected", "sum"),
            delay_sum=("delay_sum", "sum"), worst_run_fpr=("fpr", "max"), held=("held", "sum"))
        totals["pooled_fpr"] = totals.false_alarms / totals.normal
        totals["mean_delay"] = totals.delay_sum / totals.detected
        totals["minimum_goal"] = totals.pooled_fpr.le(.02) & totals.detected.ge(16) & totals.observable.eq(20)
        totals["stretch_goal"] = totals.minimum_goal & totals.detected.ge(18) & totals.mean_delay.le(3)
        totals["all_runs_fpr_limit"] = totals.worst_run_fpr.le(.02)
        totals.to_csv(test_out / "g1_run_holdout_totals.csv", index=False)
        write_json(test_out / "run_status.json", {"status": "complete", "finished_at": now(), "test_is_reused": True,
                   "q1_evaluated": bool(qm), "g1_evaluated": True, "selection_sha256": digest(out / "selection.json")})
        write_json(test_out / "manifest.json", {"outputs": {p.relative_to(test_out).as_posix(): digest(p)
                    for p in test_out.rglob("*") if p.is_file()}, "development_manifest": digest(out / "manifest.json")})
        print(totals.to_string(index=False), flush=True)
    except BaseException as exc:
        write_json(test_out / "run_status.json", {"status": "failed", "error": str(exc), "time": now()})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["develop", "evaluate", "verify"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("reports/oct03_pilot"))
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.output.resolve() if args.output.is_absolute() else root / args.output
    if args.command == "develop":
        develop(root, out)
    elif args.command == "evaluate":
        evaluate(root, out)
    else:
        frozen = verify_development(root, out, allow_historical=True)
        print(json.dumps({"verified": True, "q1_decision": frozen["q1_decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
