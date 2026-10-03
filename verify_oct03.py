"""Reconcile saved pilot predictions, fitted transforms, metrics and old baseline."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from threadpoolctl import threadpool_limits

from castguard.data import attach_roles, digest, read_inputs
from castguard.storage import write_json
from oct03_research import verify_development


def close(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12, equal_nan=True)


def verify(root, out):
    selected = verify_development(root, out, allow_historical=True)
    cfg = selected["config"]
    frames, folds, contract = read_inputs(root)
    q = frames["q42"]
    metrics = pd.read_csv(out / "q1_candidate_validation.csv", dtype={"fold": str}, float_precision="round_trip")
    predictions = pd.read_parquet(out / "q1_validation_predictions.parquet")
    keys = ["scheme", "fold", "model", "seed", "variant", "role"]
    assert not predictions.duplicated(keys + ["row_id"]).any()
    assert not metrics.duplicated(keys + ["budget"]).any()
    indexed = metrics.set_index(keys + ["budget"])
    q_groups = 0
    for key, rows in predictions.groupby(keys):
        scheme, fold, model, seed, variant, role = key
        assert role == "validation"
        part = attach_roles(q, folds, "q42", scheme, fold)
        truth = part.loc[part.role == role].set_index("row_id")
        assert set(rows.row_id) == set(truth.index)
        ordered = truth.loc[rows.row_id]
        np.testing.assert_array_equal(rows[cfg["target"]], ordered[cfg["target"]])
        np.testing.assert_array_equal(rows.y_defect, ordered.y_defect)
        assert np.isfinite(rows.probability).all() and rows.probability.between(0, 1).all()
        ranking = rows.sort_values(["probability", "row_id"], ascending=[False, True])
        for budget in cfg["budgets"]:
            saved = indexed.loc[key + (budget,)]
            k = int(np.floor(len(rows) * budget))
            hits = ranking.iloc[:k]
            positive, all_positive = int(rows[cfg["target"]].sum()), int(rows.y_defect.sum())
            assert saved.n == len(rows) and saved.inspected == k and saved.positive == positive
            assert saved.captured == hits[cfg["target"]].sum() and saved.overall_captured == hits.y_defect.sum()
            close(saved.capture, hits[cfg["target"]].sum() / positive)
            close(saved.overall_capture, hits.y_defect.sum() / all_positive)
            close(saved.actual_budget, k / len(rows))
            close(saved.average_precision, average_precision_score(rows[cfg["target"]], rows.probability))
            close(saved.roc_auc, roc_auc_score(rows[cfg["target"]], rows.probability))
        q_groups += 1
    model_count = 0
    for file in (out / "models").glob("*.joblib"):
        saved = joblib.load(file)
        scheme, fold, model, seed = file.stem.split("__")
        part = attach_roles(q, folds, "q42", scheme, fold)
        train, val = part.loc[part.role == "train"], part.loc[part.role == "validation"]
        assert saved["features"] == contract[cfg["q1_features"]]
        pipeline = saved["pipeline"]
        # Confirms train medians, and for logistic also the count/mean of train-only scaling.
        expected = train[saved["features"]].median().fillna(0).to_numpy()
        close(pipeline.named_steps["impute"].statistics_, expected)
        if "scale" in pipeline.named_steps:
            imputed = pipeline.named_steps["impute"].transform(train[saved["features"]])
            close(pipeline.named_steps["scale"].mean_, np.asarray(imputed).mean(axis=0))
            assert pipeline.named_steps["scale"].n_samples_seen_ == len(train)
        stored = predictions.loc[predictions.scheme.eq(scheme) & predictions.fold.eq(fold)
            & predictions.model.eq(model) & predictions.seed.eq(int(seed)) & predictions.variant.eq("specialist")]
        aligned = val.set_index("row_id").loc[stored.row_id]
        with threadpool_limits(limits=1):
            close(pipeline.predict_proba(aligned[saved["features"]])[:, 1], stored.probability)
        model_count += 1
    assert model_count == 90 and q_groups == 135 and len(metrics) == 405
    result = {"verified_at": datetime.now(timezone.utc).isoformat(), "q1_models_reloaded": model_count,
              "train_only_imputation_and_scaling_verified": True, "q1_prediction_groups": q_groups,
              "q1_metric_rows": len(metrics), "q1_prediction_rows": len(predictions),
              "q1_test_absent_after_development_failure": not (out / "reused_test/q1_predictions.parquet").exists()}
    test = out / "reused_test"
    receipt = json.loads((test / "manifest.json").read_text(encoding="utf-8"))
    assert receipt["development_manifest"] == digest(out / "manifest.json")
    for name, expected in receipt["outputs"].items():
        assert digest(test / name) == expected
    gmetrics = pd.read_csv(test / "g1_metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    gp = pd.read_parquet(test / "g1_predictions.parquet")
    gkeys = ["scheme", "fold", "seed", "policy"]
    assert not gp.duplicated(gkeys + ["row_id"]).any() and not gmetrics.duplicated(gkeys).any()
    gindex = gmetrics.set_index(gkeys)
    groups = 0
    for key, rows in gp.groupby(gkeys):
        saved = gindex.loc[key]
        available = rows.probability.notna()
        alarm = available & (rows.probability.ge(saved.threshold) if not saved.disabled else False)
        np.testing.assert_array_equal(rows.alarm, alarm)
        original = frames["m41"].set_index("row_id").loc[rows.row_id]
        close(rows.Machine_Status.to_numpy(dtype=float), original.Machine_Status.to_numpy(dtype=float))
        normal = rows.Machine_Status.eq(0) & available
        warm = rows.Machine_Status.eq(1)
        assert saved.normal == normal.sum() and saved.false_alarms == (normal & alarm).sum()
        close(saved.fpr, (normal & alarm).sum() / normal.sum())
        assert saved.held == (~available).sum()
        eps = rows.loc[warm].groupby("episode_id")
        assert saved.episodes_total == len(eps)
        observed, detected, delay = 0, 0, []
        for _, ep in eps:
            observed += int(ep.probability.notna().any())
            hits = ep.loc[ep.alarm]
            detected += int(len(hits) > 0)
            if len(hits):
                delay.append(int(hits.Shot.min() - ep.Shot.min()))
        assert saved.episodes_observable == observed and saved.episodes_detected == detected
        close(saved.mean_delay, np.mean(delay) if delay else np.nan)
        groups += 1
    assert groups == 165
    # The old policy is an unchanged control: all 55 groups must reproduce the original report.
    old = pd.read_csv(root / "reports/oct02/gate_metrics.csv", dtype={"fold": str}, float_precision="round_trip")
    control = gmetrics.loc[gmetrics.policy == "baseline"].merge(old, on=["scheme", "fold", "seed"], validate="one_to_one", suffixes=("", "_old"))
    assert len(control) == 55
    for new, previous in [("normal", "normal_observable"), ("false_alarms", "false_stops"),
            ("fpr", "test_fpr"), ("held", "held_unavailable"), ("episodes_total", "episodes_total_old"),
            ("episodes_observable", "episodes_observable_old"), ("episodes_detected", "episodes_detected_old"),
            ("mean_delay", "mean_delay_detected_shots")]:
        close(control[new], control[previous])
    result.update({"g1_test_prediction_groups": groups, "g1_test_prediction_rows": len(gp),
                   "old_gate_control_groups_matched": len(control), "manifest_hashes_verified": True,
                   "no_original_project_files_written": True})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("reports/oct03_pilot_r2"))
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.output if args.output.is_absolute() else root / args.output
    result = verify(root, out)
    review = root / "reports/oct03_review"
    write_json(review / "verification.json", {**result, "verifier_sha256": digest(Path(__file__))})
    print(json.dumps(result))
