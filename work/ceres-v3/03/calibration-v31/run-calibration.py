from __future__ import annotations

import ast
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[4]
evidence = Path(__file__).resolve().parent
source_path = root / "backend/app/llm/kev_provider.py"
cases_path = root / "work/ceres-v3-discussion/kev-local-probe/chinese-pilot.json"
source_text = source_path.read_text(encoding="utf-8")
source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
source_ast = ast.parse(source_text, filename=str(source_path))
constant_names = {"INSTRUCTIONS", "CRITERIA", "CRITERIA_VERSION", "KEV_TIMEOUT_SECONDS"}
constants = {}
for node in source_ast.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in constant_names:
                constants[target.id] = ast.literal_eval(node.value)
if constants.keys() != constant_names:
    raise RuntimeError(f"Could not freeze provider constants: found {sorted(constants)}")

sys.path.insert(0, str(root / "backend"))
from app.core.config import get_settings
from app.llm.kev_provider import (
    CRITERIA,
    CRITERIA_VERSION,
    INSTRUCTIONS,
    KEV_TIMEOUT_SECONDS,
    KevProvider,
    KevUnavailable,
)

if (INSTRUCTIONS, CRITERIA, CRITERIA_VERSION, KEV_TIMEOUT_SECONDS) != (
    constants["INSTRUCTIONS"],
    constants["CRITERIA"],
    constants["CRITERIA_VERSION"],
    constants["KEV_TIMEOUT_SECONDS"],
):
    raise RuntimeError("Imported KevProvider constants differ from AST-frozen source constants")
settings = get_settings()
base_url = settings.kev_base_url.rstrip("/")
if base_url != "http://127.0.0.1:18009":
    raise RuntimeError(f"Unexpected Kev endpoint: {base_url!r}")
if KEV_TIMEOUT_SECONDS != 3.0:
    raise RuntimeError(f"Expected the fixed 3.0 second provider timeout, got {KEV_TIMEOUT_SECONDS!r}")

cases_bytes = cases_path.read_bytes()
cases_hash = hashlib.sha256(cases_bytes).hexdigest()
cases = json.loads(cases_bytes.decode("utf-8"))
requests = []
for case in cases:
    payload = {
        "state": case["state"],
        "model": "kev-latest",
        "questions": {
            "service": {
                "type": "choice",
                "instructions": constants["INSTRUCTIONS"],
                "criteria": constants["CRITERIA"],
            }
        },
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    requests.append({
        "case_id": case["id"],
        "expected": case["expected"],
        "payload": payload,
        "payload_sha256_compact_utf8": hashlib.sha256(payload_bytes).hexdigest(),
    })
(evidence / "frozen-requests.json").write_text(
    json.dumps(requests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

started_utc = datetime.now(timezone.utc).isoformat()
record = {
    "event": "kev_service_v31_single_pass_calibration",
    "status": "running",
    "criteria_version": CRITERIA_VERSION,
    "source_path": str(source_path),
    "source_sha256": source_hash,
    "cases_path": str(cases_path),
    "cases_sha256": cases_hash,
    "case_count_expected": len(cases),
    "endpoint": base_url + "/v1/systemone",
    "timeout_seconds": KEV_TIMEOUT_SECONDS,
    "runtime": {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "cwd": str(Path.cwd()),
        "environment_override": {"KEV_BASE_URL": base_url},
        "other_environment": "Inherited unchanged; not enumerated to avoid exposing unrelated credentials.",
        "implementation": "Actual app.llm.kev_provider.KevProvider.decide; one sequential call per frozen case; no retry.",
    },
    "constants": constants,
    "started_utc": started_utc,
    "requests": requests,
    "results": [],
}
result_path = evidence / "results.json"
def persist():
    result_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
persist()

for case in cases:
    case_started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    try:
        answer, raw = KevProvider().decide(case["state"])
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        actual = answer.model_dump(mode="json")
        record["results"].append({
            "case_id": case["id"],
            "expected": case["expected"],
            "actual_choice": actual["choice"],
            "matches_expected": actual["choice"] == case["expected"],
            "probabilities": actual["probabilities"],
            "service_latency_ms": raw.get("latency_ms"),
            "usage": raw.get("usage"),
            "elapsed_ms": elapsed_ms,
            "started_utc": case_started,
            "status": "success",
            "raw_response": raw,
        })
    except KevUnavailable as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 3)
        record["results"].append({
            "case_id": case["id"],
            "expected": case["expected"],
            "elapsed_ms": elapsed_ms,
            "started_utc": case_started,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
    persist()
    latest = record["results"][-1]
    print(json.dumps({
        "case_id": case["id"],
        "status": latest["status"],
        "actual_choice": latest.get("actual_choice"),
        "elapsed_ms": latest["elapsed_ms"],
        "service_latency_ms": latest.get("service_latency_ms"),
    }, ensure_ascii=False), flush=True)

final_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
record["finished_utc"] = datetime.now(timezone.utc).isoformat()
record["source_sha256_after"] = final_source_hash
record["source_unchanged_during_run"] = final_source_hash == source_hash
record["case_count_completed"] = len(record["results"])
record["successful_count"] = sum(r["status"] == "success" for r in record["results"])
record["failed_count"] = sum(r["status"] == "failed" for r in record["results"])
record["match_count"] = sum(r.get("matches_expected", False) for r in record["results"])
record["status"] = "complete" if len(record["results"]) == len(cases) and final_source_hash == source_hash else "incomplete_or_source_changed"
persist()
if record["status"] != "complete":
    raise RuntimeError(f"Calibration incomplete or source changed: {record['status']}")
print(json.dumps({
    "status": record["status"],
    "case_count_completed": record["case_count_completed"],
    "successful_count": record["successful_count"],
    "failed_count": record["failed_count"],
    "match_count": record["match_count"],
    "source_unchanged_during_run": record["source_unchanged_during_run"],
}, ensure_ascii=False), flush=True)
