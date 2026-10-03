"""Independent arithmetic from raw defect columns and saved row-level actions.

Does not import the project's preprocessing, queue, summary or metric helpers.
Recomputes selected historical results; never trains or selects a policy.
"""
from pathlib import Path
from hashlib import sha256
from itertools import product
import csv,json,math
import pandas as pd

ROOT=Path(__file__).resolve().parent
POLICIES=['FIFO','RECENT_PRODUCT_RATE','Q','GQ']


def raw_truth(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        rows=csv.reader(stream);categories=next(rows);names=[x.strip() for x in next(rows)]
        defects=[i for i,x in enumerate(categories) if x=='Defects']
        assert len(defects)==26
        shot_col=names.index('Shot');id_col=names.index('id')
        run=0;previous=None;truth={};records={};total=0
        for row in rows:
            if not row:continue
            total+=1;shot=int(row[shot_col])
            if previous is not None and shot<previous:run+=1
            previous=shot;key=(run,shot)
            values=tuple(x for i,x in enumerate(row) if i!=id_col)
            if key in records:assert records[key]==values,('conflicting duplicate raw Shot',key)
            records[key]=values;truth[key]=int(any(float(row[i])>0 for i in defects))
    return truth,{'raw_rows':total,'unique_quality_shots':len(truth),'duplicate_rows':total-len(truth),
                 'positive_quality_shots':sum(truth.values()),'defect_columns':len(defects)}


def quantile(values,p):
    ordered=sorted(values);index=(len(ordered)-1)*p;lower=math.floor(index);upper=math.ceil(index)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(index-lower)


def recompute(root=ROOT,actions_override=None):
    root=Path(root)
    paths=['data/raw/DieCasting_Quality_Raw_Data.csv','reports/oct03_queue/outer_actions.parquet',
           'reports/submission_round6/baselines_final/baseline_actions.parquet']
    truth,raw=raw_truth(root/paths[0])
    actions=pd.read_parquet(root/paths[1]) if actions_override is None else actions_override.copy()
    actions=actions.loc[actions.budget.eq(.2)&actions.policy.isin(['Q','GQ'])].copy()
    actions['fold']=actions.fold.astype(str)
    base=actions.loc[actions.policy.eq('Q')&actions.seed.eq(17)].copy()
    keys=['fold','row_id'];assert not base.duplicated(keys).any()
    base=base[['fold','row_id','run_id','Shot','arrival_step','Machine_Status']].set_index(keys)
    expected=set(base.index)
    base['truth']=[truth.get((int(r),int(s)),float('nan')) for r,s in zip(base.run_id,base.Shot)]
    positives=int(base.truth.eq(1).sum());known=int(base.truth.notna().sum())
    normal=int(base.Machine_Status.eq(0).sum())
    simple=pd.read_parquet(root/paths[2]);simple['fold']=simple.fold.astype(str)
    simple=simple.loc[simple.policy.isin(['FIFO','RECENT_PRODUCT_RATE'])]
    policy_results={};run_hits={};all_frames={}
    for policy in POLICIES:
        source=actions.loc[actions.policy.eq(policy)] if policy in ['Q','GQ'] else simple.loc[simple.policy.eq(policy)]
        hits=[];counts=[];wait_sum=0.;wait_count=0;by_run={};frames=[]
        for seed,table in source.groupby('seed'):
            assert not table.duplicated(keys).any() and set(table.set_index(keys).index)==expected,(policy,seed,'cohort')
            table=table.set_index(keys).loc[base.index]
            picked=table.inspected.to_numpy(bool);served=table.service_step.to_numpy(int)
            assert (picked==(served>=0)).all()
            delays=served-base.arrival_step.to_numpy(int)
            assert (delays[picked]>=0).all()
            if 'y_defect' in table:
                assert table.y_defect.isna().equals(base.truth.isna())
                assert table.y_defect.fillna(-1).eq(base.truth.fillna(-1)).all()
            y=base.truth.eq(1).to_numpy();k=base.truth.notna().to_numpy()
            hits.append(int((picked&y).sum()));counts.append(int(picked.sum()))
            wait_sum+=float(delays[picked&k].sum());wait_count+=int((picked&k).sum())
            for run in sorted(base.run_id.unique()):
                mask=base.run_id.eq(run).to_numpy()
                by_run.setdefault(int(run),[]).append(int((picked&y&mask).sum()))
            frames.append((int(seed),picked.copy(),served.copy()))
        assert len(hits)==(5 if policy in ['Q','GQ'] else 1)
        policy_results[policy]={'seeds':len(hits),'inspections_mean':sum(counts)/len(counts),
            'hits_mean':sum(hits)/len(hits),'capture_percent':100*sum(hits)/len(hits)/positives,
            'quality_inspections_across_seed_replays':wait_count,'quality_wait_sum_records_across_seed_replays':wait_sum,
            'quality_mean_wait_records':wait_sum/wait_count}
        run_hits[policy]={r:sum(v)/len(v) for r,v in by_run.items()};all_frames[policy]=frames
    fifo=all_frames['FIFO'][0];history=all_frames['RECENT_PRODUCT_RATE'][0]
    assert (fifo[1]==history[1]).all() and (fifo[2]==history[2]).all()
    runs=sorted(run_hits['FIFO']);run_positive={int(r):int(g.truth.eq(1).sum()) for r,g in base.groupby('run_id')}
    uncertainty={}
    for policy in ['Q','GQ']:
        diffs={r:run_hits[policy][r]-run_hits['FIFO'][r] for r in runs}
        draws=[100*sum(diffs[r] for r in draw)/sum(run_positive[r] for r in draw) for draw in product(runs,repeat=len(runs))]
        uncertainty[policy]={'delta_hits':sum(diffs.values()),'delta_percentage_points':100*sum(diffs.values())/positives,
            'run_delta_hits':diffs,'run_positive_counts':run_positive,'replicates':len(draws),
            'lower_pp':quantile(draws,.025),'upper_pp':quantile(draws,.975),
            'excludes_run1_delta_pp':100*sum(v for r,v in diffs.items() if r!=1)/sum(n for r,n in run_positive.items() if r!=1),
            'interpretation':'conditional frozen-action sensitivity on four previously seen runs; not a confirmatory CI'}
    gq=actions.loc[actions.policy.eq('GQ')].set_index(keys)
    gq_normal=gq.Machine_Status.eq(0)
    fpr=100*int((gq.alarm&gq_normal).sum())/int(gq_normal.sum())
    return {'raw_quality':raw,'production_rows':len(base),'quality_known':known,'quality_unknown':len(base)-known,
        'observed_positives':positives,'normal_state_rows':normal,'policies':policy_results,
        'FIFO_history_same_inspections_and_service_steps':True,'independent_effective_baselines_not_two':True,
        'uncertainty':uncertainty,'GQ_normal_false_alarm_percent':fpr,
        'input_sha256':{name:sha256((root/name).read_bytes()).hexdigest() for name in paths},
        'new_performance_evidence':False,'private_originals_required_for_this_recomputation':False}


def compare_saved(result,root=ROOT):
    """Compare only after independent calculation; saved summaries never supply inputs."""
    root=Path(root);summary=pd.read_csv(root/'reports/oct03_round7/group_metrics.csv')
    wait=pd.read_csv(root/'reports/oct03_round7/explanation/pooled_waiting.csv')
    ranges=pd.read_csv(root/'reports/oct03_round7/paired_uncertainty.csv')
    assert (result['production_rows'],result['quality_known'],result['quality_unknown'],result['observed_positives'])==(3395,2879,516,505)
    for policy,values in result['policies'].items():
        row=summary.loc[summary.dimension.eq('all')&summary.policy.eq(policy)].iloc[0]
        for ours,theirs in [('inspections_mean','inspected_mean'),('hits_mean','hits_mean')]:
            assert math.isclose(values[ours],float(row[theirs]),abs_tol=1e-10),(policy,ours)
        assert math.isclose(values['capture_percent'],100*float(row.capture),abs_tol=1e-10)
        w=wait.loc[wait.policy.eq(policy)&wait.population.eq('quality_known')].iloc[0]
        assert math.isclose(values['quality_mean_wait_records'],float(w.mean_wait_records),abs_tol=1e-10)
    for policy,values in result['uncertainty'].items():
        row=ranges.loc[ranges.policy.eq(policy)&ranges.method.eq('whole_run_cluster_exact_enumeration')].iloc[0]
        for col in ['lower_pp','upper_pp']:assert math.isclose(values[col],float(row[col]),abs_tol=1e-10)
        assert values['lower_pp']<0<values['upper_pp']
    return True


if __name__=='__main__':
    r=recompute();compare_saved(r);print(json.dumps(r,ensure_ascii=False,indent=2))
