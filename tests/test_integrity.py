import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from castguard import experiment
from castguard.experiment import IDENTITY, make_tasks, quality_recommendations, select_history, select_models, task_name
from castguard.metrics import choose_threshold, score
from castguard.report import history_decision
from castguard.storage import CACHE_FILES, cache_valid, seal_cache, tracked_stage, write_json
from castguard.verify import verify_evidence, verify_matrix, verify_provenance


@pytest.fixture
def small_run(tmp_path, monkeypatch):
    config = {"seeds": [17, 29], "models": {"logistic": {}},
              "quality_experiments": {"A0": "q42_A0", "A": "q42_A", "B": "q42_B"},
              "b_min_ap_gain": .02, "b_seed_sd_multiplier": 2, "gate_max_validation_fpr": .02}
    frame = pd.DataFrame({"row_id": list("abcdefg"), "y_defect": [0, 1, 0, 1, 0, 1, 0]})
    folds = pd.DataFrame({"dataset": "q42", "scheme": "within_run", "fold": "primary",
                          "row_id": frame.row_id, "role": ["train", "train", "validation", "validation", "test", "test", "excluded"]})
    metrics, predictions = [], []
    for task in make_tasks(folds, config):
        for role in ["validation", "test"]:
            ids = list("cd") if role == "validation" else list("ef")
            # B clearly improves validation; no redesign is required in this fixture.
            p = [.8, .2] if task["experiment"] == "A" else [.2, .8]
            metrics.append({**task, "role": role, "threshold": .5, "train_n": 2, "train_positive": 1, **score([0, 1], p)})
            predictions.extend([{**task, "role": role, "row_id": rid, "y": y, "probability": prob,
                                 "threshold": .5, "prediction": prob >= .5} for rid, y, prob in zip(ids, [0, 1], p)])
    metrics, predictions = pd.DataFrame(metrics), pd.DataFrame(predictions)
    selection = select_models(metrics)
    history, _ = select_history(metrics, selection, config)
    for name in ["metrics.csv", "selected_metrics.csv"]:
        metrics.to_csv(tmp_path / name, index=False)
    selection.to_csv(tmp_path / "model_selection.csv", index=False)
    predictions.to_parquet(tmp_path / "predictions.parquet", index=False)
    write_json(tmp_path / "history_selection.json", history)
    write_json(tmp_path / "provenance.json", {"config": config})
    monkeypatch.setattr("castguard.verify.read_inputs", lambda root: ({"q42": frame}, folds, {}))
    return tmp_path, metrics, predictions, selection, folds, config


def test_integrity_accepts_complete_fixture(small_run):
    folder, *_ = small_run
    assert verify_evidence(folder, folder)["complete_experiment_matrix_and_populations"]


def test_whole_seed_omission_is_rejected(small_run):
    _, metrics, _, selection, folds, config = small_run
    with pytest.raises(ValueError, match="experiment matrix"):
        verify_matrix(metrics.loc[metrics.seed != 29], selection, folds, config)


def test_whole_selected_group_omission_is_rejected(small_run):
    folder, metrics, predictions, *_ = small_run
    keep = ~((metrics.experiment == "A0") & (metrics.seed == 17) & (metrics.role == "test"))
    metrics.loc[keep].to_csv(folder / "selected_metrics.csv", index=False)
    predictions.loc[~((predictions.experiment == "A0") & (predictions.seed == 17) & (predictions.role == "test"))].to_parquet(folder / "predictions.parquet", index=False)
    with pytest.raises(ValueError, match="selected metrics"):
        verify_evidence(folder, folder)


def test_single_evaluation_row_omission_is_rejected(small_run):
    folder, _, predictions, *_ = small_run
    predictions.iloc[1:].to_parquet(folder / "predictions.parquet", index=False)
    with pytest.raises(ValueError, match="evaluation rows"):
        verify_evidence(folder, folder)


def test_excluded_row_substitution_is_rejected(small_run):
    folder, _, predictions, *_ = small_run
    predictions.loc[0, "row_id"] = "g"
    predictions.to_parquet(folder / "predictions.parquet", index=False)
    with pytest.raises(ValueError, match="evaluation rows"):
        verify_evidence(folder, folder)


def test_forged_selection_is_rejected(small_run):
    _, metrics, _, selection, folds, config = small_run
    selection["selected"] = False
    with pytest.raises(AssertionError):
        verify_matrix(metrics, selection, folds, config)


