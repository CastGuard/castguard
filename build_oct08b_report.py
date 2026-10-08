"""Add the 10/8 model search, crossed model x data study and time-window study to the report.

Reads the verified 10/8 report markdown, inserts sections 2.5-2.7 (model search, crossed
comparison, time-window aggregation, final model selection rationale), patches chapter 6
reproduction commands and appendix A evidence paths, and renders the PDF with the existing
renderer. Presentation files are not rebuilt here.
"""
from pathlib import Path
import html
import json
import re

import pandas as pd

import build_oct06_submission as old

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'reports/oct08_submission/CastGuard_report.md'
BUILD = ROOT / 'reports/oct08b_submission'
OUT = BUILD / 'candidate'
MS = ROOT / 'reports/oct08_model_search'
CS = ROOT / 'reports/oct08_crossed_search'
WS = ROOT / 'reports/oct08_window_search'
FAMILY = {'logistic': '로지스틱(고정)', 'random_forest': 'RF(고정)', 'xgboost': 'XGBoost', 'lightgbm': 'LightGBM', 'catboost': 'CatBoost', 'mlp': 'MLP', 'tabm': 'TabM'}
LABEL = {'S': '#42', 'SH': '#42+#41', 'S_T': '#42+#40', 'SH_T': '#42+#41+#40'}


def f4(x):
    return f'{x:.4f}'


