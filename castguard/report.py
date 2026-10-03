"""Generate reviewable decision evidence from frozen experiment outputs."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

from .data import attach_roles, digest, read_inputs
from .experiment import IDENTITY, KEYS, paired_seed_gain, passes_gain, quality_recommendations, task_frame, task_name, write_json
from .metrics import score
from .storage import require_cache, tracked_stage


def markdown_table(frame, digits=4):
    def fmt(value):
        if pd.isna(value):
            return "—"
        if isinstance(value, (float, np.floating)):
            return f"{value:.{digits}f}"
        return str(value).replace("|", "/")
    lines = ["| " + " | ".join(map(str, frame.columns)) + " |", "| " + " | ".join(["---"] * len(frame.columns)) + " |"]
    return "\n".join(lines + ["| " + " | ".join(map(fmt, row)) + " |" for row in frame.itertuples(index=False, name=None)])


def paired_block_bootstrap(y, base, other, groups, repetitions, seed):
    y, base, other, groups = map(np.asarray, [y, base, other, groups])
    unique, inverse = np.unique(groups, return_inverse=True)
    rng = np.random.default_rng(seed)
    values = {"average_precision": [], "roc_auc": []}
    for _ in range(repetitions):
        multiplicity = np.bincount(rng.integers(0, len(unique), len(unique)), minlength=len(unique))
        weights = multiplicity[inverse]
        if np.unique(y[weights > 0]).size < 2:
            continue
        for metric, fn in [("average_precision", average_precision_score), ("roc_auc", roc_auc_score)]:
            values[metric].append(fn(y, other, sample_weight=weights) - fn(y, base, sample_weight=weights))
    return [{"metric": key, "estimate": (average_precision_score if key == "average_precision" else roc_auc_score)(y, other) - (average_precision_score if key == "average_precision" else roc_auc_score)(y, base),
             "lower_95": float(np.quantile(value, 0.025)) if value else np.nan,
             "upper_95": float(np.quantile(value, 0.975)) if value else np.nan,
             "blocks": len(unique), "valid_replicates": len(value)} for key, value in values.items()]


def bootstrap_evidence(pred, frames, config):
    rows = []
    comparisons = [("q42", "all", "A", "B"), ("q42", "all", "A", "B2"),
                   ("p40", "all", "E_no_mold6", "E_full"), ("p40", "normal_pressure", "E_no_mold6", "E_full")]
    for dataset, population, base, other in comparisons:
        scheme = "within_run" if dataset == "q42" else "chronological"
        subset = pred.loc[(pred.dataset == dataset) & (pred.population == population) & (pred.scheme == scheme) & (pred.role == "test")]
        wide = subset.groupby(["row_id", "experiment"]).probability.mean().unstack()
        if other not in wide:
            continue
        wide = wide[[base, other]].dropna()
        frame = frames[dataset].set_index("row_id").loc[wide.index]
        groups = frame.run_id if dataset == "q42" else frame.event_time.dt.strftime("%Y-%m-%d")
        for result in paired_block_bootstrap(frame.y_defect.astype(int), wide[base], wide[other], groups,
                                             config["bootstrap_repetitions"], config["bootstrap_seed"]):
            rows.append({"dataset": dataset, "population": population, "comparison": f"{other} - {base}", "scheme": scheme,
                         "estimand": "AP/AUC difference of mean probabilities across five seeds", **result})
    return pd.DataFrame(rows)


def scheduled_timeline(q, m, folds, scheme, fold):
    """Recover test population before exclusions, preserving fully unobserved episodes."""
    frame = attach_roles(m, folds, "m41", scheme, fold)
    valid_runs = q.groupby("run_id").size().loc[lambda s: s >= 20].index
    if scheme == "within_run":
        qfold = attach_roles(q, folds, "q42", scheme, fold)
        mask = pd.Series(False, index=frame.index)
        for run in valid_runs:
            boundary = qfold.loc[(qfold.run_id == run) & (qfold.role == "validation"), "Shot"].max()
            mask |= (frame.run_id == run) & (frame.Shot > boundary)
        return frame.loc[mask].copy()
    return frame.loc[frame.run_id == int(fold)].copy()


def gate_evidence(pred, frames, folds):
    episodes, rows, workflow = [], [], []
    gate_predictions = pred.loc[(pred.dataset == "m41") & (pred.role == "test")]
    for (scheme, fold, seed), group in gate_predictions.groupby(["scheme", "fold", "seed"]):
        timeline = scheduled_timeline(frames["q42"], frames["m41"], folds, scheme, fold)
        merged = timeline.merge(group[["row_id", "probability", "prediction"]], on="row_id", how="left", validate="one_to_one")
        available = merged.probability.notna()
        alarm = merged.prediction.fillna(False).astype(bool)
        normal, warm = merged.Machine_Status.eq(0), merged.Machine_Status.eq(1)
        detected, observed_count, all_count, delays = 0, 0, 0, []
        for episode, ep in merged.loc[warm].groupby("episode_id"):
            all_count += 1
            observable = ep.probability.notna().any()
            observed_count += int(observable)
            hits = ep.loc[ep.prediction.fillna(False).astype(bool)]
            hit = not hits.empty
            detected += int(hit)
            delay = int(hits.Shot.min() - ep.Shot.min()) if hit else np.nan
            if hit:
                delays.append(delay)
            episodes.append({"scheme": scheme, "fold": fold, "seed": seed, "episode_id": episode,
                             "total_shots": len(ep), "observable_shots": int(ep.probability.notna().sum()),
                             "detected": hit, "delay_shots": delay,
                             "status": "detected" if hit else ("missed" if observable else "unobservable_held")})
        denominator = int((available & warm).sum())
        rows.append({"scheme": scheme, "fold": fold, "seed": seed, "model": group.model.iloc[0],
                     "total_test_timeline": len(merged), "eligible_test": int(available.sum()), "held_unavailable": int((~available).sum()),
                     "warm_total": int(warm.sum()), "warm_observable": denominator,
                     "warm_passed_without_gate": denominator,
                     "warm_passed_with_gate": int((warm & available & ~alarm).sum()),
                     "warm_pass_rate_with_gate": float((warm & available & ~alarm).sum() / denominator) if denominator else np.nan,
                     "normal_observable": int((normal & available).sum()), "false_stops": int((normal & available & alarm).sum()),
                     "test_fpr": float((normal & available & alarm).sum() / (normal & available).sum()),
                     "episodes_total": all_count, "episodes_observable": observed_count, "episodes_detected": detected,
                     "episode_recall_observable": detected / observed_count if observed_count else np.nan,
                     "episode_recall_total": detected / all_count if all_count else np.nan,
                     "mean_delay_detected_shots": float(np.mean(delays)) if delays else np.nan})
        qp = pred.loc[(pred.dataset == "q42") & (pred.experiment == "A") & (pred.scheme == scheme) & (pred.fold == fold) & (pred.seed == seed) & (pred.role == "test")]
        quality = qp.merge(frames["q42"][["row_id", "run_id", "Shot"]], on="row_id", validate="one_to_one")
        quality = quality.merge(merged[["run_id", "Shot", "prediction"]], on=["run_id", "Shot"], suffixes=("_quality", "_gate"), validate="one_to_one")
        held = quality.prediction_gate.fillna(True).astype(bool)
        positives = quality.y.eq(1)
        workflow.append({"scheme": scheme, "fold": fold, "seed": seed, "quality_test_n": len(quality),
                         "quality_positive": int(positives.sum()), "quality_shots_held": int(held.sum()),
                         "quality_positives_held": int((held & positives).sum()),
                         "quality_tp_without_gate": int((quality.prediction_quality & positives).sum()),
                         "quality_tp_automatic_path_with_gate": int((quality.prediction_quality & positives & ~held).sum())})
    return pd.DataFrame(rows), pd.DataFrame(episodes), pd.DataFrame(workflow)


def factor_evidence(root, output, config, provenance, selection):
    cache = root / provenance["cache"]
    rows = []
    compare = [("q42", "all", "within_run", "A"), ("p40", "normal_pressure", "chronological", "E_full")]
    for dataset, population, scheme, experiment in compare:
        selected = selection.loc[selection.selected & (selection.dataset == dataset) & (selection.population == population) & (selection.scheme == scheme)].iloc[0]
        for seed in config["seeds"]:
            task = dict(zip(IDENTITY, [dataset, population, scheme, "primary", experiment, selected.model, seed]))
            require_cache(cache / task_name(task), task)
            bundle = joblib.load(cache / task_name(task) / "model.joblib")
            model, features = bundle["pipeline"], bundle["features"]
            frame, _, _ = task_frame(root, task, config)
            train, test = frame.loc[frame.role == "train"], frame.loc[frame.role == "test"]
            with threadpool_limits(limits=1):
                importance = permutation_importance(model, test[features], test.y_defect.astype(int), scoring="average_precision", n_repeats=config["permutation_repetitions"], random_state=seed, n_jobs=1)
                ranks = pd.Series(importance.importances_mean).rank(ascending=False, method="min")
                for i, feature in enumerate(features):
                    low, high = train[feature].quantile([0.25, 0.75])
                    low_frame, high_frame = test[features].copy(), test[features].copy()
                    low_frame[feature], high_frame[feature] = low, high
                    change = float(np.mean(model.predict_proba(high_frame)[:, 1] - model.predict_proba(low_frame)[:, 1]))
                    rows.append({"dataset": dataset, "population": population, "experiment": experiment, "model": selected.model,
                                 "seed": seed, "feature": feature, "permutation_ap_drop": importance.importances_mean[i],
                                 "permutation_repeat_sd": importance.importances_std[i], "rank": ranks.iloc[i],
                                 "train_q25": low, "train_q75": high, "pdp_q75_minus_q25": change})
    result = pd.DataFrame(rows)
    result.to_csv(output / "factor_details.csv", index=False)
    aggregate = result.groupby(["dataset", "population", "feature"], as_index=False).agg(ap_drop_mean=("permutation_ap_drop", "mean"), ap_drop_seed_sd=("permutation_ap_drop", "std"), rank_mean=("rank", "mean"), direction_mean=("pdp_q75_minus_q25", "mean"), direction_seed_sd=("pdp_q75_minus_q25", "std"))
    aggregate.to_csv(output / "factor_summary.csv", index=False)
    mappings = [("pressure", "Casting_Pressure", "injection_pressure"),
                ("pressure_secondary", "Cylinder_Pressure", "injection_pressure"),
                ("heat_proxy", "Melting_Furnace_Temp", "mold_temperature")]
    comparisons = []
    for factor, qfeature, pfeature in mappings:
        q = aggregate.loc[(aggregate.dataset == "q42") & (aggregate.feature == qfeature)].iloc[0]
        p = aggregate.loc[(aggregate.dataset == "p40") & (aggregate.feature == pfeature)].iloc[0]
        comparisons.append({"factor": factor, "q42_feature": qfeature, "p40_feature": pfeature,
                            "q42_direction": q.direction_mean, "p40_direction": p.direction_mean,
                            "same_sign": bool(np.sign(q.direction_mean) == np.sign(p.direction_mean)),
                            "q42_rank": q.rank_mean, "p40_rank": p.rank_mean,
                            "q42_ap_drop": q.ap_drop_mean, "p40_ap_drop": p.ap_drop_mean,
                            "interpretation": "exploratory proxies, different physical quantities; not causal or transfer validation"})
    comparison = pd.DataFrame(comparisons)
    comparison.to_csv(output / "factor_comparison.csv", index=False)
    return comparison


def history_decision(metrics, selection, history, config):
    primary = selection.loc[selection.selected & (selection.dataset == "q42") & (selection.scheme == "within_run")].iloc[0]
    choice = next(x for x in history if x["scheme"] == "within_run" and x["fold"] == "primary")
    selected_experiment = choice["validation_selected_history_experiment"]
    b_gain, b_sd = paired_seed_gain(metrics, "within_run", "primary", "test", "B", primary.model)
    gain, sd = paired_seed_gain(metrics, "within_run", "primary", "test", selected_experiment, primary.model)
    passed = passes_gain(gain, sd, config)
    return {"date": "2026-10-02", "primary_quality_model": primary.model,
            "b_ap_gain": b_gain, "b_paired_seed_sd": b_sd, "b_pass": passes_gain(b_gain, b_sd, config),
            "selected_history_experiment": selected_experiment, "selected_history_ap_gain": gain,
            "selected_history_paired_seed_sd": sd, "selected_history_pass": passed,
            "history_validation_selection": choice,
            "narrative": f"{selected_experiment} primary; C/E supporting" if passed else "History improvement not established; E primary empirical evidence, C coverage evidence with false-stop limitations",
            "deployment_ready": False,
            "reason": "Retrospective quality accuracy and unseen-run Gate false stops do not establish operational readiness"}


def summarize(root, output):
    with tracked_stage(output, "summarizing"):
        return _summarize(root, output)


def _summarize(root, output):
    root, output = Path(root), Path(output)
    from .verify import verify_evidence, verify_provenance
    provenance = verify_provenance(root, output)
    verification = verify_evidence(root, output)
    metrics = pd.read_csv(output / "metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    selected = pd.read_csv(output / "selected_metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    selection = pd.read_csv(output / "model_selection.csv", dtype={"fold": str})
    predictions = pd.read_parquet(output / "predictions.parquet")
    config = provenance["config"]
    frames, folds, _ = read_inputs(root)
    test = selected.loc[selected.role == "test"]
    group_keys = KEYS + ["experiment", "model"]
    summary = test.groupby(group_keys, as_index=False).agg(n=("n", "first"), positive=("positive", "first"), ap_mean=("average_precision", "mean"), ap_sd=("average_precision", "std"), auc_mean=("roc_auc", "mean"), auc_sd=("roc_auc", "std"), recall_mean=("recall", "mean"), fpr_mean=("fpr", "mean"), ece_mean=("ece", "mean"), brier_mean=("brier", "mean"))
    summary.to_csv(output / "ablation_summary.csv", index=False)
    print("Calculating paired run/date block intervals", flush=True)
    bootstrap = bootstrap_evidence(predictions, frames, config)
    bootstrap.to_csv(output / "bootstrap_intervals.csv", index=False)
    gate, episodes, workflow = gate_evidence(predictions, frames, folds)
    gate.to_csv(output / "gate_metrics.csv", index=False)
    episodes.to_csv(output / "gate_episodes.csv", index=False)
    workflow.to_csv(output / "gate_quality_workflow.csv", index=False)
    print("Calculating F: permutation importance and probability direction", flush=True)
    factors = factor_evidence(root, output, config, provenance, selection)
    # Empirical pressure-only rule, scored only on the frozen chronological test.
    process = attach_roles(frames["p40"], folds, "p40", "chronological", "primary")
    process = process.loc[process.role == "test"]
    rule = process.injection_pressure.le(615).astype(float)
    write_json(output / "pressure_rule.json", {"rule": "injection_pressure <= 615", "threshold_source": "team guidebook, not fitted", **score(process.y_defect, rule)})
    history = json.loads((output / "history_selection.json").read_text(encoding="utf-8"))
    decision = history_decision(metrics, selection, history, config)
    recommendation = quality_recommendations(metrics)
    recommendation.to_csv(output / "quality_recommendations.csv", index=False)
    recommended_primary = recommendation.loc[recommendation.recommended & (recommendation.scheme == "within_run")].iloc[0]
    decision["supplementary_quality_recommendation"] = recommended_primary.to_dict()
    write_json(output / "decision.json", decision)
    candidates = metrics.loc[(metrics.dataset == "q42") & (metrics.scheme == "within_run") & (metrics.experiment == "A")].groupby(["model", "role"], as_index=False).agg(ap=("average_precision", "mean"), ap_sd=("average_precision", "std"), auc=("roc_auc", "mean"), ece=("ece", "mean"), brier=("brier", "mean"), inference_us=("predict_us_per_row", "mean"))
    gate_fold = gate.groupby(["scheme", "fold"], as_index=False).agg(observable=("episodes_observable", "first"), total=("episodes_total", "first"), detected_mean=("episodes_detected", "mean"), test_fpr=("test_fpr", "mean"), warm_pass_rate=("warm_pass_rate_with_gate", "mean"), delay_detected=("mean_delay_detected_shots", "mean"), held_unavailable=("held_unavailable", "first"))
    # Full OOF episode population exists only for run_holdout (one test role per run).
    totals = gate.loc[gate.scheme == "run_holdout"].groupby("seed").agg(total=("episodes_total", "sum"), observable=("episodes_observable", "sum"), detected=("episodes_detected", "sum"), false_stops=("false_stops", "sum"), normal=("normal_observable", "sum"), warm_passed=("warm_passed_with_gate", "sum"), warm=("warm_observable", "sum"))
    totals["pooled_fpr"] = totals.false_stops / totals.normal
    totals.reset_index().to_csv(output / "gate_run_holdout_totals.csv", index=False)
    body = ["# 10월 2일 판정 게이트 결과", "", "기준일: 2026-10-02. 팀 가이드북의 9/30–10/2 실험 범위를 실제 실행한 결과다. 기존 HTML의 참고 수치는 재사용하지 않았다.", "",
            f"**검증에서 선택한 {decision['selected_history_experiment']}의 이력 변수 개선 기준을 {'통과했다' if decision['selected_history_pass'] else '충족하지 못했다'}.** {decision['primary_quality_model']}에서 A 대비 AP 차이는 {decision['selected_history_ap_gain']:+.4f}, paired seed 표준편차는 {decision['selected_history_paired_seed_sd']:.4f}다. 기준은 +0.02 이상 및 표준편차 2배 초과다.", "",
            "#41과 #42는 공정 변수가 같고 모집단·라벨이 다르다. 이번에는 E(금형온도 제거실험)를 중심 증거로, C는 예열을 구분해 적용 범위를 넓히는 근거로 사용한다. C의 새 구간 오정지가 커서 현장 적용 성능으로 포장하면 안 된다." if not decision['selected_history_pass'] else "이력의 회고적 개선과 미래 구간 일반화는 별도 주장이다. C/E 결과와 미래 구간 결과를 함께 해석한다.", "",
            "## 오늘까지 완료한 범위", "", "- 고정 입력 해시·조인·분할 검사 및 원본 CSV에서 전처리/분할 재생성 일치 검증.",
            "- 로지스틱/RF/LightGBM/CatBoost, 5개 seed, 고정 분할 전부에서 A0/A/B/C/E 실행.",
            "- validation만 사용한 후보 선택·임계값 결정, B2 한 번의 재설계, F의 변수 방향·순위 비교.",
            "- 행 단위 예측, seed별 지표, 에피소드 단위 결과, paired block 구간 및 재실행 명령 저장.", "",
            "## 후보 모델 비교", "", "모델군은 A의 validation AP 평균으로 선택했다. test 최고 모델을 다시 선택하지 않았다. ECE는 보정 전 10-bin 측정값이다. 추론 시간은 이 PC에서 배치 예측한 참고값이다.", "", markdown_table(candidates), "",
            "## 재검토: 입력군까지 포함한 보완 권고", "",
            "기존 제거실험은 A를 기준으로 모델군을 고정해야 공정한 전후 비교가 된다. 이 기준모델과 향후 사용할 입력/모델 조합은 다른 선택이다. 재검토에서는 이미 수행한 A0/A/B × 4개 모델의 validation AP 평균, Brier, 입력명·모델명 순으로만 권고를 계산했다. B2는 모든 모델군에 공통 실행되지 않아 이 표에서 제외했다. 원래 B 판정과 test 결과는 바꾸지 않았다.", "",
            f"within_run 보완 권고는 **{recommended_primary.experiment} / {recommended_primary.model}**다. 이는 최초 test 공개 후 보완한 선택 정책이며, 새 독립 시험에서 성능 개선을 입증한 결과로 해석하면 안 된다. 새 데이터 검증을 거쳐 최종 적용 여부를 정한다.", "",
            markdown_table(recommendation.loc[recommendation.scheme == "within_run", ["experiment", "model", "validation_ap", "validation_brier", "validation_ap_seed_sd", "recommended"]]), "",
            "## A0 / A / B / B2", "", markdown_table(summary.loc[(summary.dataset == "q42") & (summary.scheme == "within_run"), ["experiment", "model", "n", "positive", "auc_mean", "auc_sd", "ap_mean", "ap_sd", "ece_mean"]]), "",
            "AP는 Average Precision이다. ± 값은 5 seed의 표준편차이며 신뢰구간이 아니다. B2는 검증에서 사전 기준을 못 넘긴 fold에서만 한 번 실행했다. B2의 추가 입력은 과거 Cycle_Time의 train 제품별 중앙값 대비 비율 2개와 이전 20행 결손수/20이다. 정답이나 미래 값은 쓰지 않았다.", "",
            "A0가 시험에서 더 좋게 나온 경우도 그대로 공개한다. 이번 실험 뒤 test를 보고 A0를 최종 채택했다고 주장하지 않는다. 입력군 최종 선택의 추가 검증은 다음 단계다.", "",
            "## 새 미래 가동구간", "", "forward_run만 시간 전진 평가다. 표본·불량 수가 적은 구간에서는 AP/AUC가 불안정하다. run_holdout 상세는 CSV에 있으며 두 프로토콜을 혼합 평균하지 않았다.", "",
            markdown_table(summary.loc[(summary.dataset == "q42") & (summary.scheme == "forward_run") & summary.experiment.isin(["A", "B"]), ["fold", "experiment", "model", "n", "positive", "auc_mean", "ap_mean", "ap_sd"]]), "",
            "## C: Gate 적용 범위와 실패 조건", "", "Gate 경계는 validation 정상 FPR ≤2%로 선택했다. 아래 값은 독립 test의 실제 FPR이며 2% 보장값이 아니다. 지연은 탐지된 에피소드만의 최초 예열 Shot→최초 탐지 Shot 간격이고, 미탐지를 지연 평균에서 성공처럼 취급하지 않는다.", "", markdown_table(gate_fold), "",
            "run_holdout은 각 구간을 한 번씩 test로 평가한다. 5 seed를 5배 많은 에피소드로 세지 않도록 seed별 합계를 보존했다.", "", markdown_table(totals.reset_index()), "",
            "전체 21개 에피소드 중 20개에 관측 가능한 입력이 있다. 완전 결손 에피소드도 전체 분모에 포함하며, 결손 행은 보류한다. #42에는 정상 Shot의 품질 라벨만 있어 예열 제품의 품질 불량률/품질 정확도를 계산하지 않았다. Gate 경보는 정상 생산을 보류시킬 수도 있다. `gate_quality_workflow.csv`는 이 손실을 포함한 자동 품질 경로 TP와 보류 수를 담는다.", "",
            "## E: 금형온도 6개 제거", "", "전체 및 정상압력(>615) 모집단을 각각 학습·평가했다. top_temp1–3/bottom_temp1–3만 제거했고, mold_temperature/sleeve_temperature는 유지했다. #40 자체의 변수 유용성 근거이며 #42의 정확도 향상을 입증하지 않는다. 원본 전처리 방침대로 1,500 초과 의심값도 유지했으므로 물리적 온도 해석과 센서 단위 확인은 별도 과제다.", "",
            markdown_table(summary.loc[summary.dataset == "p40", ["population", "experiment", "model", "n", "positive", "auc_mean", "auc_sd", "ap_mean", "ap_sd"]]), "",
            "## paired block 불확실성", "", "q42는 run, p40은 날짜 단위로 1,000회 paired 재표집했다. seed 평균 확률의 AP/AUC 차이를 대상으로 하므로 위 seed별 지표 평균과 추정량이 다르다. 6개 run과 소수 날짜만 있는 탐색적 구간이며 독립 외부 재검증을 대체하지 않는다.", "",
            markdown_table(bootstrap[["dataset", "population", "comparison", "metric", "estimate", "lower_95", "upper_95", "blocks"]]), "",
            "## F: 물리인자 방향·순위", "", "순위는 test 순열 중요도(AP 감소)이며 방향은 train 25→75 분위로 해당 열만 바꾼 평균 예측확률 차이다. 5 seed 평균이다. 서로 다른 공정의 압력·온도 proxy를 비교한 탐색 분석이다. 단위/설비 계보 확인 전 방향 일치만으로 전이 가능성·인과효과를 주장하지 않는다. 상관된 변수의 단독 치환은 실제 운전 가능한 조건을 보장하지 않는다.", "",
            markdown_table(factors.drop(columns="interpretation")), "",
            f"방향 부호가 일치한 proxy는 {int(factors.same_sign.sum())}/{len(factors)}개다. 방향이 같아도 순열 중요도가 음수이거나 확률 변화가 작으면 공통 효과의 근거가 약하다. F는 물리적 인과관계나 타 공장 전이 성공의 검증이 아니다.", "",
            "## 다음 일정과 미확인 사항", "", "- 10/2–10/4: 조건별 오류분석 확대, SHAP·상호작용, 운전창·조치 정책·KPI. F의 순열/PDP는 SHAP 완료를 뜻하지 않는다.",
            "- 10/4–10/6: 보고서·PPT 작성 및 팀 검토. 10/6–10/7: 제출용 전체 파이프라인 clean-room 검수, 10/7 사전 제출.",
            "- KAMP 원본 가이드북/AAS 단위·수집주기·설비 계보와 현장 입력 가용성은 저장소에 근거 자료가 없어 미확인이다. 실제 품질비용·효과를 임의 생성하지 않았다.",
            "- 이번 `all`은 10/2 판정 게이트 전체다. 제출일까지의 KPI·보고서까지 완료했다는 의미가 아니다.", "",
            "## 재현 및 파일", "", "프로토콜: [EXPERIMENT_PROTOCOL.md](../../docs/EXPERIMENT_PROTOCOL.md). 실행: [README](../../README.md). 설정: [oct02.json](../../configs/oct02.json).",
            "`metrics.csv`는 모든 후보/seed/validation/test 결과, `model_selection.csv`는 선정 근거, `predictions.parquet`은 선정 모델군의 모든 제거실험 예측이다. 개별 후보 전체 예측·학습모델은 로컬 `artifacts/`에 저장하고 같은 명령으로 재생성한다. `provenance.json`에 해시·환경을 기록했다.", "",
            "방법 출처: [AP 정의](https://scikit-learn.org/1.7/modules/generated/sklearn.metrics.average_precision_score.html), [학습 누수 방지](https://scikit-learn.org/1.7/common_pitfalls.html).", ""]
    (output / "RESULTS.md").write_text("\n".join(body), encoding="utf-8")
    verify_provenance(root, output)
    write_json(output / "prediction_verification.json", verification)
    status = json.loads((output / "run_status.json").read_text())
    status.update(status="complete", decision=decision)
    write_json(output / "run_status.json", status)
    write_json(output / "evidence_manifest.json", {"source_hashes": {p.relative_to(root).as_posix(): digest(p) for p in sorted((root / "castguard").glob("*.py"))},
               "outputs": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != "evidence_manifest.json"}})
    print(f"Completed: {output / 'RESULTS.md'}", flush=True)
