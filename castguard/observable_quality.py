"""Explicit current-process-only inference with one existing frozen A0 baseline.

No quality-file row counter, labels, history, training table or automatic fallback.
Input capability does not establish live acquisition or prospective performance.
"""
from pathlib import Path
import argparse
import html
import json
import joblib

from .decision_review import (PROCESS, ContractError, digest, read_json, _keys, _number,
                              _integer, _identifier, _model_check, explain)

SCHEMA = "castguard-observable-quality-v1"
TASK = {"dataset": "q42", "population": "all", "scheme": "forward_run", "fold": "2",
        "experiment": "A0", "model": "logistic", "seed": 17}
MODEL_PATH = "artifacts/14b7926791a139eb/q42__all__forward_run__2__A0__logistic__17/model.joblib"
BASIS = "same_completed_shot"


def parse_record(record):
    _keys(record, ["record_id", "observation_basis", "measurements", "context"], "record",
          ["record_id", "observation_basis", "measurements"])
    _identifier(record["record_id"], "record_id")
    if record["observation_basis"] != BASIS:
        raise ContractError(f"observation_basis must be {BASIS}; current complete-shot measurements only")
    _keys(record["measurements"], PROCESS, "measurements")
    values = {k: _number(v, f"measurements.{k}") for k, v in record["measurements"].items()}
    context = record.get("context", {})
    _keys(context, ["product_type"], "context")
    product = context.get("product_type")
    if product is not None:
        _integer(product, "context.product_type", minimum=1)
    return values, product


