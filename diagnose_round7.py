"""Retrospective, paired queue diagnosis. Never trains, tunes or promotes a model."""
from pathlib import Path
from datetime import datetime,timezone
from itertools import product
import argparse,json,heapq
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score
from castguard.data import read_inputs,digest,check_features
from judge_baselines import INPUTS,baseline_scores
from oct03_queue import stream_queue
ROOT=Path(__file__).resolve().parent

def independent_queue(scores, policy='Q', threshold=np.inf, disabled=True, budget=.2, tie='fifo',seed=0,full_availability=False):
    """Independent list/min replay; never imports the production queue's priority logic."""
    forbidden={'y_defect','Machine_Status','episode_id','PassOrFail'}
    if forbidden.intersection(scores.columns): raise ValueError('Outcome in observation surface')
    rows=scores.sort_values(['source_row','row_id']).reset_index(drop=True)
    if rows.row_id.duplicated().any() or rows.run_id.nunique()!=1: raise ValueError('One unique run required')
    if not 0<budget<=1: raise ValueError('Invalid capacity')
    complete=rows.process_complete.to_numpy(bool)
    gp=rows.gate_probability.to_numpy(float); qp=rows.quality_probability.to_numpy(float)
    alarms=complete & (gp>=threshold) & (not disabled) & (policy!='Q')
    arrival=np.arange(len(rows))
    tie_values=arrival if tie=='fifo' else -arrival if tie=='lifo' else np.random.default_rng(seed).random(len(rows))
    pending=[]; served=np.full(len(rows),-1,int); reasons=[]; slots=[];candidate_count=[];top_ties=[]
    for i in range(len(rows)):
        if not complete[i]: priority=(0,0.,i,i);reason='hold'
        elif alarms[i]: priority=(1,-gp[i],float(tie_values[i]),i);reason='gate'
        elif np.isfinite(qp[i]) or full_availability: priority=(2,-qp[i] if np.isfinite(qp[i]) else 0.,float(tie_values[i]),i);reason='quality'
        else: priority=None;reason='none'
        reasons.append(reason)
        if priority is not None: pending.append(priority)
        capacity=int(np.floor((i+1)*budget+1e-12))-int(np.floor(i*budget+1e-12))
        if capacity and pending:
            best=min(pending)
            candidate_count.append(len(pending));top_ties.append(sum(p[:2]==best[:2] for p in pending))
            pending.remove(best);served[best[-1]]=i;slots.append(i)
    return pd.DataFrame({'row_id':rows.row_id,'inspected':served>=0,'service_step':served,'reason':reasons}),{
      'services':len(slots),'service_slots':slots,'decision_candidates_mean':float(np.mean(candidate_count)) if candidate_count else 0,
      'services_with_priority_ties':sum(x>1 for x in top_ties),'max_top_ties':max(top_ties,default=0)}

def paired_interval(rows, policy, lengths=(25,50,100), repetitions=4000,seed=20261003):
    """Resample paired frozen outcomes, keeping runs/contiguous blocks together."""
    runs=[g.sort_values('arrival_step') for _,g in rows.groupby('run_id',sort=True)]
    values=[np.column_stack((g.positive.to_numpy(float),g[f'delta_{policy}'].to_numpy(float))) for g in runs]
    totals=np.array([v.sum(axis=0) for v in values]);point=100*totals[:,1].sum()/totals[:,0].sum()
    def record(method, samples, block=None):
        samples=np.asarray(samples,float);valid=samples[np.isfinite(samples)]
        return {'policy':policy,'reference':'FIFO','method':method,'block_records':block,'point_pp':point,
          'lower_pp':float(np.quantile(valid,.025)),'upper_pp':float(np.quantile(valid,.975)),
          'replicates':len(samples),'valid_replicates':len(valid),'inference':'conditional frozen decisions; seen data; no confirmatory coverage claim'}
    draws=totals[np.array(list(product(range(len(runs)),repeat=len(runs))))].sum(axis=1)
    outputs=[record('whole_run_cluster_exact_enumeration',100*draws[:,1]/draws[:,0])]
    for block in lengths:
        rng=np.random.default_rng([seed,int(block)])
        sums=np.zeros((repetitions,2))
        for v in values:
            n=len(v);length=min(block,n);count=int(np.ceil(n/length))
            starts=rng.integers(0,n-length+1,size=(repetitions,count))
            indices=(starts[:,:,None]+np.arange(length)).reshape(repetitions,-1)[:,:n]
            sums+=v[indices].sum(axis=1)
        outputs.append(record('within_run_moving_block',np.divide(100*sums[:,1],sums[:,0],out=np.full(repetitions,np.nan),where=sums[:,0]>0),block))
    return outputs

