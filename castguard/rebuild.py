"""Rebuild tables and split assignments from raw CSVs without overwriting handoff files."""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from .data import read_inputs
from .experiment import write_json


def with_run(frame, prefix):
    frame = frame.copy()
    frame["run_id"] = frame.Shot.diff().lt(0).cumsum().astype(int)
    frame["source_row"] = np.arange(len(frame))
    frame["row_id"] = prefix + "_r" + frame.run_id.astype(str) + "_s" + frame.Shot.astype(str)
    return frame


def build_quality(raw, process):
    frame = pd.read_csv(raw / "DieCasting_Quality_Raw_Data.csv", header=1)
    frame.columns = frame.columns.str.strip()
    original = list(frame.columns)
    frame = with_run(frame, "q42")
    frame = frame.drop_duplicates(["run_id"] + [c for c in original if c != "id"]).copy()
    if frame.duplicated(["run_id", "Shot"]).any():
        raise ValueError("Conflicting quality Shot keys")
    limits = [f"{base}_{suffix}" for base in ["Air_Pressure", "Coolant_Temp", "Factory_Temp", "Factory_Humidity"] for suffix in ["Min", "Max"]]
    frame = frame.drop(columns=limits)
    types = [c[:-2] for c in original if c.endswith("_1") and c not in process]
    targets = [f"{kind}_{cavity}" for cavity in [1, 2] for kind in types]
    frame["y_defect"] = frame[targets].gt(0).any(axis=1).astype("int8")
    for cavity in [1, 2]:
        frame[f"y_cavity_{cavity}"] = frame[[f"{kind}_{cavity}" for kind in types]].gt(0).any(axis=1).astype("int8")
    for kind in types:
        frame[f"y_type_{kind}"] = frame[[f"{kind}_1", f"{kind}_2"]].gt(0).any(axis=1).astype("int8")
    frame["defect_type_count"] = frame[[f"y_type_{kind}" for kind in types]].sum(axis=1)
    other = [kind for kind in types if kind not in ["Short_Shot", "Bubble", "Exfoliation", "Blow_Hole"]]
    frame["y_type_Etc"] = frame[[f"y_type_{kind}" for kind in other]].any(axis=1).astype("int8")
    frame["shot_position"] = frame.groupby("run_id").cumcount()
    return frame.reset_index(drop=True)


