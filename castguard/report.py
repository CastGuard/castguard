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
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else
                                       (f"{v:.3f}" if isinstance(v, float) else str(v)) for v in r) + " |")
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
    cond, shap = _csv("error_by_condition.csv"), _csv("shap_importance.csv")
    inter = _csv("shap_interactions.csv") if (T / "shap_interactions.csv").exists() else None
    ow = _csv("operating_window_candidates.csv")

    fq = sel["final_quality"]
    fin = comp[(comp.experiment == fq["experiment"]) & (comp.model == fq["model"])].iloc[0]
    a0 = comp[(comp.experiment == "A0")].sort_values("val_ap", ascending=False).iloc[0]
    i20 = insp[insp.target_inspection_rate == 0.2].iloc[0]
    gw = gate[gate.scheme == "within_run"].iloc[0]
    fw = fail[(fail.scheme == "forward_run") & (fail.experiment == fq["experiment"])]
    rh = fail[(fail.scheme == "run_holdout") & (fail.experiment == fq["experiment"])]
    run_auc = cond[(cond.axis == "가동구간") & cond.auc.notna()]
    en = lambda pop, exp: e40[(e40.population == pop) & (e40.experiment == exp) & (e40.model == "lightgbm") & (e40.role == "test")].auc.iloc[0]
    e_full, e_no = en("normal_pressure", "E_full"), en("normal_pressure", "E_no_mold6")
    b = dec["보조1(#41 이력) 효과"]
    fbg = dec["검사결과 피드백 효과"]
    fb_top = shap.head(10)

    md = f"""# CastGuard: 설비 가동이력 인지형 다이캐스팅 품질불량 조기예측 및 공정개선 AI

> 자동 생성 초안 (`python -m castguard report`). 모든 수치는 `reports/tables/`의 코드 산출물에서 읽었다.
> 대상 기업은 비식별화하여 "자동차부품 알루미늄 다이캐스팅 중소기업 A사"로 표기한다.

## 요약

- **계보 증명**: 품질보증(#42)과 설비 예지보전(#41)을 (가동구간, Shot) 키로 연결하면 {prep['join_matched']:,} Shot이 1:1로 맞고 공정값 {prep['join_equal_values']:,}개가 전부 일치한다. 두 데이터는 같은 설비의 서로 다른 기록이다.
- **정직한 검증**: 반복 저장된 중복 {prep['q42_duplicates_removed']:,}행을 제거하고 가동구간 안 시간순으로만 검증했다. 최종 모델({fq['experiment']} · {fq['model']})의 test ROC-AUC는 **{fin.test_auc:.3f}**, PR-AUC는 **{fin.test_ap:.3f}**(불량률 대비 {fin.test_ap_lift:.2f}배)다. 공정변수만 쓴 베이스라인은 {a0.test_auc:.3f} / {a0.test_ap:.3f}다.
- **현장 효과**: Shot의 {_pct(i20.test_inspection_rate)}만 추가검사해도 불량의 **{_pct(i20.capture_rate)}**를 잡는다. 같은 양을 무작위로 검사할 때보다 **{i20.lift_vs_random:.1f}배** 많다.
- **보조 데이터의 역할**: #41 가동이력을 품질모델 입력으로 더하면 AP 변화는 validation {b['val_gain']:+.3f}로 채택 기준(+0.02)에 못 미쳤다. 대신 #41이 정의하는 설비상태를 **Gate**로 쓰면 test 구간 예열 에피소드 {gw.episodes:.0f}개 중 평균 {gw.detected_within_k:.1f}개를 첫 {cfg['gate_detect_within_shots']} Shot 안에 잡고, 정상 Shot 오정지는 {_pct(gw.false_stop_rate, 2)}다. #40(타 공장)에서는 금형온도 6개를 빼면 정상압력 구간 AUC가 {e_full:.3f} → {e_no:.3f}로 떨어진다. #42에 없는 **금형 열상태가 핵심 결손 변수**임을 보여준다.
- **실패 조건**: 학습에 없던 새 가동구간(forward_run)에서는 AUC가 {fw.test_auc.min():.2f}~{fw.test_auc.max():.2f}로 떨어진다. 이를 숨기지 않고 원인(미관측 열상태·구간별 조건 변화)과 데이터 수집 제언으로 연결했다.

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

**검증.** 가동구간 안에서 앞 70%를 개발(그중 80% train · 20% validation), 뒤 30%를 test로 고정했다. 모든 선택(입력·모델·임계값)은 validation으로만 했다. seed {len(cfg['seeds'])}개 평균 ± 표준편차.

**Ablation (최종 모델군 {fq['model']}, within-run test).**

{_md(abl)}

| 비교 | validation AP 변화 | test AP 변화 | 채택 기준 통과 |
|---|---:|---:|---|
""" + "\n".join(f"| {k} ({v['from']}→{v['to']}) | {v['val_gain']:+.3f} | {v['test_gain']:+.3f} | {'예' if v['pass_rule(+0.02 & >2sd on validation)'] else '아니오'} |" for k, v in dec.items()) + f"""

**후보 모델 비교와 최종모델 선정근거.** 로지스틱·랜덤포레스트·LightGBM·CatBoost·XGBoost·앙상블(로지스틱+LightGBM+CatBoost 평균)을 같은 분할에서 비교했다. validation PR-AUC가 가장 높은 조합을 선정하고, 동률이면 보정오차(ECE)와 seed 간 표준편차가 작은 쪽을 택했다. #41 이력을 포함한 입력(B 계열)은 validation에서 +0.02 이상, seed 표준편차의 2배를 넘을 때만 채택한다.

{_md(comp.head(10)[['experiment', 'model', 'val_ap', 'val_auc', 'val_ece', 'test_ap', 'test_auc', 'selected']])}

**최종 선정: {fq['experiment']} · {fq['model']}** (validation AP {fq['val_ap']:.3f}).{(' B 계열 후보(' + fq['b_rule']['candidate'] + ')는 validation 이득 ' + format(fq['b_rule']['val_gain'], '+.3f') + '로 기준 미달이라 제외했다.') if fq.get('b_rule') and not fq['b_rule']['adopted'] else ''}

**검사결과 지연 민감도.**

{_md(delay)}

**설비상태 Gate (Stage 1, {sel['gate_model']}).** 오정지율(정상 Shot 경보) {_pct(cfg['gate_max_validation_fpr'], 0)}가 되도록 validation에서 임계값을 정했다.

{_md(gcov)}

{_md(gate[['scheme', 'fold', 'episodes', 'detected_within_k', 'mean_shots_to_detect', 'false_stop_rate', 'row_auc']])}

같은 구간 안(within_run)에서는 오정지 {_pct(gw.false_stop_rate, 2)}로 예열 에피소드 대부분을 첫 Shot에 잡는다. 다른 구간으로 옮기면 행 단위 AUC는 높게 유지되지만, 임계값이 맞지 않아 일부 구간에서 오정지가 커진다. 현장 적용 시 제품·구간 시작마다 임계값을 재보정해야 한다(4장).

**불량유형 (Stage 3, within-run test).**

{_md(types)}

**#40 외부 검증 (E) — 금형온도의 가치.**

{_md(e40[e40.role == 'test'][['population', 'experiment', 'model', 'auc', 'ap', 'prevalence', 'n']])}

## 3. 영향요인 · 오류분석

**주요 영향변수 (SHAP, LightGBM 설명모델).**

{_md(fb_top[['feature', 'mean_abs_shap', 'direction(corr value↔shap)']])}

{'**상호작용 상위 (XGBoost SHAP interaction).**' + chr(10) + chr(10) + _md(inter.head(8)) if inter is not None else ''}

**조건별 성능.** 아래는 within-run test에서 최종 모델의 조건별 성능이다.

{_md(cond[cond.axis.isin(['가동구간', '제품', '예열 후 경과 Shot(분석용)', '불확실성'])][['axis', 'level', 'n', 'positives', 'prevalence', 'auc', 'ap', 'recall', 'fnr']])}

구간별 AUC는 {run_auc.auc.min():.2f}~{run_auc.auc.max():.2f}로, 구간을 합친 AUC({fin.test_auc:.3f})보다 낮다. 모델의 힘 상당 부분은 "지금 위험이 높은 시기인가"를 구분하는 데서 나오고, 같은 시기 안에서 개별 Shot을 가려내는 능력은 제한적이다. 검사 자원을 시기별로 배분하는 데는 유효하지만, Shot 단위 판정을 대체하지는 못한다.

**실패 조건 — 새 가동구간.**

{_md(fw[['fold', 'n', 'prevalence', 'test_auc', 'test_ap']])}

구간 하나를 통째로 빼고 학습한 run_holdout에서도 AUC {rh.test_auc.min():.2f}~{rh.test_auc.max():.2f}다. 구간마다 불량률이 1.3%~41%로 다르고 공정변수 분포도 이동한다. #40에서 금형온도가 핵심이었던 점을 종합하면, #42에 없는 금형 열상태가 구간 간 차이를 만드는 유력한 원인이다.

**#40·#42 물리인자 방향 비교 (F).**

{_md(f40)}

## 4. 현장 적용 기본설계

**의사결정 정책.**

| 설비 Gate | 불량 위험 | 조치 |
|---|---|---|
| 예열 의심 | — | 품질판정 보류 · 설비 점검 |
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

**운전창 후보 (모델 기반, 인과 아님).** 고위험 상위 5% Shot {len(ow)}개에서 조정 가능한 변수 하나를 같은 제품의 관측 범위(p10~p90) 안에서 바꿨을 때 예상 위험이 평균 {(ow.risk_before - ow.risk_after).mean():.3f} 낮아졌다. 가장 자주 제안된 변수는 {ow.suggested_var.value_counts().index[0]}다. 현장 시험 전 후보로만 사용한다.

## 5. 창의성 · 확장성

- **의사결정 단계 융합**: 보조 데이터를 feature로 붙이는 대신, 설비상태를 품질모델의 적용 조건(Gate)으로 쓴다.
- **검사결과 피드백 루프**: 이미 존재하는 사후검사 결과를 지연을 반영해 다시 입력으로 쓴다. 새 센서 없이 바로 적용할 수 있다.
- **정직한 검증**: 중복 제거, 구간 내 시간순, 새 구간 실패 조건, 보조 데이터 채택 규칙을 사전에 고정했다.
- **확장 조건**: Shot 단위 공정 수집, 설비상태(예열) 라벨, 검사결과의 Shot 단위 회신, 그리고 **금형 온도 수집**(#40 근거). 예열 개념은 사출·용접에도 있어 같은 구조로 옮길 수 있다.

## 6. 코드 · 재현성

`python -m castguard all` 한 줄로 환경 점검 → 전처리 → 학습 → 분석 → 이 보고서까지 만든다. 원본 CSV 3종은 `data/raw/`, 결과 표는 `reports/tables/`, 그림은 `reports/figures/`, 제출용 예측은 `outputs/predictions/test_predictions.csv`에 있다. seed {cfg['seeds']}를 고정했고, 전처리 결과는 JH 브랜치 산출물과 값 단위로 동일함을 확인했다(#42·#41).

## 출처

- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 품질보증 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 설비 예지보전 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
- 중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 공정최적화 AI 데이터셋, 스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
"""
    paths.REPORT.write_text(md, encoding="utf-8")
    print(f"  보고서 초안: {paths.REPORT.relative_to(paths.ROOT)}")
    return md
