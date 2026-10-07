import hashlib, json
from pathlib import Path

root = Path.cwd()
source = root / "work/ceres-v4-evaluation/run-03"
output = root / "work/ceres-v4-evaluation/diagnostics-run03-v2"
evidence = root / "work/ceres-v4-evaluation/evidence/diag-run03-v2"
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
request_without_probe_flag = {k: v for k, v in new_request.items() if k != "chat_template_kwargs"}
body_text = result["response_body_text"]
body = result["response_body"]
message = body["choices"][0]["message"]
usage = body["usage"]
checks = {
    "runner_frozen_hash_match": manifest["runner_sha256"] == freeze["frozen_sha256"],
    "runner_source_hash_match": hashlib.sha256((root / "scripts/eval_v4_judge.py").read_bytes()).hexdigest() == freeze["frozen_sha256"],
    "source_manifest_hash_match": manifest["source_manifest_sha256"] == source_manifest_hash == freeze["source_manifest_sha256"],
    "source_R01_result_hash_match": result["source_result_sha256"] == source_result_hash == freeze["source_R01_r1_result_sha256"],
    "original_request_fields_unchanged": request_without_probe_flag == original_request,
    "serialized_request_matches_request": result["serialized_request"] == new_request,
    "serialized_wire_flag_false": result["serialized_request"]["chat_template_kwargs"]["enable_thinking"] is False,
    "serialized_request_sha256_recorded": len(result["serialized_request_sha256"]) == 64,
    "raw_response_hash_matches_text": hashlib.sha256(body_text.encode("utf-8")).hexdigest() == result["response_body_sha256"],
    "one_diagnostic_call": len(result["calls"]) == 1 and summary["completed"] == 1,
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
    "request_model": new_request.get("model"),
    "request_max_tokens": new_request.get("max_tokens"),
    "chat_template_kwargs": result["serialized_request"].get("chat_template_kwargs"),
    "serialized_request_sha256": result["serialized_request_sha256"],
    "response_status": result["response_status"],
    "response_body_sha256": result["response_body_sha256"],
    "response_body_json_saved": True,
    "response_model": body.get("model"),
    "finish_reason": body["choices"][0].get("finish_reason"),
    "visible_content": message.get("content"),
    "visible_content_length": len(message["content"]) if isinstance(message.get("content"), str) else 0,
    "reasoning_content_length": len(message["reasoning_content"]) if isinstance(message.get("reasoning_content"), str) else 0,
    "usage": usage,
    "verdict": result["result"]["verdict"],
    "error": result.get("error"),
    "summary": summary,
}
print(json.dumps(out, ensure_ascii=False, indent=2))
if not all(checks.values()):
    raise SystemExit(1)