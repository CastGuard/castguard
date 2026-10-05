"""Build train-only profiles and deterministic label-stripped examples, without training.

Run once into a NEW output directory. Inference itself does not need these tables.
"""
from pathlib import Path
import argparse
import copy
import json
import sys

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from castguard.decision_review import PROCESS, SENSORS, QUALITY, GATE, SCHEMA, POSITION_BASIS, MAX_EXACT_INTEGER, digest, read_json, _model_check


def clean(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def ordered_run(timeline, run_id):
    """Historical source order is authoritative; do not break ambiguous ties."""
    run = timeline[timeline.run_id.eq(run_id)]
    if run.empty or run.source_row.isna().any() or run.source_row.duplicated().any():
        raise ValueError("Historical process source order must be present and unique within run")
    if run.Shot.duplicated().any() or run.row_id.duplicated().any():
        raise ValueError("Historical process observation identity must be unique within run")
    return run.sort_values("source_row", kind="stable")


def packet(qrow, timeline, record_id=None):
    run = ordered_run(timeline, qrow.run_id)
    positions = np.flatnonzero(run.Shot.to_numpy() == qrow.Shot)
    if len(positions) != 1:
        raise ValueError("Expected exactly one matching process observation")
    seq = int(positions[0])
    run_key = f"historical-run-{int(qrow.run_id)}"
    return {"record_id": record_id or str(qrow.row_id),
        "observation": {"run_key": run_key, "sequence": seq,
            "quality_record_position": int(qrow.shot_position), "position_basis": POSITION_BASIS},
        "measurements": {name: int(qrow[name]) if name == "Product_Type" else clean(qrow[name])
                         for name in PROCESS + SENSORS + ["Product_Type"]},
        "history": [{"run_key": run_key, "sequence": i, "Cycle_Time": clean(run.iloc[i].Cycle_Time)}
                    for i in range(max(0, seq - 5), seq)]}


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def input_schema():
    nullable_number = {"type": ["number", "null"]}
    return {"$schema":"https://json-schema.org/draft/2020-12/schema",
        "title":"CastGuard label-free shot input v1", "type":"object", "additionalProperties":False,
        "description":"Stateless packets. Runtime rejects duplicate (run_key,sequence), inconsistent Cycle_Time assertions and nonmonotonic historical quality positions across valid rows. No timestamp/arrival-order sorting, automatic history assembly or persistent deduplication. Packet order does not define model features.",
        "required":["schema_version","records"], "properties":{
            "schema_version":{"const":SCHEMA},
            "records":{"type":"array","minItems":1,"items":{
                "type":"object","additionalProperties":False,
                "required":["record_id","observation","measurements"],"properties":{
                    "record_id":{"type":"string","minLength":1},
                    "observation":{"type":"object","additionalProperties":False,
                        "required":["run_key","sequence"],"properties":{
                            "run_key":{"type":"string","minLength":1},
                            "sequence":{"type":"integer","minimum":0,"maximum":MAX_EXACT_INTEGER},
                            "quality_record_position":{"type":["integer","null"],"minimum":0,"maximum":MAX_EXACT_INTEGER},
                            "position_basis":{"type":["string","null"],
                                "description":f"Quality inference requires retrospective-only {POSITION_BASIS}; other bases abstain. Never renumber based on batch order, labels or product changes."}}},
                    "measurements":{"type":"object","additionalProperties":False,
                        "properties":{**{f:nullable_number for f in PROCESS+SENSORS},
                            "Product_Type":{"type":["integer","null"],"minimum":1,"maximum":MAX_EXACT_INTEGER}},
                        "description":"Missing/null current inputs abstain the affected model; labels/derived history are forbidden."},
                    "history":{"type":["array","null"],"maxItems":5,"items":{
                        "type":"object","additionalProperties":False,
                        "required":["run_key","sequence","Cycle_Time"],"properties":{
                            "run_key":{"type":"string","minLength":1},
                            "sequence":{"type":"integer","minimum":0,"maximum":MAX_EXACT_INTEGER},"Cycle_Time":nullable_number}},
                        "description":"Exact preceding min(sequence,5) observations, same equipment/session run, ascending original process order; never filtered by product, labels or current batch. Null/missing history means unknown; [] is known run start only. Explicit null Cycle_Time asserts an existing observation with missing measurement, not an absent event."}
                }}}}}


def build(root, out):
    root, out = Path(root), Path(out)
    manifest = read_json(root / "reports/oct03_queue/manifest.json")
    selection_path = root / "reports/oct03_queue/selection.json"
    assert digest(selection_path) == manifest["outputs"]["selection.json"]
    selection = read_json(selection_path)
    sources = ["data/processed/joined.parquet", "data/processed/m41_timeline.parquet",
               "data/processed/feature_contract.json"]
    for relative in sources:
        assert digest(root / relative) == manifest["input_hashes"][relative], relative
    # Explicit columns: even asset generation never loads the quality/state targets.
    q = pd.read_parquet(root / sources[0], columns=list(dict.fromkeys(
        ["row_id", "run_id", "Shot", "source_row"] + QUALITY)))
    m = pd.read_parquet(root / sources[1], columns=list(dict.fromkeys(
        ["row_id", "run_id", "Shot", "source_row"] + GATE)))
    config = {"schema_version": "castguard-review-profile-v1", "input_schema": SCHEMA,
        "selection_sha256": digest(selection_path), "source_hashes": {p: digest(root/p) for p in sources},
        "selection_scope": "frozen nested development; historically exposed data; no new model selection",
        "checkpoints": {}}
    for choice in selection["folds"]:
        fold = choice["fold"]
        for seed in [17, 29, 43, 71, 101]:
            entry = {}
            for task, features, data in [("quality", QUALITY, q), ("gate", GATE, m)]:
                family = choice[f"{task}_model"]
                rel = f"reports/oct03_queue/models/{fold}__{task}__{family}__{seed}.joblib"
                actual_hash = digest(root/rel)
                assert actual_hash == manifest["outputs"][rel.removeprefix("reports/oct03_queue/")]
                payload = joblib.load(root/rel)
                descriptor = {"fold":fold, "seed":seed, "task":task, "model":family,
                              "features":features, "path":rel, "sha256":actual_hash}
                _model_check(payload, descriptor, features)
                fit_ids = payload["fit_row_ids"]
                assert len(fit_ids) == len(set(fit_ids))
                fit = data.set_index("row_id").loc[fit_ids]
                descriptor["ranges"] = {name: [float(fit[name].min()), float(fit[name].max())]
                    if fit[name].notna().any() else None for name in features}
                reference = {"partition":"inner_fit_only", "rows":len(fit),
                    "run_ids":sorted(map(int, fit.run_id.unique())),
                    "fit_row_ids_sha256":__import__('hashlib').sha256(json.dumps(fit_ids).encode()).hexdigest()}
                if task == "quality":
                    reference["products"] = sorted(map(int, fit.Product_Type.unique()))
                    descriptor["encoded_target"] = "any_recorded_quality_defect_equals_1"
                else:
                    reference["products"] = None
                    reference["product_mapping"] = "not_recorded_for_all_state_training_rows"
                    descriptor["encoded_target"] = "Machine_Status_numeric_code_1_semantics_unverified"
                    descriptor["threshold"] = choice["gate_thresholds"][str(seed)]
                descriptor["training_reference"] = reference
                entry[task] = descriptor
            config["checkpoints"][f"queue-fold{fold}-seed{seed}"] = entry
    write_new(out/"configs/decision_review.json", config)
    # Fixed ordering and completeness only; no labels, predictions, or success-based selection.
    example_rows = []
    for product in [1, 2]:
        candidates = q[q.Product_Type.eq(product)].dropna(subset=QUALITY).sort_values("source_row")
        example_rows.append(candidates.iloc[0])
    supported = packet(example_rows[0], m, "observed-product1")
    unseen = packet(example_rows[1], m, "unseen-product2")
    records = [supported, unseen]
    missing_sensor = copy.deepcopy(supported)
    missing_sensor["record_id"] = "missing-sensor"
    del missing_sensor["measurements"]["Factory_Temp"]
    records.append(missing_sensor)
    missing_process = copy.deepcopy(supported)
    missing_process["record_id"] = "missing-process"
    missing_process["measurements"]["Cycle_Time"] = None
    records.append(missing_process)
    invalid = copy.deepcopy(supported)
    invalid["record_id"] = "invalid-type"
    invalid["measurements"]["Casting_Pressure"] = "not-a-number"
    records.append(invalid)
    position = copy.deepcopy(supported)
    position["record_id"] = "unsupported-position-basis"
    position["observation"]["position_basis"] = "production_shot_number"
    records.append(position)
    no_history = copy.deepcopy(supported)
    no_history["record_id"] = "unknown-history"
    del no_history["history"]
    records.append(no_history)
    # Variants are counterfactual test scenarios, not conflicting records of one event.
    for record in records[2:]:
        run_key = f"fixture-{record['record_id']}-isolated-copy"
        record["observation"]["run_key"] = run_key
        for item in record.get("history") or []:
            item["run_key"] = run_key
    write_new(out/"examples/decision_review/shots.json", {"schema_version":SCHEMA,"records":records})
    write_new(out/"examples/decision_review/provenance.json", {
        "purpose":"Deterministic functional examples, not performance evidence",
        "selection_rule":"First complete quality-input row by source_row for each Product_Type 1/2; no targets loaded",
        "source_hashes":config["source_hashes"],
        "actual_rows":[{"record_id":r["record_id"],"source_quality_row_id":str(row.row_id),
            "run_id":int(row.run_id),"Shot":int(row.Shot)} for r,row in zip(records[:2],example_rows)],
        "training_example_notice":"observed-product1 is from historical fit data, not held-out efficacy evidence",
        "other_records":"Explicit mutations of observed-product1 for missing/invalid/basis/history handling. Each has an isolated synthetic run namespace; these are alternatives, not observations from additional real runs.",
        "ordering":"Original unique process source_row order, not timestamps, incoming batch order, product subsets or label availability. Ambiguous historical process identities/order are rejected.",
        "quality_position":"Historical quality input row counter, not physical Shot sequence; live contract unresolved",
        "gate_history":"Previous at most five process observations in source order, current record excluded",
        "labels_loaded":False})
    write_new(out/"configs/decision_review_input.schema.json",input_schema())
    print(json.dumps({"checkpoints":len(config["checkpoints"]),"example_records":len(records),
                      "output_root":str(out),"new_training":False}))


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    p.add_argument("--output-root",type=Path,required=True)
    args=p.parse_args()
    build(args.root,args.output_root)
