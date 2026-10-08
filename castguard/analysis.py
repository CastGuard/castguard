"""학습 결과 → 보고서용 표·그림·예측파일.

모든 운영 임계값(검사율·비용·Gate)은 validation 예측으로 정하고 test에 그대로 적용한다.
"""
import json

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from . import paths
from .features import add_feedback
from .metrics import ece, threshold_rate
from .models import build_model

KEYS = ["kind", "scheme", "fold", "experiment", "model", "population", "delay"]


def _ms(s):
    return f"{s.mean():.3f} ± {s.std(ddof=1):.3f}" if len(s) > 1 else f"{s.mean():.3f}"


def _safe_auc(y, p):
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else np.nan


def _safe_ap(y, p):
    return float(average_precision_score(y, p)) if len(np.unique(y)) == 2 else np.nan


def _save(df, name):
    df.to_csv(paths.TABLES / name, index=False, encoding="utf-8-sig")
    return df


def seed_mean(preds: pd.DataFrame, **filt) -> pd.DataFrame:
    """조건에 맞는 예측을 seed 평균 확률로 합친다 (row_id × role)."""
    d = preds
    for k, v in filt.items():
        d = d[d[k].isna()] if v is None else d[d[k] == v]
    return d.groupby(["row_id", "role"], as_index=False).agg(y=("y", "first"), p=("p", "mean"), threshold=("threshold", "mean"))


# ───────────────────────── 1~4. 모델 비교·Ablation·실패조건·지연 ─────────────────────────
def model_tables(metrics, sel):
    q = metrics[(metrics.kind == "quality") & (metrics.scheme == "within_run") & (metrics.population == "all")]
    d = sel["label_delay_shots"]
    base = q[q.delay == d]
    rows = []
    for (e, m), g in base.groupby(["experiment", "model"]):
        v, t = g[g.role == "validation"], g[g.role == "test"]
        rows.append({"experiment": e, "model": m, "val_ap": v.average_precision.mean(), "val_ap_sd": v.average_precision.std(ddof=1),
                     "val_auc": v.roc_auc.mean(), "val_ece": v.ece.mean(), "test_ap": t.average_precision.mean(),
                     "test_ap_sd": t.average_precision.std(ddof=1), "test_auc": t.roc_auc.mean(),
                     "test_auc_sd": t.roc_auc.std(ddof=1), "test_ap_lift": t.ap_lift.mean(), "fit_seconds": g.fit_seconds.mean()})
    comp = pd.DataFrame(rows).sort_values("val_ap", ascending=False)
    comp["selected"] = (comp.experiment == sel["final_quality"]["experiment"]) & (comp.model == sel["final_quality"]["model"])
    _save(comp.round(4), "model_comparison.csv")

    fm = sel["final_quality"]["model"]
    f = base[base.model == fm]
    abl = []
    labels = {"A0": "공정 14 (베이스라인)", "A": "주 데이터 전체 (+센서·제품·순번)", "B": "A + #41 가동이력 (보조1)",
              "FB": "검사결과 피드백 단독", "A_FB": "A + 검사결과 피드백", "B_FB": "B + 검사결과 피드백"}
    for e in labels:
        g = f[f.experiment == e]
        v, t = g[g.role == "validation"], g[g.role == "test"]
        abl.append({"experiment": e, "inputs": labels[e], "model": fm, "val_ap": _ms(v.average_precision),
                    "test_ap": _ms(t.average_precision), "test_auc": _ms(t.roc_auc), "test_ap_lift": round(t.ap_lift.mean(), 2),
                    "test_prevalence": round(t.prevalence.mean(), 4)})
    _save(pd.DataFrame(abl), "ablation.csv")

    def gain(a, b, role):
        x = f[(f.role == role)].pivot_table(index="seed", columns="experiment", values="average_precision")
        diff = x[b] - x[a]
        return float(diff.mean()), float(diff.std(ddof=1))
    dec = {}
    for a, b, name in [("A", "B", "보조1(#41 이력) 효과"), ("A_FB", "B_FB", "보조1 효과(피드백 포함)"),
                       ("A", "A_FB", "검사결과 피드백 효과"), ("A0", "A", "센서·제품·순번 효과")]:
        gv, sv = gain(a, b, "validation")
        gt, st = gain(a, b, "test")
        dec[name] = {"from": a, "to": b, "val_gain": round(gv, 4), "val_sd": round(sv, 4), "test_gain": round(gt, 4),
                     "test_sd": round(st, 4), "pass_rule(+0.02 & >2sd on validation)": bool(gv >= 0.02 and gv > 2 * sv)}
    (paths.TABLES / "ablation_decisions.json").write_text(json.dumps(dec, ensure_ascii=False, indent=2), encoding="utf-8")

    fail = metrics[(metrics.kind == "quality") & metrics.scheme.isin(["run_holdout", "forward_run"]) & (metrics.role == "test")]
    ft = fail.groupby(["scheme", "fold", "experiment"]).agg(n=("n", "first"), prevalence=("prevalence", "first"),
                                                           test_auc=("roc_auc", "mean"), test_ap=("average_precision", "mean")).reset_index()
    _save(ft.round(4), "failure_conditions.csv")

    fb = sel["feedback_experiment_for_sensitivity"]
    s = q[(q.experiment == fb) & (q.model == fm) & (q.role == "test")].groupby("delay").agg(
        test_auc=("roc_auc", "mean"), test_ap=("average_precision", "mean"), test_ap_lift=("ap_lift", "mean")).reset_index()
    _save(s.round(4), "delay_sensitivity.csv")
    return comp, dec