def group_metrics(rows,policies,dimension):
    records=[]
    for key,g in rows.groupby(dimension,dropna=False,sort=True):
        for policy in policies:
            inspected=g[policy].to_numpy(float);positive=g.positive.to_numpy(float);known=g.quality_known.to_numpy(bool)
            hits=float(np.dot(inspected,positive));denom=int(positive.sum())
            records.append({'dimension':dimension,'group':str(key),'policy':policy,'rows':len(g),'quality_known':int(known.sum()),
              'positive':denom,'positive_rate_known':denom/int(known.sum()) if known.sum() else np.nan,
              'inspected_mean':float(inspected.sum()),'known_inspected_mean':float(inspected[known].sum()),
              'unknown_quality_inspected_mean':float(inspected[~known].sum()),'hits_mean':hits,
              'capture':hits/denom if denom else np.nan,
              'delta_hits_vs_FIFO':float(np.dot(inspected-g.FIFO.to_numpy(float),positive)),
              'delta_pp_of_pooled_505':100*float(np.dot(inspected-g.FIFO.to_numpy(float),positive))/505})
    return records

def run(root,out):
    if out.exists(): raise FileExistsError('Use a new diagnostic output directory')
    out.mkdir(parents=True)
    cfg=json.loads((root/'configs/oct03_round7_diagnostics.json').read_text())
    names=['diagnose_round7.py','configs/oct03_round7_diagnostics.json','docs/OCT03_ROUND7_DIAGNOSTIC_PROTOCOL.md',
      'judge_baselines.py','oct03_queue.py','castguard/rebuild.py','castguard/data.py','reports/oct03_queue/outer_actions.parquet',
      'reports/oct03_queue/selection.json','reports/oct03_queue/nested_assignments.csv',
      'reports/submission_round6/baselines_final/baseline_actions.parquet','reports/oct02/predictions.parquet']
    names += [p.relative_to(root).as_posix() for p in (root/'data/processed').iterdir() if p.is_file()]
    hashes={name:digest(root/name) for name in names}
    save=lambda name,obj:(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
    save('registration.json',{'started_at':datetime.now(timezone.utc).isoformat(),'config':cfg,'input_hashes':hashes})
    frames,folds,contract=read_inputs(root);q=frames['q42'];m=frames['m41']
    for name in ('q42_A','m41_gate'): check_features(contract[name],contract)
    original=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    original=original.loc[original.budget.eq(.2)&original.policy.isin(['Q','GQ'])].copy()
    original['fold']=original.fold.astype(str)
    baseline=pd.read_parquet(root/'reports/submission_round6/baselines_final/baseline_actions.parquet')
    baseline['fold']=baseline.fold.astype(str)
    old=original.loc[original.policy.eq('Q')&original.seed.eq(17)].sort_values(['fold','source_row','row_id']).copy()
    targets=[x for x in contract['target_columns'] if x in q and x.endswith(('_1','_2'))]
    rows=old[['fold','row_id','run_id','Shot','source_row','arrival_step','process_complete','hold','Machine_Status','y_defect']].merge(
      q[['run_id','Shot','Product_Type']+targets],on=['run_id','Shot'],how='left',validate='one_to_one')
    rows['quality_known']=rows.y_defect.notna();rows['positive']=rows.y_defect.eq(1).astype(int)
    rows['quality_available']=old.quality_probability.notna().to_numpy()
    assert len(rows)==3395 and rows.positive.sum()==505 and rows.quality_known.sum()==2879
    assert rows.groupby('run_id').row_id.nunique().sum()==len(rows)
    policies=['FIFO','RECENT_PRODUCT_RATE','Q','GQ','RANDOM','PROCESS_DEVIATION']
    combined=pd.concat([original[['fold','row_id','policy','seed','inspected','service_step']],baseline[['fold','row_id','policy','seed','inspected','service_step']]],ignore_index=True)
    for policy in policies:
        mean=combined.loc[combined.policy.eq(policy)].groupby(['fold','row_id']).inspected.mean().rename(policy).reset_index()
        rows=rows.merge(mean,on=['fold','row_id'],validate='one_to_one')
    assert rows[policies].notna().all().all()
    for p in ['Q','GQ']:rows[f'delta_{p}']=(rows[p]-rows.FIFO)*rows.positive
    sizes=rows.groupby('run_id').row_id.transform('size')
    rows['quartile']=(rows.arrival_step*4//sizes).clip(upper=3)+1
    rows['run_quartile']=rows.run_id.astype(str)+'_Q'+rows.quartile.astype(str)
    rows['availability_state']=np.select([rows.hold,~rows.quality_available],['process_missing_hold','complete_without_quality_score'],default='complete_with_quality_score')
    rows['state']=rows.Machine_Status.map({0.:'normal',1.:'warm'}).fillna('state_unknown')
    rows.to_parquet(out/'paired_rows.parquet',index=False)
    group_rows=[]
    rows['all']='all'
    for key in ['all','run_id','Product_Type','quartile','run_quartile','availability_state','state']:
        group_rows+=group_metrics(rows,policies,key)
    pd.DataFrame(group_rows).to_csv(out/'group_metrics.csv',index=False)
    defects=[]
    for target in targets:
        for run_id,g in [('all',rows)]+list(rows.groupby('run_id')):
            y=g[target].gt(0).to_numpy(float);denom=int(y.sum())
            for p in ['FIFO','Q','GQ']:
                hits=float(np.dot(g[p],y));delta=float(np.dot(g[p]-g.FIFO,y))
                defects.append({'defect':target,'run_id':run_id,'policy':p,'positive_shots':denom,'hits_mean':hits,
                  'capture':hits/denom if denom else np.nan,'delta_hits_vs_FIFO':delta,'overlapping_labels_not_additive':True})
    pd.DataFrame(defects).to_csv(out/'defect_metrics.csv',index=False)
    assigns=pd.read_csv(root/'reports/oct03_queue/nested_assignments.csv',dtype={'fold':str})
    selections={str(x['fold']):x for x in json.loads((root/'reports/oct03_queue/selection.json').read_text())['folds']}
    audits=[];equivalence=[];ties=[];waiting=[];score_stats=[];timing_pairs=[];full_availability=[]
    for fold,base in old.groupby('fold',sort=True):
        base=base.sort_values(['source_row','row_id']).reset_index(drop=True)
        rr=rows.loc[rows.fold.eq(fold)].sort_values(['source_row','row_id']).reset_index(drop=True)
        fit_ids=assigns.loc[assigns.fold.eq(fold)&assigns.dataset.eq('q42')&assigns.nested_role.eq('fit'),'row_id']
        fit=q.loc[q.row_id.isin(fit_ids)].sort_values('source_row');recent=fit.tail(100)
        assert set(fit.row_id).isdisjoint(set(q.loc[q.run_id.isin(base.run_id),'row_id']))
        observed=base[['run_id','Shot']].merge(q[['run_id','Shot','Product_Type']+contract['q42_A0']],on=['run_id','Shot'],how='left',validate='one_to_one')
        hist=baseline_scores(fit,observed,'RECENT_PRODUCT_RATE',contract['q42_A0'],[0,int(fold)],100)
        mask=base.quality_probability.notna().to_numpy()
        f=baseline.loc[baseline.fold.eq(fold)&baseline.policy.eq('FIFO')].set_index('row_id').loc[base.row_id]
        h=baseline.loc[baseline.fold.eq(fold)&baseline.policy.eq('RECENT_PRODUCT_RATE')].set_index('row_id').loc[base.row_id]
        equivalence.append({'fold':fold,'run_id':int(base.run_id.iloc[0]),'evaluation_products':sorted(rr.Product_Type.dropna().unique().tolist()),
          'recent_fit_products':sorted(recent.Product_Type.unique().tolist()),'recent_fit_rate':float(recent.y_defect.mean()),
          'score_unique_count':len(np.unique(hist[mask])),'constant_score':float(hist[mask][0]),
          'fallback_rows':int((mask&~observed.Product_Type.isin(recent.Product_Type)).sum()),
          'inspection_disagreements':int((f.inspected.to_numpy()!=h.inspected.to_numpy()).sum()),
          'service_time_disagreements':int((f.service_step.to_numpy()!=h.service_step.to_numpy()).sum()),
          'fit_last_q_source_row':int(fit.source_row.max()),'eval_first_q_source_row':int(q.loc[q.run_id.isin(base.run_id),'source_row'].min())})
        for policy in ['FIFO','RECENT_PRODUCT_RATE','Q','GQ']:
            selected=baseline.loc[baseline.fold.eq(fold)&baseline.policy.eq(policy)] if policy in ['FIFO','RECENT_PRODUCT_RATE'] else original.loc[original.fold.eq(fold)&original.policy.eq(policy)]
            for seed,group in selected.groupby('seed'):
                group=group.set_index('row_id').loc[base.row_id].reset_index()
                if policy in ['Q','GQ']:
                    source=group[INPUTS].copy(); gate=selections[fold]['gate_thresholds'][str(seed)]
                    threshold=gate['threshold'] if gate['threshold'] is not None else np.inf;disabled=gate['disabled']
                else:
                    source=base[INPUTS].copy();source['quality_probability']=group.quality_probability.to_numpy()
                    source['gate_probability']=np.nan;threshold=np.inf;disabled=True
                replay,details=independent_queue(source,'Q' if policy in ['FIFO','RECENT_PRODUCT_RATE'] else policy,threshold,disabled)
                np.testing.assert_array_equal(replay.inspected,group.inspected)
                np.testing.assert_array_equal(replay.service_step,group.service_step)
                arrival=np.arange(len(base));served=replay.service_step.to_numpy();pick=served>=0
                assert np.all(served[pick]>=arrival[pick])
                np.testing.assert_array_equal(np.isfinite(source.quality_probability),mask)
                audits.append({'fold':fold,'policy':policy,'seed':int(seed),'rows':len(base),'replay_exact':True,
                  'same_quality_mask':True,'causal_service':True,**{k:v for k,v in details.items() if k!='service_slots'}})
                for group_name,select in [('all',pick),('quality_known',pick&rr.quality_known),('positive',pick&rr.positive.eq(1)),('hold',pick&rr.hold)]:
                    delays=(served-arrival)[select]
                    waiting.append({'fold':fold,'policy':policy,'seed':int(seed),'population':group_name,'n':len(delays),
                      'wait_mean_records':float(np.mean(delays)) if len(delays) else np.nan,
                      'wait_p95_records':float(np.quantile(delays,.95)) if len(delays) else np.nan,'wait_max_records':int(max(delays)) if len(delays) else None})
                if policy in ['Q','GQ']:
                    # Align each service opportunity, allowing the two extra GQ services explicitly.
                    left=pd.DataFrame({'step':f.service_step.to_numpy(),'fifo_row':np.arange(len(f))})
                    right=pd.DataFrame({'step':served,'model_row':np.arange(len(f))})
                    joined=left.loc[left.step.ge(0)].merge(right.loc[right.step.ge(0)],on='step',how='outer',validate='one_to_one')
                    for cell in joined.itertuples():
                        fi=None if pd.isna(cell.fifo_row) else int(cell.fifo_row);mi=None if pd.isna(cell.model_row) else int(cell.model_row)
                        fy=int(rr.positive.iloc[fi]) if fi is not None else 0;my=int(rr.positive.iloc[mi]) if mi is not None else 0
                        timing_pairs.append({'fold':fold,'policy':policy,'seed':int(seed),'service_step':int(cell.step),
                          'fifo_row_id':rr.row_id.iloc[fi] if fi is not None else '',
                          'model_row_id':rr.row_id.iloc[mi] if mi is not None else '',
                          'fifo_positive':fy,'model_positive':my,'paired_delta':my-fy,
                          'fifo_reason':'hold' if fi is not None and rr.hold.iloc[fi] else 'quality' if fi is not None else 'unused',
                          'model_reason':replay.reason.iloc[mi] if mi is not None else 'unused'})
                if policy=='Q':
                    for quartile,part in rr.groupby('quartile'):
                        idx=part.index[part.quality_known].to_numpy();v=source.quality_probability.iloc[idx].to_numpy();y=rr.positive.iloc[idx].to_numpy()
                        score_stats.append({'fold':fold,'seed':int(seed),'quartile':int(quartile),'known':len(idx),'positive':int(y.sum()),
                          'mean_probability':float(np.mean(v)) if len(v) else None,'prevalence':float(np.mean(y)) if len(y) else None,
                          'score_time_spearman':float(pd.Series(v).corr(pd.Series(idx),method='spearman')) if len(v)>1 else None,
                          'ap':float(average_precision_score(y,v)) if y.sum() else None,
                          'auc':float(roc_auc_score(y,v)) if len(np.unique(y))==2 else None})
        # Tie-order sensitivity uses the same mask and hold FIFO; no policy promotion.
        scores=base[INPUTS].copy();scores['quality_probability']=np.where(mask,0.,np.nan);scores['gate_probability']=np.nan
        for mode in ['fifo','lifo','random']:
            for rep in (range(cfg['tie_repetitions']) if mode=='random' else [0]):
                action,_=independent_queue(scores,tie=mode,seed=[cfg['seed'],int(fold),rep])
                ties.append({'fold':fold,'tie':mode,'rep':rep,'inspected':int(action.inspected.sum()),
                  'positive':int(rr.positive.sum()),'captured':int(np.dot(action.inspected,rr.positive)),
                  'mean_wait_records':float((action.loc[action.inspected,'service_step'].to_numpy()-np.flatnonzero(action.inspected)).mean())})
        # Do not drop unknown quality from the population: report what cannot be measured.
        all_action,_=independent_queue(scores,full_availability=True)
        full_availability.append({'fold':fold,'run_id':int(base.run_id.iloc[0]),'inspected':int(all_action.inspected.sum()),
          'known_quality_inspected':int((all_action.inspected&rr.quality_known).sum()),
          'unknown_quality_inspected':int((all_action.inspected&~rr.quality_known).sum()),
          'known_positive_captured':int(np.dot(all_action.inspected,rr.positive)),
          'observed_positive_denominator':int(rr.positive.sum()),'true_total_quality_capture_identified':False})
    for name,records in [('replay_audit',audits),('fifo_history_equivalence',equivalence),('waiting',waiting),('score_chronology',score_stats),
                         ('paired_service_slots',timing_pairs),('tie_sensitivity',ties),('full_availability_fifo',full_availability)]:
        pd.DataFrame(records).to_csv(out/(name+'.csv'),index=False)
    intervals=[];leave=[]
    for policy in ['Q','GQ']:
        intervals+=paired_interval(rows,policy,cfg['moving_block_lengths'],cfg['bootstrap_repetitions'],cfg['seed'])
        for run_id in sorted(rows.run_id.unique()):
            subset=rows.loc[rows.run_id.ne(run_id)]
            leave.append({'policy':policy,'removed_run':int(run_id),'positive':int(subset.positive.sum()),
              'delta_hits':float(subset[f'delta_{policy}'].sum()),'delta_pp':100*float(subset[f'delta_{policy}'].sum())/subset.positive.sum()})
    pd.DataFrame(intervals).to_csv(out/'paired_uncertainty.csv',index=False)
    pd.DataFrame(leave).to_csv(out/'leave_one_run_out.csv',index=False)
    oldpred=pd.read_parquet(root/'reports/oct02/predictions.parquet',columns=['row_id','dataset','role'])
    qp=oldpred.loc[oldpred.dataset.eq('q42')]
    evaluated=set(qp.row_id);tested=set(qp.loc[qp.role.eq('test'),'row_id'])
    unused=q.loc[~q.row_id.isin(evaluated)]
    save('evaluation_exposure.json',{'quality_rows':len(q),'prior_evaluation_unique_rows':len(evaluated),
      'prior_test_unique_rows':len(tested),'not_in_saved_evaluation_rows':unused[['row_id','run_id','Shot','y_defect']].to_dict('records'),
      'eligible_q_rows':len(set(folds.loc[folds.dataset.eq('q42')&folds.role.ne('excluded'),'row_id'])),
      'genuinely_untouched_evaluation_identified':False,
      'reason':'All non-excluded q42 rows have existing test predictions. The four tiny-run rows were excluded and already inspected in data audits; they are not an independent holdout.',
      'feature_time_contract':'after shot production, before final inspection; actual sensor and inspection timestamps absent',
      'quality_presence_mask_observability_confirmed':False,'training_label_ready_time_confirmed':False,
      'current_run_shot_position':'cumcount of rows present in q42; online equivalence requires verified row availability',
      'direct_evaluation_target_value_in_queue':False,'forbidden_features_in_model_contract':False})
    assert all(digest(root/name)==h for name,h in hashes.items())
    save('receipt.json',{'completed_at':datetime.now(timezone.utc).isoformat(),'input_hashes':hashes,
      'output_hashes':{p.name:digest(p) for p in out.iterdir() if p.is_file()},'rows':len(rows),'replayed_groups':len(audits),
      'new_model_fits':0,'new_policy_selected':False,'untouched_test_identified':False})
    print(pd.DataFrame(group_rows).query("dimension=='all'")[['policy','hits_mean','capture','delta_hits_vs_FIFO']].to_string(index=False),flush=True)
    print(pd.DataFrame(equivalence).to_string(index=False),flush=True)
    print(pd.DataFrame(intervals)[['policy','method','block_records','point_pp','lower_pp','upper_pp']].to_string(index=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('reports/oct03_round7'))
    args=parser.parse_args();run(ROOT,ROOT/args.output)
