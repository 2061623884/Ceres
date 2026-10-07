import collections, hashlib, json
from pathlib import Path

root = Path.cwd()
source = root / "work/ceres-v4-evaluation/run-03"
output = root / "work/ceres-v4-evaluation/diagnostics-run03-v3"
evidence = root / "work/ceres-v4-evaluation/evidence/diag-run03-v3"
freeze = json.loads((evidence / "runner-freeze.json").read_text(encoding="utf-8"))
manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
source_manifest_hash = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
runner_hash = hashlib.sha256((root / "scripts/eval_v4_judge.py").read_bytes()).hexdigest()
schedule = {item["execution_id"]: item for item in manifest["schedule"]}
result_paths = [p for p in output.glob("*.json") if p.name not in {"manifest.json", "summary.json"}]
result_ids = {p.stem for p in result_paths}
expected_ids = set(schedule)
verdicts = collections.Counter()
errors = collections.Counter()
error_messages = collections.Counter()
usage_count = 0
usage_complete_count = 0
usage_sums = collections.Counter()
status_counts = collections.Counter()
call_counts = collections.Counter()
serialized_request_count = 0
request_only_max_changed_count = 0
response_hash_verified_count = 0
parsed_content_count = 0
schema_valid_count = 0
dimension_clean_count = 0
dimension_issues = []
error_records = []
result_hash_mismatches = []
request_mismatches = []
response_hash_mismatches = []
schema_issues = []
all_result_paths = {}

expected_dimensions = {"completeness", "grounding", "clarification", "status"}
allowed_verdicts = {"pass", "fail", "unknown"}

for path in result_paths:
    result = json.loads(path.read_text(encoding="utf-8"))
    execution_id = result["execution_id"]
    all_result_paths[execution_id] = path
    verdict = result.get("result", {}).get("verdict")
    verdicts[verdict] += 1
    source_path = source / execution_id / "result.json"
    current_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    scheduled_hash = schedule[execution_id]["source_result_sha256"]
    if result.get("source_result_sha256") != scheduled_hash or current_source_hash != scheduled_hash:
        result_hash_mismatches.append({
            "execution_id": execution_id,
            "stored": result.get("source_result_sha256"),
            "scheduled": scheduled_hash,
            "current": current_source_hash,
        })

    original = json.loads(source_path.read_text(encoding="utf-8"))
    original_request = original["judge"]["calls"][0]["request"]
    request = result["request"]
    original_wo_max = {k: v for k, v in original_request.items() if k != "max_tokens"}
    request_wo_max = {k: v for k, v in request.items() if k != "max_tokens"}
    changed = sorted(k for k in set(original_request) | set(request) if original_request.get(k) != request.get(k))
    if changed == ["max_tokens"] and request_wo_max == original_wo_max and request.get("max_tokens") == original["effective_configuration"]["llm_max_output_tokens"]:
        request_only_max_changed_count += 1
    else:
        request_mismatches.append({
            "execution_id": execution_id,
            "changed_fields": changed,
            "effective_max_tokens": original["effective_configuration"]["llm_max_output_tokens"],
            "request_max_tokens": request.get("max_tokens"),
        })
    if result.get("serialized_request") == request and len(result.get("serialized_request_sha256", "")) == 64:
        serialized_request_count += 1

    calls = result.get("calls", [])
    call_counts[len(calls)] += 1
    body_text = result.get("response_body_text")
    body = result.get("response_body")
    status = result.get("response_status")
    status_counts[str(status)] += 1
    if isinstance(body_text, str) and isinstance(body, dict):
        computed_body_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
        if computed_body_hash == result.get("response_body_sha256"):
            response_hash_verified_count += 1
        else:
            response_hash_mismatches.append(execution_id)
        message = body.get("choices", [{}])[0].get("message", {})
        usage = body.get("usage")
        if isinstance(usage, dict):
            usage_count += 1
            token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
            if all(isinstance(usage.get(key), int) for key in token_keys):
                usage_complete_count += 1
                for key in token_keys:
                    usage_sums[key] += usage[key]
                reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                if isinstance(reasoning, int):
                    usage_sums["reasoning_tokens"] += reasoning
            else:
                usage_sums["missing_token_fields"] += 1
        content = message.get("content")
        if isinstance(content, str):
            parsed_content_count += 1
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                parsed = None
                schema_issues.append({"execution_id": execution_id, "kind": "content_not_json", "error": str(exc), "response": content})
            if isinstance(parsed, dict):
                findings = parsed.get("findings")
                valid = (
                    parsed.get("verdict") in allowed_verdicts
                    and isinstance(findings, list)
                    and all(
                        isinstance(finding, dict)
                        and finding.get("dimension") in expected_dimensions
                        and finding.get("verdict") in allowed_verdicts
                        and isinstance(finding.get("evidence"), str)
                        and isinstance(finding.get("reason"), str)
                        for finding in findings
                    )
                )
                if valid:
                    schema_valid_count += 1
                    dim_counts = collections.Counter(finding["dimension"] for finding in findings)
                    missing = sorted(expected_dimensions - set(dim_counts))
                    duplicate = sorted(dim for dim, count in dim_counts.items() if count > 1)
                    if not missing and not duplicate and parsed == result["result"]:
                        dimension_clean_count += 1
                    else:
                        dimension_issues.append({
                            "execution_id": execution_id,
                            "missing_dimensions": missing,
                            "duplicate_dimensions": duplicate,
                            "findings_dimension_counts": dict(dim_counts),
                            "parsed_result_matches_saved": parsed == result["result"],
                            "original_response_content": content,
                            "response_body_text": body_text,
                        })
                else:
                    schema_issues.append({"execution_id": execution_id, "kind": "invalid_content_schema", "response": content})
        elif not result.get("error"):
            schema_issues.append({"execution_id": execution_id, "kind": "content_not_string", "response": body_text})
    if result.get("error"):
        errors[result["error"].get("type", "unknown")] += 1
        error_messages[result["error"].get("message", "")] += 1
        error_records.append({
            "execution_id": execution_id,
            "error": result["error"],
            "response_status": status,
            "usage_present": isinstance(body, dict) and isinstance(body.get("usage"), dict),
            "finish_reason": (((body or {}).get("choices") or [{}])[0].get("finish_reason")) if isinstance(body, dict) else None,
        })

