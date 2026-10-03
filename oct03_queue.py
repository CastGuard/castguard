"""Nested development comparison of OOD referral and causal inspection queues."""
import argparse
from datetime import datetime, timezone
import heapq
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score
from threadpoolctl import threadpool_limits

from castguard.data import attach_roles, check_features, digest, read_inputs, validate
from castguard.models import build_model
from castguard.storage import write_json
from oct03_research import constrained_threshold, gate_statistics
from experiment_integrity import capacity, budget_fraction, binary_labels, boolean_values, identifiers, queue_accounting, candidate_matrix

ROOT = Path(__file__).resolve().parent
POLICIES = ["Q", "GQ", "OOD1", "OOD05"]


def nested_parts(qtrain, mtrain, fraction):
    runs = sorted(qtrain.run_id.unique())
    if len(runs) >= 2:
        last = runs[-1]
        fit_q, cal_q = qtrain.loc[qtrain.run_id < last], qtrain.loc[qtrain.run_id == last]
        fit_m, cal_m = mtrain.loc[mtrain.run_id < last], mtrain.loc[mtrain.run_id == last]
        boundary = {"kind": "last_training_run", "calibration_run": int(last)}
    else:
        ordered = qtrain.sort_values("source_row")
        cut = int(ordered.Shot.iloc[int(np.floor(len(ordered) * fraction)) - 1])
        for _, episode in mtrain.dropna(subset=["episode_id"]).groupby("episode_id"):
            if episode.Shot.min() <= cut < episode.Shot.max():
                cut = int(episode.Shot.min()) - 1
        fit_q, cal_q = qtrain.loc[qtrain.Shot <= cut], qtrain.loc[qtrain.Shot > cut]
        fit_m, cal_m = mtrain.loc[mtrain.Shot <= cut], mtrain.loc[mtrain.Shot > cut]
        boundary = {"kind": "single_run_time_cut", "last_fit_shot": cut}
    assert set(fit_q.row_id).isdisjoint(set(cal_q.row_id))
    assert set(fit_m.row_id).isdisjoint(set(cal_m.row_id))
    assert set(fit_m.episode_id.dropna()).isdisjoint(set(cal_m.episode_id.dropna()))
    assert fit_m.source_row.max() < cal_m.source_row.min()
    return fit_q.copy(), cal_q.copy(), fit_m.copy(), cal_m.copy(), boundary


def fit_ood(frame, features, quantiles):
    normal = frame.loc[frame.Machine_Status.eq(0)].dropna(subset=features)
    low, high = normal[features].quantile(quantiles).to_numpy()
    iqr = (normal[features].quantile(.75) - normal[features].quantile(.25)).to_numpy()
    ranges = (normal[features].max() - normal[features].min()).to_numpy()
    scale = np.where(iqr > 0, iqr, np.where(ranges > 0, ranges, 1.0))
    return {"features": features, "low": low.tolist(), "high": high.tolist(), "scale": scale.tolist()}


def ood_scores(frame, detector):
    values = frame[detector["features"]].to_numpy(dtype=float)
    complete = np.isfinite(values).all(axis=1)
    result = np.full(len(frame), np.nan)
    distances = np.maximum(np.asarray(detector["low"]) - values[complete],
                           values[complete] - np.asarray(detector["high"]))
    result[complete] = np.maximum(distances / detector["scale"], 0).max(axis=1)
    return result


def ood_threshold(calibration, scores, allowance):
    values = np.sort(np.asarray(scores)[calibration.Machine_Status.eq(0) & np.isfinite(scores)])[::-1]
    if not len(values):
        raise ValueError("Cannot calibrate OOD threshold without normal evidence")
    return float(np.nextafter(values[int(np.floor(len(values) * allowance))], np.inf))


