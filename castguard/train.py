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
import itertools
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
    model = make(task["model"], task["seed"], cfg, task.get("params"))
    t0 = time.perf_counter()
    model.fit(train[feats], train[target].astype(int))
    fit_s = time.perf_counter() - t0
    pv = model.predict_proba(val[feats])[:, 1]
    if task["kind"] == "gate":
        thr = threshold_max_fpr(val[target].astype(int), pv, cfg["gate_max_validation_fpr"])
    else:
        thr = threshold_f1(val[target].astype(int), pv)
    meta = {k: v for k, v in task.items() if k not in ("features", "params")}
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


def _task(kind, scheme, fold, experiment, model, seed, target, features, population="all", delay=None, params=None):
    return dict(kind=kind, scheme=scheme, fold=str(fold), experiment=experiment, model=model, seed=seed,
                target=target, features=features, population=population, delay=delay, params=params)


def _run_tasks(tasks, frames, cfg, jobs):
    """frames: {(kind, scheme, fold, population, delay): DataFrame with role}"""
    def key(t):
        return (t["kind"], t["scheme"], t["fold"], t["population"], t["delay"])
    out = Parallel(n_jobs=jobs, backend="loky")(delayed(fit_eval)(frames[key(t)], t, cfg) for t in tasks)
    rows = [r for rs, _ in out for r in rs]
    preds = [p for _, p in out if p is not None]
    return rows, preds


# ───────────────────────── 개발구간 안에서의 견고한 선택 ─────────────────────────
def _dev_part(frame):
    dev = frame[frame.role.isin(["train", "validation"])].sort_values(["run_id", "source_row"]).copy()
    dev["frac"] = dev.groupby("run_id").cumcount() / dev.groupby("run_id").run_id.transform("size")
    return dev


def inner_cv_ap(dev, feats, model, params, seed, cfg, target="y_defect", combine=None):
    """개발구간(test 제외)을 시간순으로 3번 나눠 확장창 학습→다음 구간 검증. 반환: 평균 AP."""
    from sklearn.metrics import average_precision_score
    aps = []
    for a, b in cfg["inner_cv_folds"]:
        tr, va = dev[dev.frac < a], dev[(dev.frac >= a) & (dev.frac < b)]
        if va[target].sum() == 0 or tr[target].sum() < 5:
            continue
        if combine is None:
            m = make(model, seed, cfg, params)
            m.fit(tr[feats], tr[target].astype(int))
            p = m.predict_proba(va[feats])[:, 1]
        else:                       # 여러 하위 정답을 따로 예측해 '하나라도 불량' 확률로 결합
            q = np.ones(len(va))
            for t in combine:
                m = make(model, seed, cfg, params)
                m.fit(tr[feats], tr[t].astype(int))
                q *= 1 - m.predict_proba(va[feats])[:, 1]
            p = 1 - q
        aps.append(average_precision_score(va[target], p))
    return float(np.mean(aps)) if aps else np.nan


def gate_loro(m41, folds, feats, model, seed, cfg):
    """구간 이동 견고성: 개발구간(within_run의 train+validation)만으로 구간 하나씩 빼고 학습,
    가장 늦은 다른 구간에서 오정지 2% 임계값을 정해, 뺀 구간의 오정지율·에피소드 탐지를 잰다."""
    d = with_roles(m41, folds, "m41", "within_run", "primary")
    dev = d[d.role.isin(["train", "validation"])].copy()
    dev["y"] = dev.Machine_Status.astype(int)
    runs = sorted(dev.run_id.unique())
    runs = [r for r in runs if (dev.run_id == r).sum() >= cfg["min_run_size"]]
    out = []
    for r in runs:
        others = [x for x in runs if x != r]
        thr_run = max(others)
        tr = dev[dev.run_id.isin([o for o in others if o != thr_run])]
        th, te = dev[dev.run_id == thr_run], dev[dev.run_id == r].sort_values("source_row")
        if tr.y.nunique() < 2:
            continue
        m = make(model, seed, cfg)
        m.fit(tr[feats], tr.y)
        thr = threshold_max_fpr(th.y, m.predict_proba(th[feats])[:, 1], cfg["gate_max_validation_fpr"])
        alarm = m.predict_proba(te[feats])[:, 1] >= thr
        det = n = 0
        for _, g in te.assign(a=alarm)[te.episode_id.notna().to_numpy()].groupby("episode_id"):
            n += 1
            det += bool(g.a.to_numpy()[:cfg["gate_detect_within_shots"]].any())
        out.append({"run": int(r), "fpr": float(alarm[te.y.to_numpy() == 0].mean()), "detected": det, "episodes": n})
    return pd.DataFrame(out)


