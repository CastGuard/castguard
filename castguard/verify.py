"""Independently reconcile saved row predictions with every selected metric."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .data import attach_roles, digest, read_inputs, validate
from .experiment import IDENTITY, KEYS, fingerprint, make_tasks, select_history, select_models
from .metrics import score


def verify_provenance(root, output):
    root, output = Path(root).resolve(), Path(output)
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    current = fingerprint(root, root / provenance["config_path"])
    if current["fingerprint"] != provenance["fingerprint"]:
        raise ValueError("Training code, inputs, config or environment changed; rerun training before summarizing")
    config = json.loads((root / provenance["config_path"]).read_text(encoding="utf-8"))
    if config != provenance["config"]:
        raise ValueError("Provenance config snapshot disagrees with training config")
    manifest = json.loads((output / "training_manifest.json").read_text(encoding="utf-8"))
    expected = {"metrics.csv", "model_selection.csv", "history_selection.json", "selected_metrics.csv", "predictions.parquet"}
    if manifest.get("fingerprint") != current["fingerprint"] or set(manifest.get("outputs", {})) != expected:
        raise ValueError("Incomplete training manifest")
    for name, expected_hash in manifest["outputs"].items():
        if digest(output / name) != expected_hash:
            raise ValueError(f"Training output was altered: {name}; rerun training")
    validate(root)
    return provenance


def require_keys(frame, columns, expected, label):
    expected = set(expected)
    if frame[columns].isna().any().any() or frame.duplicated(columns).any():
        raise ValueError(f"Duplicate or null {label} keys")
    actual = set(frame[columns].itertuples(index=False, name=None))
    if actual != expected:
        raise ValueError(f"Incomplete {label}: missing={len(expected - actual)}, unexpected={len(actual - expected)}")


def verify_matrix(all_metrics, saved_selection, folds, config):
    base_tasks = make_tasks(folds, config)
    base_keys = {tuple(task[k] for k in IDENTITY) for task in base_tasks}
    base = all_metrics.loc[all_metrics.experiment != "B2"]
    require_keys(base, IDENTITY + ["role"], [key + (role,) for key in base_keys for role in ["validation", "test"]], "base experiment matrix")
    selection = select_models(base)
    _, redesign = select_history(base, selection, config, include_redesign=False)
    expected = base_keys | {tuple(task[k] for k in IDENTITY) for task in redesign}
    require_keys(all_metrics, IDENTITY + ["role"], [key + (role,) for key in expected for role in ["validation", "test"]], "experiment matrix")
    columns = KEYS + ["model"]
    pd.testing.assert_frame_equal(saved_selection.sort_values(columns).reset_index(drop=True),
                                  selection.sort_values(columns).reset_index(drop=True), check_exact=False, rtol=1e-12, atol=1e-12)
    return selection, select_history(all_metrics, selection, config)[0]


def verify_evidence(root, output):
    output = Path(output)
    predictions = pd.read_parquet(output / "predictions.parquet")
    metrics = pd.read_csv(output / "selected_metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    all_metrics = pd.read_csv(output / "metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    saved_selection = pd.read_csv(output / "model_selection.csv", dtype={"fold": str}, float_precision="round_trip")
    config = json.loads((output / "provenance.json").read_text(encoding="utf-8"))["config"]
    keys = IDENTITY + ["role"]
    if predictions.duplicated(keys + ["row_id"]).any() or metrics.duplicated(keys).any():
        raise ValueError("Duplicated evaluation records")
    indexed = metrics.set_index(keys)
    frames, folds, _ = read_inputs(root)
    selection, history = verify_matrix(all_metrics, saved_selection, folds, config)
    saved_history = json.loads((output / "history_selection.json").read_text(encoding="utf-8"))
    if history != saved_history:
        raise ValueError("History selection disagrees with validation metrics")
    chosen = selection.loc[selection.selected, KEYS + ["model"]]
    expected_metrics = all_metrics.merge(chosen, on=KEYS + ["model"], validate="many_to_one")
    require_keys(metrics, keys, expected_metrics[keys].itertuples(index=False, name=None), "selected metrics")
    pd.testing.assert_frame_equal(metrics.sort_values(keys).reset_index(drop=True),
                                  expected_metrics.sort_values(keys).reset_index(drop=True), check_exact=True)
    require_keys(predictions[keys].drop_duplicates(), keys, metrics[keys].itertuples(index=False, name=None), "prediction groups")
    counts = 0
    for key, group in predictions.groupby(keys):
        row = indexed.loc[key]
        dataset, population, scheme, fold, *_ = key
        role = key[-1]
        partition = attach_roles(frames[dataset], folds, dataset, scheme, fold)
        if population == "normal_pressure":
            partition = partition.loc[partition.normal_pressure.fillna(False)]
        expected_rows = partition.loc[partition.role == role]
        if set(group.row_id) != set(expected_rows.row_id):
            raise ValueError(f"Missing or unexpected evaluation rows: {key}")
        truth = expected_rows.set_index("row_id").loc[group.row_id]
        target = "Machine_Status" if dataset == "m41" else "y_defect"
        np.testing.assert_array_equal(group.y.to_numpy(), truth[target].astype(int).to_numpy())
        assignments = folds.loc[(folds.dataset == dataset) & (folds.scheme == scheme) & (folds.fold == fold)].set_index("row_id")
        if not assignments.loc[group.row_id, "role"].eq(role).all():
            raise ValueError("Prediction contains a row outside its assigned partition")
        np.testing.assert_array_equal(group.threshold.to_numpy(), np.full(len(group), row.threshold))
        np.testing.assert_array_equal(group.prediction, group.probability >= row.threshold)
        recomputed = score(group.y, group.probability, row.threshold)
        for metric in recomputed:
            np.testing.assert_allclose(recomputed[metric], row[metric], rtol=1e-12, atol=1e-12, equal_nan=True)
        train = partition.loc[partition.role == "train"]
        if row.train_n != len(train) or row.train_positive != int(train[target].sum()):
            raise ValueError(f"Train population mismatch: {key}")
        counts += 1
    if counts != len(metrics):
        raise ValueError("Some selected metrics have no row predictions")
    gate_validation = all_metrics.loc[(all_metrics.dataset == "m41") & (all_metrics.role == "validation")]
    if not gate_validation.fpr.le(config["gate_max_validation_fpr"]).all():
        raise ValueError("Gate validation FPR bound violated")
    return {"selected_prediction_metric_groups": counts, "prediction_rows": len(predictions),
            "all_candidate_metric_rows": len(all_metrics), "gate_validation_groups": len(gate_validation),
            "complete_experiment_matrix_and_populations": True,
            "validation_model_and_history_selection_recomputed": True,
            "targets_partitions_probabilities_thresholds_metrics_reconciled": True,
            "threshold_csv_read": "pandas float_precision=round_trip; exact probabilities/thresholds also retained in Parquet"}


def verify_delivery(root, output):
    root, output = Path(root).resolve(), Path(output)
    status = json.loads((output / "run_status.json").read_text(encoding="utf-8"))
    if status.get("status") != "complete":
        raise ValueError(f"Run is not complete: {status.get('status')}")
    manifest = json.loads((output / "evidence_manifest.json").read_text(encoding="utf-8"))
    required = {"RESULTS.md", "decision.json", "metrics.csv", "predictions.parquet", "provenance.json",
                "training_manifest.json", "model_selection.csv", "selected_metrics.csv", "history_selection.json",
                "prediction_verification.json", "quality_recommendations.csv", "run_status.json"}
    if not required.issubset(manifest.get("outputs", {})):
        raise ValueError("Evidence manifest omits required outputs")
    sources = {p.relative_to(root).as_posix() for p in (root / "castguard").glob("*.py")}
    if set(manifest.get("source_hashes", {})) != sources:
        raise ValueError("Evidence manifest does not cover current source files")
    for name, expected_hash in manifest["outputs"].items():
        if digest(output / name) != expected_hash:
            raise ValueError(f"Evidence output changed: {name}")
    for name, expected_hash in manifest["source_hashes"].items():
        if digest(root / name) != expected_hash:
            raise ValueError(f"Evidence source changed: {name}")
    verify_provenance(root, output)
    return verify_evidence(root, output)