def stream_queue(scores, policy, gate_threshold, gate_disabled, domain_threshold, budget):
    """Inputs contain observations and scores only; never read labels or future rows."""
    ratio=budget_fraction(budget,allow_zero=False)
    if not isinstance(gate_disabled,(bool,np.bool_)):raise ValueError('Gate disabled flag must be boolean')
    if policy not in POLICIES:raise ValueError('Unknown inspection policy')
    identifiers(scores.row_id,'queue row_id')
    boolean_values(scores.process_complete,'process_complete')
    if not np.isfinite(scores.source_row).all() or scores.source_row.duplicated().any():
        raise ValueError('Queue arrival order must be finite and unique')
    if np.isinf(scores.quality_probability).any():raise ValueError('Infinite quality score')
    available=scores.process_complete
    if not gate_disabled and policy!='Q':
        if gate_threshold is None or not np.isfinite(gate_threshold) or not np.isfinite(scores.loc[available,'gate_probability']).all():
            raise ValueError('Active Gate requires finite scores and threshold')
    if policy.startswith('OOD'):
        if domain_threshold is None or not np.isfinite(domain_threshold) or not np.isfinite(scores.loc[available,'ood_score']).all():
            raise ValueError('Active OOD requires finite scores and threshold')
    rows = scores.sort_values(["source_row", "row_id"]).reset_index(drop=True).copy()
    if rows.row_id.duplicated().any() or rows.run_id.nunique() != 1:
        raise ValueError("Queue requires one run and unique records")
    complete = rows.process_complete.to_numpy(dtype=bool)
    ood = (complete & rows.ood_score.ge(domain_threshold).to_numpy()) if policy.startswith("OOD") else np.zeros(len(rows), bool)
    hold = ~complete | ood
    raw_gate = (complete & rows.gate_probability.ge(gate_threshold).to_numpy()) if not gate_disabled else np.zeros(len(rows), bool)
    alarm = raw_gate & ~hold & (policy != "Q")
    inspected = np.zeros(len(rows), bool)
    service_step = np.full(len(rows), -1, dtype=int)
    service_shot = np.full(len(rows), np.nan)
    reasons = np.full(len(rows), "none", dtype=object)
    queue = []
    for i, row in enumerate(rows.itertuples(index=False)):
        if hold[i]:
            key, reasons[i] = (0, 0.0, i, row.row_id, i), "hold"
        elif alarm[i]:
            key, reasons[i] = (1, -float(row.gate_probability), i, row.row_id, i), "gate"
        elif np.isfinite(row.quality_probability):
            key, reasons[i] = (2, -float(row.quality_probability), i, row.row_id, i), "quality"
        else:
            key = None
        if key is not None:
            heapq.heappush(queue, key)
        # Unused past service slots are not banked or used in a future burst.
        slots = (i+1)*ratio.numerator//ratio.denominator-i*ratio.numerator//ratio.denominator
        for _ in range(slots):
            if queue:
                index = heapq.heappop(queue)[-1]
                inspected[index], service_step[index], service_shot[index] = True, i, row.Shot
    rows["ood"] = ood
    rows["hold"] = hold
    rows["alarm"] = alarm
    rows["raw_gate_alarm"] = raw_gate
    rows["inspected"] = inspected
    rows["reason"] = reasons
    rows["arrival_step"] = np.arange(len(rows))
    rows["service_step"] = service_step
    rows["service_shot"] = service_shot
    rows["wait_records"] = np.where(inspected, service_step - rows.arrival_step.to_numpy(), np.nan)
    rows["wait_shots"] = service_shot - rows.Shot
    assert inspected.sum() <= capacity(len(rows),budget)
    assert np.all(service_step[inspected] >= np.flatnonzero(inspected))
    return rows


