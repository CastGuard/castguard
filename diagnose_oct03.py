"""Post-selection error description. Does not fit or select models or thresholds."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from castguard.data import attach_roles, read_inputs
from castguard.storage import write_json
from oct03_research import inspection_mask, verify_development

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports/oct03_pilot_r2"
REVIEW = ROOT / "reports/oct03_review"


def main():
    frozen = verify_development(ROOT, OUT)
    frames, folds, contract = read_inputs(ROOT)
    q, m = frames["q42"], frames["m41"]
    rows, product_errors = [], []
    predictions = pd.read_parquet(OUT / "q1_validation_predictions.parquet")
    for choice in frozen["q1"]:
        scheme, fold = choice["scheme"], choice["fold"]
        frame = attach_roles(q, folds, "q42", scheme, fold)
        dev = frame.loc[frame.role.isin(["train", "validation"])]
        for (role, product), group in dev.groupby(["role", "Product_Type"]):
            rows.append({"scheme": scheme, "fold": fold, "role": role, "Product_Type": product,
                         "n": len(group), "target_positive": int(group.y_type_Short_Shot.sum()),
                         "target_prevalence": group.y_type_Short_Shot.mean(), "all_defect_prevalence": group.y_defect.mean()})
        selected = predictions.loc[predictions.scheme.eq(scheme) & predictions.fold.eq(fold)
            & (predictions.variant.eq("baseline") | predictions.model.eq(choice["model"]))]
        for (variant, seed), group in selected.groupby(["variant", "seed"]):
            group = group.copy()
            group["inspected"] = inspection_mask(group.row_id, group.probability, .2)
            for product, part in group.groupby("Product_Type"):
                positives = int(part.y_type_Short_Shot.sum())
                product_errors.append({"scheme": scheme, "fold": fold, "variant": variant, "seed": seed,
                    "Product_Type": product, "n": len(part), "positive": positives,
                    "inspected": int(part.inspected.sum()), "actual_subgroup_inspection_rate": part.inspected.mean(),
                    "captured": int(part.loc[part.inspected, "y_type_Short_Shot"].sum()),
                    "capture": part.loc[part.inspected, "y_type_Short_Shot"].sum() / positives if positives else np.nan})
    REVIEW.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(REVIEW / "q1_development_label_shift.csv", index=False)
    pd.DataFrame(product_errors).to_csv(REVIEW / "q1_development_product_errors.csv", index=False)
    shifts = []
    for scheme, fold in folds.loc[folds.dataset == "m41", ["scheme", "fold"]].drop_duplicates().itertuples(index=False, name=None):
        frame = attach_roles(m, folds, "m41", scheme, fold)
        normal = frame.loc[frame.Machine_Status.eq(0)]
        for feature in contract["m41_gate"]:
            train = normal.loc[normal.role == "train", feature].dropna()
            record = {"scheme": scheme, "fold": fold, "feature": feature, "train_n": len(train),
                      "train_median": train.median(), "train_min": train.min(), "train_max": train.max()}
            for role in ["validation", "test"]:
                values = normal.loc[normal.role == role, feature].dropna()
                record.update({role + "_n": len(values), role + "_median": values.median(),
                    role + "_out_of_train_range_rate": ((values < train.min()) | (values > train.max())).mean(),
                    role + "_ks_statistic": ks_2samp(train, values, method="asymp").statistic})
            shifts.append(record)
    pd.DataFrame(shifts).to_csv(REVIEW / "g1_posthoc_normal_feature_shift.csv", index=False)
    score_rows = []
    for role, path in [("validation", OUT / "g1_validation_predictions.parquet"), ("test", OUT / "reused_test/g1_predictions.parquet")]:
        pred = pd.read_parquet(path)
        for key, group in pred.groupby(["scheme", "fold", "policy", "seed", "model"]):
            normal = group.loc[group.Machine_Status.eq(0) & group.probability.notna()]
            score_rows.append({**dict(zip(["scheme", "fold", "policy", "seed", "model"], key)), "role": role,
                "normal_n": len(normal), "threshold": group.threshold.iloc[0],
                "normal_score_median": normal.probability.median(), "normal_score_p98": normal.probability.quantile(.98),
                "normal_fpr": normal.alarm.mean()})
    pd.DataFrame(score_rows).to_csv(REVIEW / "g1_posthoc_normal_score_shift.csv", index=False)
    test = pd.read_csv(OUT / "reused_test/g1_metrics.csv", dtype={"fold": str})
    forward = test.loc[test.scheme == "forward_run"].groupby(["policy", "seed"], as_index=False).agg(
        normal=("normal", "sum"), false_alarms=("false_alarms", "sum"), total=("episodes_total", "sum"),
        observable=("episodes_observable", "sum"), detected=("episodes_detected", "sum"), worst_run_fpr=("fpr", "max"))
    forward["pooled_fpr"] = forward.false_alarms / forward.normal
    forward.to_csv(REVIEW / "g1_forward_totals.csv", index=False)
    summary = forward.groupby("policy")[["pooled_fpr", "detected", "observable", "total", "worst_run_fpr"]].mean()
    print(summary.to_string())
    print(pd.DataFrame(shifts).query('scheme == "run_holdout" and fold == "2"').sort_values("test_ks_statistic", ascending=False).head(5).to_string(index=False))
    write_json(REVIEW / "diagnostic_scope.json", {"post_selection_descriptive_only": True,
        "test_read_for_diagnostics_not_retuning": True, "causality_established": False,
        "new_models_fitted": 0, "feature_shift_multiple_comparisons": "descriptive statistics; no significance claims"})


if __name__ == "__main__":
    main()
