"""Synthetic fixtures test functionality only. They are never performance evidence."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from future_evaluation import SCHEMAS,draft_contract,validate_tables,init_bundle,validate_bundle,audit_selected

def at(seconds):return (pd.Timestamp('2030-01-01T00:00:00Z')+pd.Timedelta(seconds=seconds)).isoformat()

def synthetic_bundle():
    cfg=draft_contract();cfg.update(data_kind='synthetic',protocol_frozen_at=at(-100),evaluation_start_at=at(0),
      evaluation_end_at=at(60),outcome_cutoff_at=at(120),required_features=['Velocity_1'],resources=['synthetic_inspector'],
      max_wait_seconds=50,max_queue_size=10,service_seconds=5)
    cfg['sampling'].update(design='census',probability=1,seed=123,frozen_at=at(-100))
    for p in cfg['policies']:p.update(definition_sha256='0'*64,frozen_at=at(-100))
    data={name:[] for name in SCHEMAS}
    risks=[.1,.4,.3,.2]
    for i in range(4):
        e=f'SYNTHETIC_{i}';prod=10+i
        data['events'].append([e,e,'synthetic_run',at(prod),at(prod+1)])
        data['features'].append([e,'Velocity_1',i+1,at(prod),at(prod+1)])
        data['audit_sample'].append([e,at(prod+1),True,1])
        data['quality_results'].append([e,at(prod+2),at(prod+7),at(prod+9),i%2])
        for p in ['FIFO','Q']:data['scores'].append([p,e,at(prod+1),2,0. if p=='FIFO' else risks[i]])
    for i in range(4):
        data['capacity_slots'].append([f'slot{i}','synthetic_inspector',at(15+10*i),at(20+10*i)])
        data['assignments'].append(['FIFO',f'slot{i}',f'SYNTHETIC_{i}'])
        data['assignments'].append(['Q',f'slot{i}',f'SYNTHETIC_{[1,2,3,0][i]}'])
    data['label_uses'].append(['Q','SYNTHETIC_TRAIN',at(-300),at(-200)])
    return cfg,{name:pd.DataFrame(rows,columns=SCHEMAS[name]) for name,rows in data.items()}

def codes(result):return {x['code'] for x in result['errors']}

def test_valid_synthetic_never_becomes_performance_evidence():
    c,t=synthetic_bundle();result=validate_tables(c,t)
    assert result['structural_checks_passed'],result['errors']
    assert result['status']=='synthetic_functional_checks_only'
    assert result['performance_evidence_created'] is False and result['field_readiness_certified'] is False
    assert len([r for r in result['queue_trace'] if r['action']=='inspection_completed'])==8

def test_future_feature_cannot_be_used_or_silently_filtered():
    c,t=synthetic_bundle();t['features'].loc[2,'available_at']=at(100)
    assert 'FUTURE_OR_MISSING_FEATURE' in codes(validate_tables(c,t))

def test_missing_input_has_shared_hold_fifo_priority():
    c,t=synthetic_bundle();t['features'].loc[2,'available_at']=at(100)
    t['scores'].loc[t['scores'].event_id.eq('SYNTHETIC_2'),['priority_class','score']]=[0,np.nan]
    for p,order in [('FIFO',[2,0,1,3]),('Q',[2,1,3,0])]:
        t['assignments'].loc[t['assignments'].policy.eq(p),'event_id']=[f'SYNTHETIC_{i}' for i in order]
    result=validate_tables(c,t);assert result['structural_checks_passed'],result['errors']
    for p in ['FIFO','Q']:
        first=next(r for r in result['queue_trace'] if r['policy']==p and r['action']=='inspection_completed')
        assert first['event_id']=='SYNTHETIC_2'

def test_every_production_event_needs_scores_even_without_audit_label():
    c,t=synthetic_bundle();t['scores']=t['scores'].iloc[:-1]
    assert 'SCORE_COHORT' in codes(validate_tables(c,t))

def test_label_cannot_arrive_before_inspection_completes():
    c,t=synthetic_bundle();t['quality_results'].loc[0,'label_available_at']=at(11)
    assert 'LABEL_TIME' in codes(validate_tables(c,t))

def test_training_cannot_use_future_or_evaluation_labels():
    c,t=synthetic_bundle();t['label_uses'].loc[0,'label_available_at']=at(-150)
    assert 'FUTURE_LABEL' in codes(validate_tables(c,t))
    c,t=synthetic_bundle();t['label_uses'].loc[0,'label_event_id']='SYNTHETIC_0'
    assert 'EVALUATION_LABEL_USE' in codes(validate_tables(c,t))

def test_audit_selection_is_recomputed_from_frozen_draw():
    c,t=synthetic_bundle();c['sampling'].update(design='hash_bernoulli',probability=.5,seed=7)
    t['audit_sample']['probability']=.5
    t['audit_sample']['selected']=[audit_selected(e,7,.5) for e in t['events'].event_id]
    selected=set(t['audit_sample'].loc[t['audit_sample'].selected,'event_id'])
    t['quality_results']=t['quality_results'].loc[t['quality_results'].event_id.isin(selected)]
    assert validate_tables(c,t)['structural_checks_passed']
    t['audit_sample'].loc[0,'selected']=not bool(t['audit_sample'].loc[0,'selected'])
    assert 'AUDIT_SELECTION' in codes(validate_tables(c,t))

def test_policy_sampling_labels_cannot_replace_independent_audit_labels():
    c,t=synthetic_bundle();t['quality_results']=t['quality_results'].iloc[:-1]
    assert 'AUDIT_LABEL_COVERAGE' in codes(validate_tables(c,t))

def test_future_target_or_availability_proxy_is_not_a_feature():
    c,t=synthetic_bundle();c['required_features']=['quality_available']
    assert 'CONTRACT_INCOMPLETE' in codes(validate_tables(c,t))
    c,t=synthetic_bundle();t['features'].loc[0,'feature']='y_defect'
    assert 'FORBIDDEN_INPUT' in codes(validate_tables(c,t))

def test_prediction_must_precede_inspection_and_information_time_is_shared():
    c,t=synthetic_bundle();t['scores'].loc[t['scores'].event_id.eq('SYNTHETIC_0'),'decision_at']=at(30)
    assert 'PREDICTION_AFTER_INSPECTION' in codes(validate_tables(c,t))
    c,t=synthetic_bundle();t['scores'].loc[0,'decision_at']=at(12)
    assert 'UNEQUAL_DECISION_TIME' in codes(validate_tables(c,t))

def test_resource_slots_cannot_overlap_or_be_extended_by_one_policy():
    c,t=synthetic_bundle();t['capacity_slots'].loc[1,['start_at','complete_at']]=[at(16),at(21)]
    assert 'RESOURCE_OVERLAP' in codes(validate_tables(c,t))
    c,t=synthetic_bundle();t['assignments']=t['assignments'].iloc[:-1]
    assert 'CAPACITY_COVERAGE' in codes(validate_tables(c,t))

def test_expiry_is_checked_at_completion_not_only_inspection_start():
    c,t=synthetic_bundle();c['max_wait_seconds']=6
    assert 'QUEUE_ASSIGNMENT' in codes(validate_tables(c,t))
    t['assignments']['event_id']=np.nan
    result=validate_tables(c,t);assert result['structural_checks_passed'],result['errors']
    assert not any(x['action']=='inspection_completed' for x in result['queue_trace'])

def test_bounded_waiting_room_drop_new_applies_equally():
    c,t=synthetic_bundle();c['max_queue_size']=2
    for p,order in [('FIFO',['SYNTHETIC_0','SYNTHETIC_1',np.nan,np.nan]),('Q',['SYNTHETIC_1','SYNTHETIC_0',np.nan,np.nan])]:
        t['assignments'].loc[t['assignments'].policy.eq(p),'event_id']=order
    result=validate_tables(c,t);assert result['structural_checks_passed'],result['errors']
    assert len([x for x in result['queue_trace'] if x['action']=='overflow_drop_new'])==4

def test_labels_never_change_queue_replay():
    c,t=synthetic_bundle();first=validate_tables(c,t)
    t['quality_results']['y_defect']=1-t['quality_results'].y_defect
    second=validate_tables(c,t)
    assert first['queue_trace']==second['queue_trace'] and second['structural_checks_passed']

def test_old_source_ids_are_not_a_fresh_holdout():
    c,t=synthetic_bundle()
    assert 'EXPOSED_EVENT' in codes(validate_tables(c,t,legacy_ids=['SYNTHETIC_0']))

def test_real_data_needs_explicit_provenance_review_inputs():
    c,t=synthetic_bundle();c['data_kind']='real'
    result=validate_tables(c,t)
    assert {'PROVENANCE_ATTESTATION_MISSING','SOURCE_RECORDS_MISSING'}<=codes(result)
    assert result['field_readiness_certified'] is False

def test_synthetic_fixture_cannot_be_relabeled_as_real():
    c,t=synthetic_bundle();c['data_kind']='real'
    assert 'SYNTHETIC_AS_REAL' in codes(validate_tables(c,t))

def test_naive_clock_and_invalid_numeric_values_are_blocked():
    c,t=synthetic_bundle();t['events'].loc[0,'produced_at']='2030-01-01 00:00:10'
    assert 'TIMESTAMP' in codes(validate_tables(c,t))
    c,t=synthetic_bundle();t['scores']['score']=t['scores']['score'].astype(object);t['scores'].loc[0,'score']='not a number'
    assert 'INVALID_NUMBER' in codes(validate_tables(c,t))

def test_init_creates_empty_blocked_draft_and_never_fills_fake_data(tmp_path):
    dest=tmp_path/'request';init_bundle(dest)
    result=validate_bundle(dest,root=tmp_path)
    assert result['status']=='blocked' and not result['performance_evidence_created']
    assert all(pd.read_csv(dest/(name+'.csv')).empty for name in SCHEMAS)
    with pytest.raises(FileExistsError):init_bundle(dest)
