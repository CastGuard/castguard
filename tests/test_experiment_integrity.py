"""Counterexamples for silent denominator loss, hold decisions and selection leakage."""
import numpy as np
import pandas as pd
import pytest
from oct03_research import gate_statistics, inspection_mask, inspection_metrics, q1_decision, constrained_threshold, choose_q1_family,choose_gate_family
from oct03_queue import stream_queue, measure
from experiment_integrity import missing_quality_contrast_bounds


def gate():
    timeline=pd.DataFrame({'row_id':['n0','n1','w0','w1'],'run_id':[0,0,0,0],
        'Shot':[1,2,3,4],'Machine_Status':[0,0,1,1],
        'episode_id':[None,None,'warm','warm'],'gate_eligible':[True]*4})
    scores=pd.DataFrame({'row_id':timeline.row_id,'probability':[.9,.1,.8,.8]})
    return timeline,scores


def stream():
    return pd.DataFrame({'row_id':['r'+str(i) for i in range(10)],'run_id':0,'source_row':range(10),
        'Shot':range(10),'process_complete':True,'gate_probability':.1,
        'quality_probability':np.arange(10)/10,'ood_score':0.})


@pytest.mark.parametrize('value',[np.nan,np.inf,-np.inf])
def test_corrupt_gate_score_cannot_remove_a_false_alarm_from_denominator(value):
    timeline,scores=gate();scores.loc[0,'probability']=value
    with pytest.raises(ValueError):gate_statistics(timeline,scores,.5)


def test_missing_state_row_cannot_raise_quality_capture_from_half_to_one():
    inputs=stream();actions=stream_queue(inputs,'Q',None,True,None,.2)
    truth=inputs[['row_id','run_id','Shot','source_row']].assign(Machine_Status=0,episode_id=None)
    quality=inputs[['run_id','Shot']].assign(y_defect=[0,0,0,0,1,0,0,0,1,0])
    correct,_,_=measure(actions,truth,quality,.2)
    assert correct['quality_capture']==.5
    with pytest.raises(ValueError):measure(actions,truth.drop(index=8),quality,.2)


@pytest.mark.parametrize('bad',[True,np.nan,np.inf,-.01,1.01])
def test_inspection_budget_has_a_numeric_finite_fraction_contract(bad):
    with pytest.raises(ValueError):inspection_mask(['a','b'],[.9,.1],bad)


def test_decimal_budget_does_not_lose_one_slot_to_binary_roundoff():
    # Mathematically floor(100 * 0.29) is 29, not the binary-float result 28.
    assert inspection_mask([str(i) for i in range(100)],np.arange(100),.29).sum()==29


@pytest.mark.parametrize('bad',[np.nan,-1,.5,2])
def test_quality_labels_cannot_silently_enter_capture_denominators(bad):
    frame=pd.DataFrame({'row_id':['a','b'],'probability':[.9,.1],'target':[1.,bad],'y_defect':[1,0]})
    with pytest.raises(ValueError):inspection_metrics(frame,'target',.5)


def test_q1_development_decision_rejects_test_metrics():
    comparison=pd.DataFrame({'scheme':['forward_run']*2,'fold':['2','6'],'budget':[.2]*2,
        'gain':[.1]*2,'capture':[.4]*2,'actual_budget':[.2]*2,'overall_gain':[.1]*2,'role':['test']*2})
    intervals=pd.DataFrame({'scheme':['forward_run']*2,'lower95':[.01]*2})
    with pytest.raises(ValueError):q1_decision(comparison,intervals,{'q1_min_forward_folds':2,'q1_min_gain':.05})


@pytest.mark.parametrize('change',['string_boolean','missing_gate','missing_ood','unknown_policy'])
def test_queue_cannot_silently_treat_invalid_inputs_as_normal(change):
    frame=stream();policy='GQ';domain=None
    if change=='string_boolean':frame['process_complete']='False'
    elif change=='missing_gate':frame.loc[0,'gate_probability']=np.nan
    elif change=='missing_ood':policy='OOD1';domain=1.;frame.loc[0,'ood_score']=np.nan
    else:policy='typo'
    with pytest.raises(ValueError):stream_queue(frame,policy,.8,False,domain,.2)


def test_measure_rejects_more_inspections_than_the_declared_budget():
    frame=stream();actions=stream_queue(frame,'Q',None,True,None,.5)
    truth=frame[['row_id','run_id','Shot','source_row']].assign(Machine_Status=0,episode_id=None)
    quality=frame[['run_id','Shot']].assign(y_defect=0)
    with pytest.raises(ValueError):measure(actions,truth,quality,.2)


