"""Inspect fixed diagnostic results and add arithmetic explanations, without selection."""
from pathlib import Path
from datetime import datetime,timezone
import json
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score,average_precision_score
from castguard.data import digest,read_inputs
ROOT=Path(__file__).resolve().parent

def run(root=ROOT):
    source=root/'reports/oct03_round7'; out=source/'explanation'
    if out.exists():raise FileExistsError('Keep earlier explanation outputs')
    out.mkdir()
    old=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    old=old.loc[old.budget.eq(.2)&old.policy.isin(['Q','GQ'])].copy();old['fold']=old.fold.astype(str)
    rows=pd.read_parquet(source/'paired_rows.parquet');rows['fold']=rows.fold.astype(str)
    frames,_,_=read_inputs(root);q=frames['q42']
    assigns=pd.read_csv(root/'reports/oct03_queue/nested_assignments.csv',dtype={'fold':str})
    contrasts=[]; ranks=[]; timing=[];train=[]
    for fold,g in rows.groupby('fold'):
        g=g.sort_values(['source_row','row_id']).reset_index(drop=True)
        fit=q.loc[q.row_id.isin(assigns.loc[assigns.fold.eq(fold)&assigns.dataset.eq('q42')&assigns.nested_role.eq('fit'),'row_id'])]
        train.append({'fold':fold,'fit_products':sorted(fit.Product_Type.unique().tolist()),
          'eval_products':sorted(g.Product_Type.dropna().unique().tolist()),'unseen_product_rows':int((g.quality_known&~g.Product_Type.isin(fit.Product_Type)).sum()),
          'fit_rows':len(fit),'fit_prevalence':float(fit.y_defect.mean()),'eval_prevalence':float(g.loc[g.quality_known,'positive'].mean())})
        for seed,block in old.loc[old.fold.eq(fold)].groupby('seed'):
            qactions=block.loc[block.policy.eq('Q')].set_index('row_id').loc[g.row_id]
            gactions=block.loc[block.policy.eq('GQ')].set_index('row_id').loc[g.row_id]
            for policy,a in [('Q',qactions),('GQ',gactions)]:
                chosen=a.inspected.to_numpy(bool);fifo=g.FIFO.to_numpy(bool);y=g.positive.to_numpy(bool)
                contrasts.append({'fold':fold,'run_id':int(g.run_id.iloc[0]),'policy':policy,'seed':int(seed),
                  'positive_FIFO_only':int((y&fifo&~chosen).sum()),'positive_model_only':int((y&~fifo&chosen).sum()),
                  'positive_both':int((y&fifo&chosen).sum()),'positive_neither':int((y&~fifo&~chosen).sum()),
                  'changed_inspection_rows':int((fifo!=chosen).sum())})
            known=g.quality_known.to_numpy();y=g.positive.to_numpy()[known];score=qactions.quality_probability.to_numpy()[known]
            ranks.append({'fold':fold,'run_id':int(g.run_id.iloc[0]),'seed':int(seed),'known':int(known.sum()),'positive':int(y.sum()),
              'score_arrival_spearman':float(pd.Series(score).corr(pd.Series(g.arrival_step.to_numpy()[known]),method='spearman')),
              'auc':float(roc_auc_score(y,score)),'ap':float(average_precision_score(y,score)),
              'prevalence':float(y.mean())})
            left=qactions.loc[qactions.inspected,['row_id' if 'row_id' in qactions.columns else 'service_step']].copy() if False else qactions.reset_index()
            left=left.loc[left.inspected,['row_id','service_step','y_defect','reason']].rename(columns={'row_id':'q_row','y_defect':'q_y','reason':'q_reason'})
            right=gactions.reset_index();right=right.loc[right.inspected,['row_id','service_step','y_defect','reason']].rename(columns={'row_id':'gq_row','y_defect':'gq_y','reason':'gq_reason'})
            paired=left.merge(right,on='service_step',how='outer',validate='one_to_one')
            for cell in paired.itertuples():
                timing.append({'fold':fold,'seed':int(seed),'service_step':int(cell.service_step),
                  'q_row':cell.q_row,'gq_row':cell.gq_row,'same_row':cell.q_row==cell.gq_row,
                  'q_reason':cell.q_reason if pd.notna(cell.q_reason) else 'unused',
                  'gq_reason':cell.gq_reason if pd.notna(cell.gq_reason) else 'unused',
                  'q_known_quality':bool(pd.notna(cell.q_y)),'gq_known_quality':bool(pd.notna(cell.gq_y)),
                  'delta_known_positive':int(cell.gq_y==1)-int(cell.q_y==1)})
    for name,records in [('discordant_positive_pairs',contrasts),('score_rank_by_run',ranks),('gq_q_service_pairs',timing),('fit_product_exposure',train)]:
        pd.DataFrame(records).to_csv(out/(name+'.csv'),index=False)
    weights=pd.read_csv(source/'waiting.csv');weights['weighted_wait']=weights.n*weights.wait_mean_records
    delays=weights.groupby(['policy','population'])[['n','weighted_wait']].sum().reset_index()
    delays['mean_wait_records']=delays.weighted_wait/delays.n
    delays.to_csv(out/'pooled_waiting.csv',index=False)
    ties=pd.read_csv(source/'tie_sensitivity.csv').groupby(['tie','rep'])[['captured','positive']].sum().reset_index()
    ties['capture']=ties.captured/ties.positive
    tie_summary=ties.groupby('tie').agg(mean=('capture','mean'),p025=('capture',lambda s:s.quantile(.025)),p975=('capture',lambda s:s.quantile(.975)),
      min=('capture','min'),max=('capture','max'),repetitions=('capture','size')).reset_index()
    tie_summary.to_csv(out/'tie_summary.csv',index=False)
    slot=pd.DataFrame(timing)
    slot_summary=slot.groupby(['q_reason','gq_reason','same_row'])[['delta_known_positive']].agg(['size','sum'])
    slot_summary.columns=['service_pairs_all_seeds','delta_positive_all_seeds']
    slot_summary['service_pairs_seed_mean']=slot_summary.service_pairs_all_seeds/5
    slot_summary['delta_positive_seed_mean']=slot_summary.delta_positive_all_seeds/5
    slot_summary.reset_index().to_csv(out/'gq_q_slot_summary.csv',index=False)
    inputs={name:digest(root/name) for name in ['summarize_round7.py','reports/oct03_queue/outer_actions.parquet','reports/oct03_queue/nested_assignments.csv',
      'reports/oct03_round7/receipt.json','reports/oct03_round7/paired_rows.parquet','reports/oct03_round7/waiting.csv','reports/oct03_round7/tie_sensitivity.csv']}
    receipt={'completed_at':datetime.now(timezone.utc).isoformat(),'input_hashes':inputs,
      'output_hashes':{p.name:digest(p) for p in out.iterdir() if p.is_file()},'new_models_or_selection':False}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('Chronological score and prevalence by quartile:')
    print(pd.read_csv(source/'score_chronology.csv').groupby(['fold','quartile'])[['known','positive','mean_probability','prevalence']].mean().to_string())
    print('Mean waiting records:');print(delays[['policy','population','mean_wait_records']].to_string(index=False))
    print('Training exposure:');print(pd.DataFrame(train).to_string(index=False))
    print('Paired errors:');print(pd.DataFrame(contrasts).groupby(['run_id','policy'])[['positive_FIFO_only','positive_model_only','positive_both']].mean().to_string())
    print('GQ versus Q slot arithmetic:');print(slot_summary.to_string())
    print('Tie sensitivity:');print(tie_summary.to_string(index=False))

if __name__=='__main__':run()
