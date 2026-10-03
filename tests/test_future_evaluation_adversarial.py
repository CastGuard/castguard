"""Boundary regressions only: every fixture is fabricated and proves no field performance."""
import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import pandas as pd
import pytest
import future_evaluation_core as current
from historical_sources import resolve_historical_source
from test_future_evaluation import synthetic_bundle, at, codes


def write_bundle(folder, cfg, tables):
    folder.mkdir(exist_ok=True)
    (folder/'contract.json').write_text(json.dumps(cfg), encoding='utf-8')
    for name, table in tables.items():
        table.to_csv(folder/(name+'.csv'), index=False)
    return folder


def real_mode_fixture(folder):
    """Exercise real-mode gates with declared fake local files; NEVER performance evidence."""
    cfg, tables = synthetic_bundle()
    for table in tables.values():
        for col in table.columns:
            if col.endswith('_id'):
                table[col] = table[col].str.replace('SYNTHETIC_', 'FIXTURE_', regex=False)
    cfg['data_kind'] = 'real'
    cfg['attestations'] = dict.fromkeys(current.ATTESTATIONS, True)
    folder.mkdir(exist_ok=True)
    def file_record(name, content):
        (folder/name).write_text(content, encoding='utf-8')
        return {'path':name, 'sha256':sha256((folder/name).read_bytes()).hexdigest()}
    cfg['source_files'] = [file_record('fake_source.txt', 'TEST FIXTURE ONLY: NO AUTHENTIC DATA')]
    for policy in cfg['policies']:
        rec = file_record(policy['policy']+'.txt', 'TEST POLICY '+policy['policy'])
        policy.update(definition_path=rec['path'], definition_sha256=rec['sha256'])
    cfg['sampling']['event_id_rule'] = 'TEST FIXTURE: original IDs frozen before outcomes'
    definition = {key:cfg['sampling'][key] for key in ['design','probability','seed','frozen_at','audit_resource_mode','event_id_rule']}
    rec = file_record('sampling.json', json.dumps(definition))
    cfg['sampling'].update(definition_path=rec['path'], definition_sha256=rec['sha256'])
    write_bundle(folder, cfg, tables)
    return cfg, tables


@pytest.mark.parametrize('bad', ['01/02/2030 00:00:10+00:00', '2030-01-01T00:00:10', '2030-01-01T00:00:10-00:00'])
def test_ambiguous_or_unknown_clock_is_rejected(bad):
    cfg, tables = synthetic_bundle()
    tables['events'].loc[0,'produced_at'] = bad
    assert 'TIMESTAMP' in codes(current.validate_tables(cfg,tables))


def test_explicit_offset_equivalence():
    cfg, tables = synthetic_bundle()
    tables['events'].loc[0,'produced_at'] = '2030-01-01T09:00:10+09:00'
    assert current.validate_tables(cfg,tables)['structural_checks_passed']


def test_equal_prediction_inspection_time_cannot_establish_precedence():
    cfg,tables = synthetic_bundle()
    tables['quality_results'].loc[0,'inspection_started_at'] = at(11)
    assert 'PREDICTION_AFTER_INSPECTION' in codes(current.validate_tables(cfg,tables))


@pytest.mark.parametrize('field', ['max_wait_seconds', 'service_seconds'])
def test_boolean_duration_is_not_a_number(field):
    cfg,tables = synthetic_bundle();cfg[field] = True
    assert 'CONTRACT_INCOMPLETE' in codes(current.validate_tables(cfg,tables))


def test_boolean_sampling_probability_is_not_certified_census():
    cfg,tables = synthetic_bundle();cfg['sampling']['probability'] = True
    assert 'CONTRACT_INCOMPLETE' in codes(current.validate_tables(cfg,tables))


@pytest.mark.parametrize('bad', [None, [], {'data_kind':'real','attestations':None}])
def test_nonobject_or_incomplete_contract_is_a_structured_rejection(bad):
    _,tables = synthetic_bundle()
    assert 'CONTRACT_INCOMPLETE' in codes(current.validate_tables(bad,tables))


@pytest.mark.parametrize('field,value', [('attestations',None), ('source_files',[None]), ('policies',[None])])
def test_nested_contract_shapes_do_not_crash(field,value):
    cfg,tables = synthetic_bundle();cfg[field] = value
    assert 'CONTRACT_INCOMPLETE' in codes(current.validate_tables(cfg,tables))


@pytest.mark.parametrize('mode', ['blank','duplicate'])
def test_training_label_identity_trace_must_be_valid(mode):
    cfg,tables = synthetic_bundle()
    if mode=='blank': tables['label_uses'].loc[0,'label_event_id'] = ' '
    else: tables['label_uses'] = pd.concat([tables['label_uses']]*2,ignore_index=True)
    assert 'DUPLICATE_OR_MISSING_KEY' in codes(current.validate_tables(cfg,tables))


def test_known_legacy_event_key_cannot_hide_behind_new_original_key():
    cfg,tables = synthetic_bundle();tables['events']['original_event_id'] = ['fresh'+str(i) for i in range(4)]
    assert 'EXPOSED_EVENT' in codes(current.validate_tables(cfg,tables,legacy_ids=['SYNTHETIC_0']))


