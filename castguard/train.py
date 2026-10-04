"""학습·검증 실험 전체. 모든 선택(모델·입력·임계값)은 validation으로만 하고 test는 보고에만 쓴다.

단계
 1) 품질(Stage 2) within_run: 입력 6종 × 후보 6종(로지스틱·RF·LightGBM·CatBoost·XGBoost·앙상블) × seed 5
    → validation AP로 최종 (입력, 모델) 선정
 2) 품질 실패조건: run_holdout · forward_run에서 입력 5종 × 최종 모델 × seed
 3) 검사결과 지연(delay) 민감도
 4) 설비상태 Gate(Stage 1): 후보 비교 → 선정 모델로 구간 이동 검증
 5) 불량유형(Stage 3): 주요 4종 + Etc, 유형별 이진 모델
 6) #40 외부 검증(E): 전체 vs 금형온도 6개 제외, 전체/정상압력 구간
"""
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from . import paths
from .features import add_feedback, feedback_columns, is_forbidden, quality_feature_sets
from .metrics import score, threshold_f1, threshold_max_fpr
from .models import make

QUALITY_MODELS = ["logistic", "random_forest", "lightgbm", "catboost", "xgboost", "ensemble"]
TYPE_TARGETS = ["y_type_Short_Shot", "y_type_Bubble", "y_type_Exfoliation", "y_type_Blow_Hole", "y_type_Etc"]


# ───────────────────────── 데이터 ─────────────────────────
def load_inputs():
    joined = pd.read_parquet(paths.JOINED)
    m41 = pd.read_parquet(paths.M41)
    p40 = pd.read_parquet(paths.P40)
    folds = pd.read_csv(paths.FOLDS, dtype={"fold": str, "episode_id": str, "order": str})
    contract = json.loads(paths.CONTRACT.read_text(encoding="utf-8"))
    return joined, m41, p40, folds, contract


def with_roles(frame, folds, dataset, scheme, fold):
    rows = folds.loc[(folds.dataset == dataset) & (folds.scheme == scheme) & (folds.fold == str(fold)), ["row_id", "role"]]
    if rows.empty or set(rows.row_id) != set(frame.row_id):
        raise ValueError(f"분할 배정 불완전: {dataset}/{scheme}/{fold}")
    return frame.merge(rows, on="row_id", validate="one_to_one")


def check_features(features, contract):
    bad = [f for f in features if is_forbidden(f, contract)]
    if bad or len(set(features)) != len(features):
        raise ValueError(f"금지된 입력 또는 중복: {bad}")


# ───────────────────────── 한 번의 학습 ─────────────────────────
def fit_eval(frame: pd.DataFrame, task: dict, cfg: dict, save_model: bool = False):
    feats, target = task["features"], task["target"]
    train = frame[frame.role == "train"]
    val = frame[frame.role == "validation"]
    if train[target].nunique() < 2 or val.empty:
        return [], None
    model = make(task["model"], task["seed"], cfg)
    t0 = time.perf_counter()
    model.fit(train[feats], train[target].astype(int))
    fit_s = time.perf_counter() - t0
    pv = model.predict_proba(val[feats])[:, 1]
    if task["kind"] == "gate":
        thr = threshold_max_fpr(val[target].astype(int), pv, cfg["gate_max_validation_fpr"])
    else:
        thr = threshold_f1(val[target].astype(int), pv)
    meta = {k: v for k, v in task.items() if k != "features"}
    rows, preds = [], []
    for role in ["validation", "test"]:
        part = frame[frame.role == role]
        if part.empty:
            continue
        p = pv if role == "validation" else model.predict_proba(part[feats])[:, 1]
        rows.append({**meta, "role": role, "n_features": len(feats), "fit_seconds": fit_s,
                     **score(part[target].astype(int), p, thr)})
        preds.append(pd.DataFrame({"row_id": part.row_id.to_numpy(), "y": part[target].astype(int).to_numpy(),
                                   "p": p, "threshold": thr, "role": role, **{k: meta[k] for k in
                                   ["kind", "scheme", "fold", "experiment", "model", "seed", "target", "population", "delay"]}}))
    if save_model:
        joblib.dump({"model": model, "features": feats, "threshold": thr, "task": meta},
                    paths.MODELS / f"{task['kind']}_{task['experiment']}_{task['target']}.joblib", compress=3)
    return rows, pd.concat(preds, ignore_index=True)