def protocol_table(metrics, sel):
    """같은 입력(A)·같은 모델을 검증 방식만 바꿔 평가: 숫자가 낮은 이유가 '정직한 검증'임을 보인다."""
    fm, d = sel["final_quality"]["model"], sel["label_delay_shots"]
    t = metrics[metrics.role == "test"]
    rows = []
    desc = {"random_with_duplicates": ("① 가이드북식: 중복 포함·무작위 70/30", "같은 Shot이 학습·평가에 동시에 들어감 → 부풀려짐"),
            "random_dedup": ("② 중복 제거·무작위 70/30", "이웃 Shot이 섞여 여전히 낙관적"),
            "within_run": ("③ 중복 제거·구간 내 시간순 (최종 기준)", "과거로 학습해 같은 구간의 미래를 예측"),
            "run_holdout": ("④ 구간 하나 통째로 제외", "학습에 없던 구간 (다른 구간의 미래 포함)"),
            "forward_run": ("⑤ 앞선 구간으로만 학습 → 다음 구간", "완전히 새로운 미래 구간 (실패 조건)")}
    for scheme, (name, meaning) in desc.items():
        if scheme.startswith("random"):
            g = t[(t.kind == "protocol") & (t.scheme == scheme)]
        else:
            g = t[(t.kind == "quality") & (t.scheme == scheme) & (t.experiment == "A") & (t.model == fm) & (t.population == "all")]
        rows.append({"protocol": name, "meaning": meaning, "test_auc": round(g.roc_auc.mean(), 3),
                     "test_ap": round(g.average_precision.mean(), 3), "test_ap_lift": round(g.ap_lift.mean(), 2), "evaluations": len(g)})
    f = sel["final_quality"]
    g = t[(t.kind == "quality") & (t.scheme == "within_run") & (t.experiment == f["experiment"]) & (t.model == fm)
          & (t.population == "all") & (t.delay == d)]
    rows.append({"protocol": f"③' 최종 모델 ({f['experiment']}: 검사결과 피드백 포함)", "meaning": "③과 같은 검증, 피드백 추가",
                 "test_auc": round(g.roc_auc.mean(), 3), "test_ap": round(g.average_precision.mean(), 3),
                 "test_ap_lift": round(g.ap_lift.mean(), 2), "evaluations": len(g)})
    return _save(pd.DataFrame(rows), "validation_protocols.csv")


def oracle_table(metrics, sel):
    f = sel["final_quality"]
    t = metrics[(metrics.scheme == "within_run") & (metrics.model == f["model"]) & (metrics.population == "all")
                & (metrics.delay == sel["label_delay_shots"])]
    base = t[(t.kind == "quality") & (t.experiment == f["experiment"])]
    ref = t[(t.kind == "quality_ref")]
    rows = []
    for name, g in [(f"{f['experiment']} (운영 입력)", base), (f"{f['experiment']} + 정답 설비상태 이력 (참고 상한)", ref)]:
        v, te = g[g.role == "validation"], g[g.role == "test"]
        rows.append({"inputs": name, "val_ap": round(v.average_precision.mean(), 4), "test_ap": round(te.average_precision.mean(), 4),
                     "test_auc": round(te.roc_auc.mean(), 4)})
    out = pd.DataFrame(rows)
    out["val_ap_gain_vs_operational"] = (out.val_ap - out.val_ap.iloc[0]).round(4)
    return _save(out, "ablation_oracle_upper_bound.csv")


def coverage_table(metrics, sel):
    fm, d, e = sel["final_quality"]["model"], sel["label_delay_shots"], sel["feedback_experiment_for_sensitivity"]
    t = metrics[(metrics.kind == "quality") & (metrics.scheme == "within_run") & (metrics.role == "test")
                & (metrics.experiment == e) & (metrics.model == fm) & (metrics.delay == d)]
    t = t[t.population.isin(["all"]) | t.population.str.startswith("cov")]
    out = t.assign(coverage=t.population.map(lambda x: 1.0 if x == "all" else float(x[3:]))).groupby("coverage").agg(
        test_auc=("roc_auc", "mean"), test_ap=("average_precision", "mean"), test_ap_lift=("ap_lift", "mean")).reset_index()
    a = metrics[(metrics.kind == "quality") & (metrics.scheme == "within_run") & (metrics.role == "test") & (metrics.experiment == "A")
                & (metrics.model == fm) & (metrics.population == "all")]
    out = pd.concat([out.sort_values("coverage", ascending=False),
                     pd.DataFrame([{"coverage": 0.0, "test_auc": a.roc_auc.mean(), "test_ap": a.average_precision.mean(),
                                    "test_ap_lift": a.ap_lift.mean()}])], ignore_index=True)
    return _save(out.round(4), "feedback_coverage.csv")


