"""Inference contract/adapter regressions using small synthetic test models only.

These fits are test fixtures, not competition experiments or model selection.
Actual frozen-model replay is checked separately by verify_decision_review.py.
"""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest
from lightgbm import LGBMClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from castguard.decision_review import (DecisionReviewer, ContractError, PROCESS, SENSORS,
    QUALITY, GATE, SCHEMA, POSITION_BASIS, MAX_EXACT_INTEGER, digest, read_json, render_html, parse_record)


@pytest.fixture(scope="module")
def fixture_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("decision_review")
    (root / "reports/oct03_queue/models").mkdir(parents=True)
    (root / "configs").mkdir()
    entry = {}
    rng = np.random.default_rng(3105)
    for task, features, family in [("quality", QUALITY, "logistic"), ("gate", GATE, "lightgbm")]:
        x = pd.DataFrame(rng.normal(size=(32,len(features))), columns=features)
        if task == "quality":
            x["Product_Type"] = 1
            x["shot_position"] = np.arange(len(x))
        y = np.arange(len(x)) % 2
        steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True).set_output(transform="pandas"))]
        if family == "logistic":
            steps += [("scale", StandardScaler()), ("model", LogisticRegression(random_state=17))]
        else:
            steps += [("model", LGBMClassifier(n_estimators=4,num_leaves=3,min_child_samples=2,n_jobs=1,verbosity=-1,random_state=17))]
        pipe=Pipeline(steps).fit(x,y)
        rel=f"reports/oct03_queue/models/2__{task}__{family}__17.joblib"
        data={"pipeline":pipe,"features":features,"fold":"2","task":task,"model":family,"seed":17,"fit_row_ids":[]}
        joblib.dump(data,root/rel)
        entry[task]={k:data[k] for k in ["features","fold","task","model","seed"]}
        entry[task].update(path=rel,sha256=digest(root/rel),encoded_target="synthetic_binary_fixture",
            ranges={f:[float(x[f].min()),float(x[f].max())] for f in features},
            training_reference={"partition":"inner_fit_only","rows":32,"products":[1] if task=="quality" else None})
        if task=="gate":
            entry[task]["threshold"]={"disabled":False,"threshold":.5,"reason":"synthetic_test_only"}
    cfg={"schema_version":"castguard-review-profile-v1","input_schema":SCHEMA,
         "checkpoints":{"queue-fold2-seed17":entry}}
    (root/"configs/decision_review.json").write_text(json.dumps(cfg),encoding="utf-8")
    return root


@pytest.fixture
def reviewer(fixture_root):
    return DecisionReviewer(fixture_root)


@pytest.fixture
def record():
    return {"record_id":"fixture", "observation":{"run_key":"r","sequence":3,
        "quality_record_position":2,"position_basis":POSITION_BASIS},
        "measurements":{**{f:.1 for f in PROCESS+SENSORS},"Product_Type":1},
        "history":[{"run_key":"r","sequence":i,"Cycle_Time":float(i+1)} for i in range(3)]}


def envelope(record):
    return {"schema_version":SCHEMA,"records":[record]}


def output(reviewer, record):
    return reviewer.review(envelope(record))["records"][0]


def test_real_adapters_reconstruct_margin_and_score(reviewer,record):
    result=output(reviewer,record)
    for task in ["quality","equipment_state"]:
        stage=result[task]
        assert stage["status"]=="scored"
        e=stage["explanation"]
        assert e["margin_error"]<1e-6 and e["score_error"]<1e-6
        assert sum(v["contribution"] for v in e["contributions"])+e["baseline_margin"]==pytest.approx(e["raw_margin"])
        assert not e["causal"] and not stage["calibrated"]
    assert result["quality"]["explanation"]["method"]=="linear_margin_decomposition"
    assert result["equipment_state"]["explanation"]["method"]=="lightgbm_native_tree_shap"


