import numpy as np
import pandas as pd
import pytest

from oct03_research import (inspection_mask, inspection_metrics, constrained_threshold,
    gate_statistics, choose_q1_family, choose_gate_family, train_rule, sample_support,
    q1_decision, timeline_partition, selected_baseline)


def gate_fixture():
    # An early unavailable warm shot must count in the episode's delay.
    timeline = pd.DataFrame({"row_id": [f"r{i}" for i in range(204)],
        "run_id": [0] * 102 + [1] * 102,
        "Shot": list(range(102)) + list(range(102)),
        "Machine_Status": [1, 1] + [0] * 100 + [1, 1] + [0] * 100,
        "episode_id": ["e0", "e0"] + [None] * 100 + ["e1", "e1"] + [None] * 100,
        "gate_eligible": [False] + [True] * 203})
    scores = timeline.loc[timeline.gate_eligible, ["row_id"]].copy()
    scores["probability"] = .1
    scores.loc[scores.row_id.isin(["r1", "r102", "r103"]), "probability"] = [.9, .8, .7]
    return timeline, scores


def test_inspection_budget_and_tie_are_stable_under_row_order():
    ids = np.array(["c", "a", "b", "d", "e"])
    probability = np.array([.5, .5, .5, .1, 0])
    assert list(ids[inspection_mask(ids, probability, .4)]) == ["a", "b"]
    order = np.array([4, 3, 2, 1, 0])
    assert set(ids[order][inspection_mask(ids[order], probability[order], .4)]) == {"a", "b"}
    assert inspection_mask(ids, probability, .19).sum() == 0
    with pytest.raises(ValueError):
        inspection_mask(["a", "a"], [.5, .2], .5)


def test_same_budget_reports_target_and_overall_harm():
    frame = pd.DataFrame({"row_id": ["a", "b", "c", "d"], "probability": [.9, .8, .3, .1],
                          "y_type_Short_Shot": [1, 0, 0, 0], "y_defect": [1, 0, 1, 1]})
    result = inspection_metrics(frame, "y_type_Short_Shot", .5)
    assert result["inspected"] == 2 and result["capture"] == 1
    assert result["overall_capture"] == pytest.approx(1 / 3)


def test_gate_threshold_respects_each_run_and_missing_episode_start():
    timeline, scores = gate_fixture()
    threshold, disabled, _ = constrained_threshold(timeline, scores, .02)
    assert not disabled and threshold == .8
    result, episodes, runs, _ = gate_statistics(timeline, scores, threshold)
    assert result["episodes_detected"] == 2 and result["held"] == 1
    assert episodes[0]["delay_shots"] == 1
    assert max(r["fpr"] for r in runs) <= .02


def test_gate_fully_unobservable_episode_keeps_total_denominator():
    timeline, scores = gate_fixture()
    timeline.loc[timeline.row_id.isin(["r102", "r103"]), "gate_eligible"] = False
    scores = scores.loc[~scores.row_id.isin(["r102", "r103"])]
    result, _, _, _ = gate_statistics(timeline, scores, .5)
    assert result["episodes_total"] == 2 and result["episodes_observable"] == 1
    assert result["held"] == 3
    threshold, disabled, reason = constrained_threshold(timeline, scores, .02)
    assert disabled and threshold is None and reason == "insufficient_validation_episodes"


def test_gate_no_signal_is_explicit_no_alarm_even_with_extreme_future_score():
    timeline, scores = gate_fixture()
    scores["probability"] = .5
    threshold, disabled, reason = constrained_threshold(timeline, scores, .02)
    assert disabled and reason == "no_detection_under_constraint"
    scores["probability"] = 1e6
    result, _, _, _ = gate_statistics(timeline, scores, threshold, disabled)
    assert result["false_alarms"] == result["episodes_detected"] == 0


def test_model_selection_rejects_test_rows_and_uses_registered_tiebreak():
    frame = pd.DataFrame({"role": ["validation"] * 2, "budget": [.2, .2], "model": ["b", "a"],
                          "capture": [.5, .5], "average_precision": [.3, .4]})
    assert choose_q1_family(frame) == "a"
    frame.loc[0, "role"] = "test"
    with pytest.raises(ValueError):
        choose_q1_family(frame)
    with pytest.raises(ValueError):
        choose_gate_family([{"role": "test"}])


def test_rule_uses_train_labels_and_fixed_feature_tie_order():
    train = pd.DataFrame({"Machine_Status": [0, 0, 1, 1], "b": [1, 2, 3, 4], "a": [1, 2, 3, 4]})
    rule = train_rule(train, ["b", "a"])
    assert rule == {"feature": "a", "direction": 1, "train_auc": 1.0}


def test_q1_requires_forward_support_and_every_forward_nonnegative():
    comparison = pd.DataFrame({"scheme": ["forward_run", "forward_run"], "fold": ["2", "6"],
        "budget": [.2, .2], "gain": [.3, -.01], "capture": [.7, .4],
        "actual_budget": [.2, .2], "overall_gain": [.1, 0], "role": ["validation"]*2})
    intervals = pd.DataFrame({"scheme": ["forward_run"] * 2, "lower95": [.1, -.1]})
    cfg = {"q1_min_forward_folds": 2, "q1_min_gain": .05}
    decision, _ = q1_decision(comparison, intervals, cfg)
    assert not decision["test_allowed"]
    comparison.loc[1, "gain"] = .05
    decision, _ = q1_decision(comparison, intervals, cfg)
    assert decision["test_allowed"] and decision["status"] == "partial_evidence"


def test_gate_threshold_with_per_run_constraint_stricter_than_pooled():
    timeline, scores = gate_fixture()
    # Three false alarms in run0 would be 1.5% pooled, but 3% in that run.
    scores.loc[scores.row_id.isin(["r10", "r11", "r12"]), "probability"] = .85
    threshold, disabled, _ = constrained_threshold(timeline, scores, .02)
    assert not disabled and threshold > .85
    result, _, runs, _ = gate_statistics(timeline, scores, threshold)
    assert result["episodes_detected"] == 1 and all(r["fpr"] <= .02 for r in runs)


def test_baseline_selection_is_scalar_with_other_populations_present():
    table = pd.DataFrame({"dataset": ["q42", "p40", "p40"], "population": ["all", "all", "normal_pressure"],
        "scheme": ["forward_run", "chronological", "chronological"], "fold": ["2", "primary", "primary"],
        "model": ["logistic", "lightgbm", "random_forest"], "selected": True})
    assert selected_baseline(table, "q42", "forward_run", "2") == "logistic"
    with pytest.raises(ValueError):
        selected_baseline(pd.concat([table, table.iloc[[0]]]), "q42", "forward_run", "2")
