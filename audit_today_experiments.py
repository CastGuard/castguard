"""Audit today's existing evidence; no fitting, new policy search, or unseen-test claim."""
from pathlib import Path
from datetime import datetime,timezone
from hashlib import sha256
import argparse,json,sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from castguard.data import read_inputs
from oct03_research import inspection_metrics,gate_statistics,choose_q1_family,choose_gate_family,q1_decision,timeline_partition
from oct03_queue import stream_queue,measure,choose_policy
from experiment_integrity import missing_quality_contrast_bounds

ROOT=Path(__file__).resolve().parent


def same(actual,expected):
    np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12,equal_nan=True)


def audit(root=ROOT):
    root=Path(root);frames,folds,contract=read_inputs(root);q,m=frames['q42'],frames['m41']
    pilot=root/'reports/oct03_pilot_r2';queue=root/'reports/oct03_queue'
    cfg=json.loads((root/'configs/oct03_pilot.json').read_text())
    base=json.loads((root/'configs/oct02.json').read_text())
    selection=json.loads((pilot/'selection.json').read_text())
    evidence_files=[p for folder in [root/'data/raw',root/'data/processed',pilot,queue] for p in folder.rglob('*') if p.is_file()]
    evidence_files += [root/'reports/submission_round6/baselines_final/baseline_actions.parquet',
        root/'configs/oct03_pilot.json',root/'configs/oct02.json']
    initial={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in evidence_files}

    # Independently derive key groups and every declared defect flag from raw CSV.
    raw=pd.read_csv(root/'data/raw/DieCasting_Quality_Raw_Data.csv',header=1)
    raw.columns=raw.columns.str.strip();raw['run_id']=raw.Shot.lt(raw.Shot.shift()).cumsum()
    columns=[c for c in raw if c!='id']
    groups=raw.groupby(['run_id','Shot'],sort=False)
    assert not groups[columns].nunique(dropna=False).gt(1).any().any(),'Conflicting duplicate raw shots'
    distinct=raw.loc[~raw.duplicated(['run_id','Shot'])].copy()
    assert len(raw)==7535 and len(distinct)==len(q)==4617
    linked=q.merge(distinct,on=['run_id','Shot'],validate='one_to_one',suffixes=('','_raw'))
    assert len(linked)==len(q)
    types=['Short_Shot','Bubble','Exfoliation','Blow_Hole','Stain','Dent','Deformation','Contamination','Impurity','Crack','Scratch','Buring_Mark','Inclusions']
    all_positive=[]
    for name in types:
        flag=(linked[name+'_1_raw'].gt(0)|linked[name+'_2_raw'].gt(0)).astype(int)
        np.testing.assert_array_equal(linked['y_type_'+name],flag)
        all_positive.append(flag)
    np.testing.assert_array_equal(linked.y_defect,np.maximum.reduce(all_positive))
    joined=q.merge(m,on=['run_id','Shot'],validate='one_to_one',suffixes=('_q','_m'))
    assert len(joined)==len(q)
    for col in contract['q42_A0']:same(joined[col+'_q'],joined[col+'_m'])
    forbidden=set([c for t in types for c in [t+'_1',t+'_2']]+['Machine_Status'])
    for key in ['q42_A','q42_B']:
        assert not any(c in forbidden or c.startswith(('y_','oracle_')) for c in contract[key])

    # Separate global forward chronology from group-only/within-run schemes.
    split_records=[]
    for (dataset,scheme,fold),assigned in folds.loc[folds.dataset.isin(['q42','m41'])].groupby(['dataset','scheme','fold']):
        assert not assigned.row_id.duplicated().any()
        source=frames[dataset];part=assigned.merge(source[['row_id','source_row','Shot']],on='row_id',validate='one_to_one')
        assert len(part)==len(source)
        roles={role:part.loc[part.role.eq(role)] for role in ['train','validation','test']}
        for a,b in [('train','validation'),('train','test'),('validation','test')]:
            assert set(roles[a].row_id).isdisjoint(roles[b].row_id)
        if scheme=='forward_run':
            assert roles['train'].source_row.max()<roles['validation'].source_row.min()<roles['test'].source_row.min()
            assert roles['validation'].source_row.max()<roles['test'].source_row.min()
        elif scheme=='run_holdout':
            assert set(roles['train'].run_id).isdisjoint(roles['validation'].run_id)
            assert set(roles['train'].run_id).isdisjoint(roles['test'].run_id)
        else:
            for run,rows in part.loc[part.role.ne('excluded')].groupby('run_id'):
                limits=rows.groupby('role').source_row.agg(['min','max'])
                assert limits.loc['train','max']<limits.loc['validation','min']
                assert limits.loc['validation','max']<limits.loc['test','min']
        split_records.append({'dataset':dataset,'scheme':scheme,'fold':fold,'global_forward':scheme=='forward_run'})
    for scheme,fold in folds.loc[folds.dataset.eq('m41'),['scheme','fold']].drop_duplicates().itertuples(index=False,name=None):
        expanded=pd.concat([timeline_partition(q,m,folds,scheme,fold,role).assign(audit_role=role) for role in ['train','validation','test']])
        assert not expanded.row_id.duplicated().any()
        assert not expanded.dropna(subset=['episode_id']).groupby('episode_id').audit_role.nunique().gt(1).any()
    sample=pd.read_csv(pilot/'sample_support.csv',dtype={'fold':str})
    for row in sample.itertuples(index=False):
        a=folds.loc[folds.dataset.eq('q42')&folds.scheme.eq(row.scheme)&folds.fold.eq(row.fold)]
        for role in ['train','validation']:
            ids=a.loc[a.role.eq(role),'row_id'];labels=q.set_index('row_id').loc[ids,row.target]
            assert len(labels)==getattr(row,role+'_n')
            assert labels.sum()==getattr(row,role+'_positive')
            assert len(labels)-labels.sum()==getattr(row,role+'_negative')

    # Replay ranks with fixed saved probabilities; verify all candidate metrics and selections.
    qp=pd.read_parquet(pilot/'q1_validation_predictions.parquet')
    qm=pd.read_csv(pilot/'q1_candidate_validation.csv',dtype={'fold':str},float_precision='round_trip')
    qkeys=['scheme','fold','model','seed','variant','role'];qindex=qm.set_index(qkeys+['budget'])
    qgroups=0
    for key,rows in qp.groupby(qkeys):
        for budget in cfg['budgets']:
            actual=inspection_metrics(rows,cfg['target'],budget);saved=qindex.loc[key+(budget,)]
            for name,value in actual.items():same(value,saved[name])
        qgroups+=1
    for choice in selection['q1']:
        candidates=qm.loc[qm.scheme.eq(choice['scheme'])&qm.fold.eq(choice['fold'])&qm.variant.eq('specialist')]
        assert choose_q1_family(candidates,cfg['q1_models'],cfg['seeds'],cfg['budgets'])==choice['model']
    decision,_=q1_decision(pd.read_csv(pilot/'q1_comparison.csv',dtype={'fold':str},float_precision='round_trip'),
        pd.read_csv(pilot/'q1_conditional_intervals.csv',dtype={'fold':str},float_precision='round_trip'),cfg)
    assert decision['test_allowed']==selection['q1_decision']['test_allowed']==False

    # No recomputed threshold is selected from test. Frozen policies alone are replayed.
    gm=pd.read_csv(pilot/'g1_candidate_validation.csv',dtype={'fold':str},float_precision='round_trip')
    for (scheme,fold),candidates in gm.loc[gm.policy.eq('constrained')].groupby(['scheme','fold']):
        chosen=choose_gate_family(candidates.to_dict('records'),list(base['models']),cfg['seeds'])
        assert {x['model'] for x in selection['g1'] if x['scheme']==scheme and x['fold']==fold and x['policy']=='constrained'}=={chosen}
    ggroups=0
    for pred_file,metrics_file in [('g1_validation_predictions.parquet','g1_selected_validation.csv'),('reused_test/g1_predictions.parquet','reused_test/g1_metrics.csv')]:
        gp=pd.read_parquet(pilot/pred_file);metrics=pd.read_csv(pilot/metrics_file,dtype={'fold':str},float_precision='round_trip')
        index=metrics.set_index(['scheme','fold','seed','policy'])
        for key,rows in gp.groupby(['scheme','fold','seed','policy']):
            saved=index.loc[key];timeline=rows[m.columns]
            scores=rows.loc[rows.gate_eligible,['row_id','probability']]
            result,_,_,actions=gate_statistics(timeline,scores,saved.threshold,bool(saved.disabled))
            for name,value in result.items():same(value,saved[name])
            np.testing.assert_array_equal(actions.alarm,rows.alarm)
            ggroups+=1

    # Independent label joins and action-by-action replays at every stored budget.
    choices={x['fold']:x for x in json.loads((queue/'selection.json').read_text())['folds']}
    assignments=pd.read_csv(queue/'nested_assignments.csv',dtype={'fold':str})
    for (fold,dataset),part in assignments.groupby(['fold','dataset']):
        assert not part.row_id.duplicated().any()
        limits=part.groupby('nested_role').source_row.agg(['min','max'])
        assert limits.loc['fit','max']<limits.loc['calibration','min']
        assert limits.loc['calibration','max']<limits.loc['evaluation','min']
        original=folds.loc[folds.dataset.eq(dataset)&folds.scheme.eq('forward_run')&folds.fold.eq(fold)&folds.role.eq('test')]
        assert set(part.row_id).isdisjoint(original.row_id)
    keys=['fold','seed','policy','budget'];qcount=0;action_rows=0
    input_cols=['row_id','source_row','run_id','Shot','process_complete','gate_probability','quality_probability','ood_score']
    action_cols=['row_id','ood','hold','alarm','raw_gate_alarm','inspected','reason','arrival_step','service_step','service_shot','wait_records','wait_shots']
    for prefix in ['inner','outer']:
        stored=pd.read_parquet(queue/(prefix+'_actions.parquet'))
        metric=pd.read_csv(queue/(prefix+'_policy_metrics.csv'),dtype={'fold':str},float_precision='round_trip').set_index(keys)
        for key,rows in stored.groupby(keys):
            fold,seed,policy,budget=key;choice=choices[fold];g=choice['gate_thresholds'][str(seed)]
            actions=stream_queue(rows[input_cols],policy,g['threshold'],g['disabled'],choice['ood_thresholds'].get(policy),budget)
            old=rows.sort_values(['source_row','row_id']).reset_index(drop=True)
            pd.testing.assert_frame_equal(actions[action_cols],old[action_cols],check_exact=True,check_dtype=False)
            actual,labelled,_=measure(actions,m,q,budget)
            assert len(labelled)==len(rows)
            saved=metric.loc[key]
            for name,value in actual.items():same(value,saved[name])
            # Brute integer numerator arithmetic checks every prefix independently.
            from fractions import Fraction
            ratio=Fraction(str(budget));served=actions.loc[actions.inspected,'service_step'].astype(int)
            counts=np.bincount(served,minlength=len(actions)).cumsum()
            assert all(int(v)<=n*ratio.numerator//ratio.denominator for n,v in enumerate(counts,1))
            assert not served.duplicated().any()
            qcount+=1;action_rows+=len(rows)
        if prefix=='inner':
            original=metric.reset_index()
            for fold,choice in choices.items():assert choose_policy(original.loc[original.fold.eq(fold)])==choice['selected_policy']
    # Descriptive partial-identification envelope for the 516 unobserved labels.
    outer=pd.read_parquet(queue/'outer_actions.parquet')
    outer=outer.loc[outer.budget.eq(.2)&outer.policy.isin(['Q','GQ'])]
    unit_keys=['fold','row_id']
    for _,group in outer.groupby(['policy']+unit_keys):
        assert len(group)==len(cfg['seeds']) and set(group.seed)==set(cfg['seeds'])
        assert group.y_defect.nunique(dropna=False)==1
    units=outer.loc[outer.policy.eq('Q')&outer.seed.eq(cfg['seeds'][0]),unit_keys+['y_defect']].set_index(unit_keys)
    for policy in ['Q','GQ']:
        action=outer.loc[outer.policy.eq(policy)].groupby(unit_keys).inspected.mean()
        assert set(action.index)==set(units.index);units[policy]=action
    fifo=pd.read_parquet(root/'reports/submission_round6/baselines_final/baseline_actions.parquet')
    fifo=fifo.loc[fifo.policy.eq('FIFO')].set_index(unit_keys)
    assert not fifo.index.duplicated().any() and set(fifo.index)==set(units.index)
    units['FIFO']=fifo.inspected.astype(float)
    positive=units.y_defect.eq(1);missing=units.y_defect.isna();bounds={}
    for policy,baseline in [('Q','FIFO'),('GQ','FIFO'),('GQ','Q')]:
        delta=units[policy]-units[baseline]
        bounds[policy+'_minus_'+baseline]=missing_quality_contrast_bounds(int(positive.sum()),float(delta.loc[positive].sum()),delta.loc[missing])
    for name,h in initial.items():assert sha256((root/name).read_bytes()).hexdigest()==h
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'raw_quality_rows':len(raw),'deduplicated_quality_rows':len(q),'duplicate_rows':len(raw)-len(q),
        'defect_types_reconstructed':len(types),'raw_defect_values':sorted(pd.unique(raw[[t+'_'+str(c) for t in types for c in [1,2]]].to_numpy().ravel()).tolist()),
        'raw_defect_interpretation':'declared presence flag value>0; external code semantics remain unconfirmed',
        'quality_state_join_rows':len(joined),'sample_support_rows_checked':len(sample),
        'split_groups_checked':len(split_records),'global_chronology_claimed_only_for_forward_run':True,
        'full_warm_episodes_crossing_roles':0,'test_rows_in_nested_development':0,
        'q1_prediction_groups':qgroups,'q1_metric_rows':len(qm),'g1_prediction_groups':ggroups,
        'queue_groups_replayed':qcount,'queue_action_rows_replayed':action_rows,
        'fixed_selections_unchanged':True,'stored_metrics_unchanged':True,'stored_actions_unchanged':True,
        'missing_quality_contrast_bounds':bounds,
        'missing_quality_scope':'descriptive sensitivity on the same seen cohort; unknown records assumed to be target units with binary quality, not established from field logs',
        'q1_test_allowed':decision['test_allowed'],'today_scope_reduction_changed':False,
        'source_files_preserved':len(initial),'new_training_or_retuning':False,
        'implementation_hashes':{name:sha256((root/name).read_bytes()).hexdigest() for name in [
            'audit_today_experiments.py','experiment_integrity.py','oct03_research.py','oct03_queue.py']},
        'scope':'correctness replay of already-seen evidence; not new generalization evidence'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Use a fresh receipt path')
    result=audit();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
