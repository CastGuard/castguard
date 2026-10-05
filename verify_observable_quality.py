"""Verify explicit observable-input capability with the existing pinned A0 artifact."""
from pathlib import Path
from copy import deepcopy
import argparse
import json
import shutil
import sys
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from castguard.decision_review import PROCESS, digest, read_json, ContractError
from castguard.observable_quality import ObservableQualityReviewer, SCHEMA, MODEL_PATH, BASIS
from prepare_observable_quality import write_new


def semantic_rows(result):
    return {r['record_id']:{k:v for k,v in r.items() if k!='record_index'} for r in result['records']}


def verify(root, output, assets=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    assets = Path(assets).resolve() if assets else root
    if output.exists():raise FileExistsError('Use a new verification directory')
    output.mkdir(parents=True)
    config=assets/'configs/observable_quality.json';profile=read_json(config)
    folder=(root/MODEL_PATH).parent;complete=read_json(folder/'complete.json')
    for name,expected in complete['sha256'].items():assert digest(folder/name)==expected,name
    for name in ['data/processed/joined.parquet','data/processed/folds.csv']:
        assert digest(root/name)==profile['provenance']['training_source_hashes_verified'][name]
    # Use only current process features and stored prediction numbers, no target columns.
    data=pd.read_parquet(root/'data/processed/joined.parquet',columns=['row_id']+PROCESS)
    saved=pd.read_parquet(folder/'predictions.parquet',columns=['row_id','probability','role'])
    merged=saved.merge(data,on='row_id',validate='one_to_one')
    assert len(merged)==len(saved)
    complete_rows=merged.dropna(subset=PROCESS)
    packets=[{'record_id':str(row.row_id),'observation_basis':BASIS,
              'measurements':{f:float(getattr(row,f)) for f in PROCESS}} for row in complete_rows.itertuples(index=False)]
    isolated=output/'only_model_and_profile'
    (isolated/'configs').mkdir(parents=True)
    shutil.copyfile(config,isolated/'configs/observable_quality.json')
    destination=isolated/MODEL_PATH;destination.parent.mkdir(parents=True)
    shutil.copyfile(root/MODEL_PATH,destination)
    def forbidden(*a,**kw):raise AssertionError('Inference attempted to read any data table')
    with patch.object(pd,'read_csv',forbidden),patch.object(pd,'read_parquet',forbidden):
        reviewer=ObservableQualityReviewer(isolated)
        replay=reviewer.review({'schema_version':SCHEMA,'records':packets})
    errors=[];margin_errors=[];score_errors=[]
    expected=dict(zip(complete_rows.row_id,complete_rows.probability))
    for row in replay['records']:
        assert row['status']=='scored',row
        errors.append(abs(row['score']-expected[row['record_id']]))
        margin_errors.append(row['explanation']['margin_error'])
        score_errors.append(row['explanation']['score_error'])
    assert max(errors)<=1e-6 and max(margin_errors)<=1e-6 and max(score_errors)<=1e-6
    examples=read_json(assets/'examples/observable_quality/shots.json')
    with patch.object(pd,'read_csv',forbidden),patch.object(pd,'read_parquet',forbidden):
        baseline=reviewer.review(examples)
        reverse=semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':examples['records'][::-1]}))
        assert reverse==semantic_rows(baseline)
        for packet in examples['records']:
            assert semantic_rows(reviewer.review({'schema_version':SCHEMA,'records':[packet]}))[packet['record_id']]==reverse[packet['record_id']]
        for labels in [[],[{'record_id':'irrelevant','y_defect':0}],[{'record_id':'synthetic-new-measurement-packet','y_defect':1}]]:
            (isolated/'withheld_labels.json').write_text(json.dumps(labels),encoding='utf-8')
            assert ObservableQualityReviewer(isolated).review(examples)==baseline
        counter=deepcopy(examples['records'][0]);counter['quality_record_position']=0
        assert reviewer.review({'schema_version':SCHEMA,'records':[counter]})['records'][0]['status']=='invalid_input'
        try:reviewer.review({'schema_version':'castguard-shot-v1','records':[]})
        except ContractError:pass
        else:raise AssertionError('Historical schema silently switched paths')
    assert not (isolated/'data').exists()
    summary={'scope':'Input capability and exact frozen A0 replay; not new efficacy or prospective validation',
        'model_path':MODEL_PATH,'model_sha256':digest(destination),'profile_sha256':digest(config),
        'runtime_source_sha256':digest(Path(__file__).parent/'castguard/observable_quality.py'),
        'saved_predictions_total':len(saved),'complete_input_predictions_checked':len(errors),
        'missing_current_input_rows_not_replayed':len(merged)-len(complete_rows),
        'roles':complete_rows.role.value_counts().to_dict(),'max_saved_score_error':max(errors),
        'max_margin_reconstruction_error':max(margin_errors),'max_emitted_score_reconstruction_error':max(score_errors),
        'no_raw_processed_quality_file_in_runtime_root':True,'table_read_apis_forbidden_during_inference':True,
        'counter_history_omitted_from_every_valid_packet':True,'counter_injection_rejected':True,
        'no_historical_schema_fallback':True,'label_file_absent_empty_changed_variants_invariant':4,
        'example_batch_reversed_single_calls_identical':True,'example_statuses':[
            {'record_id':r['record_id'],'status':r['status'],'score':r['score'],'warnings':r['warnings']} for r in baseline['records']],
        'synthetic_new_measurement_input_scored':next(r for r in baseline['records'] if r['record_id']=='synthetic-new-measurement-packet')['status']=='scored',
        'actual_new_field_data_collected':False,'new_training_performance_based_selection_or_policy_change':False,
        'live_acquisition_timing_or_future_performance_verified':False}
    write_new(output/'verification.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='example_statuses'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--output',type=Path,required=True);p.add_argument('--assets',type=Path)
    a=p.parse_args();verify(a.root,a.output,a.assets)
