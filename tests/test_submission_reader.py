import copy
import pytest
from castguard.submission_reader import features_from_packet, FB, PROCESS


def base():
    return {'record_id':'x','run_key':'a','event_order':30,'shot':31,'product_type':1,
            'measurements':{k:1. for k in PROCESS},'quality_feedback':[{'run_key':'a','event_order':0,'available_event':20,'defect':1}],
            'feedback_ledger_complete':True}


@pytest.mark.parametrize('change',[{'y_defect':1},{'Machine_Status':0},{'shot_position':30}])
def test_forbidden_current_fields(change):
    r=base();r.update(change)
    with pytest.raises(ValueError):features_from_packet(r,PROCESS+FB)


@pytest.mark.parametrize('event,arrival,run',[(30,50,'a'),(29,49,'a'),(0,19,'a'),(0,20,'b'),(0,31,'a')])
def test_future_early_cross_run_and_not_yet_received_labels_rejected(event,arrival,run):
    r=base();r['quality_feedback'][0].update(event_order=event,available_event=arrival,run_key=run)
    with pytest.raises(ValueError):features_from_packet(r,PROCESS+FB)


def test_received_past_feedback_and_duplicate_guard():
    r=base();v,_=features_from_packet(r,PROCESS+FB)
    assert v['fb_rate20']==1 and v['fb_known_count']==1
    r['quality_feedback'].append(copy.deepcopy(r['quality_feedback'][0]))
    with pytest.raises(ValueError):features_from_packet(r,PROCESS+FB)


def test_unverified_ledger_not_silently_imputed():
    r=base();r.pop('feedback_ledger_complete')
    with pytest.raises(ValueError):features_from_packet(r,PROCESS+FB)
