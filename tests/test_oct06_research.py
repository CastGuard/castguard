import numpy as np
import pandas as pd
import pytest
from castguard.oct06_research import delayed_feedback, event_frame, metrics


def sample():
    return pd.DataFrame({'row_id':['a','b','c','d','e'], 'run_id':[0,0,0,1,1],
        'event_order':[0,5,30,0,30], 'y_defect':[1,0,0,0,1], 'role':['train','validation','test','train','test']})


def test_feedback_uses_elapsed_process_events_and_never_current_future_or_other_run():
    f=sample(); before=delayed_feedback(f,20)
    assert before.loc[1,'fb_known_count']==0  # quality row shift would not capture event timing
    assert before.loc[2,'fb_known_count']==2
    assert before.loc[2,'fb_rate20']==.5
    assert before.loc[4,'fb_ewm']==0
    f.loc[2:,'y_defect']=1-f.loc[2:,'y_defect']
    after=delayed_feedback(f,20)
    pd.testing.assert_frame_equal(before.loc[:2],after.loc[:2])


def test_feedback_partition_returns_can_be_withheld():
    f=sample(); a=delayed_feedback(f,20,blocked_roles=('validation',))
    assert a.loc[2,'fb_known_count']==1
    assert a.loc[2,'fb_ewm']==1


def test_feedback_permutation_invariant_and_missing_not_negative():
    f=sample();a=delayed_feedback(f);b=delayed_feedback(f.iloc[::-1]).sort_index()
    pd.testing.assert_frame_equal(a,b)
    assert np.isnan(a.loc[0,'fb_rate20'])
    with pytest.raises(ValueError):delayed_feedback(f,0)


def test_metrics_topk_is_exact_and_threshold_fpr_has_normal_denominator():
    x=metrics([0,1,0,1,0],[.1,.9,.8,.2,.0],.8,list('abcde'))
    assert x['caught20']==1 and x['capture20']==.5
    assert x['fpr']==1/3 and x['inspect20']==1 and x['fp']==1


def test_event_map_rejects_duplicate_quality_event():
    m=pd.DataFrame({'run_id':[0,0,0],'source_row':[1,2,3]})
    q=pd.DataFrame({'run_id':[0,0],'source_row_m41':[1,3]})
    assert event_frame(q,m).event_order.tolist()==[0,2]
    with pytest.raises(ValueError):event_frame(pd.concat([q,q.iloc[:1]]),m)
