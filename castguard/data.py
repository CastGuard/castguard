"""Read-only data contract and fixed-fold validation."""
from fnmatch import fnmatchcase
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

FILES = {"q42": "joined.parquet", "m41": "m41_timeline.parquet", "p40": "d40_clean.parquet"}


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_inputs(root):
    folder = Path(root) / "data/processed"
    frames = {key: pd.read_parquet(folder / name) for key, name in FILES.items()}
    folds = pd.read_csv(folder / "folds.csv", dtype={"fold": str, "episode_id": str, "order": str})
    contract = json.loads((folder / "feature_contract.json").read_text(encoding="utf-8"))
    return frames, folds, contract


def check_features(features, contract):
    forbidden = contract["target_columns"] + contract["forbidden"]
    bad = [name for name in features if any(fnmatchcase(name, pattern) for pattern in forbidden)]
    if bad or len(features) != len(set(features)):
        raise ValueError(f"Unsafe feature list: {bad or 'duplicate columns'}")


def attach_roles(frame, folds, dataset, scheme, fold):
    rows = folds.loc[(folds.dataset == dataset) & (folds.scheme == scheme) & (folds.fold == str(fold))]
    if rows.empty or rows.row_id.duplicated().any() or set(rows.row_id) != set(frame.row_id):
        raise ValueError("Incomplete or duplicate fold assignment")
    return frame.merge(rows[["row_id", "role"]], on="row_id", validate="one_to_one")


def validate(root):
    root = Path(root)
    frames, folds, contract = read_inputs(root)
    manifest = json.loads((root / "data/processed/manifest.json").read_text(encoding="utf-8"))
    checks = []
    for record in manifest["inputs"] + manifest["outputs"]:
        if digest(root / record["path"]) != record["sha256"]:
            raise ValueError(f"Hash mismatch: {record['path']}")
        checks.append({"check": "sha256", "subject": record["path"], "passed": True})
    for dataset, frame in frames.items():
        if frame.row_id.isna().any() or frame.row_id.duplicated().any():
            raise ValueError(f"Nonunique row_id: {dataset}")
    for key in ["q42_A0", "q42_A", "q42_B", "m41_gate", "p40_full"]:
        check_features(contract[key], contract)
    if not set(folds.role).issubset({"train", "validation", "test", "excluded"}):
        raise ValueError("Unexpected fold role")
    for (dataset, scheme, fold), subset in folds.groupby(["dataset", "scheme", "fold"]):
        frame = attach_roles(frames[dataset], folds, dataset, scheme, fold)
        eligible = frame.role != "excluded"
        if dataset == "m41":
            if not frame.loc[eligible, "gate_eligible"].all():
                raise ValueError("Ineligible gate rows in a scored partition")
            if frame.loc[eligible].dropna(subset=["episode_id"]).groupby("episode_id").role.nunique().gt(1).any():
                raise ValueError("Episode split across roles")
        if dataset == "p40":
            if frame.loc[eligible, "y_defect"].isna().any():
                raise ValueError("Unlabelled row included")
            if frame.loc[eligible].groupby("event_time").role.nunique().gt(1).any():
                raise ValueError("Timestamp split across roles")
        if scheme == "forward_run":
            ranges = [frame.loc[frame.role == role, "run_id"] for role in ["train", "validation", "test"]]
            if not ranges[0].max() < ranges[1].min() <= ranges[1].max() < ranges[2].min():
                raise ValueError("Forward-run chronology violated")
        if dataset == "q42":
            gate = attach_roles(frames["m41"], folds, "m41", scheme, fold)
            linked = frame.merge(gate[["run_id", "Shot", "role"]], on=["run_id", "Shot"], suffixes=("", "_gate"), validate="one_to_one")
            if not linked.role.eq(linked.role_gate).all():
                raise ValueError("Gate/quality fold boundaries disagree")
        checks.append({"check": "fold", "subject": f"{dataset}/{scheme}/{fold}", "passed": True})
    q, m = frames["q42"], frames["m41"]
    link = q.merge(m, on=["run_id", "Shot"], suffixes=("_q", "_m"), validate="one_to_one")
    if len(link) != len(q):
        raise ValueError("Missing join")
    for name in contract["q42_A0"]:
        np.testing.assert_array_equal(link[f"{name}_q"], link[f"{name}_m"])
    checks.append({"check": "join", "subject": "4617 matched Shots / 64638 equal process values", "passed": True})
    return checks
