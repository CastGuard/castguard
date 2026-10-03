"""CSV identity and contract boundary regression checks; synthetic functionality only."""
import json
import pandas as pd
import pytest
from test_future_evaluation import synthetic_bundle,codes
from legacy import future_evaluation_v1 as original
import future_evaluation_v2 as current

def bundle_on_disk(tmp_path,ids):
    cfg,tables=synthetic_bundle()
    mapping={f'SYNTHETIC_{i}':v for i,v in enumerate(ids)}
    for table in tables.values():
        for column in ['event_id','original_event_id']:
            if column in table:table[column]=table[column].replace(mapping)
    folder=tmp_path/'bundle';folder.mkdir()
    (folder/'contract.json').write_text(json.dumps(cfg),encoding='utf-8')
    for name,table in tables.items():table.to_csv(folder/(name+'.csv'),index=False)
    return folder

@pytest.mark.parametrize('ids',[
 ['000001','000002','000003','000004'],
 ['NA','NULL','nan','N/A'],
 ['9007199254740993','9007199254740994','9007199254740995','9007199254740996'],
])
def test_csv_preserves_opaque_identity_and_exact_queue(tmp_path,ids):
    folder=bundle_on_disk(tmp_path,ids)
    before=original.validate_bundle(folder,root=tmp_path)
    after=current.validate_bundle(folder,root=tmp_path)
    assert before['status']=='blocked'
    assert after['structural_checks_passed'],after['errors']
    assert after['status']=='synthetic_functional_checks_only'
    for policy,order in [('FIFO',ids),('Q',[ids[1],ids[2],ids[3],ids[0]])]:
        selected=[r['event_id'] for r in after['queue_trace'] if r['policy']==policy and r['action']=='inspection_completed']
        assert selected==order
    assert not after['performance_evidence_created']

def test_blank_group_cannot_pass_stratification_contract():
    cfg,tables=synthetic_bundle();tables['events'].loc[0,'run_id']=' '
    assert original.validate_tables(cfg,tables)['structural_checks_passed']
    assert 'GROUP_OR_RESOURCE_ID' in codes(current.validate_tables(cfg,tables))

def test_boolean_queue_capacity_is_not_one_inspection_place():
    cfg,tables=synthetic_bundle();cfg['max_queue_size']=True
    result=current.validate_tables(cfg,tables)
    assert 'CONTRACT_INCOMPLETE' in codes(result)

def test_csv_idle_stays_empty_and_blank_feature_stays_missing(tmp_path):
    cfg,tables=synthetic_bundle();cfg['max_wait_seconds']=6
    tables['assignments']['event_id']=''
    folder=tmp_path/'idle';folder.mkdir()
    (folder/'contract.json').write_text(json.dumps(cfg),encoding='utf-8')
    for name,table in tables.items():table.to_csv(folder/(name+'.csv'),index=False)
    result=current.validate_bundle(folder,root=tmp_path)
    assert result['structural_checks_passed'],result['errors']
    assert not any(x['action']=='inspection_completed' for x in result['queue_trace'])
    cfg,tables=synthetic_bundle();tables['features'].loc[0,'value']=float('nan')
    (folder/'contract.json').write_text(json.dumps(cfg),encoding='utf-8')
    for name,table in tables.items():table.to_csv(folder/(name+'.csv'),index=False)
    assert 'FUTURE_OR_MISSING_FEATURE' in codes(current.validate_bundle(folder,root=tmp_path))

def test_csv_duplicate_ids_and_malformed_audit_boolean_still_block(tmp_path):
    folder=bundle_on_disk(tmp_path,['000001','000001','000003','000004'])
    assert 'DUPLICATE_OR_MISSING_KEY' in codes(current.validate_bundle(folder,root=tmp_path))
    raw=(folder/'audit_sample.csv').read_text(encoding='utf-8').replace('True','not_true')
    (folder/'audit_sample.csv').write_text(raw,encoding='utf-8')
    assert not current.validate_bundle(folder,root=tmp_path)['structural_checks_passed']