class ObservableQualityReviewer:
    def __init__(self, root, config=None):
        self.root = Path(root).resolve()
        self.profile = read_json(config or self.root / "configs/observable_quality.json")
        p = self.profile
        if p.get("schema_version") != "castguard-observable-profile-v1" or p.get("input_schema") != SCHEMA:
            raise ContractError("Unsupported observable quality profile/schema")
        if p.get("task") != TASK or p.get("features") != PROCESS or p.get("path") != MODEL_PATH:
            raise ContractError("Only the explicitly pinned process14 A0 baseline is supported; no fallback")
        if set(p.get("ranges", {})) != set(PROCESS):
            raise ContractError("Incomplete process training reference")
        for name, bounds in p["ranges"].items():
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ContractError(f"Invalid training range: {name}")
            low, high = [_number(v, name, nullable=False) for v in bounds]
            if low > high:
                raise ContractError("Reversed training range")
        ref = p.get("training_reference", {})
        if ref.get("partition") != "original_forward_run_train":
            raise ContractError("Unsupported reference partition")
        _integer(ref.get("rows"), "training_reference.rows", minimum=1)
        if not isinstance(ref.get("products"), list) or not ref["products"]:
            raise ContractError("Missing training product reference")
        for product in ref["products"]:
            _integer(product, "training_reference.products", minimum=1)
        path = (self.root / MODEL_PATH).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or digest(path) != p["sha256"]:
            raise ContractError("Missing or changed pinned A0 model; no historical counter fallback")
        payload = joblib.load(path)
        if payload.get("task") != TASK or payload.get("features") != PROCESS or payload.get("learned") != {}:
            raise ContractError("Frozen A0 payload identity/features/learned transforms mismatch")
        descriptor = {"fold": TASK["fold"], "seed": TASK["seed"], "task": "quality", "model": "logistic"}
        adapted = {**descriptor, "features": PROCESS, "pipeline": payload["pipeline"]}
        self.pipeline = _model_check(adapted, descriptor, PROCESS)

    def review(self, envelope):
        _keys(envelope, ["schema_version", "records"], "input", ["schema_version", "records"])
        if envelope["schema_version"] != SCHEMA:
            raise ContractError(f"Explicit observable input schema required: {SCHEMA}; no automatic path switch")
        rows = envelope["records"]
        if not isinstance(rows, list) or not rows:
            raise ContractError("records must be nonempty")
        ids = [r.get("record_id") for r in rows if isinstance(r, dict) and isinstance(r.get("record_id"), str)]
        if len(ids) != len(set(ids)):
            raise ContractError("record_id must be unique within a call")
        outputs = []
        for index, record in enumerate(rows):
            out = {"record_index": index, "record_id": record.get("record_id") if isinstance(record, dict) else None,
                   "status": "not_scored", "score": None, "explanation": None, "reasons": [], "warnings": [],
                   "score_interpretation": "diagnostic_only_uncalibrated_model_output",
                   "calibrated": False, "operational_recommendation": "abstain"}
            try:
                values, product = parse_record(record)
            except (ContractError, OverflowError) as error:
                out.update(status="invalid_input", reasons=[{"code": "invalid_input", "detail": str(error)}])
            else:
                out["context"] = {"product_type": product, "used_as_model_feature": False}
                missing = [f for f in PROCESS if values.get(f) is None]
                if missing:
                    out["reasons"] = [{"code": "missing_current_process_input", "feature": f} for f in missing]
                else:
                    if product is None:
                        out["warnings"].append({"code": "product_support_unknown", "detail": "Product identity is not in the process feed; not inferred from sequence or labels"})
                    elif product not in self.profile["training_reference"]["products"]:
                        out["warnings"].append({"code": "unseen_product", "value": product})
                    for name, (low, high) in self.profile["ranges"].items():
                        if not low <= values[name] <= high:
                            out["warnings"].append({"code": "outside_training_marginal_range", "feature": name,
                                                    "value": values[name], "training_min": low, "training_max": high})
                    try:
                        score, explanation = explain(self.pipeline, "logistic", PROCESS, values)
                    except (ValueError, TypeError, FloatingPointError, OverflowError) as error:
                        out["reasons"] = [{"code": "inference_or_explanation_failure", "detail": str(error)}]
                    else:
                        out.update(status="scored", score=score, explanation=explanation,
                                   applicability="warning_or_unknown_support" if out["warnings"] else "within_recorded_marginal_reference",
                                   joint_support="not_assessed")
            outputs.append(out)
        return {"schema_version": "castguard-observable-review-v1", "path": "explicit_process14_A0",
                "model": {"task": TASK, "path": MODEL_PATH, "sha256": self.profile["sha256"],
                          "features": PROCESS, "selection_rule": self.profile["selection_rule"]},
                "input_capability": {"current_observations_only": True, "quality_row_counter_required": False,
                    "process_counter_required": False, "history_required": False, "label_file_required": False,
                    "observation_lookup_performed": False, "batch_or_arrival_order_affects_score": False,
                    "same_shot_field_alignment": "caller_asserted", "live_acquisition_timing_verified": False},
                "scope": "prospective_input_capable_frozen_baseline_not_prospectively_validated",
                "encoded_target": "any_recorded_quality_defect_equals_1", "calibrated_probabilities": False,
                "performance_improvement_claimed": False, "automatic_policy_change": False,
                "training_reference": self.profile["training_reference"],
                "historical_metrics": self.profile.get("historical_metrics", []),
                "notes": ["Uses fourteen measurements of one completed shot; no quality file or derived counter.",
                    "A0 was trained on the historical quality-observed cohort, not all future production.",
                    "Functional input capability is not predictive usefulness; inspect the preserved validation/test metrics.",
                    "All scores are diagnostic and uncalibrated. No production action or threshold is selected.",
                    "Legacy A/queue historical replay remains separate and is never a fallback."], "records": outputs}


