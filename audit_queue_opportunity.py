"""Independent event replay of fixed queues; no ranking search or new labels."""
from pathlib import Path
from decimal import Decimal
from hashlib import sha256
from datetime import datetime,timezone
from itertools import product
import argparse,json,sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd

INPUTS=['row_id','source_row','run_id','Shot','process_complete','gate_probability','quality_probability','ood_score']


def reference_queue(inputs,policy,budget,threshold=None,disabled=True,domain=None):
    """Simple scan of waiting records at Decimal-defined service opportunities.

    Uses no production queue helper, heap, target or saved action fields.
    Arrival happens before the current opportunity; no terminal service loop.
    """
    if set(inputs.columns)!=set(INPUTS):raise ValueError('Reference accepts only declared observation inputs')
    if policy not in ['Q','GQ','OOD1','OOD05','FIFO']:raise ValueError('Unknown policy')
    rows=inputs.sort_values(['source_row','row_id']).to_dict('records')
    ratio=Decimal(str(budget));pending=[];services={};events=[];reasons={}
    for step,row in enumerate(rows):
        hold=not row['process_complete'] or (policy.startswith('OOD') and row['ood_score']>=domain)
        gate=(not hold and policy not in ['Q','FIFO'] and not disabled and row['gate_probability']>=threshold)
        candidate={'arrival':step,'row_id':row['row_id'],'category':None,'risk':0.}
        if hold:candidate['category']='hold'
        elif gate:candidate.update(category='gate',risk=float(row['gate_probability']))
        elif np.isfinite(row['quality_probability']):candidate.update(category='quality',risk=0. if policy=='FIFO' else float(row['quality_probability']))
        before=len(pending);kind=candidate['category'] or 'none';reasons[row['row_id']]=kind
        if candidate['category'] is not None:pending.append(candidate)
        opportunity=int(Decimal(step+1)*ratio)>int(Decimal(step)*ratio)
        chosen=None
        if opportunity and pending:
            # Group priority first; scan only already arrived candidates.
            group=next(k for k in ['hold','gate','quality'] if any(p['category']==k for p in pending))
            possible=[p for p in pending if p['category']==group]
            best_risk=max(p['risk'] for p in possible)
            chosen=min((p for p in possible if p['risk']==best_risk),key=lambda p:p['arrival'])
            services[chosen['row_id']]=step;pending.remove(chosen)
        events.append({'arrival_step':step,'row_id':row['row_id'],'source_row':row['source_row'],'Shot':row['Shot'],
            'quality_score_available':bool(np.isfinite(row['quality_probability'])),
            'process_complete':bool(row['process_complete']),'gate_score_hex':float(row['gate_probability']).hex(),
            'gate_threshold_hex':float(threshold).hex() if threshold is not None else 'unused',
            'arrival_reason':kind,'pending_before_arrival':before,'pending_after_arrival':before+int(kind!='none'),
            'opportunity':opportunity,'served_row_id':chosen['row_id'] if chosen else '',
            'served_reason':chosen['category'] if chosen else '',
            'pending_after_service':len(pending)})
    result=pd.DataFrame({'row_id':[r['row_id'] for r in rows]})
    result['service_step']=result.row_id.map(services).fillna(-1).astype(int)
    result['inspected']=result.service_step.ge(0);result['reason']=result.row_id.map(reasons)
    return result,pd.DataFrame(events)