# ───────────────────────── 5~6. Gate · 적용범위(C) ─────────────────────────
def adaptive_alarm(d: pd.DataFrame, cfg: dict) -> np.ndarray:
    """적응형 Gate 임계값: 구간 안에서 작업자가 '정상'으로 확인한 과거 Shot(지연 반영)의 점수 98% 분위를
    기존 임계값의 하한으로 삼는다. 새 운전점(예: 압력 수준이 다른 구간)에서 정상 Shot이 계속 경보되는 것을 막는다."""
    p, y = d.p.to_numpy(), d.y.to_numpy()
    base, delay, mh = d.threshold.iloc[0], cfg["gate_adapt_delay"], cfg["gate_adapt_min_history"]
    thr = np.full(len(d), base)
    for t in range(len(d)):
        past = p[:max(0, t - delay)][y[:max(0, t - delay)] == 0]
        if len(past) >= mh:
            thr[t] = max(base, np.quantile(past, 1 - cfg["gate_max_validation_fpr"]))
    return p >= thr


def gate_tables(metrics, preds, m41, cfg, sel):
    g = metrics[metrics.kind == "gate"]
    comp = g[(g.scheme == "within_run")].groupby(["model", "role"]).agg(ap=("average_precision", "mean"), auc=("roc_auc", "mean"),
                                                                       fpr=("fpr", "mean"), recall=("recall", "mean")).reset_index()
    _save(comp.round(4), "gate_model_comparison.csv")
    k = cfg["gate_detect_within_shots"]
    info = m41.set_index("row_id")[["run_id", "Shot", "episode_id", "source_row"]]
    rows = []
    gp = preds[(preds.kind == "gate") & (preds.model == sel["gate_model"]) & (preds.role == "test")]
    for (scheme, fold, seed, policy), d in [(key + (pol,), d) for key, d in gp.groupby(["scheme", "fold", "seed"])
                                           for pol in ["고정", "적응형"]]:
        d = d.join(info, on="row_id").sort_values("source_row")
        if policy == "고정":
            alarm = d.p >= d.threshold
        else:
            alarm = pd.Series(np.concatenate([adaptive_alarm(g, cfg) for _, g in d.groupby("run_id", sort=False)]), index=d.index)
        normal = d.y == 0
        eps = d[d.episode_id.notna()].groupby("episode_id")
        det, delay = 0, []
        for _, e in eps:
            a = alarm.loc[e.index].to_numpy()
            hit = np.flatnonzero(a[:k])
            if len(hit):
                det += 1
                delay.append(hit[0] + 1)
        rows.append({"policy": policy, "scheme": scheme, "fold": fold, "seed": seed, "episodes": eps.ngroups, "detected_within_k": det,
                     "mean_shots_to_detect": np.mean(delay) if delay else np.nan,
                     "warmup_rows": int((d.y == 1).sum()), "warmup_row_recall": float(alarm[d.y == 1].mean()) if (d.y == 1).any() else np.nan,
                     "false_stop_rate": float(alarm[normal].mean()) if normal.any() else np.nan,
                     "row_auc": _safe_auc(d.y, d.p)})
    ge = pd.DataFrame(rows)
    gs = ge.groupby(["policy", "scheme", "fold"]).agg(episodes=("episodes", "first"), detected_within_k=("detected_within_k", "mean"),
                                            mean_shots_to_detect=("mean_shots_to_detect", "mean"),
                                            warmup_row_recall=("warmup_row_recall", "mean"),
                                            false_stop_rate=("false_stop_rate", "mean"), row_auc=("row_auc", "mean")).reset_index()
    _save(gs.round(4), "gate_results.csv")
    w = gs[(gs.scheme == "within_run") & (gs.policy == "적응형")].iloc[0]
    # C: 적용 범위 확장 — #42 단독 모델은 예열 Shot도 정상처럼 품질판정한다.
    total_rows = int(m41.gate_eligible.sum())
    c = pd.DataFrame([
        {"flow": "#42 단독 (Gate 없음)", "warmup_shots_judged_as_normal_pct": 100.0,
         "warmup_episodes_caught": 0, "normal_shots_held_pct": 0.0},
        {"flow": "Gate + #42 (CastGuard)", "warmup_shots_judged_as_normal_pct": round(100 * (1 - w.warmup_row_recall), 1),
         "warmup_episodes_caught": f"{w.detected_within_k:.1f} / {int(w.episodes)} (첫 {k} Shot 이내)",
         "normal_shots_held_pct": round(100 * w.false_stop_rate, 2)}])
    _save(c, "ablation_C_gate_coverage.csv")
    return gs