def measure(actions, truth, quality_truth, budget):
    identifiers(actions.row_id,'action row_id');identifiers(truth.row_id,'state truth row_id')
    if not set(actions.row_id).issubset(set(truth.row_id)):
        raise ValueError('Missing state truth rows would silently shrink the production denominator')
    identity_columns=['run_id','Shot','source_row']
    if not set(identity_columns).issubset(truth.columns):
        raise ValueError('State truth must provide the original action identity')
    aligned=truth.set_index('row_id').loc[actions.row_id]
    for name in identity_columns:
        if aligned[name].isna().any() or not np.array_equal(actions[name].to_numpy(),aligned[name].to_numpy()):
            raise ValueError('Action identity disagrees with source truth: '+name)
    binary_labels(truth.Machine_Status,'Machine_Status',allow_missing=True)
    binary_labels(quality_truth.y_defect,'y_defect',allow_missing=True)
    for name in ['inspected','alarm','hold','ood','process_complete']:boolean_values(actions[name],name)
    if int(actions.inspected.sum())>capacity(len(actions),budget):
        raise ValueError('Actions exceed the declared inspection budget')
    queue_accounting(actions,budget)
    frame = actions.merge(truth[["row_id", "Machine_Status", "episode_id"]], on="row_id", how='left', validate="one_to_one")
    frame = frame.merge(quality_truth[["run_id", "Shot", "y_defect"]], on=["run_id", "Shot"], how="left", validate="one_to_one")
    normal, warm = frame.Machine_Status.eq(0), frame.Machine_Status.eq(1)
    known_quality = frame.y_defect.notna()
    quality_positive = frame.y_defect.eq(1)
    intervened = frame.alarm | frame.hold
    normal_n, observed_normal = int(normal.sum()), int((normal & frame.process_complete).sum())
    alarm_false = int((normal & frame.alarm).sum())
    episodes = []
    for episode, rows in frame.loc[warm].groupby("episode_id"):
        alarms = rows.loc[rows.alarm]
        inspected = rows.loc[rows.inspected]
        episodes.append({"episode_id": episode, "observable": bool(rows.process_complete.any()),
            "auto_detected": bool(len(alarms)), "inspection_reached": bool(len(inspected)),
            "auto_delay_records": int(alarms.arrival_step.min() - rows.arrival_step.min()) if len(alarms) else np.nan,
            "auto_delay_shots": float(alarms.Shot.min() - rows.Shot.min()) if len(alarms) else np.nan,
            "inspection_delay_records": int(inspected.service_step.min() - rows.arrival_step.min()) if len(inspected) else np.nan,
            "inspection_delay_shots": float(inspected.service_shot.min() - rows.Shot.min()) if len(inspected) else np.nan})
    eps = pd.DataFrame(episodes)
    denom = int(quality_positive.sum())
    result = {"n_total": len(frame), "normal_total": normal_n, "normal_observable": observed_normal,
        "warm_total": int(warm.sum()), "state_unknown": int(frame.Machine_Status.isna().sum()),
        "sensor_missing": int((~frame.process_complete).sum()),
        "auto_false_alarms": alarm_false, "auto_fpr_all_normal": alarm_false / normal_n if normal_n else np.nan,
        "auto_fpr_observed_normal": alarm_false / observed_normal if observed_normal else np.nan,
        "normal_alarm_or_hold": int((normal & intervened).sum()),
        "normal_intervention_rate": float((normal & intervened).sum() / normal_n) if normal_n else np.nan,
        "coverage": float((frame.process_complete & ~frame.ood).mean()), "ood_count": int(frame.ood.sum()),
        "hold_requested": int(frame.hold.sum()), "hold_rate": frame.hold.mean(),
        "hold_served": int((frame.hold & frame.inspected).sum()),
        "hold_backlog": int((frame.hold & ~frame.inspected).sum()),
        "inspection_capacity": capacity(len(frame),budget), "inspected": int(frame.inspected.sum()),
        "inspection_rate": frame.inspected.mean(), "quality_known": int(known_quality.sum()),
        "quality_positive": denom, "quality_captured": int((quality_positive & frame.inspected).sum()),
        "quality_capture": float((quality_positive & frame.inspected).sum() / denom) if denom else np.nan,
        "quality_inspected": int((known_quality & frame.inspected).sum()),
        "quality_missing_inspected": int((~known_quality & frame.inspected).sum()),
        "mean_queue_wait_records": frame.loc[frame.inspected, "wait_records"].mean(),
        "max_queue_wait_records": frame.loc[frame.inspected, "wait_records"].max(),
        "episodes_total": len(eps), "episodes_observable": int(eps.observable.sum()) if len(eps) else 0,
        "episodes_auto_detected": int(eps.auto_detected.sum()) if len(eps) else 0,
        "episodes_inspection_reached": int(eps.inspection_reached.sum()) if len(eps) else 0,
        "auto_episode_recall_total": eps.auto_detected.mean() if len(eps) else np.nan,
        "inspection_episode_reach_total": eps.inspection_reached.mean() if len(eps) else np.nan,
        "auto_mean_delay_records": eps.auto_delay_records.mean() if len(eps) else np.nan,
        "inspection_mean_delay_records": eps.inspection_delay_records.mean() if len(eps) else np.nan}
    for minutes in [1, 3, 5]:
        result[f"inspection_hours_at_{minutes}min"] = result["inspected"] * minutes / 60
        result[f"backlog_hours_at_{minutes}min"] = result["hold_backlog"] * minutes / 60
    return result, frame, episodes