def audit(root=ROOT):
    root=Path(root)
    sources=['reports/oct03_queue/outer_actions.parquet','reports/oct03_queue/inner_actions.parquet',
        'reports/oct03_queue/selection.json','reports/oct03_queue/inner_policy_metrics.csv','configs/oct03_queue.json',
        'reports/submission_round6/baselines_final/baseline_actions.parquet','docs/OCT03_QUEUE_PROTOCOL.md',
        'judge_baselines.py','oct03_queue.py','experiment_integrity.py','docs/EVIDENCE_AND_SUBMISSION_2026-10-03.md',
        'docs/sources/oct03_round4/dataset54.html','docs/sources/oct03_round4/dataset54.txt',
        'docs/sources/oct03_round4/dataset55.html','docs/sources/oct03_round4/dataset55.txt']
    hashes={n:sha256((root/n).read_bytes()).hexdigest() for n in sources}
    config=json.loads((root/'configs/oct03_queue.json').read_text())
    choices={x['fold']:x for x in json.loads((root/'reports/oct03_queue/selection.json').read_text())['folds']}
    counts=[];traces=[];same_inputs=0;rows_checked=0
    for stage in ['inner','outer']:
        original=pd.read_parquet(root/('reports/oct03_queue/'+stage+'_actions.parquet'))
        actual_groups=set(original[['fold','seed','policy','budget']].drop_duplicates().itertuples(index=False,name=None))
        expected_groups=set(product(config['outer_folds'],config['seeds'],['Q','GQ','OOD1','OOD05'],config['budgets']))
        assert actual_groups==expected_groups,'Missing or unexpected registered action groups'
        for (fold,seed,budget),part in original.groupby(['fold','seed','budget']):
            reference=part.loc[part.policy.eq('Q'),INPUTS].sort_values('row_id').reset_index(drop=True)
            assert set(part.policy)=={'Q','GQ','OOD1','OOD05'}
            for policy,rows in part.groupby('policy'):
                compared=rows[INPUTS].sort_values('row_id').reset_index(drop=True)
                pd.testing.assert_frame_equal(reference,compared,check_exact=True)
                same_inputs+=1
        for (fold,seed,policy,budget),rows in original.groupby(['fold','seed','policy','budget']):
            chosen=choices[fold];g=chosen['gate_thresholds'][str(seed)]
            replay,events=reference_queue(rows[INPUTS],policy,budget,g['threshold'],g['disabled'],chosen['ood_thresholds'].get(policy))
            ordered=rows.sort_values(['source_row','row_id']).reset_index(drop=True)
            pd.testing.assert_frame_equal(replay,ordered[replay.columns],check_dtype=False,check_exact=True)
            inspections=int(replay.inspected.sum());enqueued=int(events.arrival_reason.ne('none').sum())
            assert events.pending_after_service.iloc[-1]==enqueued-inspections
            assert int(events.opportunity.sum())==int(Decimal(str(budget))*len(rows))
            counts.append({'stage':stage,'fold':fold,'seed':int(seed),'policy':policy,'budget':float(budget),
                'records':len(rows),'offered':int(events.opportunity.sum()),'inspected':inspections,
                'eligible_arrivals':enqueued,'terminal_pending':enqueued-inspections,
                'unused_slots':int((events.opportunity&events.served_row_id.eq('')).sum()),
                'last_step':len(rows)-1,'last_service':int(replay.service_step.max())})
            if stage=='outer' and budget==.2 and policy in ['Q','GQ']:
                keep=events if fold=='4' else events.iloc[-5:]
                if fold=='4':keep=events.loc[events.arrival_step.lt(16)|events.arrival_step.ge(len(rows)-5)]
                traces.append(keep.assign(stage=stage,fold=fold,seed=int(seed),policy=policy,budget=budget))
            rows_checked+=len(rows)
    outer=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    baseline=pd.read_parquet(root/'reports/submission_round6/baselines_final/baseline_actions.parquet')
    for fold,rows in outer.loc[outer.policy.eq('Q')&outer.seed.eq(config['seeds'][0])&outer.budget.eq(.2)].groupby('fold'):
        scores=rows[INPUTS].copy();scores['quality_probability']=scores.quality_probability.where(scores.quality_probability.isna(),0.)
        replay,events=reference_queue(scores,'FIFO',.2)
        saved=baseline.loc[baseline.policy.eq('FIFO')&baseline.fold.eq(fold)].set_index('row_id').loc[replay.row_id]
        np.testing.assert_array_equal(replay.inspected,saved.inspected)
        np.testing.assert_array_equal(replay.service_step,saved.service_step)
        assert np.array_equal(saved.quality_probability.notna(),scores.set_index('row_id').loc[replay.row_id].quality_probability.notna())
        assert np.array_equal(saved.hold,~scores.set_index('row_id').loc[replay.row_id].process_complete)
        counts.append({'stage':'outer','fold':fold,'seed':0,'policy':'FIFO','budget':.2,'records':len(rows),
            'offered':int(events.opportunity.sum()),'inspected':int(replay.inspected.sum()),
            'eligible_arrivals':int(events.arrival_reason.ne('none').sum()),'terminal_pending':int(events.pending_after_service.iloc[-1]),
            'unused_slots':int((events.opportunity&events.served_row_id.eq('')).sum()),
            'last_step':len(rows)-1,'last_service':int(replay.service_step.max())})
        keep=events.loc[events.arrival_step.lt(16)|events.arrival_step.ge(len(rows)-5)] if fold=='4' else events.iloc[-5:]
        traces.append(keep.assign(stage='outer',fold=fold,seed=0,policy='FIFO',budget=.2))
        rows_checked+=len(rows)
    trace=pd.concat(traces,ignore_index=True);summary=pd.DataFrame(counts)
    first=trace.loc[trace.fold.eq('4')&trace.arrival_step.isin([4,9])]
    assert len(counts)==484 and same_inputs==480
    for _,part in trace.loc[trace.fold.eq('4')].groupby(['policy','seed']):
        assert part.loc[part.quality_score_available,'arrival_step'].min()==10
    assert first.loc[first.policy.isin(['Q','FIFO']),'served_row_id'].eq('').all()
    assert first.loc[first.policy.eq('GQ')&first.arrival_step.eq(4),'served_row_id'].eq('m41_r3_s1').all()
    assert first.loc[first.policy.eq('GQ')&first.arrival_step.eq(9),'served_row_id'].eq('m41_r3_s2').all()
    from oct03_queue import choose_policy
    metrics=pd.read_csv(root/'reports/oct03_queue/inner_policy_metrics.csv',dtype={'fold':str})
    for fold,rows in metrics.groupby('fold'):
        assert choose_policy(rows,expected_seeds=config['seeds'],expected_budgets=config['budgets'])==choices[fold]['selected_policy']
    assert all(sha256((root/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
    result={'status':'passed','checked_at':datetime.now(timezone.utc).isoformat(),'input_hashes':hashes,
        'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_queue_groups_replayed':480,'fifo_groups_replayed':4,'action_rows_replayed':rows_checked,
        'complete_input_group_comparisons':same_inputs,'exact_action_and_service_matches':True,
        'policy_selection_unchanged':True,'end_of_stream_flush':False,'unused_slot_carryover':False,
        'arrivals_processed_before_current_slot':True,'no_future_candidates':True,
        'shared_contract':['row arrivals/order','process-availability hold','quality-score availability mask','per-run Decimal opportunity schedule','one service per opportunity','no terminal flush or carryover'],
        'intended_differences':['Q quality rank vs FIFO arrival rank','GQ permits Gate candidates even without quality score','OOD adds configured hold and suppresses Gate on held records'],
        'two_unused_slots':{'fold':'4','run_id':3,'steps_zero_based':[4,9],'arrival_Shots':[5,10],
            'Q_FIFO_pending':0,'GQ_served':['m41_r3_s1','m41_r3_s2'],'first_quality_input_step':10},
        'source_definition_review':{'official_cached_54':'describes trial production during warm-up and disposal of those products',
            'official_cached_55':'describes Shot process/sensor/quality records; no rule covering missing rows',
            'numeric_status_1_mapping_in_primary_source':'not established',
            'individual_26_row_quality_target_membership':'not established',
            'relabeling_or_declaring_ineligible_performed':False},
        'retrospective_count_equalization':False,'training_retuning_or_external_actions':False}
    return result,{'event_trace':trace,'queue_accounting':summary}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise FileExistsError('Use a fresh evidence directory')
    result,tables=audit();args.output.mkdir(parents=True,exist_ok=False)
    for name,table in tables.items():table.to_csv(args.output/(name+'.csv'),index=False)
    result['output_hashes']={p.name:sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}
    (args.output/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','model_queue_groups_replayed','fifo_groups_replayed','action_rows_replayed','two_unused_slots']},ensure_ascii=False,indent=2))