def _task(kind, scheme, fold, experiment, model, seed, target, features, population="all", delay=None):
    return dict(kind=kind, scheme=scheme, fold=str(fold), experiment=experiment, model=model, seed=seed,
                target=target, features=features, population=population, delay=delay)


def _run_tasks(tasks, frames, cfg, jobs):
    """frames: {(kind, scheme, fold, population, delay): DataFrame with role}"""
    def key(t):
        return (t["kind"], t["scheme"], t["fold"], t["population"], t["delay"])
    out = Parallel(n_jobs=jobs, backend="loky")(delayed(fit_eval)(frames[key(t)], t, cfg) for t in tasks)
    rows = [r for rs, _ in out for r in rs]
    preds = [p for _, p in out if p is not None]
    return rows, preds


# ───────────────────────── 선정 규칙 ─────────────────────────
def select(metrics: pd.DataFrame, by=("experiment", "model")) -> pd.Series:
    """validation AP 평균 최대, 동률이면 ECE·seed 표준편차가 작은 쪽."""
    v = metrics[metrics.role == "validation"].groupby(list(by)).agg(
        val_ap=("average_precision", "mean"), val_ap_sd=("average_precision", "std"), val_ece=("ece", "mean")).reset_index()
    v = v.sort_values(["val_ap", "val_ece", "val_ap_sd"], ascending=[False, True, True])
    return v.iloc[0]