def content():
    text = SRC.read_text(encoding='utf-8')
    ms = json.loads((MS / 'summary.json').read_text(encoding='utf-8'))
    cs = json.loads((CS / 'summary.json').read_text(encoding='utf-8'))
    ws = json.loads((WS / 'summary.json').read_text(encoding='utf-8'))
    tw = {r['id']: r for r in ms['test_within']}
    base, mean_all = tw['baseline'], tw['mean_all']
    fwd = {r['fold']: r for r in ms['test_forward'] if r['id'] == 'mean_all'}
    unc = ms['uncertainty']
    rank = pd.read_csv(MS / 'ensemble_validation_ranking.csv')
    top = rank.iloc[0]
    b0 = cs['baseline']
    mt = pd.read_csv(CS / 'model_matrix_test.csv'); mv = pd.read_csv(CS / 'model_matrix_validation.csv')
    wt = mt[mt.scheme == 'within_run'].pivot(index='family', columns='representation', values='ap')
    ct = mt[mt.scheme == 'within_run'].pivot(index='family', columns='representation', values='caught20')
    wv = mv[mv.scheme == 'within_run'].pivot(index='family', columns='representation', values='ap')
    rows_v, rows_t = [], []
    for fam in ['logistic', 'random_forest', 'xgboost', 'lightgbm', 'catboost', 'mlp', 'tabm']:
        rows_v.append([FAMILY[fam]] + [f'{wv.loc[fam, r]:.4f}' for r in ['S', 'SH', 'S_T', 'SH_T']])
        rows_t.append([FAMILY[fam]] + [f'{wt.loc[fam, r]:.4f} ({int(ct.loc[fam, r])})' for r in ['S', 'SH', 'S_T', 'SH_T']])
    heads = [LABEL[r] for r in ['S', 'SH', 'S_T', 'SH_T']]
    matrix = old.markdown_table(['모델군 · validation AP'] + heads, rows_v) + '\n\n' + old.markdown_table(['모델군 · test AP (포착)'] + heads, rows_t)
    winners = {r['representation']: r for r in cs['within_combination_winners']}
    wrows = [[LABEL[r], winners[r]['id'].split('::')[1] + ('' if winners[r]['id'].split('::')[1] == 'single' else ' ' + winners[r]['id'].split('::')[-1]),
              f4(winners[r]['ap']), f4(winners[r]['auc']), f"{winners[r]['caught20']} ({winners[r]['capture20'] * 100:.2f}%)"] for r in ['S', 'SH', 'S_T', 'SH_T']]
    wtable = old.markdown_table(['입력', 'validation 선택', 'test AP', 'test AUC', '20% 포착 / 272'], wrows)
    obs = cs['highest_observed_no_feedback_family_cell']; ex = cs['exploratory_comparison']
    # time-window study
    dec = {(d['model'], d['representation']): d for d in ws['decisions']}
    tst = {(r['model'], r['representation']): r for r in ws['test_within']}
    wsrows = []
    for model in ['logistic', 'random_forest', 'lightgbm', 'catboost']:
        for rep in ['S', 'SWd', 'SW']:
            t = tst[(model, rep)]
            if rep == 'S':
                v = f"{dec[(model, 'SW')]['baseline_within_ap']:.4f}"; crit = '기준'
            else:
                d = dec[(model, rep)]; v = f"{d['validation_within_ap']:.4f}"; crit = f"{d['validation_ap_gain']:+.3f} " + ('통과' if d['qualifies'] else '미달')
            name = {'logistic': '로지스틱', 'random_forest': 'RF', 'lightgbm': 'LightGBM', 'catboost': 'CatBoost'}[model]
            wsrows.append([name + ' · ' + {'S': '#42', 'SWd': '+편차14', 'SW': '+집계58'}[rep], v, crit, f4(t['ap']), f"{t['caught20']:.1f}"])
    wstable = old.markdown_table(['모델 · 입력', 'val AP', 'val 차이(기준)', 'test AP', 'test 포착'], wsrows)
    wunc = {(u['model'], u['representation']): u['test_ap_diff_interval95'] for u in ws['uncertainty']}
    lgb = tst[('lightgbm', 'SW')]; lgb_s = tst[('lightgbm', 'S')]; d_lgb = dec[('lightgbm', 'SW')]
    fc = ws['feature_counts']
    sel = old.markdown_table(['선정 기준', 'S_FB 로지스틱(유지)', '10/8 탐색 후보'], [
        ['validation 선택 일관성', '7입력 탐색의 sealed 선택, 같은 구간 test에서도 S 대비 상승', '앙상블·블렌드는 validation 상승이 test 순위로 이어지지 않음'],
        ['재사용 test AP / 포착', f"{base['ap']:.4f} / {base['caught20']}건", f"mean_all {mean_all['ap']:.4f} / {mean_all['caught20']}건, MLP SH {obs['ap']:.4f} / {obs['caught20']}건(사후 관측)"],
        ['정상 FPR(validation 고정 임계값)', f"{base['fpr'] * 100:.2f}%", f"mean_all {mean_all['fpr'] * 100:.2f}%, MLP SH {obs['fpr'] * 100:.2f}%"],
        ['미래 run 안정성', '약함(2.4절)', f"mean_all run 4 정상 FPR {fwd['4']['fpr'] * 100:.2f}%"],
        ['설명 가능성·입력 요구', '계수 기반 개별 기여, #41/#40 입력 불필요', '다중 모델·추가 데이터 요구, 기여 설명 복잡'],
        ['사전 채택 기준', '해당 없음(기준 모델)', '모든 비교에서 데이터 추가 기준 통과 0건(시간 창 LightGBM 1건은 test 역전)']])
    section = f'''### 2.5 현대 모델 탐색과 앙상블

보고서 작성 당일 두 단계의 추가 탐색을 사전 계획(docs/OCT08_MODEL_SEARCH_PROTOCOL.md, docs/OCT08_MODEL_REFINE_PROTOCOL.md)에 따라 수행했다. XGBoost·CatBoost·LightGBM·MLP·TabM의 {ms['candidate_configurations']}개 설정을 같은 5개 고정 분할에서 비교했고, 조기 종료와 설정 선택은 train/validation에만 의존했다. test를 보기 전에 3 seed 후보와 {ms['ensemble_variants']}개 앙상블 선택을 봉인했다. 설정 수와 fit 수는 작업량이며 성능이 아니다.

validation 목적함수 최고 후보는 5개 새 모델군과 기존 로지스틱을 동등 가중한 mean_all이었다. validation AP는 {top.within_ap:.4f}로 기준 대비 +{top.within_ap_gain:.4f}이지만 20% 포착 차이는 +{top.within_capture_gain * 100:.2f}%p로 사전 기준 +5%p에 미달했다. 같은 구간 재사용 test에서는 AP {base['ap']:.4f}→{mean_all['ap']:.4f}, AUC {base['auc']:.4f}→{mean_all['auc']:.4f}, 동일 277건 검사의 포착 {base['caught20']}→{mean_all['caught20']}건이다. AP 차이의 run 블록 재표본 95% 범위는 [{unc['interval95'][0]:.4f}, {unc['interval95'][1]:.4f}]로 0을 포함한다. validation 고정 임계값의 정상 FPR은 {base['fpr'] * 100:.2f}%→{mean_all['fpr'] * 100:.2f}%로 늘었고 미래 run 4의 정상 FPR은 {fwd['4']['fpr'] * 100:.2f}%였다. 소폭 관측 상승과 확정 개선을 구분하여 기존 판독 모델을 유지했다.

### 2.6 모델군 × 데이터 조합 교차 비교

사용자 검토에서 지적된 공백을 보완하기 위해 7개 모델군 × 동일 {cs['experiment']['unique_settings']}개 설정 × 8개 입력({', '.join(LABEL.values())} 각각 피드백 유무)={cs['experiment']['candidate_configurations']}개 후보를 5개 고정 분할에서 비교했다(docs/OCT08_CROSSED_SEARCH_PROTOCOL.md). 이 절의 기준 B0는 #42의 현재 공정·센서·제품종류 21변수만 쓰는 고정 로지스틱(C=0.3)이며 #41 이력·#40 전이·과거 검사 피드백을 쓰지 않는다. B0의 재사용 test는 AP {b0['ap']:.4f}, AUC {b0['auc']:.4f}, 277건 검사로 {b0['caught20']}/272건 포착, 정상 FPR {b0['fpr'] * 100:.2f}%다. 앞 절의 S_FB 로지스틱은 운영 참조이며 B0와 구분한다.

아래 표는 피드백 없는 네 입력에서 모델군별로 validation 목적함수가 가장 높았던 설정의 3 seed 평균이다. 첫 표는 validation AP, 둘째 표는 재사용 test AP와 괄호 안 277건 검사 포착 수(분모 272)다.

{matrix}

입력별로 validation만으로 선택한 최종 후보(단일 또는 두 모델 블렌드)의 test 결과는 다음과 같다. 모든 입력에서 validation 선택 후보의 test AP가 B0 로지스틱({b0['ap']:.4f})보다 낮았다. validation 순위가 test로 이어지지 않는 순위 역전이 이번 데이터의 핵심 한계다.

{wtable}

같은 설정을 고정한 채 데이터만 추가한 {len(pd.read_csv(CS / 'locked_setting_differences.csv'))}개 비교 중 사전 채택 기준(validation AP +0.02, 포착 +5%p, forward 2개 fold 비감소)을 통과한 비교는 {cs['locked_setting_validation_criteria_passes']}건이다. test에서 가장 높게 관측된 피드백 없는 칸은 MLP+#42+#41로 AP {obs['ap']:.4f}, AUC {obs['auc']:.4f}, 포착 {obs['caught20']}건이지만, 이는 test를 본 뒤 고른 사후 관측이며 B0 대비 AP 차이 +{ex['ap_difference']:.4f}의 run 블록 95% 범위 [{ex['ap_interval95'][0]:.4f}, {ex['ap_interval95'][1]:.4f}]는 0을 포함하고 다중 비교를 보정하지 않았다. 정상 FPR {obs['fpr'] * 100:.2f}%와 미래 run 3의 과경보도 확인되어 최종 모델로 채택하지 않았다.

### 2.7 시간 창 집계 연계와 최종 모델 선정 근거

과제공개가 권장한 시간 창 기반 집계를 적용한 추가 제거실험을 수행했다(reports/oct08_window_search/registration.json). 품질 라벨이 없는 행을 포함한 #41 전체 타임라인에서 같은 run의 직전 5·20 Shot(현재 Shot 제외)에 대해 공정 14개의 창 평균·표준편차·현재값 편차와 창 내 결측·예열 행 수를 계산해 #42 입력 S에 붙였다. 입력은 S {fc['S']}개, 편차만 추가한 SWd {fc['SWd']}개, 전체 집계 SW {fc['SW']}개다. 모델은 2.3절과 같은 고정 설정의 로지스틱·RF·LightGBM·CatBoost, 3 seed, 5개 고정 분할이며 총 {ws['fits']} fit이다. 판정은 test를 보기 전에 validation으로 기록했다.

{wstable}

validation에서 사전 기준 세 가지를 모두 통과한 비교는 LightGBM+SW 1건이다(AP +{d_lgb['validation_ap_gain']:.4f}, 포착 +{d_lgb['validation_capture20_gain'] * 100:.2f}%p, forward {d_lgb['forward_consistent']}개 fold). 그러나 같은 모델의 재사용 test에서는 AP {lgb_s['ap']:.4f}→{lgb['ap']:.4f}, 포착 {lgb_s['caught20']:.1f}→{lgb['caught20']:.1f}건으로 역전됐고 AP 차이 95% 범위 [{wunc[('lightgbm', 'SW')][0]:.4f}, {wunc[('lightgbm', 'SW')][1]:.4f}]는 0을 포함한다. validation 647행 기준의 선택이 test 1,387행에서 유지되지 않는 양상은 2.6절의 순위 역전과 같다. 시간 창 집계가 현장에서 무가치하다는 뜻은 아니며, 현재 cohort 크기에서 일관된 추가 가치를 입증하지 못했다는 뜻이다.

세 가지 연계 방식(#41 이력 4변수, #40 분위 정렬 전이 점수, #41 시간 창 집계)과 7개 모델군을 모두 같은 고정 분할에서 비교한 뒤의 최종 모델 선정 근거는 다음과 같다.

{sel}

따라서 현재 판독기는 S_FB 로지스틱을 유지한다. 보조 데이터의 추가 가치는 validation에서 간헐적으로 관측됐지만 test·미래 구간·경보 부담을 함께 보면 채택 기준을 넘지 못했다. 이 결론은 데이터 융합이 실패했다는 확정이 아니라, 현재 cohort와 평가 설계에서 융합 효과를 분리 입증하기에 표본이 부족하다는 정량적 한계 보고다.

## 제3장'''
    text = text.replace('\n## 제3장', '\n' + section, 1)
    text = text.replace('새 보조 입력은 사전에 정한 품질 개선 기준에 미달해 기존 판독 모델을 유지한다.',
        '이어서 XGBoost·CatBoost·LightGBM·MLP·TabM 등 7개 모델군과 네 데이터 조합·시간 창 집계를 같은 고정 분할에서 교차 비교했다. validation에서 관측된 보조 입력의 이득이 test·미래 구간·경보 부담에서 유지되지 않아 기존 판독 모델을 유지하며, 선정 근거를 표로 제시한다.')
    text = text.replace('빠른 판독은 기존에 포함한 모델을 사용한다.',
        '10/8 모델 탐색은 requirements-model-search.txt 환경에서 python -m castguard.model_search register → cpu/neural, python refine_model_search.py, python analyze_model_search.py shortlist/cpu/neural/seal/evaluate 순서로, 교차 비교는 python -m castguard.crossed_search register → cpu/neural/cpu_refit/neural_refit 후 python analyze_crossed_search.py shortlist/seal/evaluate 로 재현한다. 시간 창 집계 실험은 python castguard/window_search.py 16 으로 약 1분 안에 재현된다. 각 실험의 검증은 verify_model_search.py, verify_crossed_search.py, 결과 요약은 각 reports 폴더의 summary.json이다. 빠른 판독은 기존에 포함한 모델을 사용한다.')
    text = text.replace('핵심 결과: reports/oct06_research/summary.csv',
        '10/8 모델·교차·시간 창 근거: reports/oct08_model_search의 summary.json, ensemble_validation_ranking.csv, test_metrics.csv, uncertainty.json; reports/oct08_crossed_search의 summary.json, model_matrix_validation.csv, model_matrix_test.csv, combo_test.csv, locked_setting_differences.csv, selection_seal.json; reports/oct08_window_search의 registration.json, decisions.json, seed_mean.csv, test_seed_mean.csv, uncertainty.json, summary.json. 대용량 체크포인트는 ZIP에서 제외했고 요약·지표·선택 봉인·예측은 포함했다.\n\n핵심 결과: reports/oct06_research/summary.csv')
    return text


def main():
    BUILD.mkdir(parents=True, exist_ok=True); OUT.mkdir(exist_ok=True)
    old.BUILD, old.OUT = BUILD, OUT
    text = content()
    (BUILD / 'CastGuard_report.md').write_text(text, encoding='utf-8')
    pages = old.render(text)
    (BUILD / 'report_preview.html').write_text('<meta charset="utf-8"><style>body{max-width:1000px;margin:36px auto;font:17px/1.8 "Malgun Gothic";white-space:pre-wrap}</style><body>' + html.escape(text) + '</body>', encoding='utf-8')
    print('report pages', pages)


if __name__ == '__main__':
    main()
