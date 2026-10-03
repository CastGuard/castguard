"""Read-only independent arithmetic and provenance checks for round7 diagnosis."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from castguard.data import read_inputs,digest
ROOT=Path(__file__).resolve().parent

def verify(root=ROOT):
    out=root/'reports/oct03_round7'
    for folder in [out,out/'explanation']:
        receipt=json.loads((folder/'receipt.json').read_text(encoding='utf-8'))
        for p,h in receipt['input_hashes'].items():assert digest(root/p)==h,p
        for p,h in receipt['output_hashes'].items():assert digest(folder/p)==h,p
    frame=pd.read_parquet(out/'paired_rows.parquet')
    frames,_,_=read_inputs(root)
    known=frames['q42'][['run_id','Shot','y_defect']]
    truth=frame[['fold','row_id','run_id','Shot','quality_known']].merge(known,on=['run_id','Shot'],how='left',validate='one_to_one')
    np.testing.assert_array_equal(frame.positive,truth.y_defect.eq(1))
    np.testing.assert_array_equal(frame.quality_known,truth.y_defect.notna())
    np.testing.assert_array_equal(frame.quality_available,frame.quality_known)
    policies=['FIFO','RECENT_PRODUCT_RATE','RANDOM','PROCESS_DEVIATION','Q','GQ']
    old=pd.read_parquet(root/'reports/oct03_queue/outer_actions.parquet')
    simple=pd.read_parquet(root/'reports/submission_round6/baselines_final/baseline_actions.parquet')
    for policy in policies:
        actions=old.loc[old.policy.eq(policy)&old.budget.eq(.2)] if policy in ['Q','GQ'] else simple.loc[simple.policy.eq(policy)]
        actions=actions.copy();actions['fold']=actions.fold.astype(str)
        # Derive inspection probabilities and hits directly from saved policy actions and source truth.
        grouped=actions.groupby(['fold','row_id']).inspected.mean()
        expected=frame.assign(fold=frame.fold.astype(str)).set_index(['fold','row_id']).index.map(grouped)
        np.testing.assert_allclose(frame[policy],expected,rtol=0,atol=1e-12)
    assert abs(float(frame.delta_Q.sum())+7.6)<1e-10
    assert abs(float(frame.delta_GQ.sum())+10.8)<1e-10
    assert frame.loc[frame.FIFO.eq(1)&frame.quality_known,'quartile'].eq(1).all()
    eq=pd.read_csv(out/'fifo_history_equivalence.csv')
    assert eq.score_unique_count.eq(1).all() and eq.inspection_disagreements.eq(0).all() and eq.service_time_disagreements.eq(0).all()
    audit=pd.read_csv(out/'replay_audit.csv')
    assert len(audit)==48 and audit.replay_exact.all() and audit.causal_service.all() and audit.same_quality_mask.all()
    slots=pd.read_csv(out/'paired_service_slots.csv')
    for policy in ['Q','GQ']:
        per_seed=slots.loc[slots.policy.eq(policy)].groupby('seed').paired_delta.sum()
        assert abs(per_seed.mean()-frame[f'delta_{policy}'].sum())<1e-10
    exposure=json.loads((out/'evaluation_exposure.json').read_text())
    assert exposure['prior_test_unique_rows']==exposure['eligible_q_rows']==4613
    assert len(exposure['not_in_saved_evaluation_rows'])==4 and not exposure['genuinely_untouched_evaluation_identified']
    uncertainty=pd.read_csv(out/'paired_uncertainty.csv')
    assert len(uncertainty)==8 and ((uncertainty.lower_pp<0)&(uncertainty.upper_pp>0)).all()
    return {'rows':len(frame),'positive':int(frame.positive.sum()),'replayed_policy_groups':len(audit),
      'history_FIFO_exact_equivalence':True,'paired_arithmetic_verified':True,'source_output_hashes_verified':True,
      'untouched_evaluation_identified':False,'new_training':False,'new_policy_promoted':False}

if __name__=='__main__':print(json.dumps(verify()))
