from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from audit_oct03_evidence import require_current_notice,verified_join,assert_input_contract,conditional_value,hwpx_content

ROOT=Path(__file__).resolve().parents[1]
HEADING='2026년 제6회 K-인공지능 제조데이터 분석 경진대회 과제공개(중소·중견기업 재직자)'

def test_notice_namespace_and_edition_are_both_required():
    assert require_current_notice('https://www.kamp-ai.kr/contestNoticeDetail?CPT_NOTICE_SEQ=29',HEADING)
    assert require_current_notice('https://www.kamp-ai.kr/noticeDetail?NOTICE_SEQ=87',HEADING)
    for url,title in [
        ('https://www.kamp-ai.kr/contestDetail?CPT_SEQ=29',HEADING),
        ('https://www.kamp-ai.kr/contestNoticeDetail?CPT_SEQ=29',HEADING),
        ('https://www.kamp-ai.kr/contestNoticeDetail?CPT_NOTICE_SEQ=29',HEADING.replace('2026','2025').replace('제6회','제5회'))]:
        with pytest.raises(ValueError): require_current_notice(url,title)

def test_repeated_shot_numbers_require_run_identity_and_exact_process_match():
    q=pd.DataFrame({'run_id':[0,1],'Shot':[1,1],'Cycle_Time':[20.,21.]})
    m=q.iloc[::-1].copy()
    assert verified_join(q,m,['Cycle_Time'])['matched']==2
    assert not verified_join(q,m,['Cycle_Time'])['physical_equipment_identity_confirmed']
    m['Cycle_Time']=list(reversed(m.Cycle_Time.tolist()))
    with pytest.raises(ValueError,match='Process mismatch'): verified_join(q,m,['Cycle_Time'])

def test_join_rejects_duplication_and_missing_keys():
    q=pd.DataFrame({'run_id':[0,1],'Shot':[1,1],'x':[20.,21.]})
    with pytest.raises(ValueError,match='Ambiguous'): verified_join(q,pd.concat([q,q.iloc[:1]]),['x'])
    with pytest.raises(ValueError,match='Unmatched'): verified_join(q,q.iloc[:1],['x'])

def test_label_or_oracle_columns_cannot_become_predictors():
    contract=json.loads((ROOT/'data/processed/feature_contract.json').read_text())
    assert assert_input_contract(contract)
    for forbidden in ['Machine_Status','PassOrFail','oracle_prior_episodes','y_defect','Inclusions_2','Buring_Mark_1','source_row_m41']:
        modified={k:list(v) if isinstance(v,list) else v for k,v in contract.items()}
        modified['q42_A'].append(forbidden)
        with pytest.raises(ValueError,match='Label/post-outcome'): assert_input_contract(modified)

def test_official_attachments_retain_rubric_disagreement():
    src=ROOT/'docs/sources/oct03_round4'
    _,tables=hwpx_content(src/'employee_task_2026.hwpx')
    rubric=next(t for t in tables if any('AI 모델 및 통합성능' in ''.join(row) for row in t))
    assert next(row[-1] for row in rubric if 'AI 모델 및 통합성능' in row[0])=='35'
    template,_=hwpx_content(src/'employee_report_template_2026.hwpx')
    assert 'AI 모델 개발 및 통합성능 검증〔40점〕' in template
    assert '영향요인 및 오류의 정량분석〔10점〕' in template

def test_backlog_is_not_free_and_episode_value_is_not_assumed():
    base={'quality_captured':100,'inspected':200,'hold_backlog':10,'episodes_inspection_reached':1}
    row={'quality_captured':95,'inspected':202,'hold_backlog':20,'episodes_inspection_reached':3}
    result=conditional_value(row,base,20,1,2)
    assert result['conditional_value_in_inspection_cost_units']==-122
    assert result['required_value_per_extra_episode']==61
    assert conditional_value(base,base,20,1,2)['required_value_per_extra_episode'] is None
    with pytest.raises(ValueError): conditional_value(row,base,20,1.1,2)

def test_real_comparison_uses_same_population_not_macro_quality_rates():
    m=pd.read_csv(ROOT/'reports/oct03_queue/outer_policy_metrics.csv')
    totals=m.loc[m.budget.eq(.2)].groupby(['policy','seed'])[['quality_positive','quality_captured','n_total','inspected','hold_backlog','episodes_inspection_reached']].sum().groupby('policy').mean()
    assert totals.quality_positive.nunique()==1 and totals.n_total.nunique()==1
    value=conditional_value(totals.loc['GQ'],totals.loc['Q'],20,1,0)
    assert value['capture_delta']==pytest.approx(-3.2)
    assert value['conditional_value_in_inspection_cost_units']==pytest.approx(-66)
    assert value['required_value_per_extra_episode']==pytest.approx(66/7)