def test_no_table_access_and_withheld_label_changes_do_not_matter(reviewer,record,monkeypatch,tmp_path):
    def forbidden(*a,**kw):raise AssertionError("Inference read a table")
    monkeypatch.setattr(pd,"read_csv",forbidden)
    monkeypatch.setattr(pd,"read_parquet",forbidden)
    expected=output(reviewer,record)
    labels=tmp_path/"withheld_labels.csv"
    for text in ["row_id,y_defect\nfixture,0\n", "row_id,y_defect\nother,1\nfixture,1\n", ""]:
        labels.write_text(text)
        assert output(reviewer,record)==expected
    assert output(reviewer,record)==expected


@pytest.mark.parametrize("where,key",[("record","y_defect"),("measurements","Short_Shot_1"),
    ("measurements","Machine_Status"),("measurements","oracle_prior_episodes"),
    ("observation","source_row"),("history","y_defect"),("measurements","unknown_feature")])
def test_leakage_and_unknown_fields_rejected(reviewer,record,where,key):
    target=record if where=="record" else record["history"][0] if where=="history" else record[where]
    target[key]=1
    r=output(reviewer,record)
    assert r["status"]=="invalid_input" and r["quality"] is None and r["equipment_state"] is None


@pytest.mark.parametrize("bad",["1.2",True,float("nan"),float("inf"),float("-inf"),[],{}])
def test_invalid_numbers_are_not_coerced(reviewer,record,bad):
    record["measurements"]["Casting_Pressure"]=bad
    assert output(reviewer,record)["status"]=="invalid_input"


@pytest.mark.parametrize("bad",[1.0,True,-1,"1"])
def test_product_requires_positive_integer(reviewer,record,bad):
    record["measurements"]["Product_Type"]=bad
    assert output(reviewer,record)["status"]=="invalid_input"


def test_missing_sensor_only_blocks_quality(reviewer,record):
    del record["measurements"]["Factory_Temp"]
    r=output(reviewer,record)
    assert r["quality"]["score"] is None
    assert r["equipment_state"]["status"]=="scored"


def test_missing_process_blocks_both(reviewer,record):
    record["measurements"]["Cycle_Time"]=None
    r=output(reviewer,record)
    assert r["quality"]["score"] is None and r["equipment_state"]["score"] is None


def test_unseen_product_keeps_diagnostic_score_with_warning(reviewer,record):
    record["measurements"]["Product_Type"]=2
    r=output(reviewer,record)
    assert r["quality"]["score"] is not None
    assert {"code":"unseen_product","value":2.0} in r["quality"]["warnings"]
    assert r["quality"]["operational_recommendation"]=="abstain"


def test_extreme_finite_values_warn_or_fail_closed(reviewer,record):
    record["measurements"]["Casting_Pressure"]=1e300
    r=output(reviewer,record)
    assert r["status"]=="reviewed"
    for task in ["quality","equipment_state"]:
        s=r[task]
        assert s["status"]=="not_scored" or s["applicability"]=="outside_reference"
    json.dumps(r,allow_nan=False)


def test_unknown_history_only_blocks_equipment(reviewer,record):
    del record["history"]
    r=output(reviewer,record)
    assert r["quality"]["status"]=="scored" and r["equipment_state"]["score"] is None


def test_known_run_start_uses_frozen_imputer(reviewer,record):
    record["observation"].update(sequence=0,quality_record_position=0)
    record["history"]=[]
    r=output(reviewer,record)
    assert r["equipment_state"]["status"]=="scored"
    imputed={x["feature"] for x in r["equipment_state"]["explanation"]["contributions"] if x["was_imputed"]}
    assert imputed=={"prev_cycle_time","max_cycle_previous_5"}


@pytest.mark.parametrize("mutation",["future","reverse","other_run","too_short","current"])
def test_invalid_history_never_silently_reorders(reviewer,record,mutation):
    if mutation=="future":record["history"][-1]["sequence"]=4
    if mutation=="current":record["history"][-1]["sequence"]=3
    if mutation=="reverse":record["history"].reverse()
    if mutation=="other_run":record["history"][0]["run_key"]="different"
    if mutation=="too_short":record["history"].pop()
    assert output(reviewer,record)["status"]=="invalid_input"


