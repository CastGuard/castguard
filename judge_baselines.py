"""Fixed descriptive comparisons, never selecting or promoting a policy."""
from pathlib import Path
from datetime import datetime,timezone
import json,argparse
import numpy as np
import pandas as pd
from castguard.data import read_inputs,digest
from oct03_queue import stream_queue,measure
ROOT=Path(__file__).resolve().parent
INPUTS=['row_id','source_row','run_id','Shot','process_complete','gate_probability','quality_probability','ood_score']

def baseline_scores(fit,observations,policy,features,seed,window):
    """The observations contract excludes outcomes and state labels."""
    forbidden={'y_defect','Machine_Status','episode_id','PassOrFail'}
    if forbidden.intersection(observations): raise ValueError('Outcome leaked into baseline scoring')
    if policy=='FIFO': return np.zeros(len(observations))
    if policy=='RANDOM': return np.random.default_rng(seed).random(len(observations))
    if policy=='RECENT_PRODUCT_RATE':
        recent=fit.sort_values('source_row').tail(window)
        rate=recent.groupby('Product_Type').y_defect.mean()
        return observations.Product_Type.map(rate).fillna(recent.y_defect.mean()).to_numpy()
    if policy=='PROCESS_DEVIATION':
        median=fit[features].median().fillna(0)
        scale=(fit[features].quantile(.75)-fit[features].quantile(.25)).replace(0,1).fillna(1)
        return ((observations[features].fillna(median)-median).abs()/scale).mean(axis=1).to_numpy()
    raise ValueError(policy)

