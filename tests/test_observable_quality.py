"""Contract regressions with one tiny synthetic fixture, never competition training."""
from copy import deepcopy
from pathlib import Path
import json
import math
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

from castguard.decision_review import PROCESS, ContractError, digest
from castguard.observable_quality import ObservableQualityReviewer, SCHEMA, TASK, MODEL_PATH, BASIS, render_html


@pytest.fixture(scope='module')
def fixture_root(tmp_path_factory):
    root=tmp_path_factory.mktemp('observable_quality_fixture')
    rng=np.random.default_rng(510)
    frame=pd.DataFrame(rng.normal(size=(32,14)),columns=PROCESS)
    pipe=Pipeline([('impute',SimpleImputer(strategy='median',keep_empty_features=True).set_output(transform='pandas')),
                   ('scale',StandardScaler()),('model',LogisticRegression(random_state=17))])
    pipe.fit(frame,np.arange(32)%2)
    path=root/MODEL_PATH;path.parent.mkdir(parents=True)
    joblib.dump({'pipeline':pipe,'features':PROCESS,'task':TASK,'learned':{},'threshold':.5},path)
    cfg={'schema_version':'castguard-observable-profile-v1','input_schema':SCHEMA,'task':TASK,
         'path':MODEL_PATH,'sha256':digest(path),'features':PROCESS,'selection_rule':'synthetic test fixture only',
         'training_reference':{'partition':'original_forward_run_train','rows':32,'products':[1]},
         'ranges':{f:[float(frame[f].min()),float(frame[f].max())] for f in PROCESS}}
    (root/'configs').mkdir();(root/'configs/observable_quality.json').write_text(json.dumps(cfg),encoding='utf-8')
    return root


@pytest.fixture
def reviewer(fixture_root):return ObservableQualityReviewer(fixture_root)


@pytest.fixture
def record():
    return {'record_id':'new-event-not-in-any-table','observation_basis':BASIS,'measurements':{f:0.1 for f in PROCESS}}


def envelope(*rows):return {'schema_version':SCHEMA,'records':list(rows)}


def test_complete_observable_input_scores_without_any_counter_history_or_labels(reviewer,record):
    out=reviewer.review(envelope(record));row=out['records'][0]
    assert row['status']=='scored' and len(row['explanation']['contributions'])==14
    assert not out['input_capability']['quality_row_counter_required']
    assert not out['input_capability']['process_counter_required']
    assert not out['input_capability']['history_required'] and not out['input_capability']['label_file_required']
    assert not out['input_capability']['observation_lookup_performed']
    assert not out['input_capability']['live_acquisition_timing_verified']
    assert not out['performance_improvement_claimed']
    e=row['explanation'];margin=e['baseline_margin']+sum(v['contribution'] for v in e['contributions'])
    assert e['scale']=='log_odds_of_encoded_class_1'
    assert 1/(1+math.exp(-margin))==pytest.approx(row['score'],abs=1e-6)


