import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from castguard.data import attach_roles, check_features, validate
from castguard.experiment import select_models, passes_gain, make_tasks, task_frame
from castguard.metrics import choose_threshold, score
from castguard.models import build_model

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "configs/oct02.json").read_text())


def test_frozen_data_hashes_joins_and_folds():
    assert len(validate(ROOT)) >= 30


@pytest.mark.parametrize("column", ["y_defect", "y_type_Bubble", "Machine_Status", "oracle_prior_episodes", "source_row", "Bubble_1"])
def test_label_and_identifier_leaks_are_rejected(column):
    contract = json.loads((ROOT / "data/processed/feature_contract.json").read_text())
    with pytest.raises(ValueError):
        check_features(["Cycle_Time", column], contract)


def test_duplicate_or_missing_fold_rows_fail_closed():
    frame = pd.DataFrame({"row_id": ["a", "b"]})
    folds = pd.DataFrame({"dataset": ["x", "x"], "scheme": ["s", "s"], "fold": ["f", "f"], "row_id": ["a", "a"], "role": ["train", "test"]})
    with pytest.raises(ValueError):
        attach_roles(frame, folds, "x", "s", "f")


def test_fpr_threshold_handles_ties_conservatively():
    y = np.array([0] * 100 + [1] * 2)
    p = np.array([0.1] * 97 + [0.9] * 3 + [0.9, 0.95])
    threshold = choose_threshold(y, p, max_fpr=0.02)
    assert score(y, p, threshold)["fpr"] <= 0.02
    assert threshold > 0.9
    assert score(y, p, threshold)["recall"] == 0.5


def test_saved_threshold_preserves_nextafter_boundary(tmp_path):
    from castguard.experiment import gather, task_name
    task = dict(dataset="m41", population="all", scheme="within_run", fold="primary", experiment="Gate", model="random_forest", seed=17)
    directory = tmp_path / task_name(task)
    directory.mkdir()
    threshold = float(np.nextafter(0.2, np.inf))
    pd.DataFrame([{**task, "threshold": threshold}]).to_csv(directory / "metrics.csv", index=False)
    loaded = gather(tmp_path, [task]).threshold.iloc[0]
    assert loaded == threshold and loaded > 0.2


def test_no_normal_validation_does_not_claim_fpr_control():
    assert choose_threshold([1, 1], [0.2, 0.8], max_fpr=0.02) > 1


def test_single_class_auc_and_ap_are_unavailable():
    metric = score([0, 0], [0.2, 0.7])
    assert np.isnan(metric["roc_auc"]) and np.isnan(metric["average_precision"])
    assert metric["n"] == 2 and metric["positive"] == 0


def test_imputation_uses_train_only():
    model = build_model("logistic", 17, CONFIG["models"]["logistic"])
    model.fit(pd.DataFrame({"x": [1.0, 3.0, np.nan, 5.0]}), [0, 0, 1, 1])
    model.predict_proba(pd.DataFrame({"x": [1e9, np.nan]}))
    assert model.named_steps["impute"].statistics_[0] == 3


def test_model_selection_never_reads_test_metrics():
    rows = []
    for model, val, test in [("first", 0.8, 0.1), ("second", 0.5, 1.0)]:
        for role, ap in [("validation", val), ("test", test)]:
            rows.append(dict(dataset="q42", population="all", scheme="within_run", fold="primary", experiment="A", model=model, role=role, average_precision=ap, brier=0.2, ece=0.1))
    result = select_models(pd.DataFrame(rows))
    assert result.loc[result.selected, "model"].tolist() == ["first"]


def test_b_gate_needs_effect_size_and_seed_stability():
    assert not passes_gain(0.019, 0.001, CONFIG)
    assert not passes_gain(0.03, 0.02, CONFIG)
    assert passes_gain(0.03, 0.01, CONFIG)


def test_matrix_has_every_seed_model_and_protocol():
    folds = pd.read_csv(ROOT / "data/processed/folds.csv", dtype={"fold": str, "order": str, "episode_id": str})
    tasks = make_tasks(folds, CONFIG)
    assert len(tasks) == 960
    assert len({tuple(t.values()) for t in tasks}) == len(tasks)


def test_b2_features_have_train_only_product_medians():
    task = dict(dataset="q42", population="all", scheme="within_run", fold="primary", experiment="B2", model="logistic", seed=17)
    frame, features, learned = task_frame(ROOT, task, CONFIG)
    expected = frame.loc[frame.role == "train"].groupby("Product_Type").Cycle_Time.median().to_dict()
    assert learned["product_cycle_medians"] == expected
    assert "prev_cycle_relative_to_product" in features
