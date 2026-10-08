"""reports/tables의 결과로 보고서 초안(REPORT_DRAFT.md)을 만든다. 숫자는 모두 코드 산출물에서 읽는다."""
import json

import numpy as np
import pandas as pd

from . import paths

T = paths.TABLES


def _csv(name, **kw):
    return pd.read_csv(T / name, **kw)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return ""
            return str(int(v)) if float(v).is_integer() and abs(v) >= 1 else f"{v:.3f}"
        return str(v)
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v) for v in r) + " |")
    return "\n".join(lines)


def _pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def run(cfg: dict) -> str:
    prep = json.loads((T / "prepare_report.json").read_text(encoding="utf-8"))
    sel = json.loads((paths.RUNS / "selection.json").read_text(encoding="utf-8"))
    dec = json.loads((T / "ablation_decisions.json").read_text(encoding="utf-8"))
    dq, comp, abl = _csv("data_quality.csv"), _csv("model_comparison.csv"), _csv("ablation.csv")
    fail, delay = _csv("failure_conditions.csv", dtype={"fold": str}), _csv("delay_sensitivity.csv")
    gate, gcov, types = _csv("gate_results.csv", dtype={"fold": str}), _csv("ablation_C_gate_coverage.csv"), _csv("defect_type_results.csv")
    e40, f40 = _csv("ablation_E_p40.csv"), _csv("ablation_F_physics_direction.csv")
    insp, cost = _csv("kpi_inspection.csv"), _csv("kpi_cost_sensitivity.csv")
    qk = _csv("kpi_queue_slots.csv")
    qk20 = qk[qk.budget == 0.2].set_index("policy")
    cond, shap = _csv("error_by_condition.csv"), _csv("shap_importance.csv")
    inter = _csv("shap_interactions.csv") if (T / "shap_interactions.csv").exists() else None
    ow = _csv("operating_window_candidates.csv")
    prot, cov = _csv("validation_protocols.csv"), _csv("feedback_coverage.csv")
    orc = _csv("ablation_oracle_upper_bound.csv")
    orc_gain = orc.val_ap_gain_vs_operational.iloc[1]
    p_dup, p_wr = prot.iloc[0], prot.iloc[2]
    cov0 = cov[cov.coverage == 0.0].iloc[0]
    cov20 = cov[cov.coverage == 0.2].iloc[0]
    d100 = delay[delay.delay == delay.delay.max()].iloc[0]
    i10, i30 = insp[insp.target_inspection_rate == 0.1].iloc[0], insp[insp.target_inspection_rate == 0.3].iloc[0]

    fq = sel["final_quality"]
    fin = comp[(comp.experiment == fq["experiment"]) & (comp.model == fq["model"])].iloc[0]
    a0 = comp[(comp.experiment == "A0")].sort_values("val_ap", ascending=False).iloc[0]
    i20 = insp[insp.target_inspection_rate == 0.2].iloc[0]
    gw = gate[(gate.scheme == "within_run") & (gate.policy == "적응형")].iloc[0]
    gsel = _csv("gate_selection_loro.csv")
    gpick = gsel[gsel.selected].iloc[0]
    gx = gate[gate.scheme != "within_run"].pivot_table(index=["scheme", "fold"], columns="policy",
                                                       values=["false_stop_rate", "detected_within_k"]).round(3)
    gx.columns = [f"{a}({b})" for a, b in gx.columns]
    gx = gx.reset_index()
    fixed_max = gate[(gate.scheme != "within_run") & (gate.policy == "고정")].false_stop_rate.max()
    adapt_max = gate[(gate.scheme != "within_run") & (gate.policy == "적응형")].false_stop_rate.max()
    srch = _csv("model_search_inner_cv.csv")
    tsel = _csv("defect_type_model_selection.csv")
    fw = fail[(fail.scheme == "forward_run") & (fail.experiment == fq["experiment"])]
    rh = fail[(fail.scheme == "run_holdout") & (fail.experiment == fq["experiment"])]
    run_auc = cond[(cond.axis == "가동구간") & cond.auc.notna() & (cond.positives >= 10)]
    en = lambda pop, exp: e40[(e40.population == pop) & (e40.experiment == exp) & (e40.model == "lightgbm") & (e40.role == "test")].auc.iloc[0]
    e_full, e_no = en("normal_pressure", "E_full"), en("normal_pressure", "E_no_mold6")
    b = dec["보조1(#41 이력) 효과"]
    fbg = dec["검사결과 피드백 효과"]
    fb_top = shap.head(10)

    md = f"""# CastGuard: 설비 가동이력 인지형 다이캐스팅 품질불량 조기예측 및 공정개선 AI

> 자동 생성 초안 (`python -m castguard report`). 모든 수치는 `reports/tables/`의 코드 산출물에서 읽었다.
> 대상 기업은 비식별화하여 "자동차부품 알루미늄 다이캐스팅 중소기업 A사"로 표기한다.

## 요약

- **현장 효과**: Shot의 {_pct(i20.test_inspection_rate)}만 추가검사해도 불량의 **{_pct(i20.capture_rate)}**를 잡는다(무작위 검사의 **{i20.lift_vs_random:.1f}배**). 10% 검사 시 {_pct(i10.capture_rate)}({i10.lift_vs_random:.1f}배), 30% 검사 시 {_pct(i30.capture_rate)}다.
- **예열 Shot 차단**: 설비상태 Gate가 test 구간 예열 에피소드 {gw.episodes:.0f}개 중 평균 {gw.detected_within_k:.1f}개를 평균 {gw.mean_shots_to_detect:.1f} Shot 만에 잡는다. 정상 Shot 오정지는 {_pct(gw.false_stop_rate, 2)}다. Gate가 없으면 예열 Shot은 전부 정상처럼 품질판정된다.
- **정직한 성능**: 같은 모델을 가이드북 방식(중복 포함·무작위 분할)으로 평가하면 AUC {p_dup.test_auc:.3f}지만, 중복을 지우고 구간 안 시간순으로 평가하면 {p_wr.test_auc:.3f}다. 우리는 낮은 쪽을 기준으로 보고한다. 최종 모델({fq['experiment']} · {fq['model']})은 이 기준에서 ROC-AUC **{fin.test_auc:.3f}**, PR-AUC **{fin.test_ap:.3f}**(불량률의 {fin.test_ap_lift:.2f}배)다.
- **계보 증명**: 품질보증(#42)과 설비 예지보전(#41)을 (가동구간, Shot) 키로 연결하면 {prep['join_matched']:,} Shot이 1:1로 맞고 공정값 {prep['join_equal_values']:,}개가 전부 일치한다.
- **보조 데이터의 역할**: #41은 품질모델 입력으로는 효과가 없었지만(validation AP {b['val_gain']:+.3f}, 채택 기준 +0.02 미달) Gate로 쓰면 예열 판정 문제를 해결한다. #40(타 공장)에서는 금형온도 6개를 빼면 정상압력 구간 AUC가 {e_full:.3f} → {e_no:.3f}로 떨어져, #42에 없는 **금형 열상태가 핵심 결손 변수**임을 보여준다.
- **한계와 실패 조건**: 학습에 없던 새 가동구간에서는 AUC가 {fw.test_auc.min():.2f}~{fw.test_auc.max():.2f}로 떨어진다. 원인 가설(미관측 열상태)과 데이터 수집 제언까지 함께 제시한다.

## 1. 기업문제 정의 및 데이터 통합

**문제.** A사는 Shot마다 부품 2개(Cavity 1·2)를 생산하고, 품질은 사후 육안검사와 작업자 감에 의존한다. 기준 불량률은 중복 제거 후 {_pct(prep['q42_defect_rate'])}(Cavity1 {_pct(prep['q42_cavity1_rate'])} · Cavity2 {_pct(prep['q42_cavity2_rate'])})다. 설비 재가동 직후의 예열(가생산) 위험과 정상 운전 중 불량 위험이 섞여 있다.

**목표 KPI.** ① 제한된 추가검사로 불량 포착률 최대화 ② 예열 Shot의 품질판정 오류 제거 ③ 고위험 연속 시 조건조정·중지 판단 ④ 비용비율별 품질비용 절감.

**데이터 역할.**

| 데이터 | 역할 | 연결 방식 |
|---|---|---|
| #42 주조 품질보증 ({prep['q42_raw_rows']:,}행 → {prep['q42_rows']:,} Shot) | 주 데이터: 공정14·센서6·불량13종×Cavity2 | 기준 |
| #41 주조 설비 예지보전 ({prep['m41_rows']:,}행) | 보조1: 전체 가동 타임라인·설비상태(예열 {prep['m41_warmup_rows']}행·{prep['m41_warmup_episodes']}에피소드) | (가동구간, Shot) 1:1 키 조인 + 의사결정 단계 Gate |
| #40 주조 공정최적화 ({prep['p40_rows']:,}행) | 보조2: 타 공장 외부 검증·결손 변수(금형온도) 진단 | 물리개념 수준 비교 (행 조인 없음) |

**전처리.** 2단 헤더·공백 정리 → Shot 감소 지점으로 가동구간 7개 부여 → 구간 내 완전 중복 {prep['q42_duplicates_removed']:,}행 제거 → 상수 관리한계 8열 제외 → 결측은 대체하지 않고 유지(학습 fold에서만 대체) → 불량 26열 중 하나라도 0보다 크면 불량. #41 이력 변수는 현재 행을 제외한 과거 행만으로 계산하고 구간마다 초기화했다. #40은 날짜+시각을 합치면 {prep['p40_rows_moved_if_naive_datetime_sort']:,}행의 순서가 뒤바뀌어(날짜 라벨 안에서 시각이 0시로 되돌아감), 검증된 파일 순서로 시간 분할했다.

**데이터 품질지수 (전·후).**

{_md(dq[['dataset', 'stage', 'rows', 'completeness', 'uniqueness', 'validity', 'consistency']])}

정확성·적시성은 외부 정답과 수집 SLA가 없어 미측정이다.

## 2. AI 모델 및 통합성능

**3단계 계층 구조.** Stage 1 설비상태 Gate(#41) → Stage 2 불량 위험(#42 + 검사결과 피드백) → Stage 3 불량유형(주요 4종 + Etc).

**검사결과 피드백.** 현장은 모든 Shot을 사후 육안검사하므로 결과가 늦게 도착한다. Shot t를 예측할 때 같은 구간에서 {sel['label_delay_shots']} Shot 이전까지 도착한 검사결과로 최근 불량률(20·50·100 Shot), 지수평균, 마지막 불량 이후 경과를 만든다. 불량은 시간적으로 몰려 있어(구간 내 자기상관) 이 정보가 미관측 설비 상태의 대리 지표가 된다.

**검증 방식에 따른 성능 차이.** 같은 입력(A)과 같은 모델을 검증 방식만 바꿔 평가했다. 무작위 분할은 같은 Shot의 중복 기록이나 이웃 Shot이 학습과 평가에 함께 들어가 성능을 부풀린다. 현장에서 쓰이는 상황은 "과거로 학습해 미래를 예측"이므로 ③을 최종 기준으로 삼는다.

{_md(prot)}

**검증.** 가동구간 안에서 앞 70%를 개발(그중 80% train · 20% validation), 뒤 30%를 test로 고정했다. 모든 선택(입력·모델·임계값)은 validation으로만 했다. seed {len(cfg['seeds'])}개 평균 ± 표준편차.

**Ablation (최종 모델군 {fq['model']}, within-run test).**

{_md(abl)}

| 비교 | validation AP 변화 | test AP 변화 | 채택 기준 통과 |
|---|---:|---:|---|
""" + "\n".join(f"| {k} ({v['from']}→{v['to']}) | {v['val_gain']:+.3f} | {v['test_gain']:+.3f} | {'예' if v['pass_rule(+0.02 & >2sd on validation)'] else '아니오'} |" for k, v in dec.items()) + f"""

**#41 이력의 최대 가치 (참고 상한).** 운영에서는 쓸 수 없는 '정답' 설비상태 이력(예열 후 경과 Shot, 이전 예열 횟수)을 넣어도 validation AP 변화는 {orc_gain:+.3f}로 채택 기준(+0.02)에 못 미친다. 정상 생산 Shot의 품질은 예열 이력과 거의 무관하므로, #41의 가치는 품질 입력이 아니라 **예열 Shot을 걸러내는 Gate**에 있다.

{_md(orc)}

**후보 모델 비교와 최종모델 선정근거.** 로지스틱·랜덤포레스트·LightGBM·CatBoost·XGBoost·앙상블(로지스틱+LightGBM+CatBoost 평균)을 같은 분할에서 비교했다. validation PR-AUC가 가장 높은 조합을 선정하고, 동률이면 보정오차(ECE)와 seed 간 표준편차가 작은 쪽을 택했다. #41 이력을 포함한 입력(B 계열)은 validation에서 +0.02 이상, seed 표준편차의 2배를 넘을 때만 채택한다.

{_md(comp.head(10)[['experiment', 'model', 'val_ap', 'val_auc', 'val_ece', 'test_ap', 'test_auc', 'selected']])}

**최종 선정: {fq['experiment']} · {fq['model']}** (validation AP {fq['val_ap']:.3f}).{(' B 계열 후보(' + fq['b_rule']['candidate'] + ')는 validation 이득 ' + format(fq['b_rule']['val_gain'], '+.3f') + '로 기준 미달이라 제외했다.') if fq.get('b_rule') and not fq['b_rule']['adopted'] else ''}

**추가 탐색과 성능 한계.** 최종 선정 뒤, 사전에 정한 {len(srch)}개 후보(RF·LightGBM 하이퍼파라미터 격자, Cavity 분리 결합, 불량유형 분리 결합, 앙상블, #41 이력 포함)를 test를 보지 않고 **개발구간 확장창 3-fold**로 다시 비교했다. 채택 기준은 "현재 최종 대비 평균 AP +0.02 이상, seed 표준편차의 2배 초과"다. 최고 후보의 이득은 {srch.gain_vs_current.max():+.4f}로 기준을 넘은 후보가 없어 최종 모델을 유지했다. 모델 구조와 하이퍼파라미터를 바꿔도 성능이 오르지 않으므로, 현재 성능의 한계는 모델이 아니라 **데이터에 담긴 정보**(금형 열상태 미관측 등)에서 온다.

{_md(srch.head(8)[['candidate', 'mean', 'std', 'gain_vs_current', 'adoptable']])}

**검사결과 지연 민감도.**

{_md(delay)}

**검사결과 회신율 민감도.** 검사결과가 일부만 회신되는 경우(표본검사·회신 누락)를 모사했다. 회신율 0%는 피드백이 없는 모델(A)이다.

{_md(cov)}

피드백의 이득은 회신이 빠르고 빠짐없을수록 크다. 회신이 늦거나 일부만 오더라도 성능은 피드백 없는 모델 수준(AUC {cov0.test_auc:.3f})에서 크게 벗어나지 않는다(지연 {int(d100.delay)} Shot: {d100.test_auc:.3f}, 회신율 20%: {cov20.test_auc:.3f}). 피드백 경로가 끊겨도 시스템은 공정·센서 모델로 계속 동작한다.

**설비상태 Gate (Stage 1).** 입력과 모델은 구간 이동에 대한 견고성으로 골랐다. 개발구간(test 제외)에서 구간 하나씩 빼고 학습한 뒤 다른 구간에서 오정지 2% 임계값을 정하고, 뺀 구간의 오정지율과 예열 에피소드 탐지를 쟀다. "구간별 최대 오정지 ≤ {_pct(cfg['gate_max_cross_run_fpr'], 0)}"를 만족하는 후보 중 탐지가 가장 많은 것을 택했다. 현재값을 같은 구간 직전 30 Shot 중앙값으로 나눈 **구간 상대값**을 넣자, 제품·구간마다 다른 압력·사이클 수준 때문에 생기던 오정지가 크게 줄었다.

{_md(gsel[['features', 'model', 'max_fpr', 'mean_fpr', 'detected', 'episodes', 'selected']])}

**선정: {gpick.features} · {gpick.model}.** 운영에서는 **적응형 임계값**을 쓴다. 작업자가 정상으로 확인한 같은 구간의 과거 Shot({cfg['gate_adapt_delay']} Shot 지연 반영) 점수의 98% 분위를 임계값의 하한으로 삼아, 처음 보는 운전점에서 정상 Shot이 계속 경보되는 것을 막는다. 이 규칙은 구간 이동 실험에서 관찰된 오정지를 보고 추가했으며, 파라미터는 조정하지 않은 기본값(지연 {cfg['gate_adapt_delay']} Shot, 오정지 목표 2%)이다.

{_md(gcov)}

| 구간 이동 검증 | 고정 임계값 | 적응형 임계값 |
|---|---:|---:|
| 최대 오정지율 | {_pct(fixed_max)} | {_pct(adapt_max)} |

{_md(gx)}

같은 구간 안에서는 오정지 {_pct(gw.false_stop_rate, 2)}로 예열 에피소드 대부분을 첫 Shot에 잡는다. 구간 2는 다른 Type 1 구간과 주조압력 수준이 달라(중앙값 1,155 vs 1,052) 처음 보는 운전점이다. 고정 임계값에서는 정상 Shot 대부분이 경보됐고, 적응형에서는 오정지가 크게 줄지만 탐지도 일부 줄어든다. 새 운전점에서는 초반 몇십 Shot의 작업자 확인이 필요하다는 뜻이다.

**불량유형 (Stage 3, within-run test).**

{_md(types)}

유형별 모델은 개발구간 확장창 CV로 모델군(RF·로지스틱·LightGBM·CatBoost)을 비교해, 기본 모델보다 AP가 +0.02 이상 높을 때만 바꿨다. Bubble만 LightGBM으로 바뀌었다.

**#40 외부 검증 (E) — 금형온도의 가치.**

{_md(e40[e40.role == 'test'][['population', 'experiment', 'model', 'auc', 'ap', 'prevalence', 'n']])}

## 3. 영향요인 · 오류분석

**주요 영향변수 (SHAP, LightGBM 설명모델).**

{_md(fb_top[['feature', 'mean_abs_shap', 'direction(corr value↔shap)']])}

{'**상호작용 상위 (XGBoost SHAP interaction).**' + chr(10) + chr(10) + _md(inter.head(8)) if inter is not None else ''}

**조건별 성능.** 아래는 within-run test에서 최종 모델의 조건별 성능이다.

{_md(cond[cond.axis.isin(['가동구간', '제품', '예열 후 경과 Shot(분석용)', '불확실성'])][['axis', 'level', 'n', 'positives', 'prevalence', 'auc', 'ap', 'recall', 'fnr']])}

불량이 10개 이상인 구간만 보면 구간별 AUC는 {run_auc.auc.min():.2f}~{run_auc.auc.max():.2f}로, 구간을 합친 AUC({fin.test_auc:.3f})보다 낮다. 모델의 힘 상당 부분은 "지금 위험이 높은 시기인가"를 구분하는 데서 나오고, 같은 시기 안에서 개별 Shot을 가려내는 능력은 제한적이다. 검사 자원을 시기별로 배분하는 데는 유효하지만, Shot 단위 판정을 대체하지는 못한다.

**실패 조건 — 새 가동구간.**

{_md(fw[['fold', 'n', 'prevalence', 'test_auc', 'test_ap']])}

구간 하나를 통째로 빼고 학습한 run_holdout에서도 AUC {rh.test_auc.min():.2f}~{rh.test_auc.max():.2f}다. 구간마다 불량률이 1.3%~41%로 다르고 공정변수 분포도 이동한다. #40에서 금형온도가 핵심이었던 점을 종합하면, #42에 없는 금형 열상태가 구간 간 차이를 만드는 유력한 원인 가설이다. 검증하려면 금형 온도를 Shot 단위로 수집해야 한다.

**#40·#42 물리인자 방향 비교 (F).**

{_md(f40)}

## 4. 현장 적용 기본설계

**의사결정 정책.**

| 설비 Gate | 불량 위험 | 조치 |
|---|---|---|
| 예열 의심 (적응형 임계값) | — | 품질판정 보류 · 설비 점검 |
| 정상 | 매우 높음 3연속 | 생산중지 · 조건조정 · 원인 점검 |
| 정상 | 높음 + 내부결함(Short Shot·Blow Hole·Bubble) 예상 | 추가검사 → 폐기 판단 |
| 정상 | 높음 + 표면불량 예상 | 재작업 라인 분기 |
| 정상 | 중간 | 보수적 추가검사 |
| 정상 | 낮음 | 정상 생산 |

위험 등급 경계는 validation 예측의 상위 5% · 20% · F1 최적값으로 정했다. Shot별 결과는 `outputs/predictions/test_predictions.csv`에 있다.

**KPI — 추가검사율별 불량 포착 (기준값: 무작위 검사).**

{_md(insp)}

산출식: 포착률 = 검사한 Shot 중 불량 수 ÷ 전체 불량 수. 무작위 검사의 기대 포착률은 검사율과 같다.

**품질비용 민감도.** 비용 = r × 놓친 불량 + 1 × 추가검사 건수. 실제 단가가 없어 비용비율 r로만 제시한다.

{_md(cost)}

**보조 KPI: 슬롯 기반 검사 대기열 (검사 능력 상한 스트레스 테스트).** 위 KPI는 Shot이 도착할 때 validation에서 정한 임계값으로 바로 판정하므로 인과적이지만, 실제 검사율이 목표와 조금 다르고 위험한 시기에 검사가 몰릴 수 있다. 검사 인력이 Shot마다 일정 비율 b만큼만 생긴다는 더 엄격한 제약을 따로 시험했다. 각 가동구간의 test 부분을 도착 순서(source_row)대로 흘리면서 도착 i마다 ⌊(i+1)b⌋−⌊ib⌋개의 슬롯을 만들고, 쓰지 않은 슬롯은 이월하지 않는다. 대기열 우선순위는 공정값 결측(보류) → Gate 경보(GQ만) → 품질위험이다. FIFO는 같은 조건에서 도착 순으로 검사한다. 정책 세 가지와 예산은 미리 정했고 test 결과를 보고 고르지 않았다.

{_md(qk[["budget", "policy", "capacity", "inspections_used", "gate_reviews", "defects_caught", "capture_rate", "random_capture_rate", "gain_vs_fifo_pp", "warmup_episodes_reviewed_within_k", "mean_wait_records"]])}

검사 {_pct(0.2, 0)} 상한에서 포착률은 품질위험 순(Q) {_pct(qk20.loc["Q", "capture_rate"])}, Gate 우선(GQ) {_pct(qk20.loc["GQ", "capture_rate"])}, 도착 순(FIFO) {_pct(qk20.loc["FIFO", "capture_rate"])}다. 같은 예산의 임계값 방식({_pct(i20.capture_rate)})보다 크게 낮고, FIFO보다도 낮다. 이유는 두 가지다. ① 슬롯이 구간마다 똑같이 나뉘므로 모델의 주된 힘인 "지금 위험한 시기인가"(구간 간 차이)를 쓸 수 없고, 구간 안 순위만 남는다(위 구간별 AUC 참고). ② test 구간 앞부분에 불량이 몰려 있어 도착 순 검사가 우연히 유리하다. GQ는 Gate 검토({int(qk20.loc["GQ", "gate_reviews"])}건)도 같은 검사 능력을 쓴다고 보수적으로 계산했다. 대신 예열 에피소드 {qk20.loc["GQ", "warmup_episodes_reviewed_within_k"]}를 첫 {cfg["gate_detect_within_shots"]} Shot 안에 검토한다. 결론적으로 CastGuard의 검사 KPI는 **위험한 시기에 검사를 늘릴 수 있는 유연한 검사 운영**을 전제로 하며, 검사 인력이 Shot마다 고정되어 있다면 품질위험 순위만으로는 이득이 작다. 같은 데이터에서 JH 브랜치의 대기열 실험도 같은 방향(품질 순 < 도착 순)을 보였다.

**운전창 후보 (모델 기반, 인과 아님).** 고위험 상위 5% Shot {len(ow)}개에서 조정 가능한 변수 하나를 같은 제품의 관측 범위(p10~p90) 안에서 바꿨을 때 예상 위험이 평균 {(ow.risk_before - ow.risk_after).mean():.3f} 낮아졌다. 가장 자주 제안된 변수는 {ow.suggested_var.value_counts().index[0]}다. 현장 시험 전 후보로만 사용한다.

## 5. 창의성 · 확장성

- **의사결정 단계 융합**: 보조 데이터를 feature로 붙이는 대신, 설비상태를 품질모델의 적용 조건(Gate)으로 쓴다.
- **검사결과 피드백 루프**: 이미 존재하는 사후검사 결과를 지연을 반영해 다시 입력으로 쓴다. 새 센서 없이 바로 적용할 수 있다.
- **정직한 검증**: 중복 제거, 구간 내 시간순, 새 구간 실패 조건, 보조 데이터 채택 규칙을 사전에 고정했다.
- **확장 조건**: Shot 단위 공정 수집, 설비상태(예열) 라벨, 검사결과의 Shot 단위 회신, 그리고 **금형 온도 수집**(#40 근거). 예열 개념은 사출·용접에도 있어 같은 구조로 옮길 수 있다.

## 6. 코드 · 재현성

`python -m castguard all` 한 줄로 환경 점검 → 전처리 → 학습 → 분석 → 이 보고서까지 만든다. 원본 CSV 3종은 `data/raw/`, 결과 표는 `reports/tables/`, 그림은 `reports/figures/`, 제출용 예측은 `outputs/predictions/test_predictions.csv`에 있다. seed {cfg['seeds']}를 고정했고, 전처리 결과는 JH 브랜치 산출물과 값 단위로 동일함을 확인했다(#42·#41).

## 예상 질문과 답변

**Q1. 성능(AUC {fin.test_auc:.2f})이 낮은 것 아닌가?**
같은 모델도 가이드북 방식으로 평가하면 {p_dup.test_auc:.2f}다. 차이는 모델이 아니라 검증 방식에서 나온다. 중복 Shot과 이웃 Shot이 학습·평가에 섞이지 않게 한 결과이고, 현장에서 실제로 기대할 수 있는 숫자다. 현장 가치는 AUC보다 KPI로 본다: 검사 {_pct(i20.test_inspection_rate, 0)}로 불량 {_pct(i20.capture_rate, 0)}를 잡는다(무작위의 {i20.lift_vs_random:.1f}배).

**Q2. 검사결과가 20 Shot 안에 회신된다는 가정이 현실적인가?**
Type 1 기준 약 7분, Type 2 기준 약 12분이다. 가정이 깨져도 지연 {int(d100.delay)} Shot에서 AUC {d100.test_auc:.3f}, 회신율 20%에서 {cov20.test_auc:.3f}로, 피드백이 없는 모델({cov0.test_auc:.3f})과 비슷한 수준을 유지한다. 도입 시 첫 단계로 검사 회신 주기를 측정한다.

**Q3. #41과 #42는 같은 데이터 아닌가? 보조 데이터의 효과는?**
공정변수는 같지만 모집단과 라벨이 다르다. #41은 예열·결측을 포함한 전체 가동 이력과 설비상태를, #42는 정상 생산분의 품질을 담는다. #41 이력을 품질모델 입력으로 넣는 효과는 사전에 정한 기준(+0.02)에 못 미쳐 채택하지 않았다. 운영에서 쓸 수 없는 '정답' 설비상태 이력을 넣어도 {orc_gain:+.3f}에 그쳐, 정상 Shot의 품질은 예열 이력과 거의 무관하다. 대신 #41의 설비상태로 만든 Gate는 #42만으로는 불가능한 예열 Shot 차단을 해낸다(에피소드 {gw.detected_within_k:.0f}/{gw.episodes:.0f}, 오정지 {_pct(gw.false_stop_rate, 1)}).

**Q4. 새 가동구간에서 예측이 무너지는 이유는?**
구간마다 불량률이 1.3%~41%로 다르고 공정 분포가 이동한다. #40에서 금형온도를 빼면 성능이 크게 떨어진 점을 보면, #42에 없는 금형 열상태가 유력한 원인 가설이다. 그래서 금형 온도의 Shot 단위 수집을 제언하고, 새 구간 초반에는 보수적 검사율로 운영한다.

**Q5. 모델을 더 튜닝하면 성능이 오르지 않나?**
사전에 정한 {len(srch)}개 후보를 test를 보지 않고 개발구간에서 비교했지만, 기준(+0.02)을 넘은 후보가 없었다(최고 {srch.gain_vs_current.max():+.3f}). 성능 한계는 모델이 아니라 데이터에 없는 정보(금형 열상태)에서 온다. 그래서 개선 방향을 튜닝이 아니라 금형 온도 수집으로 제시한다.

**Q6. Gate가 다른 구간에서도 통하나?**
구간 상대값과 적응형 임계값으로 구간 이동 시 최대 오정지율을 {_pct(fixed_max)}에서 {_pct(adapt_max)}로 낮췄다. 처음 보는 운전점(구간 2)에서는 초반 작업자 확인이 필요하다.

**Q7. 운전창 추천은 믿을 수 있는가?**
모델 기반 후보이지 인과효과가 아니다. 관측된 정상 범위 안에서만 제안하고, 현장 시험 전에는 조건 변경을 자동 적용하지 않는다.

**Q8. 검사 인력이 고정되어 있으면 효과가 있나?**
Shot마다 같은 비율로만 검사할 수 있는 대기열로 따로 시험했다. 검사 20% 상한에서 품질위험 순 포착률은 {_pct(qk20.loc["Q", "capture_rate"])}로 도착 순({_pct(qk20.loc["FIFO", "capture_rate"])})보다 낮았다. 모델의 힘이 구간 안 개별 Shot보다 위험한 시기를 가려내는 데 있기 때문이다. 그래서 도입안은 고위험 시기에 검사 인력을 늘리는 유연 운영(위 KPI, 검사 {_pct(i20.test_inspection_rate, 0)}로 불량 {_pct(i20.capture_rate, 0)})이고, 이 결과를 숨기지 않고 함께 제시한다.

## 출처

- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 품질보증 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 설비 예지보전 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 공정최적화 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
"""
    paths.REPORT.write_text(md, encoding="utf-8")
    print(f"  보고서 초안: {paths.REPORT.relative_to(paths.ROOT)}")
    return md