def choose_policy(metrics,expected_seeds=None,expected_budgets=None):
    if metrics.empty or not metrics.stage.eq("inner_calibration").all():
        raise ValueError("Policy selection requires inner calibration only")
    policies={'GQ','OOD1','OOD05'}|({'Q'} if metrics.policy.eq('Q').any() else set())
    candidate_matrix(metrics.rename(columns={'policy':'model'}),policies,expected_seeds,expected_budgets)
    if 'fold' in metrics and metrics.fold.nunique(dropna=False)!=1:
        raise ValueError('Queue policy selection must use one calibration fold')
    for name in ['n_total','quality_known','quality_positive','normal_total','normal_observable','warm_total','state_unknown','episodes_total']:
        if name in metrics and metrics[name].nunique(dropna=False)!=1:
            raise ValueError('Queue candidate population differs: '+name)
    scored=metrics.loc[metrics.budget.eq(.2)&metrics.policy.ne('Q')]
    fields=['quality_capture','hold_backlog','episodes_inspection_reached','hold_requested']
    if scored.empty or not np.isfinite(scored[fields].to_numpy(dtype=float)).all():
        raise ValueError('Queue selection requires finite complete comparison metrics')
    grouped = metrics.loc[metrics.budget.eq(.2) & metrics.policy.ne("Q")].groupby("policy").mean(numeric_only=True)
    baseline = grouped.loc["GQ"]
    feasible = grouped.loc[grouped.hold_backlog.le(baseline.hold_backlog + 1e-12)
        & grouped.episodes_inspection_reached.ge(baseline.episodes_inspection_reached - 1e-12)].reset_index()
    return feasible.sort_values(["quality_capture", "hold_requested", "policy"], ascending=[False, True, True], na_position="last").policy.iloc[0]


def combined_scores(mpart, qpart, quality_model, gate_model, features_q, features_g, detector):
    frame = mpart.sort_values("source_row").copy()
    frame["process_complete"] = frame[detector["features"]].notna().all(axis=1)
    frame["gate_probability"] = np.nan
    with threadpool_limits(limits=1):
        available = frame.process_complete
        frame.loc[available, "gate_probability"] = gate_model.predict_proba(frame.loc[available, features_g])[:, 1]
        qscore = quality_model.predict_proba(qpart[features_q])[:, 1]
    qpred = qpart[["run_id", "Shot"]].assign(quality_probability=qscore)
    frame = frame.merge(qpred, on=["run_id", "Shot"], how="left", validate="one_to_one")
    frame["ood_score"] = ood_scores(frame, detector)
    # Labels are deliberately omitted from the entire queue input surface.
    return frame[["row_id", "source_row", "run_id", "Shot", "process_complete", "gate_probability", "quality_probability", "ood_score"]]


def make_identity(root):
    files = [root / "oct03_queue.py", root / "oct03_research.py", root / "experiment_integrity.py", root / "configs/oct03_queue.json", root / "configs/oct02.json"]
    files += list((root / "castguard").glob("*.py")) + list((root / "data/processed").glob("*"))
    return {p.relative_to(root).as_posix(): digest(p) for p in files if p.is_file()}