@pytest.mark.parametrize("name", CACHE_FILES)
def test_cache_checks_every_artifact(tmp_path, name):
    task = {"seed": 17}
    for filename in CACHE_FILES:
        (tmp_path / filename).write_bytes(b"original fixture content")
    seal_cache(tmp_path, {"task": task})
    assert cache_valid(tmp_path, task)
    (tmp_path / name).write_bytes(b"damaged")
    assert not cache_valid(tmp_path, task)
    (tmp_path / name).unlink()
    assert not cache_valid(tmp_path, task)


def test_cache_marker_alone_is_insufficient(tmp_path):
    write_json(tmp_path / "complete.json", {"task": {"seed": 17}})
    assert not cache_valid(tmp_path, {"seed": 17})


def test_failed_refresh_cannot_remain_complete(tmp_path):
    write_json(tmp_path / "run_status.json", {"status": "complete", "decision": "old"})
    with pytest.raises(RuntimeError):
        with tracked_stage(tmp_path, "summarizing"):
            raise RuntimeError("fixture failure")
    state = json.loads((tmp_path / "run_status.json").read_text())
    assert state["status"] == "failed" and state["stage"] == "summarizing"
    assert "decision" not in state


def test_changed_training_source_blocks_summary(tmp_path, monkeypatch):
    write_json(tmp_path / "provenance.json", {"config_path": "fixture.json", "fingerprint": "previous"})
    monkeypatch.setattr("castguard.verify.fingerprint", lambda *args: {"fingerprint": "changed"})
    with pytest.raises(ValueError, match="changed"):
        verify_provenance(tmp_path, tmp_path)


def test_b2_selection_controls_final_history_decision(small_run):
    _, metrics, _, selection, _, config = small_run
    b2 = metrics.loc[metrics.experiment == "B"].copy()
    b2["experiment"] = "B2"
    # Both validation and test favour B2; B fails. The decision must respect the validation choice.
    metrics.loc[metrics.experiment == "B", "average_precision"] = .5
    all_metrics = pd.concat([metrics, b2], ignore_index=True)
    history, _ = select_history(all_metrics, selection, config)
    result = history_decision(all_metrics, selection, history, config)
    assert not result["b_pass"]
    assert result["selected_history_experiment"] == "B2" and result["selected_history_pass"]


def test_recommendation_considers_a0_without_reading_test(small_run):
    _, metrics, *_ = small_run
    metrics.loc[(metrics.experiment == "A0") & (metrics.role == "validation"), "average_precision"] = .99
    metrics.loc[(metrics.experiment == "B") & (metrics.role == "validation"), "average_precision"] = .7
    metrics.loc[(metrics.experiment == "A0") & (metrics.role == "test"), "average_precision"] = .01
    selected = quality_recommendations(metrics)
    assert selected.loc[selected.recommended, "experiment"].tolist() == ["A0"]


def test_corrupted_cache_is_retrained(tmp_path, monkeypatch):
    task = dict(zip(IDENTITY, ["q42", "all", "within_run", "primary", "A", "logistic", 17]))
    frame = pd.DataFrame({"row_id": list("abcdefgh"), "x": [0, 1, 0, 1, 0, 1, 0, 1], "y_defect": [0, 1] * 4,
                          "role": ["train"] * 4 + ["validation"] * 2 + ["test"] * 2})
    monkeypatch.setattr(experiment, "task_frame", lambda *args: (frame, ["x"], {}))
    config = {"models": {"logistic": {"max_iter": 100}}}
    experiment.fit_one(tmp_path, tmp_path, task, config)
    directory = tmp_path / task_name(task)
    original = (directory / "predictions.parquet").read_bytes()
    (directory / "predictions.parquet").write_bytes(b"broken")
    experiment.fit_one(tmp_path, tmp_path, task, config)
    assert (directory / "predictions.parquet").read_bytes() == original
    assert cache_valid(directory, task)


@pytest.mark.parametrize("labels,probability", [([0, .5], [.1, .9]), ([0, 2], [.1, .9]), ([0, np.nan], [.1, .9]), ([0, 1], [.1, np.nan]), ([[0, 1]], [[.1, .9]])])
def test_invalid_metric_inputs_fail_instead_of_coercing(labels, probability):
    with pytest.raises(ValueError):
        score(labels, probability)
    with pytest.raises(ValueError):
        choose_threshold(labels, probability)


@pytest.mark.parametrize("limit", [-.1, 1., np.nan])
def test_invalid_fpr_limit_fails(limit):
    with pytest.raises(ValueError):
        choose_threshold([0, 1], [.1, .9], max_fpr=limit)
