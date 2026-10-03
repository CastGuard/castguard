"""Trace the fixed retrospective cohort's missing quality; never fill in labels."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from fractions import Fraction
from itertools import product
import argparse,json,sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from experiment_integrity import missing_quality_contrast_bounds


def paired_panel(actions,fifo,seeds,budget=.2):
    """One row per actual Shot, shared labels across seeds/policies, exact coverage."""
    keys=['fold','row_id'];seeds=set(seeds)
    selected=actions.loc[actions.budget.eq(budget)&actions.policy.isin(['Q','GQ'])].copy()
    if selected.empty:raise ValueError('Empty policy comparison')
    if selected.duplicated(keys+['policy','seed']).any():raise ValueError('Duplicate policy action')
    identities=['run_id','Shot','source_row','y_defect','process_complete']
    for _,group in selected.groupby(keys,dropna=False):
        if set(zip(group.policy,group.seed))!=set(product(['Q','GQ'],seeds)):
            raise ValueError('Incomplete shared policy/seed panel')
        if group[identities].nunique(dropna=False).ne(1).any():
            raise ValueError('Inconsistent Shot identity, quality, or input availability')
    if selected[keys+['run_id','Shot','source_row']].isna().any().any():
        raise ValueError('Missing physical comparison key')
    if not selected.inspected.map(lambda v:isinstance(v,(bool,np.bool_))).all():
        raise ValueError('Actions must be explicit booleans')
    units=selected.loc[selected.policy.eq('Q')&selected.seed.eq(min(seeds)),keys+identities].set_index(keys)
    if units.reset_index().duplicated(['run_id','Shot']).any() or units.source_row.duplicated().any():
        raise ValueError('One physical Shot appears in more than one fold')
    reference=fifo.loc[fifo.policy.eq('FIFO')].copy()
    if reference.duplicated(keys).any():raise ValueError('Duplicate FIFO action')
    reference=reference.set_index(keys)
    if set(reference.index)!=set(units.index):raise ValueError('FIFO coverage differs')
    if not reference.inspected.map(lambda v:isinstance(v,(bool,np.bool_))).all():
        raise ValueError('FIFO actions must be explicit booleans')
    for policy in ['Q','GQ']:
        # Integer vote counts retain the pairing before converting to seed means.
        units[policy+'_votes']=selected.loc[selected.policy.eq(policy)].groupby(keys).inspected.sum().astype(int)
    units['FIFO_votes']=reference.inspected.astype(int)*len(seeds)
    return units


def exact_vote_envelope(known_positive,known_difference_votes,unknown_difference_votes,nseeds):
    """Independent rational implementation: enumerate k, explicitly sum sorted votes."""
    votes=sorted(int(x) for x in unknown_difference_votes)
    low=[];high=[]
    for k in range(len(votes)+1):
        denominator=nseeds*(known_positive+k)
        low.append(Fraction(known_difference_votes+sum(votes[:k]),denominator))
        high.append(Fraction(known_difference_votes+sum(votes[len(votes)-k:]) if k else known_difference_votes,denominator))
    return min(low),max(high)


def audit(root=ROOT):
    root=Path(root)
    paths=['data/raw/DieCasting_Raw_Data.csv','data/raw/DieCasting_Quality_Raw_Data.csv',
        'data/processed/joined.parquet','data/processed/m41_timeline.parquet','data/processed/folds.csv',
        'data/processed/feature_contract.json','reports/oct03_queue/outer_actions.parquet',
        'reports/oct03_queue/nested_assignments.csv','reports/submission_round6/baselines_final/baseline_actions.parquet',
        'configs/oct03_queue.json','reports/today_closeout/experiment_integrity_final.json']
    hashes={n:sha256((root/n).read_bytes()).hexdigest() for n in paths}
    cfg=json.loads((root/'configs/oct03_queue.json').read_text(encoding='utf-8'));seeds=cfg['seeds'];nseeds=len(seeds)
    contract=json.loads((root/'data/processed/feature_contract.json').read_text(encoding='utf-8'));process=contract['q42_A0']
    q=pd.read_parquet(root/'data/processed/joined.parquet');m=pd.read_parquet(root/'data/processed/m41_timeline.parquet')
    a=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    f=pd.read_parquet(root/'reports/submission_round6/baselines_final/baseline_actions.parquet')
    units=paired_panel(a,f,seeds)
    raw=pd.read_csv(root/'data/raw/DieCasting_Raw_Data.csv')
    raw['run_id']=raw.Shot.diff().lt(0).cumsum().astype(int);raw['source_row']=np.arange(len(raw))
    raw['row_id']='m41_r'+raw.run_id.astype(str)+'_s'+raw.Shot.astype(str)
    assert not raw.duplicated(['run_id','Shot']).any() and raw.row_id.is_unique
    pd.testing.assert_frame_equal(m[raw.columns].reset_index(drop=True),raw,check_dtype=False,check_exact=True)
    aligned=raw.set_index('row_id').loc[units.reset_index().row_id]
    for col in ['run_id','Shot','source_row']:
        np.testing.assert_array_equal(units[col].to_numpy(),aligned[col].to_numpy())
    quality=pd.read_csv(root/'data/raw/DieCasting_Quality_Raw_Data.csv',header=1);quality.columns=quality.columns.str.strip()
    original=list(quality.columns)
    quality['run_id']=quality.Shot.diff().lt(0).cumsum().astype(int);quality['quality_source_row']=np.arange(len(quality))
    groups=quality.groupby(['run_id','Shot'],sort=False)
    assert not groups[[c for c in original if c!='id']].nunique(dropna=False).gt(1).any().any()
    unique=quality.drop_duplicates(['run_id','Shot']).copy()
    rawkeys=set(zip(unique.run_id,unique.Shot));qkeys=set(zip(q.run_id,q.Shot))
    assert rawkeys==qkeys and not q.duplicated(['run_id','Shot']).any()
    target_cols=[c for c in original if c.endswith(('_1','_2')) and c not in process]
    assert len(target_cols)==26 and not quality[target_cols].isna().any().any()
    unique['raw_positive']=unique[target_cols].gt(0).any(axis=1).astype(int)
    unique['raw_occurrences']=groups.size().reindex(pd.MultiIndex.from_frame(unique[['run_id','Shot']])).to_numpy()
    raw_truth=unique[['run_id','Shot','raw_positive','Product_Type','quality_source_row','raw_occurrences']]
    frame=units.reset_index().merge(raw[['row_id','_id','Machine_Status']+process],on='row_id',validate='one_to_one')
    frame=frame.merge(raw_truth,on=['run_id','Shot'],how='left',validate='one_to_one',indicator='raw_quality_join')
    known=frame.raw_quality_join.eq('both');missing=~known
    assert np.array_equal(known,frame.y_defect.notna())
    np.testing.assert_array_equal(frame.loc[known,'raw_positive'],frame.loc[known,'y_defect'])
    assert frame.loc[known,process].notna().all().all() and frame.loc[known,'Machine_Status'].eq(0).all()
    assert np.array_equal(frame.process_complete,frame[process].notna().all(axis=1))
    # Exact input matching establishes an internal file relationship, not physical provenance.
    qq=q.merge(raw[['run_id','Shot']+process],on=['run_id','Shot'],validate='one_to_one',suffixes=('_q','_m'))
    np.testing.assert_array_equal(qq[[x+'_q' for x in process]],qq[[x+'_m' for x in process]])
    frame['missing_quality']=missing;frame['state_code']=frame.Machine_Status.map({0:'0',1:'1'}).fillna('missing')
    frame['raw_timeline_csv_line']=frame.source_row+2
    frame['raw_quality_csv_line']=frame.quality_source_row+3
    frame['exclusion_reason']=np.where(missing,'no_matching_key_in_raw_quality','quality_record_present')
    frame['quality_target_eligibility']='unconfirmed_for_missing_records'
    frame.loc[known,'quality_target_eligibility']='observed_quality_shot'
    # Folds excluded sensor/state rows from Gate scoring, but queue retained them.
    folds=pd.read_csv(root/'data/processed/folds.csv',dtype={'fold':str,'order':str,'episode_id':str})
    roles=folds.loc[folds.dataset.eq('m41')&folds.scheme.eq('forward_run'),['fold','row_id','role']]
    frame=frame.merge(roles,on=['fold','row_id'],how='left',validate='one_to_one').rename(columns={'role':'original_gate_role'})
    assert frame.original_gate_role.notna().all()
    frame=frame.sort_values('source_row').reset_index(drop=True)
    missing=frame.missing_quality;known=~missing;positive=frame.y_defect.eq(1)
    assert len(frame)==3395 and missing.sum()==516 and positive.sum()==505
    # All unobserved records lack the quality score in every saved run, not only seed 17.
    active=a.loc[a.budget.eq(.2)&a.policy.isin(['Q','GQ'])]
    for _,rows in active.groupby(['policy','seed']):
        assert np.array_equal(rows.y_defect.notna(),rows.quality_probability.notna())
        unknown=rows.y_defect.isna()
        assert int((unknown&rows.hold).sum())==409
        assert int((unknown&rows.hold&rows.inspected).sum())==168
        assert int((unknown&rows.hold&~rows.inspected).sum())==241
    budget_rows=[]
    for (policy,seed,fold),rows in active.groupby(['policy','seed','fold']):
        order=rows.sort_values(['source_row','row_id']).reset_index(drop=True)
        services=order.loc[order.inspected,'service_step'].astype(int)
        allowed=[i for i in range(len(order)) if (i+1)//5>i//5]
        assert len(set(services))==len(services) and set(services).issubset(allowed)
        assert (services.to_numpy()>=order.loc[order.inspected,'arrival_step'].to_numpy()).all()
        budget_rows.append({'policy':policy,'seed':int(seed),'fold':fold,'run_id':int(order.run_id.iloc[0]),
            'records':len(order),'available_slots':len(order)//5,'used_slots':int(order.inspected.sum()),
            'unused_service_steps':';'.join(map(str,sorted(set(allowed)-set(services)))),
            'quality_known_inspected':int((order.inspected&order.y_defect.notna()).sum()),
            'quality_missing_inspected':int((order.inspected&order.y_defect.isna()).sum())})
    # Replay FIFO independently using arrival-order candidates and the hold priority.
    fifo=f.loc[f.policy.eq('FIFO')].set_index(['fold','row_id'])
    for fold,rows in active.loc[active.policy.eq('Q')&active.seed.eq(seeds[0])].groupby('fold'):
        rows=rows.sort_values('source_row').reset_index(drop=True);waiting=[];served={}
        for i,row in enumerate(rows.itertuples(index=False)):
            if not row.process_complete:waiting.append((0,i))
            elif np.isfinite(row.quality_probability):waiting.append((1,i))
            if (i+1)%5==0 and waiting:
                take=min(waiting);waiting.remove(take);served[rows.iloc[take[1]].row_id]=i
        reference=fifo.loc[fold]
        assert set(served)==set(reference.loc[reference.inspected].index)
        assert all(reference.loc[rid,'service_step']==step for rid,step in served.items())
    comparisons={};prior=json.loads((root/'reports/today_closeout/experiment_integrity_final.json').read_text(encoding='utf-8'))
    for policy,base in [('Q','FIFO'),('GQ','FIFO'),('GQ','Q')]:
        votes=frame[policy+'_votes']-frame[base+'_votes'];d=int(votes[positive].sum());v=votes[missing].to_numpy()
        exact=exact_vote_envelope(505,d,v,nseeds)
        floating=missing_quality_contrast_bounds(505,d/nseeds,v/nseeds)
        np.testing.assert_allclose([floating['lower'],floating['upper']],[float(x) for x in exact],rtol=0,atol=1e-14)
        previous=prior['missing_quality_contrast_bounds'][policy+'_minus_'+base]
        np.testing.assert_allclose([previous['lower'],previous['upper']],[float(x) for x in exact],rtol=0,atol=1e-14)
        nonwarm=missing&frame.Machine_Status.ne(1)
        no_warm=exact_vote_envelope(505,d,votes[nonwarm],nseeds)
        comparisons[policy+'_minus_'+base]={
            'known_capture_difference_votes':d,'seeds':nseeds,'known_positive_shots':505,
            'lower_exact':str(exact[0]),'upper_exact':str(exact[1]),
            'lower_pp':float(exact[0])*100,'upper_pp':float(exact[1])*100,
            'unknown_difference_votes_histogram':{str(int(k)):int(v) for k,v in pd.Series(v).value_counts().sort_index().items()},
            'if_state1_not_quality_targets_fixed_actions_only_pp':[float(x)*100 for x in no_warm]}
    # Overlap is preserved. These are joint action cells, not two separate label assignments.
    overlap=frame.loc[missing].groupby(['Q_votes','GQ_votes','FIFO_votes','state_code','process_complete'],dropna=False).size().reset_index(name='records')
    positive_delta=(frame.GQ_votes-frame.FIFO_votes).gt(0)&missing
    assert positive_delta.sum()==26 and frame.loc[positive_delta,'Machine_Status'].eq(1).all()
    assert (frame.loc[missing,'Q_votes']==frame.loc[missing,'FIFO_votes']).all()
    assert int((frame.loc[missing,'GQ_votes']-frame.loc[missing,'FIFO_votes']).sum())==114
    budget_table=pd.DataFrame(budget_rows)
    assert budget_table.groupby(['policy','seed']).available_slots.sum().eq(677).all()
    assert budget_table.loc[budget_table.policy.eq('Q')].groupby('seed').used_slots.sum().eq(675).all()
    assert budget_table.loc[budget_table.policy.eq('GQ')].groupby('seed').used_slots.sum().eq(677).all()
    assert int((frame.FIFO_votes/nseeds).sum())==675
    # Time is source order/Shot only. Do not derive dates or propagate Product_Type.
    counts=frame.groupby(['run_id','fold','missing_quality','state_code','process_complete'],dropna=False).agg(
        records=('row_id','size'),shot_min=('Shot','min'),shot_max=('Shot','max'),source_min=('source_row','min'),source_max=('source_row','max')).reset_index()
    blocks=[]
    for run,rows in frame.groupby('run_id'):
        group=(rows.missing_quality.ne(rows.missing_quality.shift())|rows.source_row.diff().ne(1)).cumsum()
        for _,part in rows.loc[rows.missing_quality].groupby(group):
            blocks.append({'run_id':int(run),'records':len(part),'source_start':int(part.source_row.min()),'source_end':int(part.source_row.max()),
                'shot_start':int(part.Shot.min()),'shot_end':int(part.Shot.max()),
                'state_codes':','.join(sorted(part.state_code.unique()))})
    proc_missing={c:int(frame.loc[missing,c].isna().sum()) for c in process}
    process_rows=[]
    for (no_quality,state),part in frame.groupby(['missing_quality','state_code']):
        for name in process:
            values=part[name].dropna()
            process_rows.append({'missing_quality':bool(no_quality),'state_code':state,'feature':name,
                'records':len(part),'observed':len(values),'missing':int(part[name].isna().sum()),
                'minimum':values.min(),'q25':values.quantile(.25),'median':values.median(),
                'q75':values.quantile(.75),'maximum':values.max()})
    qcohort=q.merge(frame[['run_id','Shot']],on=['run_id','Shot'],validate='one_to_one')
    assert len(qcohort)==2879 and int(qcohort.y_defect.sum())==505
    payload={'status':'passed','checked_at':datetime.now(timezone.utc).isoformat(),
        'input_hashes':hashes,'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'timeline_raw_rows':len(raw),'quality_raw_rows':len(quality),'quality_unique_shots':len(unique),
        'quality_duplicate_rows_removed':len(quality)-len(unique),'quality_keys_lost_in_preprocessing':0,
        'quality_target_cells_missing_in_raw':0,'timeline_keys_without_raw_quality_global':len(raw)-len(unique),
        'cohort_unique_shots':len(frame),'cohort_duplicate_physical_shots':0,'known_quality_shots':2879,
        'known_positive_shots':505,'unknown_quality_shots':516,'unknown_quality_found_in_raw':0,
        'unknown_by_state_and_process':counts.loc[counts.missing_quality].to_dict('records'),
        'unknown_gate_role_counts':frame.loc[missing,'original_gate_role'].value_counts().to_dict(),
        'missing_process_values_by_column':proc_missing,
        'unknown_product_type_records':int(frame.loc[missing,'Product_Type'].isna().sum()),
        'known_product_counts':frame.loc[known].groupby('Product_Type').size().to_dict(),
        'known_product_counts_by_run':frame.loc[known].groupby(['run_id','Product_Type']).size().reset_index(name='records').to_dict('records'),
        'quality_features_absent_from_raw_timeline':[c for c in contract['q42_A'] if c not in raw.columns],
        'wall_clock_and_physical_lineage_available':False,
        'cohort_raw_quality_occurrences':int(frame.loc[known,'raw_occurrences'].sum()),
        'cohort_multi_defect_type_shots':int(qcohort.defect_type_count.gt(1).sum()),
        'cohort_defect_type_sum':int(qcohort.defect_type_count.sum()),
        'cohort_two_defective_cavities_shots':int((qcohort.y_cavity_1.eq(1)&qcohort.y_cavity_2.eq(1)).sum()),
        'cohort_defective_cavities_sum':int(qcohort.y_cavity_1.sum()+qcohort.y_cavity_2.sum()),
        'unknown_quality_score_available':0,'unknown_hold_requested':409,'unknown_hold_served_each_policy':168,
        'unknown_hold_unserved_each_policy':241,'unknown_complete_not_candidates_Q_FIFO':107,
        'unknown_GQ_only_inspected_union':26,'unknown_GQ_only_all_state_code1':True,
        'unknown_GQ_extra_inspections_seed_mean':22.8,
        'offered_capacity_sum_per_run':677,'incorrect_global_floor_capacity':679,
        'actual_Q_FIFO_inspections':675,'actual_GQ_inspections_each_seed':677,
        'equal_offered_budget_not_equal_used_workload':True,'bounds':comparisons,
        'assumptions':['fixed stored actions and availability, including service opportunities on every timeline row',
            'same unknown binary Shot outcome shared across policies and five seeds',
            'known 505 positives remain included; target is Shot with any defect, not defective cavity/product count',
            'existing run/Shot file correspondence accepted; not externally verified physical provenance',
            'no relabeling, new scores, rerouting, target-based capacity recalculation, policy selection or retraining'],
        'eligibility_caveat':'All 516 being eligible is sufficient. Allowing unknown rows to be ineligible also gives the same envelope for fixed actions when ineligible rows contribute zero positive mass; deleting them from the queue or budget changes the estimand and is not evaluated.',
        'not_identified':['physical target eligibility and reasons absent from quality source','Product_Type of all 516 rows',
            'wall-clock input/inspection/label availability','quality of 516 rows','product/cavity-level loss or future policy superiority'],
        'new_training_or_policy_selection':False,'scope_reduction_changed':False}
    assert all(sha256((root/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
    return payload,{'units':frame,'missing_records':frame.loc[missing].copy(),'distribution':counts,
        'missing_blocks':pd.DataFrame(blocks),'joint_missing_actions':overlap,'budget_accounting':budget_table,
        'process_distribution':pd.DataFrame(process_rows)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Use a fresh evidence directory')
    result,tables=audit();args.output.mkdir(parents=True,exist_ok=False)
    for name,table in tables.items():table.to_csv(args.output/(name+'.csv'),index=False)
    result['output_hashes']={p.name:sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}
    (args.output/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','unknown_quality_shots','unknown_quality_found_in_raw','unknown_gate_role_counts','bounds']},ensure_ascii=False,indent=2))
