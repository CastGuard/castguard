"""Bounded experiment matrix, resumable only under an identical fingerprint."""
from functools import lru_cache
import importlib.metadata
import json
from pathlib import Path
import platform
import time

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from threadpoolctl import threadpool_limits

from .data import attach_roles, check_features, digest, read_inputs, validate
from .metrics import choose_threshold, score
from .models import build_model
from .storage import cache_valid, seal_cache, tracked_stage, write_json

KEYS = ["dataset", "population", "scheme", "fold"]
IDENTITY = KEYS + ["experiment", "model", "seed"]


def environment():
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in
                         ["pandas", "numpy", "pyarrow", "scikit-learn", "lightgbm", "catboost", "scipy", "joblib", "threadpoolctl"]}}


def fingerprint(root, config_path):
    root = Path(root)
    paths = [root / "castguard" / name for name in ["data.py", "metrics.py", "models.py", "experiment.py", "storage.py"]]
    paths += [Path(config_path)] + sorted((root / "data/processed").glob("*"))
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in paths if p.is_file()}
    import hashlib
    identity = {"hashes": hashes, "environment": environment()}
    identity["fingerprint"] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return identity


@lru_cache(maxsize=2)
def _cached_inputs(root, signature):
    return read_inputs(root)


def inputs(root):
    # Reused worker processes must notice input replacements between runs.
    folder = Path(root) / "data/processed"
    signature = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(folder.iterdir()) if p.is_file())
    return _cached_inputs(str(root), signature)


def task_name(task):
    return "__".join(str(task[k]) for k in IDENTITY)


def task_frame(root, task, config):
    frames, folds, contract = inputs(str(root))
    frame = attach_roles(frames[task["dataset"]], folds, task["dataset"], task["scheme"], task["fold"])
    if task["dataset"] == "q42":
        key = config["quality_experiments"].get(task["experiment"], "q42_B")
    else:
        key = "m41_gate" if task["dataset"] == "m41" else "p40_full"
    features = list(contract[key])
    check_features(features, contract)
    learned = {}
    if task["population"] == "normal_pressure":
        frame = frame.loc[frame.normal_pressure.fillna(False)].copy()
    if task["experiment"] == "E_no_mold6":
        features = [x for x in features if x not in config["mold_six"]]
    if task["experiment"] == "B2":
        # Fit normalization on train only; no status/quality labels in the features.
        train = frame.loc[frame.role == "train"]
        medians = train.groupby("Product_Type").Cycle_Time.median()
        fallback = float(train.Cycle_Time.median())
        denominator = frame.Product_Type.map(medians).fillna(fallback)
        for raw, derived in [("prev_cycle_time", "prev_cycle_relative_to_product"),
                             ("max_cycle_previous_5", "max_cycle_relative_to_product")]:
            frame[derived] = frame[raw] / denominator
            features.append(derived)
        frame["missing_previous20_normalized"] = frame.missing_process_previous_20 / 20.0
        features.append("missing_previous20_normalized")
        learned = {"product_cycle_medians": medians.to_dict(), "fallback_cycle_median": fallback}
    return frame, features, learned


