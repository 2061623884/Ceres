import hashlib, json
from pathlib import Path

root = Path.cwd()
source = root / "work/ceres-v4-evaluation/run-03"
output = root / "work/ceres-v4-evaluation/diagnostics-run03-v3"
evidence = root / "work/ceres-v4-evaluation/evidence/diag-run03-v3"
freeze = json.loads((evidence / "runner-freeze.json").read_text(encoding="utf-8"))
manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
result_path = output / "R01-r1.json"
result = json.loads(result_path.read_text(encoding="utf-8"))
source_path = source / "R01-r1/result.json"
source_result = json.loads(source_path.read_text(encoding="utf-8"))
source_manifest_hash = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
source_result_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
original_request = source_result["judge"]["calls"][0]["request"]
new_request = result["request"]
original_without_max = {k: v for k, v in original_request.items() if k != "max_tokens"}
new_without_max = {k: v for k, v in new_request.items() if k != "max_tokens"}
changed_fields = sorted(k for k in set(original_request) | set(new_request) if original_request.get(k) != new_request.get(k))
body_text = result["response_body_text"]
body = result["response_body"]
message = body["choices"][0]["message"]
usage = body["usage"]
content = message["content"]
content_json = json.loads(content)
allowed_dimensions = {"completeness", "grounding", "clarification", "status"}
allowed_verdicts = {"pass", "fail", "unknown"}
schema_valid = (
    isinstance(content_json, dict)
    and content_json.get("verdict") in allowed_verdicts
    and isinstance(content_json.get("findings"), list)
    and all(
        isinstance(finding, dict)
        and finding.get("dimension") in allowed_dimensions
        and finding.get("verdict") in allowed_verdicts
        and isinstance(finding.get("evidence"), str)
        and isinstance(finding.get("reason"), str)
        for finding in content_json["findings"]
    )
)
checks = {
    "runner_frozen_hash_match": manifest["runner_sha256"] == freeze["frozen_sha256"],
    "runner_source_hash_match": hashlib.sha256((root / "scripts/eval_v4_judge.py").read_bytes()).hexdigest() == freeze["frozen_sha256"],
    "source_manifest_hash_match": manifest["source_manifest_sha256"] == source_manifest_hash == freeze["source_manifest_sha256"],
    "source_R01_result_hash_match": result["source_result_sha256"] == source_result_hash == freeze["source_R01_r1_result_sha256"],
    "only_max_tokens_changed": new_without_max == original_without_max and changed_fields == ["max_tokens"],
    "max_tokens_uses_effective_config": new_request["max_tokens"] == source_result["effective_configuration"]["llm_max_output_tokens"] == 3072,
    "thinking_parameters_unchanged": "chat_template_kwargs" not in new_request and "enable_thinking" not in new_request,
    "serialized_request_matches_request": result["serialized_request"] == new_request,
    "serialized_request_sha256_recorded": len(result["serialized_request_sha256"]) == 64,
    "response_status_ok": result["response_status"] == 200,
    "raw_response_hash_matches_text": hashlib.sha256(body_text.encode("utf-8")).hexdigest() == result["response_body_sha256"],
    "response_content_schema_valid": schema_valid,
    "parsed_result_matches_response": content_json == result["result"],
    "one_call_and_one_result": len(result["calls"]) == 1 and summary["completed"] == 1,
    "source_batch_unchanged": hashlib.sha256(source_path.read_bytes()).hexdigest() == result["source_result_sha256"],
    "no_product_tasks_reexecuted": summary["product_tasks_reexecuted"] == 0,
}
out = {
    "checks": checks,
    "all_checks_passed": all(checks.values()),
    "runner_sha256": manifest["runner_sha256"],
    "source_manifest_sha256": manifest["source_manifest_sha256"],
    "source_R01_result_sha256": result["source_result_sha256"],
    "diagnostic_output_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    "execution_id": result["execution_id"],
    "original_request_model": original_request.get("model"),
    "original_max_tokens": original_request.get("max_tokens"),
    "effective_llm_max_output_tokens": source_result["effective_configuration"]["llm_max_output_tokens"],
    "request_max_tokens": new_request.get("max_tokens"),
    "changed_request_fields": changed_fields,
    "serialized_request_sha256": result["serialized_request_sha256"],
    "response_status": result["response_status"],
    "response_model": body.get("model"),
    "finish_reason": body["choices"][0].get("finish_reason"),
    "content_length": len(content),
    "content_schema_valid": schema_valid,
    "verdict": result["result"]["verdict"],
    "findings": result["result"]["findings"],
    "usage": usage,
    "summary": summary,
}
print(json.dumps(out, ensure_ascii=False, indent=2))
if not all(checks.values()):
    raise SystemExit(1)