# ───────────────────────── 검증 방식 비교 ─────────────────────────
def _random_split_eval(frame, feats, model, seed, cfg, protocol):
    from sklearn.model_selection import train_test_split
    tr, te = train_test_split(frame, test_size=0.3, random_state=seed, stratify=frame.y_defect)
    m = make(model, seed, cfg)
    m.fit(tr[feats], tr.y_defect)
    p = m.predict_proba(te[feats])[:, 1]
    return {"kind": "protocol", "scheme": protocol, "fold": "random70_30", "experiment": "A", "model": model,
            "seed": seed, "target": "y_defect", "population": "all", "delay": None, "role": "test",
            **score(te.y_defect, p, threshold_f1(te.y_defect, p))}


def protocol_comparison(joined, folds, feats, model, seeds, cfg, jobs):
    """가이드북식(중복 포함 무작위) → 중복 제거 무작위 → 구간 내 시간순 → 새 구간 순으로 같은 모델을 평가한다."""
    from .prepare import build_quality, with_run
    raw = pd.read_csv(paths.RAW_Q42, header=1)
    raw.columns = raw.columns.str.strip()
    raw = with_run(raw, "q42")
    types = [c[:-2] for c in raw.columns if c.endswith("_1") and c not in feats]
    raw["y_defect"] = raw[[f"{k}_{c}" for c in [1, 2] for k in types]].gt(0).any(axis=1).astype(int)
    raw["shot_position"] = raw.groupby("run_id").cumcount()
    jobs_list = [delayed(_random_split_eval)(raw, feats, model, s, cfg, "random_with_duplicates") for s in seeds]
    jobs_list += [delayed(_random_split_eval)(joined, feats, model, s, cfg, "random_dedup") for s in seeds]
    return Parallel(n_jobs=jobs, backend="loky")(jobs_list)


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

    # 1b) 사전 등록한 추가 탐색: 하이퍼파라미터 격자·Cavity 결합·유형 결합·앙상블·B_FB
    #     개발구간 확장창 3-fold 평균 AP로만 비교하고, 현재 최종 대비 +adoption_min_gain 이상일 때만 교체한다.
    dev_q = _dev_part(qframe("within_run", "primary", delay))
    cm = cfg["candidate_models"]
    specs = {f"현재 최종: {final['experiment']}·{final['model']}": (final["experiment"], final["model"], None, None)}
    for name, grid in cfg["quality_search"].items():
        keys = list(grid)
        for vals in itertools.product(*[grid[k] for k in keys]):
            prm = {**cm[name], **dict(zip(keys, vals))}
            specs[f"{name} " + " ".join(f"{k}={v}" for k, v in zip(keys, vals))] = ("A_FB", name, prm, None)
    specs["Cavity1·2 분리 후 결합 (RF)"] = ("A_FB", "random_forest", None, ["y_cavity_1", "y_cavity_2"])
    specs["불량유형 5종 분리 후 결합 (RF)"] = ("A_FB", "random_forest", None, TYPE_TARGETS)
    specs["앙상블 (LR+LGBM+CatBoost)"] = ("A_FB", "ensemble", None, None)
    specs["B_FB (#41 이력 포함, RF)"] = ("B_FB", "random_forest", None, None)
    jobs_l = [(k, sd) for k in specs for sd in seeds]
    res = Parallel(n_jobs=jobs, backend="loky")(
        delayed(inner_cv_ap)(dev_q, sets[specs[k][0]], specs[k][1], specs[k][2], sd, cfg, "y_defect", specs[k][3]) for k, sd in jobs_l)
    srch = pd.DataFrame([{"candidate": k, "seed": sd, "inner_cv_ap": v} for (k, sd), v in zip(jobs_l, res)])
    srch = srch.groupby("candidate", sort=False).inner_cv_ap.agg(["mean", "std"]).reset_index()
    base_ap = srch.iloc[0]["mean"]
    srch["gain_vs_current"] = srch["mean"] - base_ap
    srch["adoptable"] = (srch.gain_vs_current >= cfg["adoption_min_gain"]) & (srch.gain_vs_current > 2 * srch["std"].fillna(0))
    srch = srch.sort_values("mean", ascending=False)
    srch.round(4).to_csv(paths.TABLES / "model_search_inner_cv.csv", index=False, encoding="utf-8-sig")
    adopt = srch[srch.adoptable & srch.candidate.map(lambda k: specs[k][3] is None)]
    final["search"] = {"candidates": len(specs), "current_inner_cv_ap": round(float(base_ap), 4),
                       "best": srch.iloc[0].candidate, "best_gain": round(float(srch.iloc[0].gain_vs_current), 4),
                       "adopted": None}
    final_params = None
    if len(adopt):
        k = adopt.iloc[0].candidate
        final.update(experiment=specs[k][0], model=specs[k][1])
        final_params = specs[k][2]
        final["search"]["adopted"] = k
    log(f"[1b] 추가 탐색 {len(specs)}개 후보: 최고 이득 {final['search']['best_gain']:+.4f} → 채택 {final['search']['adopted']}")

    # 2) 실패 조건: 구간 이동·새 미래 구간
    abl = ["A0", "A", "B", "A_FB", "B_FB"]
    frames = {("quality", s, f, "all", delay): qframe(s, f, delay) for s, f in q_schemes if s != "within_run"}
    tasks = [_task("quality", s, f, e, final["model"], sd, "y_defect", sets[e], delay=delay, params=final_params)
             for s, f in q_schemes if s != "within_run" for e in abl for sd in seeds]
    if final_params is not None:      # 채택된 탐색 설정을 within_run에서도 평가 (보고용)
        tasks += [_task("quality", "within_run", "primary", e, final["model"], sd, "y_defect", sets[e], delay=delay,
                        params=final_params) for e in abl for sd in seeds]
        frames[("quality", "within_run", "primary", "all", delay)] = qframe("within_run", "primary", delay)
    log(f"[2/6] 품질 run_holdout·forward_run: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 3) 검사결과 지연 민감도
    fb_exp = final["experiment"] if "FB" in final["experiment"] else "A_FB"
    dl = [d for d in cfg["label_delay_sensitivity"] if d != delay]
    frames = {("quality", "within_run", "primary", "all", d): qframe("within_run", "primary", d) for d in dl}
    tasks = [_task("quality", "within_run", "primary", fb_exp, final["model"], s, "y_defect", sets[fb_exp], delay=d,
                   params=final_params) for d in dl for s in seeds]
    log(f"[3/6] 지연 민감도 {dl}: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 3b) 검사결과 회신율 민감도 (일부만 회신되는 경우)
    covs = [c for c in cfg["feedback_coverage_sensitivity"] if c < 1.0]
    frames = {("quality", "within_run", "primary", f"cov{c}", delay):
              with_roles(add_feedback(joined, delay, windows, cfg["feedback_halflife"], coverage=c, seed=7),
                         folds, "q42", "within_run", "primary") for c in covs}
    tasks = [_task("quality", "within_run", "primary", fb_exp, final["model"], s, "y_defect", sets[fb_exp],
                   population=f"cov{c}", delay=delay, params=final_params) for c in covs for s in seeds]
    log(f"[3b] 회신율 민감도 {covs}: {len(tasks)}회")
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows; all_preds += preds

    # 3b') 참고 상한: '정답' 설비상태 이력(oracle_*)을 넣으면 품질예측이 얼마나 좋아지는가
    #      운영에서는 쓸 수 없는 정보다(입력 계약상 금지). #41 이력의 최대 가치를 가늠하는 분석 전용 실험.
    oracle = ["oracle_shots_since_warm", "oracle_prior_episodes"]
    base_exp = final["experiment"]
    frames = {("quality_ref", "within_run", "primary", "all", delay): qframe("within_run", "primary", delay)}
    tasks = [_task("quality_ref", "within_run", "primary", f"{base_exp}+oracle", final["model"], s, "y_defect",
                   sets[base_exp] + oracle, delay=delay, params=final_params) for s in seeds]
    rows, preds = _run_tasks(tasks, frames, cfg, jobs)
    all_rows += rows
    log(f"[3b'] 참고 상한(정답 설비상태 이력): {len(tasks)}회")

    # 3c) 검증 방식 비교: 같은 입력(A)·같은 모델을 검증 방식만 바꿔 평가 (숫자가 왜 낮은지의 근거)
    prot_rows = protocol_comparison(joined, folds, sets["A"], final["model"], seeds, cfg, jobs)
    all_rows += prot_rows
    log(f"[3c] 검증 방식 비교: {len(prot_rows)}행")

    # 4) 설비상태 Gate: 구간 이동 견고성(LORO, 개발구간만)으로 입력·모델 선정
    #    규칙: 구간별 최대 오정지율 ≤ gate_max_cross_run_fpr 인 후보 중 에피소드 탐지 최대, 동률이면 평균 오정지 최소
    gsets = {"공정+이력": contract["m41_gate"], "공정+이력+구간상대값": contract["m41_gate_rel"]}
    for fs in gsets.values():
        check_features(fs, contract)
    gcands = [(gname, mname) for gname in gsets for mname in ["logistic", "random_forest", "lightgbm", "catboost", "xgboost"]]
    gj = [(gn, mn, sd) for gn, mn in gcands for sd in seeds[:3]]
    gres = Parallel(n_jobs=jobs, backend="loky")(delayed(gate_loro)(m41, folds, gsets[gn], mn, sd, cfg) for gn, mn, sd in gj)
    grow = []
    for (gn, mn, sd), d in zip(gj, gres):
        grow.append({"features": gn, "model": mn, "seed": sd, "max_fpr": d.fpr.max(), "mean_fpr": d.fpr.mean(),
                     "detected": d.detected.sum(), "episodes": d.episodes.sum()})
    gsel = pd.DataFrame(grow).groupby(["features", "model"]).agg(max_fpr=("max_fpr", "mean"), mean_fpr=("mean_fpr", "mean"),
                                                                 detected=("detected", "mean"), episodes=("episodes", "first")).reset_index()
    ok = gsel[gsel.max_fpr <= cfg["gate_max_cross_run_fpr"]]
    pick = (ok.sort_values(["detected", "mean_fpr"], ascending=[False, True]) if len(ok)
            else gsel.sort_values(["max_fpr", "detected"], ascending=[True, False])).iloc[0]
    gsel["selected"] = (gsel.features == pick.features) & (gsel.model == pick.model)
    gsel.round(4).to_csv(paths.TABLES / "gate_selection_loro.csv", index=False, encoding="utf-8-sig")
    gfeat, gate_model = gsets[pick.features], pick.model
    log(f"[4/6] Gate 선정(구간 이동 견고성): {pick.features} · {gate_model} (최대 오정지 {pick.max_fpr:.3f})")
    g_schemes = [(s, f) for s, f in folds.loc[folds.dataset == "m41", ["scheme", "fold"]].drop_duplicates().itertuples(index=False)]
    gframes = {("gate", s, f, "all", None): with_roles(m41, folds, "m41", s, f).query("role != 'excluded'")
               .assign(Machine_Status=lambda d: d.Machine_Status.astype(int)) for s, f in g_schemes}
    tasks = [_task("gate", s, f, "Gate", gate_model, sd, "Machine_Status", gfeat) for s, f in g_schemes for sd in seeds]
    rows, preds = _run_tasks(tasks, gframes, cfg, jobs)
    all_rows += rows; all_preds += preds
    gbest = pick

    # 5) 불량유형: 유형마다 모델군을 개발구간 확장창 CV로 비교, 기본(최종 품질모델) 대비 +adoption_min_gain 이상이면 교체
    frames_q = qframe("within_run", "primary", delay)
    tframe = {("type", "within_run", "primary", "all", delay): frames_q}
    fexp = final["experiment"]
    tj = [(t, mn, sd) for t in TYPE_TARGETS for mn in ["random_forest", "logistic", "lightgbm", "catboost"] for sd in seeds[:3]]
    tres = Parallel(n_jobs=jobs, backend="loky")(delayed(inner_cv_ap)(dev_q, sets[fexp], mn, None, sd, cfg, t) for t, mn, sd in tj)
    tsel = pd.DataFrame([{"target": t, "model": mn, "seed": sd, "inner_cv_ap": v} for (t, mn, sd), v in zip(tj, tres)])
    tsel = tsel.groupby(["target", "model"]).inner_cv_ap.mean().reset_index()
    type_models = {}
    for t, g in tsel.groupby("target"):
        default = g[g.model == final["model"]].inner_cv_ap.iloc[0] if (g.model == final["model"]).any() else -1
        best = g.sort_values("inner_cv_ap", ascending=False).iloc[0]
        type_models[t] = best.model if best.inner_cv_ap - default >= cfg["adoption_min_gain"] else final["model"]
    tsel["selected"] = [type_models[t] == mn for t, mn in zip(tsel.target, tsel.model)]
    tsel.round(4).to_csv(paths.TABLES / "defect_type_model_selection.csv", index=False, encoding="utf-8-sig")
    tasks = [_task("type", "within_run", "primary", fexp, type_models[t], s, t, sets[fexp], delay=delay,
                   params=final_params if type_models[t] == final["model"] else None)
             for t in TYPE_TARGETS for s in seeds]
    log(f"[5/6] 불량유형 모델: {type_models}")
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
                             "y_defect", sets[final["experiment"]], delay=delay, params=final_params), cfg, save_model=True)
    fit_eval(gframes[("gate", "within_run", "primary", "all", None)],
             _task("gate", "within_run", "primary", "Gate", gate_model, seeds[0], "Machine_Status", gfeat), cfg, save_model=True)
    for t in TYPE_TARGETS:
        fit_eval(frames_q, _task("type", "within_run", "primary", final["experiment"], type_models[t], seeds[0], t,
                                 sets[final["experiment"]], delay=delay), cfg, save_model=True)

    metrics = pd.DataFrame(all_rows)
    preds = pd.concat(all_preds, ignore_index=True)
    metrics.to_csv(paths.RUNS / "metrics.csv", index=False)
    preds.to_parquet(paths.RUNS / "predictions.parquet", index=False)
    selection = {"final_quality": final, "final_params": final_params, "gate_model": gate_model,
                 "gate_features": str(gbest.features), "gate_loro_max_fpr": float(gbest.max_fpr), "type_models": type_models,
                 "feedback_experiment_for_sensitivity": fb_exp, "label_delay_shots": delay,
                 "feature_sets": sets}
    (paths.RUNS / "selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"학습 완료: 지표 {len(metrics)}행, 예측 {len(preds)}행")
    return selection