def run(root, out):
    if out.exists():
        raise ValueError("Refusing to reuse a run directory")
    out.mkdir(parents=True)
    cfg = json.loads((root / "configs/oct03_queue.json").read_text(encoding="utf-8"))
    base_cfg = json.loads((root / "configs/oct02.json").read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat()
    identity = make_identity(root)
    write_json(out / "registration.json", {"started_at": started, "config": cfg, "input_hashes": identity,
        "scope": "historically_seen_nested_development_not_independent_validation"})
    write_json(out / "status.json", {"status": "running", "stage": "inner_fit"})
    try:
        validate(root)
        frames, folds, contract = read_inputs(root)
        q, m = frames["q42"], frames["m41"]
        fq, fg = contract["q42_A"], contract["m41_gate"]
        check_features(fq, contract)
        check_features(fg, contract)
        splits, model_rows, inner_metrics, inner_actions, inner_episodes, frozen, contexts = [], [], [], [], [], [], {}
        models, fitted, candidate_predictions = {}, 0, []
        (out / "models").mkdir()
        for fold in cfg["outer_folds"]:
            qassigned = attach_roles(q, folds, "q42", "forward_run", fold)
            trainq = qassigned.loc[qassigned.role == "train"].copy()
            evalq = qassigned.loc[qassigned.role == "validation"].copy()
            trainm = m.loc[m.run_id.isin(trainq.run_id.unique())].copy()
            evalm = m.loc[m.run_id.isin(evalq.run_id.unique())].copy()
            assert trainm.run_id.max() < evalm.run_id.min()
            fitq, calq, fitm, calm, boundary = nested_parts(trainq, trainm, cfg["single_train_run_fraction"])
            contexts[fold] = (evalq, evalm)
            for dataset, parts in [("q42", [("fit", fitq), ("calibration", calq), ("evaluation", evalq)]),
                                   ("m41", [("fit", fitm), ("calibration", calm), ("evaluation", evalm)])]:
                for role, part in parts:
                    splits.extend({"fold": fold, "dataset": dataset, "nested_role": role, "row_id": row.row_id,
                                   "run_id": int(row.run_id), "source_row": int(row.source_row)} for row in part.itertuples())
            detector = fit_ood(fitm, contract["q42_A0"], cfg["ood_train_bounds"])
            thresholds = {"OOD1": ood_threshold(calm, ood_scores(calm, detector), .01),
                          "OOD05": ood_threshold(calm, ood_scores(calm, detector), .005)}
            gtrain = fitm.loc[fitm.gate_eligible]
            gcal = calm.loc[calm.gate_eligible]
            gate_thresholds, qrank, grank = {}, [], []
            for family in cfg["models"]:
                for seed in cfg["seeds"]:
                    for task, features, train, target, cal in [("quality", fq, fitq, "y_defect", calq),
                            ("gate", fg, gtrain, "Machine_Status", gcal)]:
                        if train[target].nunique() != 2:
                            raise ValueError("Untrainable inner partition")
                        model = build_model(family, seed, base_cfg["models"][family])
                        with threadpool_limits(limits=1):
                            model.fit(train[features], train[target].astype(int))
                            probability = model.predict_proba(cal[features])[:, 1]
                        key = (fold, task, family, seed)
                        models[key] = model
                        joblib.dump({"pipeline": model, "features": features, "fold": fold, "task": task,
                                     "model": family, "seed": seed, "fit_row_ids": train.row_id.tolist()},
                                    out / "models" / ("__".join(map(str, key)) + ".joblib"), compress=3)
                        meta = {"fold": fold, "task": task, "model": family, "seed": seed,
                                "train_n": len(train), "train_positive": int(train[target].sum()), "cal_n": len(cal)}
                        candidate_predictions.append(cal[["row_id", "run_id", "Shot"]].assign(
                            fold=fold, task=task, model=family, seed=seed, stage="inner_calibration",
                            y=cal[target].to_numpy(), probability=probability))
                        if task == "quality":
                            ap = float(average_precision_score(cal[target], probability)) if cal[target].nunique() == 2 else np.nan
                            qrank.append({"model": family, "ap": ap})
                            model_rows.append({**meta, "cal_ap": ap})
                        else:
                            prediction = cal[["row_id"]].assign(probability=probability)
                            threshold, disabled, reason = constrained_threshold(calm, prediction, cfg["gate_fpr"], cfg["minimum_calibration_episodes"])
                            stats, _, _, _ = gate_statistics(calm, prediction, threshold, disabled)
                            gate_thresholds[family, seed] = {"threshold": threshold, "disabled": disabled, "reason": reason}
                            grank.append({"model": family, **stats})
                            model_rows.append({**meta, "cal_ap": float(average_precision_score(cal[target], probability)) if cal[target].nunique() == 2 else np.nan,
                                               "gate_threshold": threshold, "gate_disabled": disabled, "gate_reason": reason, **stats})
                        fitted += 1
            quality_family = pd.DataFrame(qrank).groupby("model").ap.mean().reset_index().sort_values(["ap", "model"], ascending=[False, True], na_position="last").model.iloc[0]
            gate_family = pd.DataFrame(grank).groupby("model")[["episode_recall", "mean_delay"]].mean().reset_index().sort_values(["episode_recall", "mean_delay", "model"], ascending=[False, True, True], na_position="last").model.iloc[0]
            choices = {"fold": fold, "quality_model": quality_family, "gate_model": gate_family,
                       "gate_thresholds": {str(seed): gate_thresholds[gate_family, seed] for seed in cfg["seeds"]},
                       "detector": detector, "ood_thresholds": thresholds, "boundary": boundary}
            for seed in cfg["seeds"]:
                scores = combined_scores(calm, calq, models[fold, "quality", quality_family, seed],
                    models[fold, "gate", gate_family, seed], fq, fg, detector)
                gate = choices["gate_thresholds"][str(seed)]
                for policy in POLICIES:
                    for budget in cfg["budgets"]:
                        actions = stream_queue(scores, policy, gate["threshold"], gate["disabled"], thresholds.get(policy), budget)
                        result, labelled, episodes = measure(actions, calm, calq, budget)
                        meta = {"fold": fold, "seed": seed, "stage": "inner_calibration", "policy": policy, "budget": budget}
                        inner_metrics.append({**meta, **result})
                        inner_actions.append(labelled.assign(**meta))
                        inner_episodes.extend({**meta, **episode} for episode in episodes)
            choices["selected_policy"] = choose_policy(pd.DataFrame([row for row in inner_metrics if row["fold"] == fold]),
                expected_seeds=cfg['seeds'],expected_budgets=cfg['budgets'])
            frozen.append(choices)
            print(f"Inner fold{fold}: {fitted}/80 fits; Q={quality_family}, G={gate_family}, policy={choices['selected_policy']}", flush=True)
        pd.DataFrame(splits).to_csv(out / "nested_assignments.csv", index=False)
        pd.DataFrame(model_rows).to_csv(out / "model_candidates.csv", index=False)
        pd.concat(candidate_predictions, ignore_index=True).to_parquet(out / "candidate_predictions.parquet", index=False)
        pd.DataFrame(inner_metrics).to_csv(out / "inner_policy_metrics.csv", index=False)
        pd.concat(inner_actions, ignore_index=True).to_parquet(out / "inner_actions.parquet", index=False)
        pd.DataFrame(inner_episodes).to_csv(out / "inner_episodes.csv", index=False)
        write_json(out / "selection.json", {"frozen_at": datetime.now(timezone.utc).isoformat(), "folds": frozen,
            "outer_outcomes_used_for_selection": False, "legacy_test_evaluated": False})
        # All fold selections are durably frozen before any outer outcomes are computed.
        write_json(out / "status.json", {"status": "running", "stage": "outer_development", "fits": fitted})
        outer_metrics, outer_actions, outer_episodes = [], [], []
        for choice in frozen:
            fold, thresholds = choice["fold"], choice["ood_thresholds"]
            evalq, evalm = contexts[fold]
            for seed in cfg["seeds"]:
                scores = combined_scores(evalm, evalq, models[fold, "quality", choice["quality_model"], seed],
                    models[fold, "gate", choice["gate_model"], seed], fq, fg, choice["detector"])
                gate = choice["gate_thresholds"][str(seed)]
                for policy in POLICIES:
                    for budget in cfg["budgets"]:
                        actions = stream_queue(scores, policy, gate["threshold"], gate["disabled"], thresholds.get(policy), budget)
                        result, labelled, episodes = measure(actions, evalm, evalq, budget)
                        meta = {"fold": fold, "seed": seed, "stage": "outer_development", "policy": policy, "budget": budget,
                                "selected": policy == choice["selected_policy"]}
                        outer_metrics.append({**meta, **result})
                        outer_actions.append(labelled.assign(**meta))
                        outer_episodes.extend({**meta, **episode} for episode in episodes)
            print(f"Outer development fold{fold}: frozen policy evaluated; no legacy test", flush=True)
        pd.DataFrame(outer_metrics).to_csv(out / "outer_policy_metrics.csv", index=False)
        pd.concat(outer_actions, ignore_index=True).to_parquet(out / "outer_actions.parquet", index=False)
        pd.DataFrame(outer_episodes).to_csv(out / "outer_episodes.csv", index=False)
        assert make_identity(root) == identity
        write_json(out / "status.json", {"status": "complete", "finished_at": datetime.now(timezone.utc).isoformat(),
            "fits": fitted, "legacy_test_evaluated": False, "evaluation_scope": cfg["evaluation_scope"]})
        write_json(out / "manifest.json", {"input_hashes": identity, "outputs": {
            p.relative_to(out).as_posix(): digest(p) for p in out.rglob("*") if p.is_file()}})
    except BaseException as error:
        write_json(out / "status.json", {"status": "failed", "error": str(error)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=Path("reports/oct03_queue"))
    args = parser.parse_args()
    root = args.root.resolve()
    run(root, args.output if args.output.is_absolute() else root / args.output)
