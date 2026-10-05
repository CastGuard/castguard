"""Freeze provenance/reference metadata for an existing A0 artifact; never train/select."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse
import hashlib
import json
import sys

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from castguard.decision_review import PROCESS, digest, read_json
from castguard.observable_quality import TASK, MODEL_PATH, SCHEMA, BASIS


def write_new(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def build(root, output):
    root, output = Path(root), Path(output)
    provenance_path = root / 'reports/oct02/provenance.json'
    provenance = read_json(provenance_path)
    assert provenance['cache'] == 'artifacts/14b7926791a139eb'
    assert provenance['config']['quality_experiments']['A0'] == 'q42_A0'
    for name, expected in provenance['hashes'].items():
        assert digest(root/name) == expected, name
    contract = read_json(root/'data/processed/feature_contract.json')
    assert contract['q42_A0'] == PROCESS
    folder = (root/MODEL_PATH).parent
    complete = read_json(folder/'complete.json')
    assert complete['task'] == TASK and complete['features'] == PROCESS and complete['learned'] == {}
    for name, expected in complete['sha256'].items():
        assert digest(folder/name) == expected
    payload = joblib.load(root/MODEL_PATH)
    assert payload['task'] == TASK and payload['features'] == PROCESS and payload['learned'] == {}
    # Explicit feature/identity columns only. Training targets are not loaded.
    q = pd.read_parquet(root/'data/processed/joined.parquet', columns=['row_id','run_id','Product_Type']+PROCESS)
    folds = pd.read_csv(root/'data/processed/folds.csv', usecols=['dataset','scheme','fold','row_id','role'], dtype={'fold':str})
    assigned = folds[folds.dataset.eq('q42') & folds.scheme.eq('forward_run') & folds.fold.eq('2')]
    assert not assigned.row_id.duplicated().any() and set(assigned.row_id) == set(q.row_id)
    fit = q.merge(assigned[['row_id','role']], on='row_id', validate='one_to_one').query("role == 'train'")
    assert len(fit) == 1099 and fit.run_id.unique().tolist() == [0]
    comparisons = []
    for experiment in ['A0', 'A', 'B']:
        group = root/provenance['cache']/f'q42__all__forward_run__2__{experiment}__logistic__17'
        seal = read_json(group/'complete.json')
        assert digest(group/'metrics.csv') == seal['sha256']['metrics.csv']
        records = pd.read_csv(group/'metrics.csv', dtype={'fold':str}).to_dict('records')
        comparisons.extend(records)
    inventory = Counter()
    feature_sets = {}
    for file in (root/provenance['cache']).glob('*/complete.json'):
        item = read_json(file)
        task = item['task']
        key = task['dataset']+'/'+task['experiment']
        inventory[key] += 1
        feature_sets.setdefault(key, set()).add(tuple(item['features']))
    selection_rule = 'Existing A0 process14 input contract; provenance-linked original cache; earliest forward fold 2; logistic for faithful existing linear adapter; first configured seed 17. No exposed-test performance used for this choice.'
    profile = {'schema_version':'castguard-observable-profile-v1','input_schema':SCHEMA,
        'task':TASK,'path':MODEL_PATH,'sha256':digest(root/MODEL_PATH),'features':PROCESS,
        'selection_rule':selection_rule,
        'provenance':{'original_run':'reports/oct02','fingerprint':provenance['fingerprint'],
                      'provenance_sha256':digest(provenance_path),'complete_sha256':digest(folder/'complete.json'),
                      'training_source_hashes_verified':provenance['hashes']},
        'training_reference':{'partition':'original_forward_run_train','rows':len(fit),
            'run_ids':sorted(map(int,fit.run_id.unique())),'products':sorted(map(int,fit.Product_Type.unique())),
            'row_ids_sha256':hashlib.sha256(json.dumps(fit.row_id.tolist()).encode()).hexdigest(),
            'cohort':'Historical quality-file observed rows only; not all production arrivals'},
        'ranges':{f:[float(fit[f].min()),float(fit[f].max())] for f in PROCESS},
        'historical_metrics':comparisons,
        'prospective_input_timing':'All 14 values from the same completed shot; actual arrival before inspection not field-verified',
        'learned_preprocessing':'Stored train-only median imputer then StandardScaler then LogisticRegression. Runtime requires complete finite current inputs.',
        'counter_history_labels_required':False,'performance_promotion':False}
    write_new(output/'configs/observable_quality.json',profile)
    manifest = read_json(root/'data/processed/manifest.json')
    raw_path = 'data/raw/DieCasting_Raw_Data.csv'
    original = next(r for r in manifest['inputs'] if r['path'] == raw_path)
    assert digest(root/raw_path) == original['sha256']
    current = pd.read_csv(root/raw_path, usecols=PROCESS)
    row = current.dropna(subset=PROCESS).iloc[0]
    base = {'record_id':'process-observation-0001','observation_basis':BASIS,
            'measurements':{f:float(row[f]) for f in PROCESS}}
    records = [base]
    synthetic = deepcopy(base);synthetic['record_id']='synthetic-new-measurement-packet'
    synthetic['measurements']['Casting_Pressure'] += .123
    synthetic['measurements']['High_Velocity'] += .002
    records.append(synthetic)
    for product in [1,2]:
        item=deepcopy(base);item['record_id']=f'product-context-{product}';item['context']={'product_type':product};records.append(item)
    missing=deepcopy(base);missing['record_id']='missing-cycle';del missing['measurements']['Cycle_Time'];records.append(missing)
    forbidden=deepcopy(base);forbidden['record_id']='injected-quality-counter';forbidden['quality_record_position']=0;records.append(forbidden)
    bad=deepcopy(base);bad['record_id']='invalid-pressure';bad['measurements']['Casting_Pressure']='not-a-number';records.append(bad)
    write_new(output/'examples/observable_quality/shots.json',{'schema_version':SCHEMA,'records':records})
    write_new(output/'examples/observable_quality/provenance.json',{
        'source':raw_path,'source_sha256':digest(root/raw_path),'source_zero_based_row':int(row.name),
        'selection_rule':'First complete process14 row in original process-file order; no quality table/labels used to select example',
        'fields_read':PROCESS,'quality_file_read_for_example':False,
        'synthetic_new_packet':'Explicit small numeric perturbation to demonstrate arbitrary current-observation input, not a real newly collected shot or efficacy evidence',
        'product_context_examples':'Counterfactual metadata variants; product identity is absent from the process source and is not inferred',
        'other_variants':'Explicit missing/forbidden/bad-type fixtures; no additional observed production',
        'quality_counter_or_history_in_valid_inputs':False})
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'CastGuard observable current-process quality input',
        'type':'object','additionalProperties':False,'required':['schema_version','records'],
        'properties':{'schema_version':{'const':SCHEMA},'records':{'type':'array','minItems':1,'items':{
            'type':'object','additionalProperties':False,'required':['record_id','observation_basis','measurements'],
            'properties':{'record_id':{'type':'string','minLength':1},'observation_basis':{'const':BASIS},
                'measurements':{'type':'object','additionalProperties':False,'properties':{f:{'type':['number','null']} for f in PROCESS},
                    'description':'All 14 finite current measurements required to score; missing/null explicitly abstains. No counters, labels, sensors, timestamps or history.'},
                'context':{'type':'object','additionalProperties':False,'properties':{'product_type':{'type':['integer','null'],'minimum':1,'maximum':2**53-1}},
                    'description':'Optional external product identity for warning only; never a model feature or inferred from quality files.'}}}}}}
    write_new(output/'configs/observable_quality_input.schema.json',schema)
    audit={'root_cause':'q42 A/B/B2 use shot_position = cumcount after quality-file-dependent run segmentation and deduplication, which includes target columns. Row presence/order can change it. It is not a process counter.',
        'source_roles':{'process14':'Measured columns independently present in process CSV; no target/row-order derivation',
            'shot_position':'Quality-file run-local retained row ordinal; retrospective availability dependency',
            'sensor6_Product_Type':'Recorded in quality source; not label-value transforms, but absent from process feed; independent timely source unverified',
            'B_history4':'Previous process observations only, label-free in derivation; requires complete original process order and missingness before current shot',
            'B2_relative_history':'B inputs plus product-cycle train medians and previous20 missing fraction; still inherits shot_position',
            'queue_score_presence':'Quality scores created from qpart and joined to process timeline, historically coupled to quality-file row presence'},
        'canonical_cache':provenance['cache'],'canonical_manifest_counts':dict(inventory),
        'features_by_family':{k:[list(v) for v in sorted(values)] for k,values in feature_sets.items()},
        'appropriate_frozen_baseline_found':True,'chosen_task':TASK,'selection_rule':selection_rule,
        'model_sha256':digest(root/MODEL_PATH),'source_provenance_verified':True,
        'training_boundary':'Original forward fold2: run0 train (1099 quality-observed rows); run1 validation; run2 exposed historical test. No refit.',
        'future_capability_boundary':'New externally supplied complete process14 packets require no quality table/counter/history. Source availability before inspection, all-production validity, calibration and future performance remain unverified.',
        'historical_comparisons':comparisons,'new_training_or_model_sweep':False}
    write_new(output/'reports/observable_quality/dependency_audit.json',audit)
    print(json.dumps({'model':MODEL_PATH,'features':len(PROCESS),'fit_rows':len(fit),'frozen_A0_artifacts':inventory['q42/A0'],'new_training':False}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--output-root',type=Path,required=True)
    a=p.parse_args();build(a.root,a.output_root)