def test_expiry_at_same_clock_releases_capacity_before_new_arrival():
    cfg,tables = synthetic_bundle();cfg.update(max_wait_seconds=10,max_queue_size=1)
    ids={'SYNTHETIC_0','SYNTHETIC_1'}
    for name in ['events','features','scores','audit_sample','quality_results']:
        tables[name] = tables[name].loc[tables[name].event_id.isin(ids)].copy()
    tables['events'].loc[1,['produced_at','event_available_at']] = [at(19),at(20)]
    tables['features'].loc[1,['measured_at','available_at']] = [at(19),at(20)]
    tables['scores'].loc[tables['scores'].event_id.eq('SYNTHETIC_1'),'decision_at'] = at(20)
    tables['audit_sample'].loc[1,'selected_at'] = at(20)
    tables['quality_results'].loc[1,['inspection_started_at','inspection_completed_at','label_available_at']] = [at(21),at(26),at(28)]
    tables['capacity_slots'] = pd.DataFrame([['slot0','synthetic_inspector',at(20),at(25)]],columns=current.SCHEMAS['capacity_slots'])
    tables['assignments'] = pd.DataFrame([[p,'slot0','SYNTHETIC_1'] for p in ['FIFO','Q']],columns=current.SCHEMAS['assignments'])
    result=current.validate_tables(cfg,tables)
    assert result['structural_checks_passed'],result['errors']
    assert sum(x['action']=='expired' for x in result['queue_trace'])==2


def test_completion_exactly_at_expiry_is_allowed():
    cfg,tables=synthetic_bundle();cfg['max_wait_seconds']=10
    tables['capacity_slots']=tables['capacity_slots'].iloc[:1]
    tables['assignments']=tables['assignments'].loc[tables['assignments'].slot_id.eq('slot0')]
    result=current.validate_tables(cfg,tables)
    assert result['structural_checks_passed'],result['errors']
    fifo=[x for x in result['queue_trace'] if x['policy']=='FIFO' and x['action']=='inspection_completed']
    assert fifo[0]['event_id']=='SYNTHETIC_0' and fifo[0]['at']==at(20)


def test_arrivals_after_last_slot_still_apply_overflow_and_final_expiry():
    cfg,tables=synthetic_bundle();cfg.update(max_queue_size=1,max_wait_seconds=15)
    tables['capacity_slots']=pd.DataFrame([['early','synthetic_inspector',at(5),at(10)]],columns=current.SCHEMAS['capacity_slots'])
    tables['assignments']=pd.DataFrame([[p,'early',''] for p in ['FIFO','Q']],columns=current.SCHEMAS['assignments'])
    result=current.validate_tables(cfg,tables)
    assert result['structural_checks_passed'],result['errors']
    for policy in ['FIFO','Q']:
        trace=[x for x in result['queue_trace'] if x['policy']==policy]
        assert [x['action'] for x in trace].count('overflow_drop_new')==3
        assert [x['action'] for x in trace].count('expired')==1
        assert not any(x['action']=='unserved_at_window_end' for x in trace)


def test_decision_at_window_end_never_enters_waiting_queue():
    cfg,tables=synthetic_bundle()
    tables['scores'].loc[tables['scores'].event_id.eq('SYNTHETIC_3'),'decision_at']=at(60)
    tables['quality_results'].loc[3,['inspection_started_at','inspection_completed_at','label_available_at']]=[at(61),at(66),at(70)]
    tables['assignments'].loc[tables['assignments'].policy.eq('FIFO'),'event_id']=['SYNTHETIC_0','SYNTHETIC_1','SYNTHETIC_2','']
    tables['assignments'].loc[tables['assignments'].policy.eq('Q'),'event_id']=['SYNTHETIC_1','SYNTHETIC_2','SYNTHETIC_0','']
    result=current.validate_tables(cfg,tables)
    assert result['structural_checks_passed'],result['errors']
    assert sum(x['action']=='unavailable_by_window_end' for x in result['queue_trace'])==2


@pytest.mark.parametrize('mode',['missing','hash','content'])
def test_independent_sampling_requires_a_bound_consistent_local_plan(tmp_path,mode):
    folder=tmp_path/'real';cfg,tables=real_mode_fixture(folder)
    if mode=='missing': cfg['sampling'].pop('definition_path')
    elif mode=='hash': cfg['sampling']['definition_sha256']='0'*64
    else:
        path=folder/'sampling.json';definition=json.loads(path.read_text());definition['probability']=0.5
        path.write_text(json.dumps(definition),encoding='utf-8');cfg['sampling']['definition_sha256']=sha256(path.read_bytes()).hexdigest()
    write_bundle(folder,cfg,tables)
    result=current.validate_bundle(folder,root=tmp_path)
    assert not result['structural_checks_passed']
    assert codes(result)&{'SAMPLING_EVIDENCE_MISSING','SOURCE_HASH','SAMPLING_DEFINITION'}