def fit_one(root, cache, task, config):
    output = Path(cache) / task_name(task)
    output.mkdir(parents=True, exist_ok=True)
    if cache_valid(output, task):
        return task_name(task)
    (output / "complete.json").unlink(missing_ok=True)
    frame, features, learned = task_frame(root, task, config)
    target = "Machine_Status" if task["dataset"] == "m41" else "y_defect"
    partitions = {r: frame.loc[frame.role == r] for r in ["train", "validation", "test"]}
    train, val = partitions["train"], partitions["validation"]
    if train.empty or val.empty or train[target].nunique() < 2:
        raise ValueError(f"Untrainable split: {task}")
    model = build_model(task["model"], task["seed"], config["models"][task["model"]])
    with threadpool_limits(limits=1):
        start = time.perf_counter()
        model.fit(train[features], train[target].astype(int))
        fit_seconds = time.perf_counter() - start
        validation_probability = model.predict_proba(val[features])[:, 1]
        threshold = choose_threshold(val[target], validation_probability,
                                     config["gate_max_validation_fpr"] if task["dataset"] == "m41" else None)
        measurements, predictions = [], []
        for role in ["validation", "test"]:
            part = partitions[role]
            start = time.perf_counter()
            probability = model.predict_proba(part[features])[:, 1]
            elapsed = time.perf_counter() - start
            measurements.append({**task, "role": role, "threshold": threshold, "train_n": len(train),
                                 "train_positive": int(train[target].sum()), "features": len(features),
                                 "fit_seconds": fit_seconds, "predict_us_per_row": elapsed * 1e6 / len(part),
                                 **score(part[target], probability, threshold)})
            pred = part[["row_id"]].copy()
            pred["y"] = part[target].astype(int)
            pred["probability"] = probability
            pred["prediction"] = probability >= threshold
            pred["threshold"] = threshold
            pred["role"] = role
            for k, v in task.items():
                pred[k] = v
            predictions.append(pred)
    pd.DataFrame(measurements).to_csv(output / "metrics.csv", index=False)
    pd.concat(predictions, ignore_index=True).to_parquet(output / "predictions.parquet", index=False)
    joblib.dump({"pipeline": model, "features": features, "threshold": threshold,
                 "task": task, "learned": learned}, output / "model.joblib", compress=3)
    seal_cache(output, {"task": task, "features": features, "learned": learned})
    return task_name(task)


def make_tasks(folds, config):
    tasks = []
    for dataset, scheme, fold in folds[["dataset", "scheme", "fold"]].drop_duplicates().itertuples(index=False, name=None):
        experiments = list(config["quality_experiments"]) if dataset == "q42" else (["Gate"] if dataset == "m41" else ["E_full", "E_no_mold6"])
        populations = ["all", "normal_pressure"] if dataset == "p40" else ["all"]
        for pop in populations:
            for exp in experiments:
                for model in config["models"]:
                    for seed in config["seeds"]:
                        tasks.append(dict(zip(IDENTITY, [dataset, pop, scheme, str(fold), exp, model, seed])))
    return tasks


def execute(root, cache, tasks, config, jobs):
    with parallel_config(backend="loky", inner_max_num_threads=1):
        completed = Parallel(n_jobs=jobs, return_as="generator_unordered")(
            delayed(fit_one)(str(root), str(cache), task, config) for task in tasks)
        for number, name in enumerate(completed, 1):
            if number == 1 or number % 20 == 0 or number == len(tasks):
                print(f"[{number}/{len(tasks)}] {name}", flush=True)


def gather(cache, tasks):
    return pd.concat([pd.read_csv(Path(cache) / task_name(task) / "metrics.csv", dtype={"fold": str}, float_precision="round_trip") for task in tasks], ignore_index=True)


def select_models(metrics):
    base = metrics.loc[(metrics.role == "validation") & metrics.experiment.isin(["A", "Gate", "E_full"])]
    table = base.groupby(KEYS + ["model"], as_index=False).agg(validation_ap=("average_precision", "mean"), validation_brier=("brier", "mean"), validation_ece=("ece", "mean"), seed_ap_sd=("average_precision", "std"))
    table["selected"] = False
    for _, group in table.groupby(KEYS):
        best = group.sort_values(["validation_ap", "validation_brier", "model"], ascending=[False, True, True], na_position="last").index[0]
        table.loc[best, "selected"] = True
    return table


def paired_seed_gain(metrics, scheme, fold, role, experiment, model):
    base = metrics.loc[(metrics.dataset == "q42") & (metrics.scheme == scheme) & (metrics.fold == str(fold)) & (metrics.role == role) & (metrics.model == model)]
    pair = base.loc[base.experiment.isin(["A", experiment])].pivot(index="seed", columns="experiment", values="average_precision")
    difference = pair[experiment] - pair.A
    return float(difference.mean()), float(difference.std(ddof=1))


def passes_gain(mean, std, config):
    return bool(mean >= config["b_min_ap_gain"] and mean > config["b_seed_sd_multiplier"] * std)


