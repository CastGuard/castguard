"""Deterministic input-order adversaries against frozen models; no training/data tables."""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from castguard.decision_review import DecisionReviewer, ContractError, SCHEMA, read_json, digest
from prepare_decision_review import write_new


def envelope(records):
    return {"schema_version": SCHEMA, "records": records}


def semantic_rows(result):
    return {r["record_id"]: {k: v for k, v in r.items() if k != "record_index"} for r in result["records"]}


def timeline(base, run="synthetic-order-a", count=9):
    rows = []
    cycle = base["measurements"]["Cycle_Time"]
    for seq in range(count):
        row = deepcopy(base)
        row["record_id"] = f"{run}:{seq}"
        row["observation"].update(run_key=run, sequence=seq, quality_record_position=seq)
        row["measurements"]["Cycle_Time"] = cycle + seq / 10
        row["history"] = [{"run_key": run, "sequence": i, "Cycle_Time": cycle + i / 10}
                          for i in range(max(0, seq - 5), seq)]
        rows.append(row)
    return rows


def adversaries(rows):
    cases = {}
    duplicate = deepcopy(rows[:1]) * 2
    duplicate = deepcopy(duplicate)
    duplicate[1] = deepcopy(duplicate[0])
    duplicate[1]["record_id"] = "different-id-same-observation"
    cases["duplicate_event"] = duplicate
    cases["duplicate_record_id"] = [deepcopy(rows[0]), deepcopy(rows[0])]
    current_history = deepcopy(rows[:2])
    current_history[1]["history"][0]["Cycle_Time"] += 1
    cases["current_history_conflict"] = current_history
    overlap = deepcopy(rows[5:7])
    overlap[1]["history"][0]["Cycle_Time"] += 1
    cases["overlapping_history_conflict"] = overlap
    null = deepcopy(rows[:2])
    null[0]["measurements"]["Cycle_Time"] = None
    cases["null_vs_measured_conflict"] = null
    for name, before, after in [("counter_reuse", 2, 2), ("counter_reverse", 2, 1), ("counter_jump", 0, 4)]:
        case = deepcopy([rows[2], rows[4]])
        case[0]["observation"]["quality_record_position"] = before
        case[1]["observation"]["quality_record_position"] = after
        cases[name] = case
    return cases


def verify(root, output, examples=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Verification output must be a new directory")
    example_path = Path(examples) if examples else root / "examples/decision_review/shots.json"
    source = read_json(example_path)
    base = next(r for r in source["records"] if r["record_id"] == "observed-product1")
    rows = timeline(base)
    bad_batches = adversaries(rows)
    checks = []
    for checkpoint in ["queue-fold2-seed17", "queue-fold4-seed17"]:
        reviewer = DecisionReviewer(root, checkpoint)
        full = semantic_rows(reviewer.review(envelope(rows)))
        variants = {"full": rows, "reverse": rows[::-1], "partial": rows[::2],
                    "permutation": [rows[i] for i in [8, 0, 3, 5, 2, 7, 1, 6, 4]]}
        for name, selected in variants.items():
            assert semantic_rows(reviewer.review(envelope(selected))) == {r["record_id"]: full[r["record_id"]] for r in selected}
            checks.append({"checkpoint": checkpoint, "case": name, "outcome": "exact_semantic_equality"})
        for size in [1, 2, 5]:
            chunks = {}
            for start in range(0, len(rows), size):
                chunks.update(semantic_rows(reviewer.review(envelope(rows[start:start + size]))))
            assert chunks == full
            checks.append({"checkpoint": checkpoint, "case": f"chunks_{size}", "outcome": "exact_semantic_equality"})
        for name, case in bad_batches.items():
            for reverse in [False, True]:
                try:
                    reviewer.review(envelope(case[::-1] if reverse else case))
                except ContractError as error:
                    checks.append({"checkpoint": checkpoint, "case": name, "reverse": reverse,
                                   "outcome": "entire_call_rejected", "reason": str(error)})
                else:
                    raise AssertionError(f"{name} silently accepted")
        for name in ["missing_predecessor", "other_run", "same_timestamp", "label_field", "incomplete_counter"]:
            case = deepcopy(rows[4])
            if name == "missing_predecessor":
                case["history"].pop()
            elif name == "other_run":
                case["history"][0]["run_key"] = "wrong-equipment"
            elif name == "same_timestamp":
                case["observation"]["timestamp"] = "2026-10-05T01:00:00Z"
            elif name == "label_field":
                case["measurements"]["Machine_Status"] = 1
            else:
                del case["observation"]["sequence"]
            result = reviewer.review(envelope([case]))["records"][0]
            assert result["status"] == "invalid_input"
            checks.append({"checkpoint": checkpoint, "case": name, "outcome": "invalid_input_no_score", "reason": result["errors"]})
        mixed = deepcopy(rows)
        for i, row in enumerate(mixed):
            row["measurements"]["Product_Type"] = 1 + i % 2
        other_run = timeline(base, "synthetic-order-b", 3)
        combined = mixed + other_run
        batch = semantic_rows(reviewer.review(envelope(combined)))
        for row in combined:
            assert batch[row["record_id"]] == semantic_rows(reviewer.review(envelope([row])))[row["record_id"]]
        unseen = batch[mixed[1]["record_id"]]["quality"]
        assert any(w["code"] == "unseen_product" for w in unseen["warnings"])
        assert unseen["score_interpretation"] == "diagnostic_only_uncalibrated_model_output"
        checks.append({"checkpoint": checkpoint, "case": "mixed_runs_products", "outcome": "exact_semantic_equality_diagnostic_product_warning"})
        for row in batch.values():
            for key in ["quality", "equipment_state"]:
                stage = row[key]
                explanation = stage["explanation"]
                margin = explanation["baseline_margin"] + sum(x["contribution"] for x in explanation["contributions"])
                assert explanation["scale"] == "log_odds_of_encoded_class_1"
                assert abs(1 / (1 + math.exp(-margin)) - stage["score"]) <= 1e-6
        missing = deepcopy(rows[4])
        missing.pop("history")
        first = reviewer.review(envelope([missing]))
        reviewer.review(envelope(rows[:4]))
        assert reviewer.review(envelope([missing])) == first
        assert first["records"][0]["equipment_state"]["score"] is None
        assert first["invocation_contract"]["cross_call_consistency_checked"] is False
        checks.append({"checkpoint": checkpoint, "case": "no_implicit_stream_state", "outcome": "equipment_abstains_even_after_predecessor_calls"})
    summary = {
        "scope": "Deterministic synthetic input-contract adversaries on frozen artifacts; no model efficacy measurement",
        "fixture_source_sha256": digest(example_path), "fixture_derivation": "Copy first historical example's measurements; create explicit synthetic sequences, histories, products and run keys. Not additional observed data.",
        "checkpoints": ["queue-fold2-seed17", "queue-fold4-seed17"], "checks": checks, "check_count": len(checks),
        "training_or_selection_performed": False, "runtime_source_sha256": digest(Path(__file__).parent / "castguard/decision_review.py"),
        "stream_contract": "Independent complete packets only. No arrival-order inference, history buffering, persistent ID ledger, timestamp tie resolution or live operational input validation.",
        "quality_position_contract": "Historical retained quality-input ordinal only. Never inferred from labels, current batch membership or physical Shot; live mapping unresolved."
    }
    write_new(output / "fixtures.json", {"valid_sequence": envelope(rows), "rejected_batches": {k: envelope(v) for k, v in bad_batches.items()}})
    write_new(output / "verification.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "checks"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--examples", type=Path)
    args = parser.parse_args()
    verify(args.root, args.output, args.examples)
