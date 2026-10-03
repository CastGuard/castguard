import numpy as np
import pandas as pd
import pytest
from diagnose_round7 import independent_queue,paired_interval
from oct03_queue import stream_queue

def observations(probabilities):
    n=len(probabilities)
    return pd.DataFrame({'row_id':[f'r{i}' for i in range(n)],'source_row':np.arange(n),'run_id':0,'Shot':np.arange(n),
       'process_complete':True,'gate_probability':0.,'quality_probability':probabilities,'ood_score':0.})

def test_queue_priority_and_no_future_inspection():
    scores=observations([.1,.9,.8,.7,1.])
    scores.loc[0,'process_complete']=False
    scores.loc[2,'gate_probability']=.95
    action,_=independent_queue(scores,'GQ',.9,False,.5)
    # Service at arrivals 1 and 3: missing-input hold first, then eligible gate.
    assert action.service_step.tolist()==[1,-1,3,-1,-1]
    native=stream_queue(scores,'GQ',.9,False,np.inf,.5)
    np.testing.assert_array_equal(action.service_step,native.service_step)

def test_equal_scores_make_recent_rate_and_fifo_identical():
    zero=observations([0.]*10);constant=observations([.37]*10)
    first,_=independent_queue(zero)
    second,_=independent_queue(constant)
    assert first.service_step.tolist()==[4,9,-1,-1,-1,-1,-1,-1,-1,-1]
    np.testing.assert_array_equal(first.service_step,second.service_step)
    last,_=independent_queue(constant,tie='lifo')
    assert last.service_step.tolist()==[-1,-1,-1,-1,4,-1,-1,-1,-1,9]

def test_queue_rejects_evaluation_labels():
    with pytest.raises(ValueError,match='Outcome'):
        independent_queue(observations([.1,.2]).assign(y_defect=[0,1]))

def test_future_suffix_cannot_change_completed_services():
    full=observations(np.linspace(0,1,20))
    full.loc[3,'process_complete']=False
    before,_=independent_queue(full.iloc[:10])
    full.loc[10:,'quality_probability']=1000.
    after,_=independent_queue(full)
    np.testing.assert_array_equal(before.service_step.where(before.service_step.lt(10),-1),
        after.service_step.iloc[:10].where(after.service_step.iloc[:10].lt(10),-1))

def test_paired_bootstrap_preserves_zero_difference_and_denominator():
    frame=pd.DataFrame({'run_id':np.repeat([1,2,3,4],5),'arrival_step':list(range(5))*4,
                        'positive':[1,0,0,0,0]*4,'delta_Q':0.})
    intervals=paired_interval(frame,'Q',lengths=[2],repetitions=100)
    assert intervals[0]['replicates']==256
    assert all(x['point_pp']==x['lower_pp']==x['upper_pp']==0 for x in intervals)
    frame['delta_Q']=frame.positive*.5
    intervals=paired_interval(frame,'Q',lengths=[2],repetitions=100)
    assert all(x['point_pp']==x['lower_pp']==x['upper_pp']==50 for x in intervals)

def test_removing_quality_presence_mask_retains_unknown_rows():
    scores=observations([np.nan,0.,0.,0.,0.])
    masked,_=independent_queue(scores)
    unmasked,_=independent_queue(scores,full_availability=True)
    assert masked.loc[1,'inspected'] and unmasked.loc[0,'inspected']
    assert masked.inspected.sum()==unmasked.inspected.sum()==1