def test_history_features_use_previous_records_not_current(record):
    values,known,_=parse_record(record)
    assert known and values["prev_cycle_time"]==3 and values["max_cycle_previous_5"]==3
    record["measurements"]["Cycle_Time"]=999
    changed,_,_=parse_record(record)
    assert changed["prev_cycle_time"]==3 and changed["max_cycle_previous_5"]==3


def test_unsupported_counter_basis_abstains_quality(reviewer,record):
    record["observation"]["position_basis"]="physical_shot_number"
    r=output(reviewer,record)
    assert r["quality"]["score"] is None and r["equipment_state"]["score"] is not None


def test_counter_cannot_exceed_process_sequence(reviewer,record):
    record["observation"]["quality_record_position"]=4
    assert output(reviewer,record)["status"]=="invalid_input"


@pytest.mark.parametrize("mutation",["version","unknown_key","duplicate_id","empty"])
def test_invalid_envelope_rejected(reviewer,record,mutation):
    data=envelope(record)
    if mutation=="version":data["schema_version"]="v0"
    if mutation=="unknown_key":data["labels"]={}
    if mutation=="duplicate_id":data["records"].append(deepcopy(record))
    if mutation=="empty":data["records"]=[]
    with pytest.raises(ContractError):reviewer.review(data)


