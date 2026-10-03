"""Reconcile saved baseline actions independently of the score-generation loop."""
from pathlib import Path
import json
import pandas as pd
import numpy as np
from castguard.data import read_inputs,digest
ROOT=Path(__file__).resolve().parent

def verify(root=ROOT):
    out=root/'reports/submission_round6/baselines_final'
    receipt=json.loads((out/'receipt.json').read_text())
    for name,expected in receipt['input_hashes'].items():assert digest(root/name)==expected,name
    for name,expected in receipt['output_hashes'].items():assert digest(out/name)==expected,name
    frames,_,_=read_inputs(root)
    truth=frames['m41'][['row_id','run_id','Shot','source_row','Machine_Status']].merge(frames['q42'][['run_id','Shot','y_defect']],on=['run_id','Shot'],how='left',validate='one_to_one')
    actions=pd.read_parquet(out/'baseline_actions.parquet').merge(truth,on='row_id',validate='many_to_one')
    metrics=pd.read_csv(out/'baseline_metrics.csv',dtype={'fold':str}).set_index(['fold','policy','seed'])
    for key,rows in actions.groupby(['fold','policy','seed']):
        rows=rows.sort_values(['source_row','row_id']).reset_index(drop=True);m=metrics.loc[key]
        assert m.quality_positive==rows.y_defect.eq(1).sum()
        assert m.quality_captured==(rows.inspected&rows.y_defect.eq(1)).sum()
        assert m.inspected==rows.inspected.sum()
        assert m.hold_backlog==(rows.hold&~rows.inspected).sum()
        served=rows.loc[rows.inspected]
        assert served.service_step.ge(served.index).all() and not served.service_step.duplicated().any()
        assert np.all(np.bincount(served.service_step,minlength=len(rows)).cumsum()<=np.floor(np.arange(1,len(rows)+1)*.2+1e-12))
    summary=pd.read_csv(out/'baseline_summary.csv').set_index('policy')
    assert len(metrics)==412 and len(actions)==349685
    assert summary.loc['FIFO','hits']==113 and summary.loc['RECENT_PRODUCT_RATE','hits']==113
    assert summary.Q_gain_pp.loc['FIFO']<0 and summary.Q_gain_pp.loc['RANDOM']>0
    return {'metric_groups':len(metrics),'action_rows':len(actions),'same_population_and_prefix_capacity':True,
      'source_and_output_hashes':True,'training_runs':0,'policy_promotion':False,'scope':'seen development only'}

if __name__=='__main__':print(json.dumps(verify()))
