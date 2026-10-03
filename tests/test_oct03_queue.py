import numpy as np
import pandas as pd
import pytest

from oct03_queue import stream_queue, measure, nested_parts, choose_policy, fit_ood, ood_scores, ood_threshold


def scores(n=10):
    return pd.DataFrame({"row_id": [f"r{i}" for i in range(n)], "source_row": range(n), "run_id": 0,
        "Shot": np.arange(1,n+1), "process_complete": True, "gate_probability": .1,
        "quality_probability": np.linspace(.1,.9,n), "ood_score": 0.0})


def test_queue_never_uses_future_scores_and_respects_prefix_capacity():
    original = scores()
    prefix = stream_queue(original.iloc[:5], "GQ", .8, False, None, .2)
    changed = original.copy()
    changed.loc[5:, "quality_probability"] = 1000
    full = stream_queue(changed, "GQ", .8, False, None, .2)
    assert prefix.loc[prefix.inspected, "row_id"].tolist() == full.loc[full.service_step.between(0,4), "row_id"].tolist()
    for i in range(1,11):
        assert int(full.service_step.between(0,i-1).sum()) <= int(np.floor(i*.2+1e-12))
    assert full.inspected.sum() == 2


def test_all_held_cannot_hide_normal_workload_or_unserved_backlog():
    frame = scores()
    frame["ood_score"] = 100
    actions = stream_queue(frame, "OOD1", .8, False, 1, .2)
    truth = frame[["row_id","run_id","Shot","source_row"]].assign(Machine_Status=0, episode_id=None)
    quality = frame[["run_id", "Shot"]].assign(y_defect=0)
    metrics, _, _ = measure(actions, truth, quality, .2)
    assert metrics["auto_fpr_all_normal"] == 0
    assert metrics["normal_intervention_rate"] == 1
    assert metrics["coverage"] == 0 and metrics["hold_rate"] == 1
    assert metrics["hold_backlog"] == 8 and metrics["inspected"] == 2


def test_state_or_quality_labels_are_not_queue_inputs():
    frame = scores()
    before = stream_queue(frame, "GQ", .05, False, None, .2)
    frame["Machine_Status"], frame["y_defect"] = 1, 1
    after = stream_queue(frame, "GQ", .05, False, None, .2)
    pd.testing.assert_frame_equal(before[["inspected", "hold", "alarm", "service_step"]],
                                  after[["inspected", "hold", "alarm", "service_step"]])


def test_missing_input_episode_stays_in_all_denominators():
    frame = scores()
    frame.loc[0:1, "process_complete"] = False
    actions = stream_queue(frame, "GQ", .8, False, None, .1)
    truth = frame[["row_id","run_id","Shot","source_row"]].assign(Machine_Status=[1,1]+[0]*8, episode_id=["e","e"]+[None]*8)
    quality = frame.loc[2:, ["run_id", "Shot"]].assign(y_defect=0)
    metrics, _, ep = measure(actions, truth, quality, .1)
    assert metrics["episodes_total"] == 1 and metrics["episodes_observable"] == 0
    assert metrics["warm_total"] == 2 and metrics["hold_backlog"] == 1
    assert ep[0]["inspection_reached"] and not ep[0]["auto_detected"]
    assert ep[0]["inspection_delay_records"] == 9


def test_single_run_split_never_cuts_warm_episode():
    q = pd.DataFrame({"row_id": [f"q{i}" for i in range(10)], "run_id": 0, "source_row": range(10), "Shot": range(1,11)})
    m = q.copy()
    m["row_id"] = [f"m{i}" for i in range(10)]
    m["episode_id"] = [None]*6 + ["e","e"] + [None]*2
    fitq, calq, fitm, calm, boundary = nested_parts(q,m,.7)
    assert boundary["last_fit_shot"] == 6
    assert fitm.episode_id.notna().sum() == 0 and calm.episode_id.notna().sum() == 2


def test_multi_run_split_uses_last_train_run_only_for_calibration():
    q = pd.DataFrame({"row_id": [f"q{i}" for i in range(12)], "run_id": [0]*4+[1]*4+[2]*4,
        "source_row": range(12), "Shot": list(range(4))*3})
    m = q.assign(episode_id=None)
    fitq, calq, fitm, calm, boundary = nested_parts(q,m,.7)
    assert set(fitq.run_id) == {0,1} and set(calq.run_id) == {2}


def test_ood_detector_is_fixed_and_calibration_ties_obey_hold_allowance():
    train = pd.DataFrame({"Machine_Status": 0, "x": np.arange(100,dtype=float), "constant": 3.})
    detector = fit_ood(train,["x","constant"],[.01,.99])
    scored = ood_scores(train,detector)
    threshold = ood_threshold(train,scored,.01)
    assert (scored >= threshold).sum() <= 1
    assert ood_scores(pd.DataFrame({"x":[1000.],"constant":[3.]}),detector)[0] > threshold
    assert np.isnan(ood_scores(pd.DataFrame({"x":[np.nan],"constant":[3.]}),detector)[0])


def test_policy_selection_rejects_outer_outcomes_and_hides_no_backlog():
    metrics = pd.DataFrame({"stage": "inner_calibration", "budget": .2, "policy": ["GQ","OOD1","OOD05"],
        "quality_capture": [.3,.8,.5], "hold_backlog": [0,5,0], "episodes_inspection_reached": [2,2,2],
        "hold_requested": [0,10,1]})
    assert choose_policy(metrics) == "OOD05"
    metrics["stage"] = "outer_development"
    with pytest.raises(ValueError):
        choose_policy(metrics)


def test_unused_capacity_is_not_banked_for_future_bursts():
    frame = scores()
    frame.loc[:4,"quality_probability"] = np.nan
    result = stream_queue(frame,"Q",None,True,None,.2)
    assert result.inspected.sum() == 1
    assert result.loc[result.inspected,"service_step"].tolist() == [9]