def run(root,out):
    if out.exists(): raise FileExistsError('Use a new output folder')
    out.mkdir(parents=True)
    cfg=json.loads((root/'configs/oct03_judge_review.json').read_text())
    inputs=['judge_baselines.py','configs/oct03_judge_review.json','docs/OCT03_JUDGE_REVIEW_PROTOCOL.md',
     'oct03_queue.py','reports/oct03_queue/outer_actions.parquet','reports/oct03_queue/nested_assignments.csv',
     'reports/oct03_queue_review/pooled_at20.csv']
    inputs += [p.relative_to(root).as_posix() for p in (root/'data/processed').iterdir() if p.is_file()]
    hashes={p:digest(root/p) for p in inputs}
    save=lambda name,obj:(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    save('registration.json',{'started_at':datetime.now(timezone.utc).isoformat(),'config':cfg,'input_hashes':hashes})
    frames,_,contract=read_inputs(root);q=frames['q42'];m=frames['m41'];features=contract['q42_A0']
    assignments=pd.read_csv(root/'reports/oct03_queue/nested_assignments.csv',dtype={'fold':str})
    old=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    base=old.loc[old.policy.eq('Q')&old.budget.eq(cfg['budget'])&old.seed.eq(17)].copy()
    assert len(base)==3395 and base.y_defect.eq(1).sum()==505
    rows=[];actions=[];fit_records=[]
    for fold,stream in base.groupby('fold',sort=True):
        stream=stream.sort_values(['source_row','row_id']).reset_index(drop=True)
        ids=assignments.loc[assignments.fold.eq(fold)&assignments.dataset.eq('q42')&assignments.nested_role.eq('fit'),'row_id']
        fit=q.loc[q.row_id.isin(ids)].copy(); evaluation=q.merge(stream[['run_id','Shot']],on=['run_id','Shot'],validate='one_to_one')
        assert set(fit.row_id).isdisjoint(set(evaluation.row_id))
        assert fit.source_row.max()<evaluation.source_row.min()
        fit_records.append({'fold':fold,'fit_rows':len(fit),'recent_rows':min(len(fit),cfg['recent_fit_window']),
          'fit_row_ids':fit.row_id.tolist(),'recent_row_ids':fit.sort_values('source_row').tail(cfg['recent_fit_window']).row_id.tolist()})
        # The original availability mask is kept, and inspected outcomes are not score inputs.
        observed=stream[['run_id','Shot']].merge(q[['run_id','Shot','Product_Type']+features],on=['run_id','Shot'],how='left',validate='one_to_one')
        mask=stream.quality_probability.notna().to_numpy()
        for policy in cfg['policies']:
            seeds=range(cfg['random_seed_start'],cfg['random_seed_start']+cfg['random_repetitions']) if policy=='RANDOM' else [0]
            for seed in seeds:
                scores=stream[INPUTS].copy()
                scores['quality_probability']=np.where(mask,baseline_scores(fit,observed,policy,features,[seed,int(fold)],cfg['recent_fit_window']),np.nan)
                scores['gate_probability']=np.nan;scores['ood_score']=0.
                action=stream_queue(scores,'Q',np.inf,True,np.inf,cfg['budget'])
                stats,labelled,_=measure(action,m,q,cfg['budget'])
                assert stats['n_total']==len(stream) and stats['inspected']==int(stream.inspected.sum())
                assert stats['hold_backlog']==int((stream.hold&~stream.inspected).sum())
                assert stats['quality_positive']==int(stream.y_defect.eq(1).sum())
                np.testing.assert_array_equal(action.hold,stream.hold)
                service=action.loc[action.inspected,'service_step'].to_numpy(dtype=int)
                assert (np.bincount(service,minlength=len(stream)).cumsum() <= np.floor(np.arange(1,len(stream)+1)*.2+1e-12)).all()
                rows.append({'fold':fold,'policy':policy,'seed':seed,**stats})
                actions.append(action[['row_id','quality_probability','inspected','service_step','hold']].assign(fold=fold,policy=policy,seed=seed))
    metrics=pd.DataFrame(rows);metrics.to_csv(out/'baseline_metrics.csv',index=False)
    pd.concat(actions,ignore_index=True).to_parquet(out/'baseline_actions.parquet',index=False)
    save('fit_registry.json',fit_records)
    counts=['n_total','quality_known','quality_positive','quality_captured','inspected','hold_backlog','normal_total','normal_alarm_or_hold','episodes_inspection_reached']
    totals=metrics.groupby(['policy','seed'])[counts].sum().reset_index()
    totals['capture']=totals.quality_captured/totals.quality_positive
    totals.to_csv(out/'baseline_pooled_repetitions.csv',index=False)
    summary=totals.groupby('policy').agg(capture=('capture','mean'),capture_p025=('capture',lambda v:v.quantile(.025)),
      capture_p975=('capture',lambda v:v.quantile(.975)),hits=('quality_captured','mean'),inspected=('inspected','mean'),
      hold_backlog=('hold_backlog','mean'),repetitions=('capture','size')).reset_index()
    reference=pd.read_csv(root/'reports/oct03_queue_review/pooled_at20.csv').set_index('policy')
    summary['Q_gain_pp']=(float(reference.loc['Q','quality_capture_pooled'])-summary.capture)*100
    summary['GQ_gain_pp']=(float(reference.loc['GQ','quality_capture_pooled'])-summary.capture)*100
    summary.to_csv(out/'baseline_summary.csv',index=False)
    # No test, threshold, model, or report source is mutated.
    assert all(digest(root/name)==h for name,h in hashes.items())
    save('receipt.json',{'completed_at':datetime.now(timezone.utc).isoformat(),'input_hashes':hashes,
     'output_hashes':{p.name:digest(p) for p in out.iterdir() if p.is_file()},'metric_groups':len(metrics),
     'action_rows':sum(len(x) for x in actions),'new_model_fits':0,'legacy_test_rows_used':0,
     'scope':'historically seen development only; descriptive baselines registered after prior model results',
     'selection_or_promotion':False,'all_prefix_budgets_and_same_hold_and_populations_checked':True})
    print(summary.to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path('reports/submission_round6/baselines'));a=p.parse_args();run(ROOT,ROOT/a.output)
