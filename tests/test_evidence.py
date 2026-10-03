import json
from pathlib import Path

import numpy as np
import pandas as pd

from castguard.data import read_inputs
from castguard.rebuild import add_history, rebuild_check
from castguard.report import gate_evidence, paired_block_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_matches_every_handoff_value_and_fold(tmp_path):
    rebuild_check(ROOT, tmp_path)
    result = json.loads((tmp_path / "rebuild_verification.json").read_text())
    assert all(row["all_values_equal"] for row in result["checks"])


def test_history_ignores_current_and_future_values_and_resets_at_run():
    frame = pd.DataFrame({"run_id": [0, 0, 0, 1, 1], "Shot": [1, 2, 3, 1, 2], "Cycle_Time": [10., 20., 30., 40., 50.], "Machine_Status": [0, 1, 0, 0, 1]})
    original = add_history(frame, ["Cycle_Time"])
    changed = frame.copy()
    changed.loc[2, "Cycle_Time"] = 1e6
    changed.loc[2, "Machine_Status"] = 1
    new = add_history(changed, ["Cycle_Time"])
    cols = ["prev_cycle_time", "max_cycle_previous_5", "missing_process_previous_20", "oracle_prior_episodes", "oracle_shots_since_warm"]
    pd.testing.assert_frame_equal(original.loc[:2, cols], new.loc[:2, cols])
    assert np.isnan(original.loc[3, "prev_cycle_time"])
    assert original.loc[3, "oracle_prior_episodes"] == 0


def test_bootstrap_is_paired_and_preserves_identical_predictions():
    result = paired_block_bootstrap([0, 1, 0, 1], [.1, .9, .3, .7], [.1, .9, .3, .7], [0, 0, 1, 1], 20, 17)
    assert all(x["estimate"] == x["lower_95"] == x["upper_95"] == 0 for x in result)


def test_gate_denominators_preserve_unobservable_episode():
    frames, folds, _ = read_inputs(ROOT)
    m = frames["m41"]
    assignments = folds.loc[(folds.dataset == "m41") & (folds.scheme == "run_holdout") & (folds.role == "test")]
    pred = assignments[["row_id", "scheme", "fold"]].copy()
    pred["dataset"], pred["experiment"], pred["role"] = "m41", "Gate", "test"
    pred["seed"], pred["model"], pred["probability"], pred["prediction"] = 17, "fixture", .1, False
    pred["y"] = pred.row_id.map(m.set_index("row_id").Machine_Status)
    q_assignments = folds.loc[(folds.dataset == "q42") & (folds.scheme == "run_holdout") & (folds.role == "test")]
    quality = q_assignments[["row_id", "scheme", "fold"]].copy()
    quality["dataset"], quality["experiment"], quality["role"] = "q42", "A", "test"
    quality["seed"], quality["model"], quality["probability"], quality["prediction"] = 17, "fixture", .1, False
    quality["y"] = quality.row_id.map(frames["q42"].set_index("row_id").y_defect)
    gate, episodes, workflow = gate_evidence(pd.concat([pred, quality]), frames, folds)
    assert gate.episodes_total.sum() == 21
    assert gate.episodes_observable.sum() == 20
    assert gate.episodes_detected.sum() == 0
    assert gate.warm_observable.sum() == 104
    assert gate.warm_total.sum() == 118
    assert (episodes.status == "unobservable_held").sum() == 1
    assert workflow.quality_test_n.sum() == 4613
