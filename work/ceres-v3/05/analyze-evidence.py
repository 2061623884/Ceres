"""Run by the dedicated evaluator; retains failures in route latency/reporting."""
import argparse
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--routes", type=Path, required=True)
parser.add_argument("--role-samples", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
route_data = json.loads((args.routes / "results.json").read_text(encoding="utf-8"))
route_rows = route_data["rows"]
timings = sorted(row["actual"]["route_ms"] for row in route_rows if row["actual"].get("route_ms") is not None)
p95 = timings[math.ceil(.95 * len(timings)) - 1] if timings else None
confusion = {}
for row in route_rows:
    key = row["expected"] + " -> " + str(row["actual"]["decision"])
    confusion[key] = confusion.get(key, 0) + 1
samples = []
for receipt in sorted(args.role_samples.glob("*.json")):
    row = json.loads(receipt.read_text(encoding="utf-8"))
    case_id = row["case_id"]
    prompts = []
    for call in row["upstream"]:
        body = json.loads(call["request_body"])
        if "messages" in body:
            response_body = call.get("response_body", "")  # Absent on recorded network failure.
            usage = json.loads(response_body).get("usage") if response_body.lstrip().startswith("{") else None
            prompts.append({"model": body["model"],
                "system_chars": len(body["messages"][0]["content"]),
                "message_chars": sum(len(m["content"] or "") for m in body["messages"]),
                "request_utf8_bytes": len(call["request_body"].encode()),
                "usage": usage,
                "token_scope": "Provider usage when present; character counts are not tokens, no guessed stream usage"})
    samples.append({"case_id": case_id, "passed": row["passed"],
        "initial_api_wall_ms": row["backend_api_wall_ms"],
        "handoff_wall_ms": row["handoff_backend_wall_ms"] if case_id == "H01" and "handoff_backend_wall_ms" in row else None,
        "selection_wall_ms": row["selection_backend_wall_ms"] if case_id == "R01" and "selection_backend_wall_ms" in row else None,
        "prompts": prompts})
reply_times = [row["initial_api_wall_ms"] for row in samples]
reply_times += [row["handoff_wall_ms"] for row in samples if row["handoff_wall_ms"] is not None]
reply_times += [row["selection_wall_ms"] for row in samples if row["selection_wall_ms"] is not None]
expected_roles = {"R01", "R01-named-product-variant", "R02", "R03", "H01"}
recorded_roles = {row["case_id"] for row in samples}
reply_max = max(reply_times) if reply_times else None
result = {"route_n": len(route_rows), "route_correct": sum(row["passed"] for row in route_rows),
    "route_failed": sum(row["actual"]["status"] != "completed" for row in route_rows),
    "route_confusion": confusion, "route_p95_ms": p95,
    "route_timing_missing_n": len(route_rows) - len(timings),
    "route_q20_pass": p95 is not None and p95 <= 1000 and len(timings) == len(route_rows)
        and len(route_rows) == route_data.get("requested_rows", 22)
        and all(row["actual"]["status"] == "completed" for row in route_rows),
    "role_sample_n": len(samples), "role_samples": samples,
    "role_missing_cases": sorted(expected_roles - recorded_roles),
    "reply_observations_n": len(reply_times), "reply_max_ms": reply_max,
    "reply_q20_pass": len(samples) == 5 and recorded_roles == expected_roles
        and len(reply_times) == 7 and reply_max is not None and reply_max <= 15000
        and all(row["passed"] for row in samples),
    "measurement_scope": "In-process public API terminal SSE; no browser evidence; R01 explicit product choice and H01 confirmed handoff separately timed",
    "cold_start": "Not measured here; GPU already loaded. See ticket01 raw cold start and ticket03 client initialization.",
    "quality_scope": "Fixed public samples, not independent holdout or generalization proof"}
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: result[key] for key in ["route_n", "route_correct", "route_failed", "route_p95_ms", "route_q20_pass", "role_sample_n", "reply_max_ms", "reply_q20_pass"]}))