# ───────────────────────── 7~9. 유형 · #40(E) · 물리방향(F) ─────────────────────────
def type_table(metrics):
    t = metrics[(metrics.kind == "type") & (metrics.role == "test")]
    out = t.groupby("target").agg(model=("model", "first"), test_positive=("positive", "first"), prevalence=("prevalence", "first"),
                                  test_auc=("roc_auc", "mean"), test_auc_sd=("roc_auc", "std"),
                                  test_ap=("average_precision", "mean"), test_ap_lift=("ap_lift", "mean")).reset_index()
    out["target"] = out.target.str.replace("y_type_", "")
    return _save(out.round(4), "defect_type_results.csv")


def p40_table(metrics):
    p = metrics[(metrics.kind == "p40")]
    out = p.groupby(["population", "experiment", "model", "role"]).agg(auc=("roc_auc", "mean"), auc_sd=("roc_auc", "std"),
                                                                    ap=("average_precision", "mean"), prevalence=("prevalence", "first"),
                                                                    n=("n", "first")).reset_index()
    return _save(out.round(4), "ablation_E_p40.csv")


def physics_table(joined, p40, folds, cfg):
    qt = folds[(folds.dataset == "q42") & (folds.scheme == "within_run") & (folds.role == "train")].row_id
    pt = folds[(folds.dataset == "p40") & (folds.role == "train")].row_id
    q = joined[joined.row_id.isin(qt)]
    p = p40[p40.row_id.isin(pt)]
    rows = []
    for m in cfg["physical_map"]:
        r42 = q[[m["q42"], "y_defect"]].corr(method="spearman").iloc[0, 1]
        sub = p.dropna(subset=[m["p40"]])
        r40 = sub[[m["p40"], "y_defect"]].astype(float).corr(method="spearman").iloc[0, 1]
        rn = sub[sub.normal_pressure.fillna(False).astype(bool)][[m["p40"], "y_defect"]].astype(float).corr(method="spearman").iloc[0, 1]
        rows.append({"concept": m["concept"], "q42_var": m["q42"], "rho_q42": round(r42, 3), "p40_var": m["p40"],
                     "rho_p40_all": round(r40, 3), "rho_p40_normal_pressure": round(rn, 3),
                     "same_direction(all)": bool(np.sign(r42) == np.sign(r40))})
    return _save(pd.DataFrame(rows), "ablation_F_physics_direction.csv")


# ───────────────────────── 10~12. 최종 예측 · KPI · 조건별 오류 ─────────────────────────
def final_predictions(preds, sel):
    f = sel["final_quality"]
    return seed_mean(preds, kind="quality", scheme="within_run", experiment=f["experiment"], model=f["model"],
                     delay=sel["label_delay_shots"], population="all")


def kpi_tables(fp, cfg):
    v, t = fp[fp.role == "validation"], fp[fp.role == "test"]
    rows = []
    for rate in cfg["inspection_rates"]:
        thr = threshold_rate(v.p, rate)
        a = t.p >= thr
        cap = float(a[t.y == 1].mean())
        rows.append({"target_inspection_rate": rate, "test_inspection_rate": round(float(a.mean()), 4),
                     "capture_rate": round(cap, 4), "random_capture_rate": round(float(a.mean()), 4),
                     "lift_vs_random": round(cap / max(a.mean(), 1e-9), 2), "precision": round(float(t.y[a].mean()), 4),
                     "defects_caught": int((a & (t.y == 1)).sum()), "defects_total": int(t.y.sum()),
                     "inspections": int(a.sum()), "shots": len(t)})
    insp = _save(pd.DataFrame(rows), "kpi_inspection.csv")
    # 비용 민감도: 비용 = r × 놓친 불량 + 1 × 추가검사 건수 (단가 미확보 → 비율로만)
    cost_rows = []
    grid = np.unique(np.quantile(v.p, np.linspace(0, 1, 201)))
    for r in cfg["cost_ratios"]:
        costs = [r * ((v.p < g) & (v.y == 1)).sum() + (v.p >= g).sum() for g in grid]
        g = grid[int(np.argmin(costs))]
        a = t.p >= g
        model_cost = r * int(((~a) & (t.y == 1)).sum()) + int(a.sum())
        all_cost, none_cost = len(t), r * int(t.y.sum())
        rnd_cost = r * t.y.sum() * (1 - a.mean()) + a.sum()
        cost_rows.append({"cost_ratio_miss_to_inspect": r, "chosen_inspection_rate": round(float(a.mean()), 4),
                          "model_cost": model_cost, "inspect_all_cost": all_cost, "inspect_none_cost": none_cost,
                          "random_same_rate_cost": round(float(rnd_cost), 1),
                          "saving_vs_best_baseline_pct": round(100 * (1 - model_cost / min(all_cost, none_cost)), 1),
                          "saving_vs_random_pct": round(100 * (1 - model_cost / rnd_cost), 1)})
    cost = _save(pd.DataFrame(cost_rows), "kpi_cost_sensitivity.csv")
    return insp, cost


# ───────────────────────── 12b. 슬롯 기반 검사 대기열 KPI (JH 방식 보조 KPI) ─────────────────────────
QUEUE_POLICIES = ("FIFO", "Q", "GQ")


