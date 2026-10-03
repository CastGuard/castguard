from itertools import product
import numpy as np
import pandas as pd
import pytest
from audit_queue_opportunity import INPUTS,reference_queue
from oct03_queue import stream_queue,measure,choose_policy


def inputs(pattern):
    return pd.DataFrame([dict(row_id='r'+str(i),source_row=i,run_id=0,Shot=i+1,
        process_complete=kind!='hold',quality_probability=.6 if kind=='quality' else np.nan,
        gate_probability=.9 if kind=='gate' else .1,ood_score=2. if kind=='domain' else 0.)
        for i,kind in enumerate(pattern)])


def test_exhaustive_small_queues_match_independent_reference():
    for pattern in product(['none','quality','gate','hold'],repeat=4):
        frame=inputs(pattern)
        for policy,budget in [('Q',.5),('GQ',.5),('OOD1',1.)]:
            actual=stream_queue(frame,policy,.8,False,1.,budget)
            expected,_=reference_queue(frame,policy,budget,.8,False,1.)
            pd.testing.assert_frame_equal(actual[expected.columns],expected,check_dtype=False)


@pytest.mark.parametrize('first,length,expected',[(4,5,[4]),(5,9,[]),(5,10,[9]),(0,4,[])])
def test_boundary_arrival_and_terminal_rules(first,length,expected):
    frame=inputs(['none']*length)
    if first<length:frame.loc[first,'quality_probability']=.5
    actual=stream_queue(frame,'Q',None,True,None,.2)
    assert actual.loc[actual.inspected,'service_step'].tolist()==expected


def test_new_hold_preempts_waiting_gate_and_quality_on_the_same_arrival_slot():
    frame=inputs(['quality','gate','none','none','hold'])
    actual=stream_queue(frame,'GQ',.8,False,None,.2)
    assert actual.loc[actual.inspected,'row_id'].tolist()==['r4']


def test_exact_gate_threshold_and_ood_hold_precedence():
    frame=inputs(['gate','gate','domain','quality','none'])
    frame.loc[0,'gate_probability']=np.nextafter(.8,0)
    frame.loc[1,'gate_probability']=.8
    frame.loc[2,['gate_probability','ood_score']]=[.99,1.]
    actual=stream_queue(frame,'OOD1',.8,False,1.,.2)
    assert actual.reason.tolist()==['none','gate','hold','quality','none']
    assert actual.loc[actual.inspected,'row_id'].tolist()==['r2']


def test_ties_use_arrival_and_reordering_input_storage_does_not_change_services():
    frame=inputs(['quality']*10)
    actual=stream_queue(frame.sample(frac=1,random_state=3),'Q',None,True,None,.2)
    assert actual.loc[actual.inspected,'row_id'].tolist()==['r0','r1']
    expected,_=reference_queue(frame,'Q',.2)
    pd.testing.assert_frame_equal(actual[expected.columns],expected,check_dtype=False)


def test_decimal_budget_and_final_pending_are_not_flushed():
    frame=inputs(['quality']*100)
    actual=stream_queue(frame,'Q',None,True,None,.29)
    reference,events=reference_queue(frame,'Q',.29)
    assert actual.inspected.sum()==29 and events.pending_after_service.iloc[-1]==71
    pd.testing.assert_frame_equal(actual[reference.columns],reference,check_dtype=False)


def test_reference_rejects_ground_truth_in_the_observation_surface():
    with pytest.raises(ValueError):reference_queue(inputs(['quality']*5).assign(y_defect=1),'Q',.2)


def test_evaluation_cannot_swap_shot_keys_to_turn_half_capture_into_full_capture():
    frame=inputs(['quality']*10)
    actions=stream_queue(frame,'Q',None,True,None,.2)
    truth=frame[['row_id','run_id','Shot','source_row']].assign(Machine_Status=0,episode_id=None)
    quality=frame[['run_id','Shot']].assign(y_defect=[1,0,0,0,0,0,0,1,0,0])
    correct,_,_=measure(actions,truth,quality,.2);assert correct['quality_capture']==.5
    # Each action key remains unique, every service opportunity/time is valid,
    # but row r1 is now associated with another Shot's positive outcome.
    actions.loc[[1,7],'Shot']=actions.loc[[7,1],'Shot'].to_numpy()
    actions['wait_shots']=actions.service_shot-actions.Shot
    with pytest.raises(ValueError,match='identity'):measure(actions,truth,quality,.2)


def candidates():
    return pd.DataFrame([dict(stage='inner_calibration',fold='4',seed=seed,budget=.2,policy=policy,
        quality_capture=capture,hold_backlog=0,episodes_inspection_reached=2,hold_requested=0,
        n_total=100,quality_known=90,quality_positive=20,normal_total=85)
        for policy,captures in [('GQ',[.3,.3]),('OOD1',[.7,0.]),('OOD05',[.4,.4])]
        for seed,capture in zip([17,29],captures)])


def test_a_dropped_bad_seed_cannot_change_the_selected_queue_policy():
    complete=candidates();assert choose_policy(complete)=='OOD05'
    partial=complete.loc[~(complete.policy.eq('OOD1')&complete.seed.eq(29))]
    with pytest.raises(ValueError):choose_policy(partial)


@pytest.mark.parametrize('corruption',['missing_policy','different_population','nonfinite_capture','mixed_fold'])
def test_queue_policy_selection_needs_a_complete_comparable_calibration(corruption):
    frame=candidates()
    if corruption=='missing_policy':frame=frame.loc[frame.policy.ne('OOD05')]
    elif corruption=='different_population':frame.loc[frame.policy.eq('OOD1'),'n_total']=10
    elif corruption=='nonfinite_capture':frame.loc[0,'quality_capture']=np.nan
    else:frame.loc[0,'fold']='2'
    with pytest.raises(ValueError):choose_policy(frame)