@pytest.mark.parametrize("content",['{"records":[],"records":[]}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_duplicates_and_nonstandard_numbers(tmp_path,content):
    p=tmp_path/"input.json";p.write_text(content)
    with pytest.raises(ContractError):read_json(p)


@pytest.mark.parametrize("mutation",["schema","family","features","range","product_reference","hash","identity","path"])
def test_unsupported_or_changed_artifact_rejected(fixture_root,tmp_path,mutation):
    cfg=read_json(fixture_root/"configs/decision_review.json")
    q=cfg["checkpoints"]["queue-fold2-seed17"]["quality"]
    if mutation=="schema":cfg["schema_version"]="unknown"
    if mutation=="family":q["model"]="random_forest"
    if mutation=="features":q["features"]=q["features"][::-1]
    if mutation=="range":q["ranges"]["Cycle_Time"]=[10,1]
    if mutation=="product_reference":q["training_reference"]["products"]=[]
    if mutation=="hash":q["sha256"]="0"*64
    if mutation=="identity":q["seed"]=29
    if mutation=="path":q["path"]="elsewhere/model.joblib"
    path=tmp_path/"profile.json";path.write_text(json.dumps(cfg))
    with pytest.raises(ContractError):DecisionReviewer(fixture_root,config=path)


def test_alarm_threshold_comparison_and_disabled_are_distinct(reviewer,record):
    g=reviewer.profile["gate"]["threshold"]
    g.update(threshold=0.,disabled=False)
    assert output(reviewer,record)["equipment_state"]["alarm"]["value"] is True
    g.update(threshold=None,disabled=True,reason="insufficient_validation_episodes")
    alarm=output(reviewer,record)["equipment_state"]["alarm"]
    assert alarm["value"] is None and alarm["status"]=="disabled" and not alarm["production_stop"]


def test_html_escapes_user_input_and_names_actual_scale(reviewer,record):
    record["record_id"]='<script>alert(1)</script>'
    text=render_html(reviewer.review(envelope(record)))
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert 'log-odds' in text and '미보정' in text


def test_cli_runs_and_refuses_overwrite(fixture_root,tmp_path,record):
    p=tmp_path/"input.json";p.write_text(json.dumps(envelope(record)))
    out=tmp_path/"output.json";web=tmp_path/"output.html"
    script=Path(__file__).resolve().parents[1]/"decision_review.py"
    cmd=[sys.executable,"-I","-B","-X","utf8",str(script),"--root",str(fixture_root),
         "--input",str(p),"--output",str(out),"--html",str(web)]
    first=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8")
    assert first.returncode==0,first.stderr
    old=out.read_bytes()
    second=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8")
    assert second.returncode==2 and out.read_bytes()==old
    assert 'preserved' in second.stderr


def series(record, count=9, run='consistent-run'):
    """Deterministic observed sequence with complete, unfiltered packet history."""
    records=[]
    for seq in range(count):
        r=deepcopy(record)
        r['record_id']=f'{run}:{seq}'
        r['observation'].update(run_key=run,sequence=seq,quality_record_position=seq)
        r['measurements']['Cycle_Time']=float(seq+1)/10
        r['history']=[{'run_key':run,'sequence':i,'Cycle_Time':float(i+1)/10}
                      for i in range(max(0,seq-5),seq)]
        records.append(r)
    return records


def semantic_rows(result):
    return {r['record_id']:{k:v for k,v in r.items() if k!='record_index'} for r in result['records']}


@pytest.mark.parametrize('order',[list(range(9)),list(reversed(range(9))),[8,0,3,5,2,7,1,6,4],[0,4,8]])
def test_full_permuted_and_partial_packets_equal_single_calls(reviewer,record,order):
    rows=series(record)
    baseline={r['record_id']:semantic_rows(reviewer.review(envelope(r)))[r['record_id']] for r in rows}
    selected=[rows[i] for i in order]
    actual=semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':selected}))
    assert actual=={r['record_id']:baseline[r['record_id']] for r in selected}


@pytest.mark.parametrize('size',[1,2,5,9])
def test_chunked_calls_with_explicit_history_equal_full_batch(reviewer,record,size):
    rows=series(record)
    full=semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':rows}))
    chunks={}
    for start in range(0,len(rows),size):
        chunks.update(semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':rows[start:start+size]})))
    assert chunks==full


@pytest.mark.parametrize('case',['duplicate_event','duplicate_event_bad_row','current_history','overlapping_history',
    'null_value_conflict','counter_reused','counter_reversed','counter_jumps'])
@pytest.mark.parametrize('reverse',[False,True])
def test_batch_conflicts_rejected_before_any_scoring(reviewer,record,monkeypatch,case,reverse):
    rows=series(record)
    if case.startswith('duplicate_event'):
        rows=[rows[2],deepcopy(rows[2])];rows[1]['record_id']='different-id'
        if case=='duplicate_event_bad_row':rows[1]['measurements']['Casting_Pressure']='bad'
    elif case=='current_history':
        rows=rows[:2];rows[1]['history'][0]['Cycle_Time']=999
    elif case=='overlapping_history':
        rows=rows[5:7];rows[1]['history'][0]['Cycle_Time']=999
    elif case=='null_value_conflict':
        rows=rows[:2];rows[0]['measurements']['Cycle_Time']=None
    else:
        rows=[rows[2],rows[4]]
        rows[1]['observation']['quality_record_position']={'counter_reused':2,'counter_reversed':1,'counter_jumps':4}[case]
        if case=='counter_jumps':rows[0]['observation']['quality_record_position']=0
    if reverse:rows.reverse()
    def forbidden(*args,**kwargs):raise AssertionError('Scoring started before batch context validation')
    monkeypatch.setattr(reviewer,'_stage',forbidden)
    with pytest.raises(ContractError,match='Duplicate observation|Conflicting Cycle_Time|Inconsistent historical'):
        reviewer.review({'schema_version':SCHEMA,'records':rows})


def test_missing_event_is_not_filled_from_batch_or_prior_call(reviewer,record):
    rows=series(record,2)
    reviewer.review(envelope(rows[0]))
    rows[1]['history']=None
    batch=reviewer.review({'schema_version':SCHEMA,'records':rows})
    solo=reviewer.review(envelope(rows[1]))
    assert batch['records'][1]['equipment_state']['score'] is None
    assert semantic_rows(solo)[rows[1]['record_id']]==semantic_rows(batch)[rows[1]['record_id']]
    assert not batch['invocation_contract']['cross_call_consistency_checked']


def test_explicit_missing_cycle_is_not_absent_observation(reviewer,record):
    rows=series(record,2)
    rows[0]['measurements']['Cycle_Time']=None
    rows[1]['history'][0]['Cycle_Time']=None
    result=reviewer.review({'schema_version':SCHEMA,'records':rows})['records'][1]
    assert result['equipment_state']['status']=='scored'
    assert result['input_support']['history_missing_cycle_values']==1
    imputed={c['feature'] for c in result['equipment_state']['explanation']['contributions'] if c['was_imputed']}
    assert imputed=={'prev_cycle_time','max_cycle_previous_5'}
    del rows[1]['history'][0]
    assert output(reviewer,rows[1])['status']=='invalid_input'


def test_mixed_products_do_not_reset_or_filter_process_history(reviewer,record):
    rows=series(record,7)
    for i,r in enumerate(rows):r['measurements']['Product_Type']=1+i%2
    result=reviewer.review({'schema_version':SCHEMA,'records':rows})
    for r in result['records'][1:]:
        parts={c['feature']:c for c in r['equipment_state']['explanation']['contributions']}
        seq=r['observation']['sequence']
        assert parts['prev_cycle_time']['input_value']==float(seq)/10
    supported=output(reviewer,rows[5])
    assert supported['quality']['score_interpretation']=='diagnostic_only_uncalibrated_model_output'
    assert any(w['code']=='unseen_product' for w in supported['quality']['warnings'])
    assert '미학습 제품: 적용 성능 미검증' in render_html(result)


def test_interleaved_runs_do_not_share_history(reviewer,record):
    a,b=series(record,4,'equipment-A-session-1'),series(record,4,'equipment-B-session-1')
    mixed=[r for pair in zip(a,b) for r in pair]
    batch=semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':mixed}))
    for r in mixed:assert batch[r['record_id']]==semantic_rows(reviewer.review(envelope(r)))[r['record_id']]
    a[3]['history'][0]['run_key']=b[0]['observation']['run_key']
    assert output(reviewer,a[3])['status']=='invalid_input'


def test_partial_quality_subset_keeps_original_positions(reviewer,record):
    rows=series(record,9)
    rows=[rows[2],rows[5],rows[8]]
    for r,p in zip(rows,[0,2,3]):r['observation']['quality_record_position']=p
    full=semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':rows}))
    for r in rows:assert semantic_rows(reviewer.review(envelope(r)))[r['record_id']]==full[r['record_id']]


@pytest.mark.parametrize('field',['timestamp','event_time','tie_breaker'])
def test_timestamps_and_tie_rules_are_not_silently_interpreted(reviewer,record,field):
    rows=series(record,2)
    for r in rows:r['observation'][field]='2026-10-05T01:00:00Z'
    result=reviewer.review({'schema_version':SCHEMA,'records':rows})
    assert all(r['status']=='invalid_input' for r in result['records'])
    assert not result['invocation_contract']['timestamps_or_arrival_order_supported_as_feature_order']


@pytest.mark.parametrize('field',['sequence','quality_record_position','Product_Type'])
def test_integer_above_exact_model_representation_rejected(reviewer,record,field):
    target=record['measurements'] if field=='Product_Type' else record['observation']
    target[field]=MAX_EXACT_INTEGER+1
    assert output(reviewer,record)['status']=='invalid_input'


@pytest.mark.parametrize('field',['record_id','run_key'])
def test_identity_whitespace_is_not_silently_normalized(reviewer,record,field):
    target=record if field=='record_id' else record['observation']
    target[field]=' padded '
    assert output(reviewer,record)['status']=='invalid_input'


def test_returned_explanations_reconstruct_emitted_scores_including_unsupported_product(reviewer,record):
    rows=series(record,3)
    rows[1]['measurements']['Product_Type']=2
    for r in reviewer.review({'schema_version':SCHEMA,'records':rows})['records']:
        for key in ['quality','equipment_state']:
            stage=r[key];e=stage['explanation']
            reconstructed=e['baseline_margin']+sum(c['contribution'] for c in e['contributions'])
            assert e['scale']=='log_odds_of_encoded_class_1'
            assert float(1/(1+np.exp(-reconstructed)))==pytest.approx(stage['score'],abs=1e-6)
            assert stage['score_interpretation']=='diagnostic_only_uncalibrated_model_output'


def test_historical_packet_builder_rejects_source_order_ties(record):
    from prepare_decision_review import ordered_run
    data=pd.DataFrame({'run_id':[0,0],'source_row':[1,1],'Shot':[1,2],'row_id':['a','b']})
    with pytest.raises(ValueError,match='source order'):ordered_run(data,0)