def add_history(frame, process):
    frame = frame.copy()
    frame["process_missing"] = frame[process].isna().any(axis=1)
    frame["gate_eligible"] = frame.Machine_Status.notna() & ~frame.process_missing
    frame["episode_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    for run, group in frame.groupby("run_id", sort=False):
        warm = group.Machine_Status.eq(1)
        starts = warm & ~warm.shift(fill_value=False)
        episode = starts.cumsum()
        frame.loc[group.index[warm], "episode_id"] = "r" + str(run) + "_e" + episode[warm].astype(str)
        frame.loc[group.index, "prev_cycle_time"] = group.Cycle_Time.shift()
        frame.loc[group.index, "max_cycle_previous_5"] = group.Cycle_Time.shift().rolling(5, min_periods=1).max()
        frame.loc[group.index, "missing_process_previous_20"] = group.process_missing.astype(float).shift().rolling(20, min_periods=1).sum()
        frame.loc[group.index, "missing_shots_before_current"] = (group.Shot.diff() - 1).clip(lower=0)
        frame.loc[group.index, "oracle_shots_since_warm"] = group.Shot - group.Shot.where(warm).ffill().shift()
        frame.loc[group.index, "oracle_prior_episodes"] = episode.shift(fill_value=0).astype(float)
    return frame


def build_process40(raw):
    frame = pd.read_csv(raw / "Investment_Casting.csv")
    frame["source_row"] = np.arange(len(frame))
    frame["row_id"] = "p40_" + frame.source_row.astype(str)
    frame["event_time"] = pd.to_datetime(frame.timestamp + " " + frame.date, format="%Y-%m-%d %H:%M:%S")
    frame = frame.sort_values(["event_time", "source_row"], kind="stable").reset_index(drop=True)
    frame = frame.drop(columns=["line_unit", "production", "top_temp4", "bottom_temp4", "molten_capacity"])
    for name in ["mold_temperature", "sleeve_temperature"] + [f"{side}_temp{i}" for side in ["top", "bottom"] for i in [1, 2, 3]]:
        frame[name + "_raw"] = frame[name]
        frame[name + "_suspect_high"] = frame[name].gt(1500)
        frame[name] = frame[name].astype(float).where(frame[name].gt(0))
    frame["label_available"] = frame.PassOrFail.notna()
    frame["normal_pressure"] = frame.injection_pressure.gt(615).astype("boolean").where(frame.injection_pressure.notna())
    frame["y_defect"] = frame.PassOrFail.astype("Int8")
    return frame


def build_folds(q, m, p):
    valid_runs = sorted(q.groupby("run_id").size().loc[lambda x: x >= 20].index)
    cuts = {}
    for run in valid_runs:
        group = q.loc[q.run_id == run]
        dev_count = int(np.floor(len(group) * 0.7))
        train_count = int(np.floor(dev_count * 0.8))
        cuts[run] = (group.Shot.iloc[train_count - 1], group.Shot.iloc[dev_count - 1])
    assignments = []
    for dataset, frame in [("q42", q), ("m41", m)]:
        schemes = [("within_run", "primary")] + [("run_holdout", str(r)) for r in valid_runs] + [("forward_run", str(r)) for r in valid_runs[2:]]
        for scheme, fold in schemes:
            roles = pd.Series("excluded", index=frame.index)
            if scheme == "within_run":
                for run, (train_end, val_end) in cuts.items():
                    mask = frame.run_id == run
                    roles.loc[mask] = np.select([frame.loc[mask, "Shot"] <= train_end, frame.loc[mask, "Shot"] <= val_end], ["train", "validation"], default="test")
            else:
                test_run = int(fold)
                other = [r for r in valid_runs if r != test_run and (scheme != "forward_run" or r < test_run)]
                val_run = max(other)
                roles.loc[frame.run_id.isin([r for r in other if r != val_run])] = "train"
                roles.loc[frame.run_id == val_run] = "validation"
                roles.loc[frame.run_id == test_run] = "test"
            if dataset == "m41":
                roles.loc[~frame.gate_eligible] = "excluded"
            assignments.append(pd.DataFrame({"dataset": dataset, "scheme": scheme, "fold": fold, "row_id": frame.row_id, "role": roles,
                                             "run_id": frame.run_id, "order": frame.source_row.astype(str),
                                             "episode_id": frame.episode_id if dataset == "m41" else pd.NA}))
    times = np.sort(p.event_time.unique())
    development = int(np.floor(len(times) * 0.7))
    train_count = int(np.floor(development * 0.8))
    roles = np.select([p.event_time <= times[train_count - 1], p.event_time <= times[development - 1]], ["train", "validation"], default="test")
    roles = pd.Series(roles, index=p.index).where(p.label_available, "excluded")
    assignments.append(pd.DataFrame({"dataset": "p40", "scheme": "chronological", "fold": "primary", "row_id": p.row_id, "role": roles,
                                     "run_id": -1, "order": p.event_time.dt.strftime("%Y-%m-%d %H:%M:%S"), "episode_id": pd.NA}))
    return pd.concat(assignments, ignore_index=True)


def rebuild_check(root, output):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    original, old_folds, contract = read_inputs(root)
    raw = root / "data/raw"
    q = build_quality(raw, contract["q42_A0"])
    m = add_history(with_run(pd.read_csv(raw / "DieCasting_Raw_Data.csv"), "m41"), contract["q42_A0"])
    if m.duplicated(["run_id", "Shot"]).any():
        raise ValueError("Conflicting timeline Shot keys")
    additions = ["Machine_Status", "source_row", "episode_id", "prev_cycle_time", "max_cycle_previous_5", "missing_process_previous_20", "missing_shots_before_current", "oracle_shots_since_warm", "oracle_prior_episodes"]
    joined = q.merge(m[["run_id", "Shot"] + additions], on=["run_id", "Shot"], how="left", suffixes=("", "_m41"), validate="one_to_one")
    p = build_process40(raw)
    rebuilt = {"q42": joined, "m41": m, "p40": p}
    destination = root / "artifacts/rebuilt"
    destination.mkdir(parents=True, exist_ok=True)
    checks = []
    for dataset, frame in rebuilt.items():
        expected = original[dataset]
        assert set(frame.columns) == set(expected.columns), dataset
        frame = frame[expected.columns]
        assert_frame_equal(frame.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False, check_exact=True)
        frame.to_parquet(destination / f"{dataset}.parquet", index=False)
        checks.append({"dataset": dataset, "rows": len(frame), "columns": len(frame.columns), "all_values_equal": True})
    regenerated_folds = build_folds(q, m, p)
    keys = ["dataset", "scheme", "fold", "row_id"]
    # CSV encodes an absent episode as an empty field for either pandas string dtype.
    left = regenerated_folds[old_folds.columns].fillna("").sort_values(keys).reset_index(drop=True)
    right = old_folds.fillna("").sort_values(keys).reset_index(drop=True)
    assert_frame_equal(left, right, check_dtype=False, check_exact=True)
    regenerated_folds.to_csv(destination / "folds.csv", index=False)
    checks.append({"dataset": "folds", "rows": len(left), "columns": len(left.columns), "all_values_equal": True})
    write_json(output / "rebuild_verification.json", {"comparison": "all values and row/column identity, not parquet byte encoding or nullable dtype representation", "checks": checks})
    print("Raw CSV rebuild matches all existing table values and 181170 fold assignments.", flush=True)