def test_fpr_one_boundary_can_use_every_normal_row():
    timeline,scores=gate()
    threshold,disabled,reason=constrained_threshold(timeline,scores,1,min_episodes=1)
    assert not disabled and reason=='eligible'
    stats,_,_,_=gate_statistics(timeline,scores,threshold)
    assert stats['episodes_detected']==1 and stats['fpr']<=1


def test_quality_family_cannot_win_by_silently_losing_bad_seeds():
    frame=pd.DataFrame({'role':['validation']*3,'budget':[.2]*3,'model':['a','a','b'],
        'seed':[17,29,17],'capture':[.5,.5,.9],'average_precision':[.5,.5,.9]})
    with pytest.raises(ValueError):choose_q1_family(frame)


def test_gate_family_cannot_win_by_silently_losing_bad_seeds():
    rows=[{'role':'validation','model':m,'seed':seed,'episode_recall':recall,'mean_delay':1.,'threshold':.5}
          for m,seed,recall in [('a',17,.5),('a',29,.5),('b',17,.9)]]
    with pytest.raises(ValueError):choose_gate_family(rows)


def test_candidate_denominators_cannot_change_between_models():
    frame=pd.DataFrame({'role':['validation']*2,'budget':[.2]*2,'model':['a','b'],
        'seed':[17,17],'n':[100,10],'capture':[.5,.9],'average_precision':[.5,.9]})
    with pytest.raises(ValueError):choose_q1_family(frame)


def test_missing_quality_envelope_matches_exhaustive_shared_label_assignments():
    from itertools import product
    differences=np.array([-1.,-.25,.5,1.])
    values=[(.5+np.dot(labels,differences))/(3+sum(labels)) for labels in product([0,1],repeat=4)]
    result=missing_quality_contrast_bounds(3,.5,differences)
    assert result['lower']==pytest.approx(min(values))
    assert result['upper']==pytest.approx(max(values))


def test_without_missing_quality_the_envelope_reduces_to_observed_contrast():
    result=missing_quality_contrast_bounds(5,-1,[])
    assert result['lower']==result['upper']==-.2


def test_historical_replay_cannot_authorize_evaluation_with_changed_code(tmp_path,monkeypatch):
    import json
    from hashlib import sha256
    import oct03_research as research
    archived=tmp_path/'legacy/before_experiment_integrity/oct03_research.py'
    archived.parent.mkdir(parents=True);archived.write_bytes(b'EXPLICIT HISTORIC TEST FIXTURE')
    current=tmp_path/'oct03_research.py';current.write_bytes(b'CHANGED TEST FIXTURE')
    original={'hashes':{'oct03_research.py':sha256(archived.read_bytes()).hexdigest()},'environment':{}}
    out=tmp_path/'saved';out.mkdir()
    (out/'manifest.json').write_text(json.dumps({'identity':original,'outputs':{}}))
    (out/'selection.json').write_text('{"fixture": true}')
    monkeypatch.setattr(research,'environment',lambda:{})
    monkeypatch.setattr(research,'identity',lambda root:{'hashes':{'oct03_research.py':sha256(current.read_bytes()).hexdigest()},'environment':{}})
    with pytest.raises(ValueError):research.verify_development(tmp_path,out)
    assert research.verify_development(tmp_path,out,allow_historical=True)=={'fixture':True}
    archived.write_bytes(b'TAMPERED HISTORIC TEST FIXTURE')
    with pytest.raises(AssertionError):research.verify_development(tmp_path,out,allow_historical=True)


@pytest.mark.parametrize('case',['early_service','reused_slot','fabricated_wait'])
def test_evaluator_checks_prefix_capacity_and_timing_not_just_total(case):
    frame=stream();actions=stream_queue(frame,'Q',None,True,None,.2)
    truth=frame[['row_id','run_id','Shot','source_row']].assign(Machine_Status=0,episode_id=None)
    quality=frame[['run_id','Shot']].assign(y_defect=0)
    idx=actions.index[actions.inspected]
    if case=='early_service':actions.loc[idx[0],'service_step']=0
    elif case=='reused_slot':actions.loc[idx,'service_step']=9
    else:actions.loc[idx[0],'wait_records']=999
    with pytest.raises(ValueError):measure(actions,truth,quality,.2)


def test_worst_run_fpr_cannot_hide_a_run_with_no_normal_evidence():
    timeline,scores=gate()
    timeline=pd.concat([timeline,pd.DataFrame({'row_id':['other_warm'],'run_id':[1],'Shot':[1],
        'Machine_Status':[1],'episode_id':['other_episode'],'gate_eligible':[True]})],ignore_index=True)
    scores=pd.concat([scores,pd.DataFrame({'row_id':['other_warm'],'probability':[.9]})],ignore_index=True)
    result,_,_,_=gate_statistics(timeline,scores,.5)
    assert np.isnan(result['worst_run_fpr'])