def run(cfg: dict, jobs: int | None = None, log=print) -> dict:
    paths.ensure_dirs()
    jobs = jobs or max(1, (os.cpu_count() or 2))
    joined, m41, p40, folds, contract = load_inputs()
    seeds = cfg["seeds"]
    windows = cfg["feedback_windows"]
    sets = quality_feature_sets(contract, windows)
    for fs in sets.values():
        check_features(fs, contract)
    delay = cfg["label_delay_shots"]

    def qframe(scheme, fold, d):
        f = add_feedback(joined, d, windows, cfg["feedback_halflife"])
        return with_roles(f, folds, "q42", scheme, fold)

    q_schemes = folds.loc[folds.dataset == "q42", ["scheme", "fold"]].drop_duplicates().itertuples(index=False)
    q_schemes = [(s, f) for s, f in q_schemes]
    all_rows, all_preds = [], []

    # 1) 품질 within_run 전체 비교
    frames = {("quality", "within_run", "primary", "all", delay): qframe("within_run", "primary", delay)}
    tasks = [_task("quality", "within_run", "primary", e, m, s, "y_defect", fs, delay=delay)
             for e, fs in sets.items() for m in QUALITY_MODELS for s in seeds]
    log(f"[1/6] 품질 within_run: {len(tasks)}회 학습")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds
    m1 = pd.DataFrame(rows)
    best = select(m1)
    b_rule = None
    if best.experiment.startswith("B"):
        # 보조데이터(#41 이력)는 validation에서 +0.02 이상 & seed 표준편차 2배 초과일 때만 채택 (HTML 판정 규칙)
        a_exp = "A" + best.experiment[1:]
        v = m1[(m1.role == "validation") & (m1.model == best.model)].pivot_table(
            index="seed", columns="experiment", values="average_precision")
        d = v[best.experiment] - v[a_exp]
        ok = bool(d.mean() >= cfg["b_min_ap_gain"] and (len(d) < 2 or d.mean() > 2 * d.std(ddof=1)))
        b_rule = {"candidate": best.experiment, "vs": a_exp, "val_gain": float(d.mean()),
                  "val_gain_sd": float(d.std(ddof=1)) if len(d) > 1 else None, "adopted": ok}
        if not ok:
            best = select(m1[~m1.experiment.str.startswith("B")])
    final = {"experiment": best.experiment, "model": best.model, "val_ap": float(best.val_ap), "b_rule": b_rule}
    log(f"      최종 품질모델(validation 선정): {final}")

    # 2) 실패 조건: 구간 이동·새 미래 구간
    abl = ["A0", "A", "B", "A_FB", "B_FB"]
    frames = {("quality", s, f, "all", delay): qframe(s, f, delay) for s, f in q_schemes if s != "within_run"}
    tasks = [_task("quality", s, f, e, final["model"], sd, "y_defect", sets[e], delay=delay)
             for s, f in q_schemes if s != "within_run" for e in abl for sd in seeds]
    log(f"[2/6] 품질 run_holdout·forward_run: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 3) 검사결과 지연 민감도
    fb_exp = final["experiment"] if "FB" in final["experiment"] else "A_FB"
    dl = [d for d in cfg["label_delay_sensitivity"] if d != delay]
    frames = {("quality", "within_run", "primary", "all", d): qframe("within_run", "primary", d) for d in dl}
    tasks = [_task("quality", "within_run", "primary", fb_exp, final["model"], s, "y_defect", sets[fb_exp], delay=d)
             for d in dl for s in seeds]
    log(f"[3/6] 지연 민감도 {dl}: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 4) 설비상태 Gate
    gfeat = contract["m41_gate"]
    check_features(gfeat, contract)
    g_schemes = [(s, f) for s, f in folds.loc[folds.dataset == "m41", ["scheme", "fold"]].drop_duplicates().itertuples(index=False)]
    gframes = {("gate", s, f, "all", None): with_roles(m41, folds, "m41", s, f).query("role != 'excluded'")
               .assign(Machine_Status=lambda d: d.Machine_Status.astype(int)) for s, f in g_schemes}
    tasks = [_task("gate", "within_run", "primary", "Gate", m, s, "Machine_Status", gfeat)
             for m in QUALITY_MODELS for s in seeds]
    log(f"[4/6] Gate 후보 비교: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, gframes, cfg, jobs)
    all_rows += rows; all_preds += preds
    gbest = select(pd.DataFrame(rows))
    gate_model = gbest.model
    tasks = [_task("gate", s, f, "Gate", gate_model, sd, "Machine_Status", gfeat)
             for s, f in g_schemes if s != "within_run" for sd in seeds]
    rows, preds = _run_tasks(tasks, gframes, cfg, jobs)
    all_rows += rows; all_preds += preds
    log(f"      Gate 모델: {gate_model}")

    # 5) 불량유형
    frames_q = qframe("within_run", "primary", delay)
    tframe = {("type", "within_run", "primary", "all", delay): frames_q}
    tasks = [_task("type", "within_run", "primary", final["experiment"], final["model"], s, t, sets[final["experiment"]], delay=delay)
             for t in TYPE_TARGETS for s in seeds]
    log(f"[5/6] 불량유형: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, tframe, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 6) #40 외부 검증
    pframe = with_roles(p40, folds, "p40", "chronological", "primary").query("role != 'excluded'")
    pframe = pframe.assign(y_defect=pframe.y_defect.astype(int))
    pfull = contract["p40_full"]
    pno = [c for c in pfull if c not in cfg["mold_six"]]
    pframes = {("p40", "chronological", "primary", "all", None): pframe,
               ("p40", "chronological", "primary", "normal_pressure", None): pframe[pframe.normal_pressure.fillna(False).astype(bool)]}
    tasks = [_task("p40", "chronological", "primary", e, m, s, "y_defect", fs, population=pop)
             for pop in ["all", "normal_pressure"] for e, fs in [("E_full", pfull), ("E_no_mold6", pno)]
             for m in cfg["p40_models"] for s in seeds]
    log(f"[6/6] #40 외부 검증: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, pframes, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 최종 모델 저장 (예측 단계용, 첫 seed)
    fit_eval(frames_q, _task("quality", "within_run", "primary", final["experiment"], final["model"], seeds[0],
                             "y_defect", sets[final["experiment"]], delay=delay), cfg, save_model=True)
    fit_eval(gframes[("gate", "within_run", "primary", "all", None)],
             _task("gate", "within_run", "primary", "Gate", gate_model, seeds[0], "Machine_Status", gfeat), cfg, save_model=True)
    for t in TYPE_TARGETS:
        fit_eval(frames_q, _task("type", "within_run", "primary", final["experiment"], final["model"], seeds[0], t,
                                 sets[final["experiment"]], delay=delay), cfg, save_model=True)

    metrics = pd.DataFrame(all_rows)
    preds = pd.concat(all_preds, ignore_index=True)
    metrics.to_csv(paths.RUNS / "metrics.csv", index=False)
    preds.to_parquet(paths.RUNS / "predictions.parquet", index=False)
    selection = {"final_quality": final, "gate_model": gate_model, "gate_val_ap": float(gbest.val_ap),
                 "feedback_experiment_for_sensitivity": fb_exp, "label_delay_shots": delay,
                 "feature_sets": sets}
    (paths.RUNS / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"학습 완료: 지표 {len(metrics)}행, 예측 {len(preds)}행")
    return selection
