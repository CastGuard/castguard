"""Label-free, read-only inference and faithful explanations for frozen queue models.

No training tables, label files, policy selection, or automatic production actions
are used here. A versioned profile supplies train-only reference summaries.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from scipy.special import expit
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

SCHEMA = "castguard-shot-v1"
PROCESS = ["Velocity_1", "Velocity_2", "Velocity_3", "High_Velocity",
           "Cylinder_Pressure", "Rapid_Rise_Time", "Biscuit_Thickness",
           "Clamping_Force", "Cycle_Time", "Pressure_Rise_Time", "Casting_Pressure",
           "Spray_Time", "Spray_1_Time", "Spray_2_Time"]
SENSORS = ["Melting_Furnace_Temp", "Air_Pressure", "Coolant_Temp",
           "Coolant_Pressure", "Factory_Temp", "Factory_Humidity"]
QUALITY = PROCESS + SENSORS + ["Product_Type", "shot_position"]
GATE = PROCESS + ["prev_cycle_time", "max_cycle_previous_5"]
POSITION_BASIS = "legacy_quality_input_order"
TOLERANCE = 1e-6
MAX_EXACT_INTEGER = 2**53 - 1


class ContractError(ValueError):
    """Invalid input envelope, profile, or frozen artifact; inference must stop."""


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(value):
        raise ContractError(f"Nonstandard JSON numeric constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=_pairs, parse_constant=invalid_constant)


def _keys(value, allowed, where, required=()):
    if not isinstance(value, dict):
        raise ContractError(f"{where}: expected object")
    extra, missing = set(value) - set(allowed), set(required) - set(value)
    if extra:
        raise ContractError(f"{where}: forbidden or unknown fields: {sorted(extra)}")
    if missing:
        raise ContractError(f"{where}: missing fields: {sorted(missing)}")


def _integer(value, where, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_EXACT_INTEGER:
        raise ContractError(f"{where}: expected integer in [{minimum}, {MAX_EXACT_INTEGER}]")
    return value


def _identifier(value, where):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"{where}: expected nonempty string without surrounding whitespace")
    return value


def _number(value, where, nullable=True):
    if value is None and nullable:
        return None
    if type(value) not in (int, float):
        raise ContractError(f"{where}: expected JSON number, not string/bool")
    try:
        valid = math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    if not valid:
        raise ContractError(f"{where}: value must be finite")
    return float(value)


def parse_record(record):
    _keys(record, ["record_id", "observation", "measurements", "history"], "record",
          ["record_id", "observation", "measurements"])
    _identifier(record["record_id"], "record_id")
    observation = record["observation"]
    _keys(observation, ["run_key", "sequence", "quality_record_position", "position_basis"],
          "observation", ["run_key", "sequence"])
    _identifier(observation["run_key"], "observation.run_key")
    sequence = _integer(observation["sequence"], "observation.sequence")
    position = observation.get("quality_record_position")
    if position is not None:
        _integer(position, "observation.quality_record_position")
        if position > sequence:
            raise ContractError("quality_record_position cannot exceed the process observation sequence")
    basis = observation.get("position_basis")
    if basis is not None and not isinstance(basis, str):
        raise ContractError("observation.position_basis: expected string or null")
    measurements = record["measurements"]
    _keys(measurements, PROCESS + SENSORS + ["Product_Type"], "measurements")
    values = {name: _number(value, f"measurements.{name}") for name, value in measurements.items()}
    if measurements.get("Product_Type") is not None:
        _integer(measurements["Product_Type"], "measurements.Product_Type", minimum=1)
    values["shot_position"] = float(position) if position is not None else None
    history = record.get("history")
    if history is not None:
        if not isinstance(history, list):
            raise ContractError("history: expected list or null (unknown history)")
        expected = list(range(max(0, sequence - 5), sequence))
        if len(history) != len(expected):
            raise ContractError("history: provide exactly the preceding min(sequence, 5) process observations")
        cycles = []
        for item, seq in zip(history, expected):
            _keys(item, ["run_key", "sequence", "Cycle_Time"], "history item",
                  ["run_key", "sequence", "Cycle_Time"])
            _integer(item["sequence"], "history.sequence")
            if item["sequence"] != seq or item["run_key"] != observation["run_key"]:
                raise ContractError("history: observations must precede the current record, in order, in the same run")
            cycles.append(_number(item["Cycle_Time"], "history.Cycle_Time"))
        values["prev_cycle_time"] = cycles[-1] if cycles else None
        finite_cycles = [x for x in cycles if x is not None]
        values["max_cycle_previous_5"] = max(finite_cycles) if finite_cycles else None
    return values, history is not None, basis


def validate_batch_context(records, parsed):
    """Reject contradictory packet assertions before any scoring.

    Packets carry their own history. Batch position never creates features.
    This checks only evidence present in this call, not a persistent event log.
    """
    events, cycle_claims, quality_positions = {}, {}, {}
    for record, item in zip(records, parsed):
        if not isinstance(record, dict) or not isinstance(record.get("observation"), dict):
            continue
        obs = record["observation"]
        run, sequence = obs.get("run_key"), obs.get("sequence")
        if isinstance(run, str) and type(sequence) is int:
            key = (run, sequence)
            if key in events:
                raise ContractError(f"Duplicate observation (run_key, sequence): {key}; use a separate call for alternative scenarios")
            events[key] = record.get("record_id")
        if isinstance(item, Exception):
            continue
        values, _, basis = item
        claims = [(h["run_key"], h["sequence"], h["Cycle_Time"]) for h in record.get("history") or []]
        if "Cycle_Time" in record["measurements"]:
            claims.append((run, sequence, record["measurements"]["Cycle_Time"]))
        for claim_run, claim_sequence, cycle in claims:
            key = (claim_run, claim_sequence)
            if key in cycle_claims and cycle_claims[key] != cycle:
                raise ContractError(f"Conflicting Cycle_Time assertions for observation {key}; no first/last-row tie rule")
            cycle_claims[key] = cycle
        if basis == POSITION_BASIS and values["shot_position"] is not None:
            quality_positions.setdefault(run, []).append((sequence, obs["quality_record_position"]))
    for run, positions in quality_positions.items():
        ordered = sorted(positions)
        for (seq_a, pos_a), (seq_b, pos_b) in zip(ordered, ordered[1:]):
            if not 0 < pos_b - pos_a <= seq_b - seq_a:
                raise ContractError(f"Inconsistent historical quality positions in run {run!r}: counters must increase with process order without exceeding its increment")


def _model_check(payload, descriptor, features):
    for key in ["fold", "seed", "task", "model"]:
        if payload.get(key) != descriptor.get(key):
            raise ContractError(f"Frozen artifact identity mismatch: {key}")
    if payload.get("features") != features:
        raise ContractError("Frozen model feature schema mismatch")
    pipeline = payload.get("pipeline")
    family = descriptor["model"]
    expected_steps = ["impute", "scale", "model"] if family == "logistic" else ["impute", "model"]
    if not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != expected_steps:
        raise ContractError("Unsupported preprocessing pipeline")
    imputer = pipeline.named_steps["impute"]
    if not isinstance(imputer, SimpleImputer) or imputer.strategy != "median":
        raise ContractError("Unsupported imputer")
    if list(pipeline.feature_names_in_) != features:
        raise ContractError("Pipeline feature order mismatch")
    model = pipeline.named_steps["model"]
    if family == "logistic":
        if not isinstance(model, LogisticRegression) or not isinstance(pipeline.named_steps["scale"], StandardScaler):
            raise ContractError("Unsupported logistic adapter")
    elif family == "lightgbm":
        if not isinstance(model, LGBMClassifier):
            raise ContractError("Unsupported LightGBM adapter")
    else:
        raise ContractError(f"Unsupported model family: {family}")
    if list(model.classes_) != [0, 1]:
        raise ContractError("Only binary classes [0, 1] are supported")
    return pipeline


def explain(pipeline, family, features, values):
    frame = pd.DataFrame([[values.get(name) for name in features]], columns=features, dtype=float)
    with threadpool_limits(limits=1):
        transformed = pipeline[:-1].transform(frame)
        transformed_array = np.asarray(transformed, dtype=float)
        if transformed_array.shape != (1, len(features)) or not np.isfinite(transformed_array).all():
            raise ContractError("Preprocessing produced invalid values or changed feature dimensions")
        model = pipeline.named_steps["model"]
        score = float(pipeline.predict_proba(frame)[0, 1])
        if family == "logistic":
            baseline = float(model.intercept_[0])
            contributions = transformed_array[0] * model.coef_[0]
            margin = float(model.decision_function(transformed)[0])
            method = "linear_margin_decomposition"
            baseline_description = "intercept at zero standardized coordinates; not SHAP expected value"
        elif family == "lightgbm":
            parts = np.asarray(model.booster_.predict(transformed, pred_contrib=True), dtype=float)[0]
            contributions, baseline = parts[:-1], float(parts[-1])
            margin = float(model.booster_.predict(transformed, raw_score=True)[0])
            method = "lightgbm_native_tree_shap"
            baseline_description = "native TreeSHAP expected raw margin"
        else:
            raise ContractError("Unsupported explanation adapter")
    reconstructed = float(baseline + np.sum(contributions))
    margin_error = abs(reconstructed - margin)
    score_error = abs(float(expit(reconstructed)) - score)
    numbers = [score, baseline, margin, reconstructed, margin_error, score_error, *contributions]
    if not np.isfinite(numbers).all() or not 0 <= score <= 1:
        raise ContractError("Model produced nonfinite or invalid output")
    if margin_error > TOLERANCE or score_error > TOLERANCE:
        raise ContractError("Explanation does not reconstruct the actual model output")
    return score, {
        "method": method, "scale": "log_odds_of_encoded_class_1", "causal": False,
        "baseline_description": baseline_description, "baseline_margin": baseline,
        "raw_margin": margin, "reconstructed_margin": reconstructed,
        "reconstructed_score": float(expit(reconstructed)), "margin_error": margin_error,
        "score_error": score_error, "tolerance": TOLERANCE,
        "contributions": [{"feature": name, "input_value": values.get(name),
            "model_input_value": float(transformed_array[0, i]),
            "was_imputed": values.get(name) is None, "contribution": float(contributions[i])}
            for i, name in enumerate(features)]}


class DecisionReviewer:
    def __init__(self, root, checkpoint="queue-fold2-seed17", config=None):
        self.root = Path(root).resolve()
        self.config = read_json(config or self.root / "configs/decision_review.json")
        if self.config.get("schema_version") != "castguard-review-profile-v1" or self.config.get("input_schema") != SCHEMA:
            raise ContractError("Unsupported profile/input schema combination")
        if checkpoint not in self.config.get("checkpoints", {}):
            raise ContractError(f"Unknown checkpoint: {checkpoint}")
        self.checkpoint = checkpoint
        self.profile = self.config["checkpoints"][checkpoint]
        self.models = {}
        for task, features in [("quality", QUALITY), ("gate", GATE)]:
            descriptor = self.profile[task]
            if descriptor.get("features") != features or descriptor.get("task") != task:
                raise ContractError(f"Unsupported {task} feature schema")
            if descriptor.get("model") not in ["logistic", "lightgbm"]:
                raise ContractError("Unsupported model family")
            if set(descriptor.get("ranges", {})) != set(features):
                raise ContractError("Incomplete training reference feature schema")
            for name, bounds in descriptor["ranges"].items():
                if bounds is not None:
                    if not isinstance(bounds, list) or len(bounds) != 2:
                        raise ContractError(f"Invalid reference bounds: {name}")
                    low, high = [_number(v, f"reference.{name}", nullable=False) for v in bounds]
                    if low > high:
                        raise ContractError(f"Reversed reference bounds: {name}")
            reference = descriptor.get("training_reference", {})
            _integer(reference.get("rows"), "training_reference.rows", minimum=1)
            if reference.get("partition") != "inner_fit_only":
                raise ContractError("Applicability references must use inner fit only")
            if task == "quality":
                products = reference.get("products")
                if not isinstance(products, list) or not products:
                    raise ContractError("Missing quality product reference")
                for product in products:
                    _integer(product, "training_reference.products", minimum=1)
            else:
                threshold = descriptor.get("threshold", {})
                if type(threshold.get("disabled")) is not bool:
                    raise ContractError("Invalid frozen alarm state")
                if not threshold["disabled"]:
                    value = _number(threshold.get("threshold"), "alarm.threshold", nullable=False)
                    if not 0 <= value <= np.nextafter(1., np.inf):
                        raise ContractError("Frozen alarm threshold outside score range")
            path = (self.root / descriptor["path"]).resolve()
            if not path.is_relative_to((self.root / "reports/oct03_queue/models").resolve()):
                raise ContractError("Model must be a locally pinned frozen queue artifact")
            if not path.is_file() or digest(path) != descriptor["sha256"]:
                raise ContractError(f"Missing or changed frozen model: {descriptor['path']}")
            # joblib is loaded only after verifying the explicitly pinned local artifact.
            payload = joblib.load(path)
            self.models[task] = _model_check(payload, descriptor, features)

    def _stage(self, task, values, history_known, position_basis):
        descriptor = self.profile[task]
        features = QUALITY if task == "quality" else GATE
        required = QUALITY if task == "quality" else PROCESS
        reasons = [{"code": "missing_input", "feature": name} for name in required if values.get(name) is None]
        if task == "quality" and position_basis != POSITION_BASIS:
            reasons.append({"code": "unsupported_position_basis", "required": POSITION_BASIS})
        if task == "gate" and not history_known:
            reasons.append({"code": "unknown_process_history"})
        stage = {"status": "not_scored", "score": None, "encoded_target": descriptor["encoded_target"],
                 "calibrated": False, "reasons": reasons, "warnings": [], "explanation": None,
                 "score_interpretation": "unavailable",
                 "model_id": Path(descriptor["path"]).stem, "model_sha256": descriptor["sha256"],
                 "training_reference": descriptor["training_reference"]}
        if reasons:
            return stage
        warnings = []
        if task == "quality" and values["Product_Type"] not in descriptor["training_reference"]["products"]:
            warnings.append({"code": "unseen_product", "value": values["Product_Type"]})
        for name, bounds in descriptor["ranges"].items():
            value = values.get(name)
            if value is not None and bounds is not None and not bounds[0] <= value <= bounds[1]:
                warnings.append({"code": "outside_training_marginal_range", "feature": name,
                                 "value": value, "training_min": bounds[0], "training_max": bounds[1]})
        try:
            score, explanation = explain(self.models[task], descriptor["model"], features, values)
        except (ValueError, TypeError, FloatingPointError, OverflowError) as error:
            stage["reasons"] = [{"code": "inference_or_explanation_failure", "detail": str(error)}]
            return stage
        stage.update(status="scored", score=score, explanation=explanation, warnings=warnings,
                     score_interpretation="diagnostic_only_uncalibrated_model_output",
                     applicability="outside_reference" if warnings else "within_recorded_marginal_reference",
                     joint_support="not_assessed", operational_recommendation="abstain")
        if task == "gate":
            threshold = descriptor["threshold"]
            stage["alarm"] = {"status": "disabled" if threshold["disabled"] else "research_threshold_comparison",
                              "value": None if threshold["disabled"] else score >= threshold["threshold"],
                              "threshold": threshold["threshold"], "reason": threshold["reason"],
                              "physical_state_code_mapping": "unverified", "production_stop": False}
        return stage

    def review(self, envelope):
        _keys(envelope, ["schema_version", "records"], "input", ["schema_version", "records"])
        if envelope["schema_version"] != SCHEMA:
            raise ContractError(f"Unsupported input schema; expected {SCHEMA}")
        records = envelope["records"]
        if not isinstance(records, list) or not records:
            raise ContractError("records: expected nonempty list")
        identifiers = [record.get("record_id") for record in records if isinstance(record, dict)]
        valid_ids = [value for value in identifiers if isinstance(value, str)]
        if len(set(valid_ids)) != len(valid_ids):
            raise ContractError("record_id must be unique within a batch")
        parsed = []
        for record in records:
            try:
                parsed.append(parse_record(record))
            except (ContractError, OverflowError) as error:
                parsed.append(error)
        validate_batch_context(records, parsed)
        outputs = []
        for index, (record, item) in enumerate(zip(records, parsed)):
            output = {"record_index": index, "record_id": record.get("record_id") if isinstance(record, dict) else None}
            if isinstance(item, Exception):
                output.update(status="invalid_input", errors=[str(item)], quality=None, equipment_state=None)
            else:
                values, history_known, basis = item
                quality = self._stage("quality", values, history_known, basis)
                gate = self._stage("gate", values, history_known, basis)
                output.update(status="reviewed", errors=[], quality=quality, equipment_state=gate,
                              observation=dict(record["observation"]),
                              input_support={"order_authority": "caller_supplied_process_ordinal",
                                "run_partition": "caller_asserted_not_independently_verified",
                                "quality_position_use": "retrospective_only" if basis == POSITION_BASIS else "unsupported",
                                "history_status": "explicit_packet" if history_known else "unknown",
                                "history_missing_cycle_values": sum(h["Cycle_Time"] is None for h in record.get("history") or []),
                                "history_product_filter": "none_all_process_observations_in_run"},
                              action="human_review_only_no_automatic_control",
                              applicability_notes=["Marginal training ranges do not establish joint or physical support.",
                                "Product/run shift is a warning, not a causal diagnosis or measured policy improvement."])
            outputs.append(output)
        return {"schema_version": "castguard-review-v1", "checkpoint": self.checkpoint,
                "input_contract_revision": "order-consistency-2026-10-05",
                "invocation_contract": {"mode": "stateless_explicit_history_packets",
                    "batch_order_affects_features": False, "cross_call_consistency_checked": False,
                    "batch_conflict_policy": "reject_entire_call_before_scoring",
                    "event_identity": ["run_key", "sequence"],
                    "timestamps_or_arrival_order_supported_as_feature_order": False},
                "scope": "frozen_model_research_replay", "calibrated_probabilities": False,
                "live_input_availability_verified": False, "performance_improvement_claimed": False,
                "notes": ["Scores are uncalibrated model outputs, not verified defect probabilities.",
                          "Contribution units are log-odds of encoded class 1, not percentage points or causality.",
                          "Quality position is a legacy input-file counter, not physical Shot or process sequence.",
                          "State code semantics, physical units and joint support remain unverified.",
                          "No labels, training tables or evaluation outcomes are read by this inference command."],
                "records": outputs}


def render_html(result):
    def esc(value):
        return html.escape(str(value))
    cards = []
    for record in result["records"]:
        content = [f'<article><h2>{esc(record["record_id"])}</h2><p>{esc(record["status"])}</p>']
        if record.get("observation"):
            content.append(f'<p class="model">입력 순서: {esc(json.dumps(record["observation"], ensure_ascii=False))}</p>')
        if record["errors"]:
            content.append(f'<pre>{esc(json.dumps(record["errors"], ensure_ascii=False))}</pre>')
        for key, title in [("quality", "품질 위험 점수"), ("equipment_state", "설비 상태1 점수")]:
            stage = record.get(key)
            if not stage:
                continue
            content.append(f'<h3>{title}: {esc(stage["score"])}</h3>')
            if stage["score"] is not None:
                content.append('<p class="warning"><strong>진단용 미보정 점수 · 검증된 불량 확률 아님</strong></p>')
            if any(w.get("code") == "unseen_product" for w in stage["warnings"]):
                content.append('<p class="warning"><strong>미학습 제품: 적용 성능 미검증 · 운영 판단 보류</strong></p>')
            content.append(f'<p>{esc(stage["status"])} · {esc(stage.get("applicability", "판독 보류"))}</p>')
            content.append(f'<p class="model">{esc(stage["model_id"])}</p>')
            if stage["reasons"] or stage["warnings"]:
                content.append(f'<pre>{esc(json.dumps(stage["reasons"]+stage["warnings"],ensure_ascii=False,indent=2))}</pre>')
            if stage.get("alarm"):
                content.append(f'<p>경보 비교: {esc(json.dumps(stage["alarm"],ensure_ascii=False))}</p>')
            explanation = stage.get("explanation")
            if explanation:
                rows = sorted(explanation["contributions"], key=lambda v: -abs(v["contribution"]))
                content.append('<details open><summary>개별 기여 · log-odds (확률 %p가 아님)</summary><table><tr><th>변수</th><th>입력</th><th>기여</th></tr>')
                content.extend(f'<tr><td>{esc(v["feature"])}</td><td>{esc(v["input_value"])}</td><td>{v["contribution"]:+.6f}</td></tr>' for v in rows)
                content.append(f'</table><p>기준값 {explanation["baseline_margin"]:.6f} · 합 재구성 오차 {explanation["margin_error"]:.2g}</p></details>')
        content.append('</article>')
        cards.append(''.join(content))
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>CastGuard 판독</title>
<style>body{font-family:Segoe UI,Malgun Gothic,sans-serif;margin:2rem auto;max-width:1100px;background:#f5f7fa;color:#14293c;padding:0 1rem}article{background:white;border:1px solid #d6dfe8;border-radius:12px;padding:1.4rem;margin:1.4rem 0}h1,h2{color:#174a64}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f6;padding:1rem}table{border-collapse:collapse;width:100%}td,th{padding:.4rem;text-align:left;border-bottom:1px solid #ddd}.model{font-size:.85rem;overflow-wrap:anywhere}.warning{color:#8a3600;background:#fff4e5;padding:.65rem;border-left:4px solid #bd5b00}</style>
<h1>CastGuard · 정답 없는 입력의 판독</h1><p>동결 모델 연구 재생 · 점수는 미보정 · 기여는 인과/제어 효과가 아님</p>
<p>학습 범위 안이라는 표시는 개별 변수의 관측 범위만 뜻합니다. 실제 수신시각·공동지지·현장 성능은 미검증이며 자동조치를 권고하지 않습니다.</p>
<p>입력은 각 행의 고정 순서와 직전 이력을 사용합니다. 화면 행 순서는 특징을 바꾸지 않습니다. 호출 사이의 중복·이력 충돌은 추적하지 않으며, 품질 입력 순서는 과거 자료 재생 전용입니다.</p>''' + f'<p>{esc(result["checkpoint"])}</p>' + ''.join(cards) + '</html>\n'


def main(root=None):
    parser = argparse.ArgumentParser(description="Read label-free shot JSON with frozen models; never train or overwrite outputs.")
    parser.add_argument("--root", type=Path, default=root or Path(__file__).resolve().parents[1])
    parser.add_argument("--checkpoint", default="queue-fold2-seed17")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--html", type=Path)
    args = parser.parse_args()
    try:
        paths = [p.resolve() for p in [args.output, args.html] if p is not None]
        if len(set(paths)) != len(paths) or any(p.exists() for p in paths):
            raise ContractError("Output files must be distinct new paths; existing files are preserved")
        reviewer = DecisionReviewer(args.root, args.checkpoint)
        result = reviewer.review(read_json(args.input))
        payloads = [json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"]
        if args.html:
            payloads.append(render_html(result))
        for path in paths:
            if not path.parent.is_dir():
                raise ContractError(f"Output parent directory does not exist: {path.parent}")
        for path, content in zip(paths, payloads):
            with path.open("x", encoding="utf-8", newline="\n") as f:
                f.write(content)
        print(json.dumps({"output": str(args.output), "records": len(result["records"]),
            "invalid_records": sum(r["status"] == "invalid_input" for r in result["records"]),
            "checkpoint": args.checkpoint}, ensure_ascii=False))
    except (ContractError, OSError, ValueError, KeyError) as error:
        parser.exit(2, f"CastGuard review failed: {error}\n")


if __name__ == "__main__":
    main()