def render_html(result):
    esc = lambda value: html.escape(str(value))
    cards = []
    metric_rows = [r for r in result.get("historical_metrics", []) if r["role"] == "validation"]
    comparison = ''
    if metric_rows:
        comparison = '<h2>기존 저장 검증구간 비교 · 새 실험 아님</h2><table><tr><th>모델 입력</th><th>ROC-AUC</th><th>AP</th><th>Brier</th><th>불량률</th></tr>'
        for r in metric_rows:
            comparison += f'<tr><td>{esc(r["experiment"])} / logistic seed17</td><td>{r["roc_auc"]:.4f}</td><td>{r["average_precision"]:.4f}</td><td>{r["brier"]:.4f}</td><td>{r["prevalence"]:.4f}</td></tr>'
        comparison += '</table><p>동일 forward fold2의 기존 validation입니다. 현재 모델은 입력 가용성으로 선택했으며 A/B·대기열의 기존 모델을 교체하거나 정책을 변경하지 않았습니다.</p>'
    for row in result["records"]:
        card = [f'<article><h2>{esc(row["record_id"])}</h2><p>{esc(row["status"])}</p>',
                f'<h3>공정14 품질 점수: {esc(row["score"])}</h3>',
                '<p class="warning"><strong>진단용 미보정 점수 · 검증된 불량 확률 아님 · 운영 판단 보류</strong></p>']
        if row["warnings"] or row["reasons"]:
            card.append('<pre>'+esc(json.dumps(row["reasons"]+row["warnings"], ensure_ascii=False, indent=2))+'</pre>')
        e = row["explanation"]
        if e:
            card.append('<details open><summary>개별 설명 · log-odds (확률 %p/인과 아님)</summary><table><tr><th>변수</th><th>입력</th><th>기여</th></tr>')
            card.extend(f'<tr><td>{esc(v["feature"])}</td><td>{esc(v["input_value"])}</td><td>{v["contribution"]:+.6f}</td></tr>'
                        for v in sorted(e["contributions"], key=lambda v: -abs(v["contribution"])))
            card.append(f'</table><p>기준값 {e["baseline_margin"]:.6f} · margin 재구성 오차 {e["margin_error"]:.2g} · 점수 재구성 오차 {e["score_error"]:.2g}</p></details>')
        cards.append(''.join(card)+'</article>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8"><title>CastGuard 공정 관측 입력 판독</title>
<style>body{font-family:Segoe UI,Malgun Gothic,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#f5f7fa;color:#14293c}article{background:white;border:1px solid #d6dfe8;border-radius:12px;padding:1.4rem;margin:1.4rem 0}h1,h2{color:#174a64}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f4f6;padding:1rem}table{border-collapse:collapse;width:100%}td,th{padding:.4rem;border-bottom:1px solid #ddd;text-align:left}.warning{color:#8a3600;background:#fff4e5;padding:.65rem;border-left:4px solid #bd5b00}</style>
<h1>CastGuard · 공정 관측값만으로 품질 판독</h1>
<p>기존 A0 동결 모델 · 완료된 동일 Shot의 공정값 14개 · 품질 정답/행 순서/과거 이력 불필요</p>
<p>새 관측 형식의 입력을 처리하는 기능입니다. 실제 현장 수신과 미래 성능은 검증하지 않았습니다. 기존 A/queue 재생 경로와 별도이며 자동 전환하지 않습니다.</p>
<p class="warning">관측 입력으로 계산할 수 있다는 것과 유용한 예측 성능은 별개입니다. 기존 AP·불량률·Brier와 적용 한계를 함께 확인하세요.</p>''' + comparison + ''.join(cards) + '</html>\n'


def main(root=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=root or Path(__file__).resolve().parents[1])
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--html", type=Path)
    args = p.parse_args()
    try:
        paths = [x.resolve() for x in [args.output, args.html] if x is not None]
        if len(set(paths)) != len(paths) or any(x.exists() for x in paths):
            raise ContractError("Distinct new output paths required; existing files preserved")
        if any(not x.parent.is_dir() for x in paths):
            raise ContractError("Output parent directory must exist")
        result = ObservableQualityReviewer(args.root).review(read_json(args.input))
        contents = [json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n']
        if args.html:
            contents.append(render_html(result))
        for path, content in zip(paths, contents):
            with path.open('x', encoding='utf-8', newline='\n') as f:
                f.write(content)
        print(json.dumps({"output": str(args.output), "records": len(result["records"]), "path": result["path"]}))
    except (ContractError, OSError, ValueError, KeyError) as error:
        p.exit(2, f"Observable quality review failed: {error}\n")