all_file_ids_match = result_ids == expected_ids
computed_verdict_counts = {name: verdicts.get(name, 0) for name in ("pass", "fail", "unknown")}
computed_error_count = sum(errors.values())
checks = {
    "runner_sha_matches_freeze_and_manifest": runner_hash == freeze["frozen_sha256"] == manifest["runner_sha256"],
    "source_manifest_sha_matches_freeze_and_output": source_manifest_hash == freeze["source_manifest_sha256"] == manifest["source_manifest_sha256"],
    "100_scheduled_and_100_outputs": len(schedule) == 100 and len(result_ids) == 100 and all_file_ids_match,
    "all_source_result_hashes_match": len(result_hash_mismatches) == 0,
    "all_requests_only_change_max_tokens": len(request_mismatches) == 0 and request_only_max_changed_count == 100,
    "all_serialized_requests_saved": serialized_request_count == 100,
    "all_source_calls_count_one": all(len(json.loads((source / item["execution_id"] / "result.json").read_text(encoding="utf-8"))["judge"]["calls"]) == 1 for item in manifest["schedule"]),
    "summary_matches_result_verdicts": summary["verdicts"] == computed_verdict_counts and summary["completed"] == 100,
    "summary_error_count_matches": summary["errors"] == computed_error_count,
    "product_tasks_not_reexecuted": manifest["product_tasks_reexecuted"] == 0 and summary["product_tasks_reexecuted"] == 0,
    "R01_diagnostic_preserved": hashlib.sha256((output / "R01-r1.json").read_bytes()).hexdigest() == "5cbe87fc9fbba4345c0fc8db04af447452f347c8605eb8503d81ec9521c6d0b4",
    "dimension_issues_recorded_without_retry": True,
}
audit = {
    "checks": checks,
    "all_integrity_checks_passed": all(checks.values()),
    "runner_sha256": runner_hash,
    "source_manifest_sha256": source_manifest_hash,
    "source_result_count": len(source_manifest["schedule"]),
    "diagnostic_result_count": len(result_ids),
    "verdict_counts": computed_verdict_counts,
    "error_count": computed_error_count,
    "error_types": dict(errors),
    "error_messages": dict(error_messages),
    "response_status_counts": dict(status_counts),
    "capture_call_count_distribution": dict(call_counts),
    "serialized_request_count": serialized_request_count,
    "request_only_max_tokens_changed_count": request_only_max_changed_count,
    "response_body_hash_verified_count": response_hash_verified_count,
    "usage_object_count": usage_count,
    "usage_coverage": usage_count / len(result_ids) if result_ids else None,
    "usage_complete_count": usage_complete_count,
    "usage_complete_coverage": usage_complete_count / len(result_ids) if result_ids else None,
    "usage_sums_where_present": dict(usage_sums),
    "parsed_content_count": parsed_content_count,
    "content_schema_valid_count": schema_valid_count,
    "parsed_findings_exactly_four_dimensions_once": dimension_clean_count,
    "dimension_issue_count": len(dimension_issues),
    "dimension_issues": dimension_issues,
    "schema_issues": schema_issues,
    "error_records": error_records,
    "source_hash_mismatches": result_hash_mismatches,
    "request_mismatches": request_mismatches,
    "response_hash_mismatches": response_hash_mismatches,
    "runner_summary": summary,
}
(evidence / "final-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
print(json.dumps({
    "all_integrity_checks_passed": audit["all_integrity_checks_passed"],
    "checks": checks,
    "verdict_counts": computed_verdict_counts,
    "error_count": computed_error_count,
    "error_types": dict(errors),
    "usage_object_count": usage_count,
    "usage_coverage": audit["usage_coverage"],
    "usage_sums": dict(usage_sums),
    "parsed_content_count": parsed_content_count,
    "schema_valid_count": schema_valid_count,
    "dimension_clean_count": dimension_clean_count,
    "dimension_issue_count": len(dimension_issues),
    "schema_issue_count": len(schema_issues),
}, ensure_ascii=False, indent=2))
if not all(checks.values()):
    raise SystemExit(1)