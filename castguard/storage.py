"""Atomic receipts and integrity checks for reproducible local experiments."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from .data import digest

CACHE_FILES = ("metrics.csv", "predictions.parquet", "model.joblib")


def write_json(path, value):
    def clean(obj):
        if isinstance(obj, dict):
            return {str(k): clean(v) for k, v in obj.items()}
        if isinstance(obj, (tuple, list)):
            return [clean(v) for v in obj]
        if isinstance(obj, np.generic):
            return clean(obj.item())
        if isinstance(obj, float) and not np.isfinite(obj):
            return None
        return obj
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def seal_cache(directory, metadata):
    directory = Path(directory)
    write_json(directory / "complete.json", {**metadata, "schema_version": 2,
               "sha256": {name: digest(directory / name) for name in CACHE_FILES}})


def cache_valid(directory, task):
    directory = Path(directory)
    try:
        metadata = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
        return (metadata.get("schema_version") == 2 and metadata.get("task") == task
                and set(metadata.get("sha256", {})) == set(CACHE_FILES)
                and all(digest(directory / name) == metadata["sha256"][name] for name in CACHE_FILES))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def require_cache(directory, task):
    if not cache_valid(directory, task):
        raise ValueError(f"Missing or damaged cached experiment: {Path(directory).name}; rerun training")


@contextmanager
def tracked_stage(output, stage):
    """A failed refresh must never retain the previous 'complete' state."""
    path = Path(output) / "run_status.json"
    previous = {}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
    counters = {key: previous[key] for key in ["fits", "metric_rows", "seeds"] if key in previous}
    write_json(path, {**counters, "status": "running", "stage": stage})
    try:
        yield
    except BaseException as error:
        write_json(path, {**counters, "status": "failed", "stage": stage,
                          "error_type": type(error).__name__, "error": str(error)})
        raise