def queue_capacity(n: int, budget: float) -> int:
    from fractions import Fraction
    r = Fraction(budget).limit_denominator(1000)
    return n * r.numerator // r.denominator


def stream_queue(rows: pd.DataFrame, policy: str, budget: float) -> pd.DataFrame:
    """한 가동구간의 Shot을 도착 순서(source_row)대로 흘려보내며 검사 슬롯을 배정한다.
    - 도착 i마다 floor((i+1)b) - floor(ib)개의 슬롯이 생기고, 쓰지 않은 슬롯은 이월하지 않는다.
    - 우선순위: 공정값 결측(보류) → Gate 경보(GQ만, Gate 확률 높은 순) → 품질위험(높은 순, FIFO는 도착 순).
    - 입력은 점수·관측값뿐이며 정답 라벨과 미래 행은 읽지 않는다."""
    import heapq
    from fractions import Fraction
    if policy not in QUEUE_POLICIES:
        raise ValueError(policy)
    r = Fraction(budget).limit_denominator(1000)
    rows = rows.sort_values("source_row").reset_index(drop=True)
    n = len(rows)
    hold = rows.process_missing.to_numpy(bool)
    alarm = rows.gate_alarm.to_numpy(bool) & ~hold & (policy == "GQ")
    q = rows.quality_p.to_numpy(float)
    inspected = np.zeros(n, bool)
    served = np.full(n, -1)
    reason = np.full(n, "none", dtype=object)
    heap = []
    for i in range(n):
        if hold[i]:
            key, reason[i] = (0, 0.0, i), "hold"
        elif alarm[i]:
            key, reason[i] = (1, -float(rows.gate_p.iat[i]), i), "gate"
        elif np.isfinite(q[i]):
            key, reason[i] = (2, 0.0 if policy == "FIFO" else -q[i], i), "quality"
        else:
            key = None
        if key is not None:
            heapq.heappush(heap, key)
        for _ in range((i + 1) * r.numerator // r.denominator - i * r.numerator // r.denominator):
            if heap:
                j = heapq.heappop(heap)[-1]
                inspected[j], served[j] = True, i
    assert inspected.sum() <= queue_capacity(n, budget)
    out = rows.assign(inspected=inspected, reason=reason, wait_records=np.where(inspected, served - np.arange(n), np.nan),
                      left_in_queue=(reason != "none") & ~inspected)
    return out


def queue_kpi(fp, preds, joined, m41, folds, sel, cfg):
    """운영 현실 보조 KPI: 검사 능력이 Shot마다 일정 비율로만 생긴다는 제약 하에서 실제로 잡히는 불량 비율.
    오프라인 임계값 KPI(kpi_inspection.csv)는 test 전체를 본 뒤 상위 k%를 고르는 것과 같지만, 이 KPI는
    도착 순서대로만 결정하므로 더 보수적이다. 정책·예산은 미리 정하고 test 결과로 고르지 않는다."""
    ids = folds[(folds.dataset == "m41") & (folds.scheme == "within_run") & (folds.role == "test")].row_id
    base = m41[m41.row_id.isin(ids)][["row_id", "run_id", "Shot", "source_row", "process_missing", "Machine_Status", "episode_id"]]
    q = fp[fp.role == "test"].merge(joined[["row_id", "run_id", "Shot"]], on="row_id")
    q = q.assign(m41_row_id="m41_r" + q.run_id.astype(str) + "_s" + q.Shot.astype(str))[["m41_row_id", "p", "y"]]
    q.columns = ["row_id", "quality_p", "y_defect"]
    g = seed_mean(preds, kind="gate", scheme="within_run", model=sel["gate_model"])
    g = g[g.role == "test"].merge(m41[["row_id", "run_id", "source_row"]], on="row_id").sort_values("source_row")
    g["gate_alarm"] = np.concatenate([adaptive_alarm(x, cfg) for _, x in g.groupby("run_id", sort=False)])
    d = base.merge(q, on="row_id", how="left").merge(g[["row_id", "p", "gate_alarm"]].rename(columns={"p": "gate_p"}),
                                                       on="row_id", how="left")
    d["gate_alarm"] = d.gate_alarm.fillna(False).astype(bool)
    rows, k = [], cfg["gate_detect_within_shots"]
    for budget in cfg["inspection_rates"]:
        for policy in QUEUE_POLICIES:
            a = pd.concat([stream_queue(x, policy, budget) for _, x in d.groupby("run_id", sort=True)], ignore_index=True)
            cap = sum(queue_capacity(len(x), budget) for _, x in d.groupby("run_id"))
            labeled = a.y_defect.notna()
            pos = a.y_defect == 1
            qi = a.inspected & labeled
            eps = a[a.episode_id.notna()].groupby("episode_id")
            reach = sum(bool((e.inspected & (e.reason == "gate")).to_numpy()[:k].any()) for _, e in eps)
            capture = float((a.inspected & pos).sum() / pos.sum())
            rnd = float(qi.sum() / labeled.sum())
            rows.append({"budget": budget, "policy": policy, "arrivals": len(a), "capacity": int(cap),
                         "inspections_used": int(a.inspected.sum()),
                         "quality_inspections": int(qi.sum()), "gate_reviews": int((a.inspected & (a.reason == "gate")).sum()),
                         "defects_caught": int((a.inspected & pos).sum()), "defects_total": int(pos.sum()),
                         "capture_rate": round(capture, 4), "random_capture_rate": round(rnd, 4),
                         "lift_vs_random": round(capture / max(rnd, 1e-9), 2),
                         "precision": round(float(a.y_defect[qi].mean()), 4) if qi.any() else np.nan,
                         "warmup_episodes_reviewed_within_k": f"{reach} / {eps.ngroups}",
                         "mean_wait_records": round(float(a.wait_records.mean()), 2),
                         "p90_wait_records": round(float(a.wait_records.quantile(0.9)), 1),
                         "left_in_queue": int(a.left_in_queue.sum())})
    out = pd.DataFrame(rows)
    for b in cfg["inspection_rates"]:
        f = out[(out.budget == b) & (out.policy == "FIFO")].capture_rate.iloc[0]
        out.loc[out.budget == b, "gain_vs_fifo_pp"] = (100 * (out.loc[out.budget == b, "capture_rate"] - f)).round(1)
    return _save(out, "kpi_queue_slots.csv")


def condition_table(fp, joined, folds):
    t = fp[fp.role == "test"].merge(joined, on="row_id", suffixes=("", "_j"))
    train = joined[joined.row_id.isin(folds[(folds.dataset == "q42") & (folds.scheme == "within_run") & (folds.role == "train")].row_id)]
    axes = {"가동구간": t.run_id.astype(str), "제품": "Type " + t.Product_Type.astype(str),
            "예열 후 경과 Shot(분석용)": pd.cut(t.oracle_shots_since_warm, [0, 20, 100, 1e9], labels=["≤20", "21–100", ">100"]).astype(str)
            .replace("nan", "예열 이력 없음"),
            "센서 결측": np.where(t.Factory_Temp.isna(), "결측", "정상")}
    for v in ["Casting_Pressure", "High_Velocity", "Cycle_Time", "Melting_Furnace_Temp"]:
        qs = train[v].quantile([0.25, 0.5, 0.75]).to_numpy()
        axes[f"{v} 분위(train 기준)"] = pd.Series(np.digitize(t[v], qs), index=t.index).map({0: "Q1", 1: "Q2", 2: "Q3", 3: "Q4"})
    unc = (t.p - t.threshold).abs()
    axes["불확실성"] = np.where(unc <= unc.quantile(0.3), "높음(임계값 근처)", "낮음")
    rows = []
    for axis, lab in axes.items():
        for level, g in t.groupby(pd.Series(lab, index=t.index)):
            alarm = g.p >= g.threshold
            rows.append({"axis": axis, "level": level, "n": len(g), "positives": int(g.y.sum()),
                         "prevalence": round(float(g.y.mean()), 4), "auc": _safe_auc(g.y, g.p), "ap": _safe_ap(g.y, g.p),
                         "recall": float(alarm[g.y == 1].mean()) if g.y.sum() else np.nan,
                         "fnr": float((~alarm)[g.y == 1].mean()) if g.y.sum() else np.nan,
                         "alarm_rate": float(alarm.mean()), "ece": ece(g.y, g.p) if len(g) >= 30 else np.nan})
    # 불량유형별·Cavity별 포착률 (양성 Shot 중)
    alarm = t.p >= t.threshold
    for col, axis in [(c, "불량유형") for c in t.columns if c.startswith("y_type_") and c != "y_type_Etc"] + \
                     [("y_type_Etc", "불량유형"), ("y_cavity_1", "Cavity"), ("y_cavity_2", "Cavity")]:
        pos = t[col] == 1
        if pos.sum():
            rows.append({"axis": axis, "level": col.replace("y_type_", "").replace("y_cavity_", "cavity_"), "n": int(pos.sum()),
                         "positives": int(pos.sum()), "recall": float(alarm[pos].mean()), "fnr": float((~alarm)[pos].mean())})
    out = pd.DataFrame(rows)
    return _save(out.round(4), "error_by_condition.csv")


# ───────────────────────── 13~14. SHAP · 상호작용 · 운전창 ─────────────────────────
def explain(joined, folds, sel, cfg):
    feats = sel["feature_sets"][sel["final_quality"]["experiment"]]
    f = add_feedback(joined, sel["label_delay_shots"], cfg["feedback_windows"], cfg["feedback_halflife"])
    r = folds[(folds.dataset == "q42") & (folds.scheme == "within_run")][["row_id", "role"]]
    f = f.merge(r, on="row_id")
    tr, te = f[f.role == "train"], f[f.role == "test"]
    lgb = build_model("lightgbm", cfg["seeds"][0], cfg["candidate_models"]["lightgbm"])
    lgb.fit(tr[feats], tr.y_defect)
    Xte = pd.DataFrame(lgb.named_steps["impute"].transform(te[feats]), columns=feats, index=te.index)
    contrib = lgb.named_steps["model"].predict(Xte, pred_contrib=True)[:, :-1]
    imp = pd.DataFrame({"feature": feats, "mean_abs_shap": np.abs(contrib).mean(0),
                        "direction(corr value↔shap)": [np.corrcoef(Xte[c], contrib[:, i])[0, 1] if Xte[c].std() > 0 and contrib[:, i].std() > 0 else np.nan
                                                       for i, c in enumerate(feats)]}).sort_values("mean_abs_shap", ascending=False)
    imp["explain_model_test_auc"] = _safe_auc(te.y_defect, lgb.predict_proba(te[feats])[:, 1])
    _save(imp.round(4), "shap_importance.csv")
    # 상호작용: XGBoost SHAP interaction (shap 패키지 없이)
    inter = None
    try:
        import xgboost as xgb
        xm = build_model("xgboost", cfg["seeds"][0], cfg["candidate_models"]["xgboost"])
        xm.fit(tr[feats], tr.y_defect)
        Xi = xm.named_steps["impute"].transform(te[feats])
        iv = xm.named_steps["model"].get_booster().predict(xgb.DMatrix(Xi, feature_names=feats), pred_interactions=True)
        m = np.abs(iv[:, :-1, :-1]).mean(0)
        pairs = [(feats[i], feats[j], m[i, j] * 2) for i in range(len(feats)) for j in range(i + 1, len(feats))]
        inter = pd.DataFrame(pairs, columns=["feature_a", "feature_b", "mean_abs_interaction"]).sort_values(
            "mean_abs_interaction", ascending=False).head(15)
        _save(inter.round(5), "shap_interactions.csv")
    except Exception as exc:          # xgboost가 없으면 상호작용 표는 생략
        print(f"  상호작용 분석 생략: {exc}")
    # 운전창 후보: 고위험 Shot에서 조정 가능한 변수 하나를 관측된 정상 범위 안에서 바꿨을 때의 모델 위험
    pt = lgb.predict_proba(te[feats])[:, 1]
    hi = te.assign(p=pt).sort_values("p", ascending=False).head(max(10, int(0.05 * len(te))))
    rows = []
    for idx, shot in hi.iterrows():
        same = tr[tr.Product_Type == shot.Product_Type]
        best = (None, None, shot.p)
        for v in cfg["controllable_vars"]:
            if v not in feats:
                continue
            for val in same[v].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unique():
                x = shot[feats].to_frame().T.astype(float)
                x[v] = val
                pr = lgb.predict_proba(x)[:, 1][0]
                if pr < best[2]:
                    best = (v, val, pr)
        rows.append({"row_id": shot.row_id, "Product_Type": int(shot.Product_Type), "risk_before": round(shot.p, 4),
                     "suggested_var": best[0], "current_value": None if best[0] is None else round(float(shot[best[0]]), 3),
                     "suggested_value": None if best[1] is None else round(float(best[1]), 3), "risk_after": round(best[2], 4)})
    ow = _save(pd.DataFrame(rows), "operating_window_candidates.csv")
    return imp, inter, ow


# ───────────────────────── 15. 제출용 test 예측 ─────────────────────────
def submission_predictions(fp, preds, joined, m41, sel, cfg):
    v, t = fp[fp.role == "validation"], fp[fp.role == "test"]
    q20, q05 = threshold_rate(v.p, 0.2), threshold_rate(v.p, 0.05)
    out = t.merge(joined[["row_id", "run_id", "Shot", "Product_Type"]], on="row_id")
    out["m41_row_id"] = "m41_r" + out.run_id.astype(str) + "_s" + out.Shot.astype(str)
    g = seed_mean(preds, kind="gate", scheme="within_run", model=sel["gate_model"])
    g = g[g.role == "test"].merge(m41[["row_id", "run_id", "source_row"]], on="row_id").sort_values("source_row")
    g["gate_alarm"] = np.concatenate([adaptive_alarm(x, cfg) for _, x in g.groupby("run_id", sort=False)])
    g = g[["row_id", "p", "gate_alarm"]].rename(columns={"row_id": "m41_row_id", "p": "gate_p"})
    out = out.merge(g, on="m41_row_id", how="left")
    types = []
    for tname in ["Short_Shot", "Bubble", "Exfoliation", "Blow_Hole", "Etc"]:
        tp = seed_mean(preds, kind="type", target=f"y_type_{tname}")
        tp = tp[tp.role == "test"][["row_id", "p"]].rename(columns={"p": f"p_{tname}"})
        out = out.merge(tp, on="row_id", how="left")
        types.append(f"p_{tname}")
    out["predicted_type"] = out[types].idxmax(axis=1).str.replace("p_", "")
    out["gate_alarm"] = out.gate_alarm.fillna(False).astype(bool)
    out["risk_grade"] = np.select([out.p >= q05, out.p >= q20, out.p >= out.threshold], ["매우 높음", "높음", "중간"], "낮음")
    internal = out.predicted_type.isin(["Short_Shot", "Blow_Hole", "Bubble"])
    run_hi = (out.sort_values("Shot").groupby("run_id").p.transform(lambda s: (s >= q05).rolling(3, min_periods=3).sum()) >= 3)
    out["action"] = np.select(
        [out.gate_alarm, run_hi, out.risk_grade.isin(["매우 높음", "높음"]) & internal,
         out.risk_grade.isin(["매우 높음", "높음"]), out.risk_grade == "중간"],
        ["품질판정 보류·설비 점검(예열 의심)", "생산중지·조건조정(고위험 연속)", "추가검사→폐기 판단(내부결함 의심)",
         "재작업 라인 분기(표면불량 의심)", "보수적 추가검사"], "정상 생산")
    cols = ["row_id", "run_id", "Shot", "Product_Type", "p", "risk_grade", "predicted_type", "gate_p", "gate_alarm", "action", "y"] + types
    out = out[cols].rename(columns={"p": "p_defect", "y": "y_true(평가용)"}).sort_values(["run_id", "Shot"])
    out.to_csv(paths.PREDICTIONS / "test_predictions.csv", index=False, encoding="utf-8-sig")
    return out


# ───────────────────────── 16. 그림 ─────────────────────────
def figures(fp, comp, fail, delay_df, imp):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return
    t = fp[fp.role == "test"].sort_values("p", ascending=False)
    rate = np.arange(1, len(t) + 1) / len(t)
    cap = np.cumsum(t.y.to_numpy()) / t.y.sum()
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(rate, cap, label="CastGuard"); ax.plot([0, 1], [0, 1], "--", label="Random")
    ax.set_xlabel("Inspection rate"); ax.set_ylabel("Defect capture rate"); ax.legend(); ax.set_title("Capture curve (within-run test)")
    fig.tight_layout(); fig.savefig(paths.FIGURES / "capture_curve.png", dpi=150); plt.close(fig)
    ab = pd.read_csv(paths.TABLES / "ablation.csv")
    fig, ax = plt.subplots(figsize=(6, 3.5))
    vals = ab.test_ap.astype(str).str.split(" ± ").str[0].astype(float)
    ax.bar(ab.experiment, vals); ax.axhline(ab.test_prevalence.iloc[0], ls="--", c="gray", label="prevalence")
    ax.set_ylabel("Test PR-AUC"); ax.set_title("Ablation (within-run test)"); ax.legend()
    fig.tight_layout(); fig.savefig(paths.FIGURES / "ablation_ap.png", dpi=150); plt.close(fig)
    fw = fail[(fail.scheme == "forward_run")].pivot(index="fold", columns="experiment", values="test_auc")
    fig, ax = plt.subplots(figsize=(6, 3.5)); fw.plot.bar(ax=ax); ax.axhline(0.5, ls="--", c="gray")
    ax.set_ylabel("Test ROC-AUC"); ax.set_title("Forward-run (new future run)"); fig.tight_layout()
    fig.savefig(paths.FIGURES / "forward_run_auc.png", dpi=150); plt.close(fig)
    top = imp.head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6, 5)); ax.barh(top.feature, top.mean_abs_shap); ax.set_title("Mean |SHAP|")
    fig.tight_layout(); fig.savefig(paths.FIGURES / "shap_top15.png", dpi=150); plt.close(fig)