def select_history(metrics, selection, config, include_redesign=True):
    decisions, redesign = [], []
    for row in selection.loc[selection.selected & (selection.dataset == "q42")].itertuples(index=False):
        gain, sd = paired_seed_gain(metrics, row.scheme, row.fold, "validation", "B", row.model)
        retry = not passes_gain(gain, sd, config)
        decision = {"scheme": row.scheme, "fold": row.fold, "model": row.model,
                    "b_validation_ap_gain": gain, "b_validation_gain_sd": sd,
                    "redesign_triggered": retry, "validation_selected_history_experiment": "B"}
        if retry:
            for seed in config["seeds"]:
                redesign.append(dict(zip(IDENTITY, ["q42", "all", row.scheme, row.fold, "B2", row.model, seed])))
            if include_redesign:
                gain, sd = paired_seed_gain(metrics, row.scheme, row.fold, "validation", "B2", row.model)
                decision.update(b2_validation_ap_gain=gain, b2_validation_gain_sd=sd)
                if passes_gain(gain, sd, config):
                    decision["validation_selected_history_experiment"] = "B2"
        decisions.append(decision)
    return decisions, redesign


def quality_recommendations(metrics):
    """Supplementary input/model choice; original A-based ablations stay fixed."""
    validation = metrics.loc[(metrics.dataset == "q42") & (metrics.role == "validation")
                             & metrics.experiment.isin(["A0", "A", "B"])]
    table = validation.groupby(KEYS + ["experiment", "model"], as_index=False).agg(
        validation_ap=("average_precision", "mean"), validation_brier=("brier", "mean"),
        validation_ap_seed_sd=("average_precision", "std"))
    table["recommended"] = False
    for _, group in table.groupby(KEYS):
        index = group.sort_values(["validation_ap", "validation_brier", "experiment", "model"],
                                  ascending=[False, True, True, True]).index[0]
        table.loc[index, "recommended"] = True
    return table


def run(root, config_path, output, jobs=4):
    with tracked_stage(output, "training"):
        return _run(root, config_path, output, jobs)


def _run(root, config_path, output, jobs):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks = validate(root)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    identity = fingerprint(root, config_path)
    cache = root / "artifacts" / identity["fingerprint"][:16]
    cache.mkdir(parents=True, exist_ok=True)
    write_json(output / "data_validation.json", checks)
    write_json(output / "provenance.json", {**identity, "config": config,
               "config_path": Path(config_path).resolve().relative_to(root).as_posix(),
               "cache": cache.relative_to(root).as_posix()})
    _, folds, _ = inputs(str(root))
    tasks = make_tasks(folds, config)
    print(f"Fingerprint {identity['fingerprint'][:16]}, {len(tasks)} fits, {jobs} workers", flush=True)
    execute(root, cache, tasks, config, jobs)
    metrics = gather(cache, tasks)
    selection = select_models(metrics)
    # One bounded redesign, triggered using validation only, separately per fold.
    _, redesign = select_history(metrics, selection, config, include_redesign=False)
    if redesign:
        print(f"Validation-triggered B2: {len(redesign)} fits", flush=True)
        execute(root, cache, redesign, config, jobs)
        tasks += redesign
        metrics = gather(cache, tasks)
    decisions, _ = select_history(metrics, selection, config)
    metrics.to_csv(output / "metrics.csv", index=False)
    selection.to_csv(output / "model_selection.csv", index=False)
    write_json(output / "history_selection.json", decisions)
    selected = selection.loc[selection.selected, KEYS + ["model"]]
    selected_metrics = metrics.merge(selected, on=KEYS + ["model"], validate="many_to_one")
    selected_metrics.to_csv(output / "selected_metrics.csv", index=False)
    chosen_tasks = [t for t in tasks if ((selected[KEYS + ["model"]] == pd.Series({k: t[k] for k in KEYS + ["model"]})).all(axis=1)).any()]
    predictions = pd.concat([pd.read_parquet(cache / task_name(task) / "predictions.parquet") for task in chosen_tasks], ignore_index=True)
    predictions.to_parquet(output / "predictions.parquet", index=False)
    training_files = ["metrics.csv", "model_selection.csv", "history_selection.json", "selected_metrics.csv", "predictions.parquet"]
    write_json(output / "training_manifest.json", {"fingerprint": identity["fingerprint"],
               "outputs": {name: digest(output / name) for name in training_files}})
    write_json(output / "run_status.json", {"status": "models_complete", "fits": len(tasks), "metric_rows": len(metrics), "seeds": config["seeds"]})
    return cache, config