def test_no_table_access_even_in_constructor(fixture_root,record,monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('Table access is forbidden')
    monkeypatch.setattr(pd,'read_csv',forbidden);monkeypatch.setattr(pd,'read_parquet',forbidden)
    out=ObservableQualityReviewer(fixture_root).review(envelope(record))
    assert out['records'][0]['status']=='scored'
    assert not (fixture_root/'data').exists()


@pytest.mark.parametrize('key',['quality_record_position','shot_position','history','observation','y_defect','timestamp'])
def test_historical_and_label_fields_rejected_without_fallback(reviewer,record,key):
    record[key]=0
    out=reviewer.review(envelope(record))['records'][0]
    assert out['status']=='invalid_input' and out['score'] is None


@pytest.mark.parametrize('key',['Machine_Status','Short_Shot_1','Factory_Temp','Product_Type','shot_position'])
def test_only_process14_can_be_model_features(reviewer,record,key):
    record['measurements'][key]=1
    assert reviewer.review(envelope(record))['records'][0]['status']=='invalid_input'


def test_old_schema_requires_explicit_separate_path(reviewer,record):
    data=envelope(record);data['schema_version']='castguard-shot-v1'
    with pytest.raises(ContractError,match='no automatic path switch'):reviewer.review(data)


@pytest.mark.parametrize('missing',[None,'absent'])
def test_missing_measurement_abstains_without_silent_imputation(reviewer,record,missing):
    if missing is None:record['measurements']['Cycle_Time']=None
    else:del record['measurements']['Cycle_Time']
    row=reviewer.review(envelope(record))['records'][0]
    assert row['status']=='not_scored' and row['score'] is None and row['explanation'] is None
    assert row['reasons']==[{'code':'missing_current_process_input','feature':'Cycle_Time'}]


@pytest.mark.parametrize('bad',[True,'1.2',float('nan'),float('inf')])
def test_invalid_numeric_values_never_coerced(reviewer,record,bad):
    record['measurements']['Casting_Pressure']=bad
    assert reviewer.review(envelope(record))['records'][0]['status']=='invalid_input'


def test_product_context_warns_but_never_changes_the_score(reviewer,record):
    variants=[]
    for product in [None,1,2]:
        r=deepcopy(record);r['record_id']=f'context-{product}'
        if product is not None:r['context']={'product_type':product}
        variants.append(r)
    out=reviewer.review(envelope(*variants));rows=out['records']
    assert len({r['score'] for r in rows})==1
    assert rows[0]['warnings'][0]['code']=='product_support_unknown'
    assert rows[2]['warnings'][0]['code']=='unseen_product'
    assert all(r['score_interpretation']=='diagnostic_only_uncalibrated_model_output' and not r['calibrated'] for r in rows)


def test_batch_permutation_single_call_and_feature_key_order_invariance(reviewer,record):
    a=deepcopy(record);b=deepcopy(record);b['record_id']='arbitrary-new-id';b['measurements']['Casting_Pressure']=.123
    full=reviewer.review(envelope(a,b))['records']
    reverse=reviewer.review(envelope(b,a))['records'][::-1]
    for left,right in zip(full,reverse):
        assert {k:v for k,v in left.items() if k!='record_index'}=={k:v for k,v in right.items() if k!='record_index'}
    b['measurements']=dict(reversed(list(b['measurements'].items())))
    one=reviewer.review(envelope(b))['records'][0]
    assert one['score']==full[1]['score'] and one['explanation']==full[1]['explanation']


def test_duplicate_id_rejected(reviewer,record):
    with pytest.raises(ContractError):reviewer.review(envelope(record,record))


@pytest.mark.parametrize('mutation',['features','path','task','hash'])
def test_only_pinned_original_baseline_allowed(fixture_root,tmp_path,mutation):
    cfg=json.loads((fixture_root/'configs/observable_quality.json').read_text(encoding='utf-8'))
    if mutation=='features':cfg['features']=PROCESS+['shot_position']
    if mutation=='path':cfg['path']='reports/oct03_queue/model.joblib'
    if mutation=='task':cfg['task']['experiment']='A'
    if mutation=='hash':cfg['sha256']='0'*64
    path=tmp_path/'cfg.json';path.write_text(json.dumps(cfg),encoding='utf-8')
    with pytest.raises(ContractError):ObservableQualityReviewer(fixture_root,config=path)


def test_html_escapes_ids_and_distinguishes_input_capability_from_validation(reviewer,record):
    record['record_id']='<script>bad</script>'
    html=render_html(reviewer.review(envelope(record)))
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '미보정' in html and '미래 성능은 검증하지 않았습니다' in html and 'log-odds' in html


def test_cli_only_needs_pinned_model_and_profile(fixture_root,tmp_path,record):
    inp=tmp_path/'input.json';inp.write_text(json.dumps(envelope(record)),encoding='utf-8')
    out=tmp_path/'output.json'
    script=Path(__file__).resolve().parents[1]/'observable_quality.py'
    command=[sys.executable,'-I','-B','-X','utf8',str(script),'--root',str(fixture_root),'--input',str(inp),'--output',str(out)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    assert json.loads(out.read_text(encoding='utf-8'))['records'][0]['status']=='scored'
    old=out.read_bytes();result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==2 and out.read_bytes()==old