def run(cfg: dict, log=print) -> dict:
    paths.ensure_dirs()
    metrics = pd.read_csv(paths.RUNS / "metrics.csv", dtype={"fold": str})
    preds = pd.read_parquet(paths.RUNS / "predictions.parquet")
    sel = json.loads((paths.RUNS / "selection.json").read_text(encoding="utf-8"))
    joined = pd.read_parquet(paths.JOINED)
    m41 = pd.read_parquet(paths.M41)
    p40 = pd.read_parquet(paths.P40)
    folds = pd.read_csv(paths.FOLDS, dtype={"fold": str, "episode_id": str, "order": str})
    comp, dec = model_tables(metrics, sel); log("  모델 비교·Ablation·실패조건·지연 민감도")
    protocol_table(metrics, sel); coverage_table(metrics, sel); oracle_table(metrics, sel); log("  검증 방식 비교·회신율 민감도")
    gs = gate_tables(metrics, preds, m41, cfg, sel); log("  Gate·적용범위(C)")
    type_table(metrics); p40_table(metrics); physics_table(joined, p40, folds, cfg); log("  유형·#40(E)·물리방향(F)")
    fp = final_predictions(preds, sel)
    kpi_tables(fp, cfg); queue_kpi(fp, preds, joined, m41, folds, sel, cfg); condition_table(fp, joined, folds)
    log("  KPI·슬롯 대기열 KPI·조건별 오류분석")
    imp, inter, ow = explain(joined, folds, sel, cfg); log("  SHAP·상호작용·운전창")
    submission_predictions(fp, preds, joined, m41, sel, cfg); log("  제출용 test 예측")
    figures(fp, comp, pd.read_csv(paths.TABLES / "failure_conditions.csv", dtype={"fold": str}),
            pd.read_csv(paths.TABLES / "delay_sensitivity.csv"), imp)
    return {"selection": sel, "ablation": dec}