def test_file_consistency_is_distinct_from_external_provenance(tmp_path):
    folder=tmp_path/'real';cfg,tables=real_mode_fixture(folder)
    tables_only=current.validate_tables(cfg,tables)
    assert tables_only['structural_checks_passed'] and tables_only['status']=='tables_checked_bundle_evidence_required'
    assert tables_only['source_files_verified'] is False
    result=current.validate_bundle(folder,root=tmp_path)
    assert result['structural_checks_passed'],result['errors']
    assert result['source_files_verified'] is True and result['external_provenance_verified'] is False
    assert result['status']=='ready_for_human_provenance_review'
    assert not result['performance_evidence_created'] and not result['field_readiness_certified']


@pytest.mark.parametrize('mode',['hash','traversal'])
def test_policy_source_hash_and_path_checks(tmp_path,mode):
    folder=tmp_path/'real';cfg,tables=real_mode_fixture(folder)
    if mode=='hash': cfg['policies'][0]['definition_sha256']='0'*64
    else: cfg['source_files'][0]['path']='../outside.txt';(tmp_path/'outside.txt').write_text('fixture')
    write_bundle(folder,cfg,tables)
    assert {'SOURCE_HASH','SOURCE_PATH'}&codes(current.validate_bundle(folder,root=tmp_path))


@pytest.mark.parametrize('raw',['[]','null','{"data_kind":"synthetic","data_kind":"real"}','{"probability":NaN}'])
@pytest.mark.parametrize('entry',['future_evaluation.py','future_evaluation_v2.py'])
def test_both_public_entrypoints_fail_closed_with_a_receipt(tmp_path,raw,entry):
    cfg,tables=synthetic_bundle();folder=write_bundle(tmp_path/'input',cfg,tables)
    (folder/'contract.json').write_text(raw,encoding='utf-8');out=tmp_path/'receipt.json'
    run=subprocess.run([sys.executable,'-B',str(Path(current.__file__).parent/entry),'validate','--directory',str(folder),'--output',str(out)],capture_output=True,text=True)
    assert run.returncode==2,run.stderr
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='blocked' and result['validator_revision']==3


@pytest.mark.parametrize('entry',['future_evaluation.py','future_evaluation_v2.py'])
def test_both_public_entrypoints_use_current_revision(tmp_path,entry):
    cfg,tables=synthetic_bundle();folder=write_bundle(tmp_path/'input',cfg,tables);out=tmp_path/'receipt.json'
    run=subprocess.run([sys.executable,'-B',str(Path(current.__file__).parent/entry),'validate','--directory',str(folder),'--output',str(out)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert json.loads(out.read_text(encoding='utf-8'))['validator_revision']==3


def test_historical_resolver_requires_the_exact_archived_bytes(tmp_path):
    (tmp_path/'legacy').mkdir()
    (tmp_path/'future_evaluation.py').write_bytes(b'current implementation')
    archived=tmp_path/'legacy/future_evaluation_v1.py';archived.write_bytes(b'original implementation')
    expected=sha256(archived.read_bytes()).hexdigest()
    assert resolve_historical_source(tmp_path,'future_evaluation.py',expected)==archived
    archived.write_bytes(b'tampered')
    with pytest.raises(AssertionError):resolve_historical_source(tmp_path,'future_evaluation.py',expected)
    with pytest.raises(AssertionError):resolve_historical_source(tmp_path,'unmapped.py',expected)
    with pytest.raises(AssertionError):resolve_historical_source(tmp_path,'../outside.py',expected)


@pytest.mark.parametrize('name', ['../outside.csv','', 'C:/outside.csv'])
def test_bundle_input_containment_is_checked_before_read(tmp_path,name):
    with pytest.raises(ValueError):current.local_file(tmp_path.resolve(),name)


def test_in_service_work_is_not_waiting_capacity_and_not_inspected_twice():
    cfg,tables=synthetic_bundle();cfg['resources']=['r1','r2']
    tables['capacity_slots']=pd.DataFrame([
        ['a','r1',at(15),at(20)],['b','r2',at(15),at(20)],
        ['c','r1',at(20),at(25)],['d','r2',at(20),at(25)]],columns=current.SCHEMAS['capacity_slots'])
    rows=[]
    for policy,order in [('FIFO',[0,1,2,3]),('Q',[1,2,3,0])]:
        rows.extend([[policy,slot,'SYNTHETIC_'+str(i)] for slot,i in zip(['a','b','c','d'],order)])
    tables['assignments']=pd.DataFrame(rows,columns=current.SCHEMAS['assignments'])
    result=current.validate_tables(cfg,tables)
    assert result['structural_checks_passed'],result['errors']
    for policy in ['FIFO','Q']:
        completed=[x['event_id'] for x in result['queue_trace'] if x['policy']==policy and x['action']=='inspection_completed']
        assert len(completed)==len(set(completed))==4
    tables['assignments'].loc[1,'event_id']='SYNTHETIC_0'
    assert 'QUEUE_ASSIGNMENT' in codes(current.validate_tables(cfg,tables))
