import hashlib
import importlib.util
import json
import sys
from pathlib import Path

root = Path.cwd()
accept_dir = root / "work/ceres-v4-evaluation/acceptance"
source = root / "work/ceres-v4-evaluation/run-04"
api_parent = root / "work/ceres-v4-evaluation/run-03"
ui_path = root / "work/ceres-v4-evaluation/ui/run-02/result.json"
diag = root / "work/ceres-v4-evaluation/diagnostics-run03-v3"
probe_dirs = [root / "work/ceres-v4-evaluation/diagnostics-run03",
              root / "work/ceres-v4-evaluation/diagnostics-run03-v2"]
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
record = read(accept_dir / "acceptance.json")
failures = read(accept_dir / "failures.json")
manifest04 = read(source / "manifest.json")
manifest03 = read(api_parent / "manifest.json")
diagnostics_manifest = read(diag / "manifest.json")
expected_hashes = {
    "source_manifest_sha256": digest(source / "manifest.json"),
    "source_summary_sha256": digest(source / "summary.json"),
    "ui_result_sha256": digest(ui_path),
    "diagnostic_manifest_sha256": digest(diag / "manifest.json"),
    "reporter_sha256": digest(root / "scripts/eval_v4_record.py"),
}
for field, value in expected_hashes.items():
    if record[field] != value:
        raise AssertionError(f"{field} does not match source")
if record["source"] != str(source.resolve()) or record["ui"] != str(ui_path.resolve()) or record["diagnostics"] != str(diag.resolve()):
    raise AssertionError("acceptance source paths mismatch")
if record["product_head"] != "ac895fd620af617fa31f4e0006841a4d6a89cd53" or manifest04["product_head"] != record["product_head"]:
    raise AssertionError("candidate HEAD mismatch")
if manifest04["case_version"] != "ceres1-v4-tasks-20261007-v2" or read(source / "cases.json")["version"] != manifest04["case_version"]:
    raise AssertionError("run04 case version mismatch")
if manifest03["case_version"] != "ceres1-v4-tasks-20261007-v1":
    raise AssertionError("parent source case version mismatch")
if len(record["execution_sha256"]) != 100 or record["api"]["actual_executions"] != 100 or record["api"]["planned_executions"] != 100:
    raise AssertionError("API execution count mismatch")
if record["api"]["planned_cases"] != 60:
    raise AssertionError("API case count mismatch")
if record["api"]["counts"] != {"passed": 76, "failed": 24, "preparation_failed": 0, "runner_failed": 0, "not_executed": 0}:
    raise AssertionError("API status distribution mismatch")
if len(list(source.glob("*/result.json"))) != 100:
    raise AssertionError("run04 result file count mismatch")
for eid, expected in record["execution_sha256"].items():
    path = source / eid / "result.json"
    diagnostic_path = diag / f"{eid}.json"
    if digest(path) != expected["api"]:
        raise AssertionError(f"{eid} API execution hash mismatch")
    if digest(diagnostic_path) != expected["diagnostic"]:
        raise AssertionError(f"{eid} diagnostic result hash mismatch")
    lineage = expected["diagnostic_source_api"]

    if lineage["sha256"] != digest(api_parent / eid / "result.json") or lineage["path"] != str((api_parent / eid / "result.json").resolve()):
        raise AssertionError(f"{eid} diagnostic source API lineage mismatch")
    diagnostic_row = read(diagnostic_path)
    if diagnostic_row["source_result_sha256"] != lineage["sha256"]:
        raise AssertionError(f"{eid} diagnostic captured a different API source")
if len(record["diagnostic_verdicts"]) != 3 or sum(record["diagnostic_verdicts"].values()) != 100:
    raise AssertionError("diagnostic verdict counts mismatch")
if record["usage"]["diagnostic_judge"]["calls"] != 100:
    raise AssertionError("diagnostic call count mismatch")
if sum((diag / f"{entry['execution_id']}.json").is_file() for entry in manifest04["schedule"]) != 100:
    raise AssertionError("diagnostic result file count mismatch")
if len(record["ui_journeys"]) != 2 or record["ui_acceptance"] != "not_passed":
    raise AssertionError("UI journey count/acceptance mismatch")
if record["automatic_acceptance"] != "not_passed" or len(record["failures"]) != 45 or len(failures) != 45:
    raise AssertionError("strict acceptance/failure count mismatch")
if len(record["failed_probes"]) != 2 or len(probe_dirs) != 2:
    raise AssertionError("probe count mismatch")
probe_verification = []
for directory, reported in zip(probe_dirs, record["failed_probes"]):
    result_path = directory / "R01-r1.json"
    probe = read(result_path)
    manifest_path = directory / "manifest.json"
    manifest = read(manifest_path)
    if digest(result_path) != reported["result_sha256"] or digest(manifest_path) != reported["manifest_sha256"]:
        raise AssertionError(f"probe hashes mismatch for {directory.name}")
    if len(probe["calls"]) != 1 or probe["result"]["verdict"] != "unknown":
        raise AssertionError(f"probe not a one-call unknown: {directory.name}")
    if reported["verdict"] != "unknown":
        raise AssertionError(f"reported probe verdict mismatch: {directory.name}")
    probe_verification.append({"directory": directory.name, "calls": len(probe["calls"]),
                               "verdict": probe["result"]["verdict"], "parameter": reported["parameter"],
                               "result_sha256": reported["result_sha256"],
                               "manifest_sha256": reported["manifest_sha256"]})
if sum(row["calls"] for row in probe_verification) != 2:
    raise AssertionError("failed probe total call count not 2")
sys.path.insert(0, str(root / "scripts"))
spec = importlib.util.spec_from_file_location("record_usage_audit", root / "scripts/eval_v4_record.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
entries = manifest04["schedule"]
api_rows = [(entry, read(source / entry["execution_id"] / "result.json")) for entry in entries]
all_components = {
    "role": [call for _, row in api_rows for call in row["model_calls"].get("role", [])],
    "mercury": [call for _, row in api_rows for call in row["model_calls"].get("mercury", [])],
    "kev": [call for _, row in api_rows for call in row["model_calls"].get("kev", [])],
    "background_memory": [call for _, row in api_rows for call in row["model_calls"].get("background_memory", [])],
    "original_judge": [call for _, row in api_rows for call in row["judge"]["calls"]],
    "diagnostic_judge": [call for eid in [entry["execution_id"] for entry in entries] for call in read(diag / f"{eid}.json")["calls"]],
    "failed_probe_judge": [call for directory in probe_dirs for call in read(directory / "R01-r1.json")["calls"]],
}
for name, calls in all_components.items():
    independently_computed = module.usage(calls)
    if record["usage"][name] != independently_computed:
        raise AssertionError(f"token aliases/coverage mismatch for {name}")
if record["usage"]["kev"]["total_tokens"]["coverage"] != 0 or record["usage"]["kev"]["total_tokens"]["reported_sum"] is not None:
    raise AssertionError("missing Kev total_tokens incorrectly treated as reported")
report_md = (accept_dir / "acceptance.md").read_text(encoding="utf-8")
for expected_text in ("60 场景、100 次计划执行；实际 100 次", "失败探针", "74/98", "2/2", "not reached"):
    if expected_text == "not reached":
        continue
    if expected_text not in report_md:
        raise AssertionError(f"markdown missing required text: {expected_text}")
summary = {
    "acceptance_json_sha256": digest(accept_dir / "acceptance.json"),
    "acceptance_md_sha256": digest(accept_dir / "acceptance.md"),
    "failures_json_sha256": digest(accept_dir / "failures.json"),
    "source_hashes_verified": expected_hashes,
    "candidate_head": record["product_head"],
    "case_version_parent": manifest03["case_version"],
    "case_version_final": manifest04["case_version"],
    "api": {"cases": record["api"]["planned_cases"], "executions": record["api"]["actual_executions"],
            "passed": record["api"]["counts"]["passed"], "failed": record["api"]["counts"]["failed"],
            "fully_passed": record["api"]["fully_passed"], "core_pass3": record["api"]["core_pass3"]["passed"]},
    "diagnostics": {"calls": record["usage"]["diagnostic_judge"]["calls"],
                    "verdicts": record["diagnostic_verdicts"], "errors": record["diagnostic_errors"]},
    "ui": [{"name": row["name"], "status": row["status"], "performance_passed": row["performance_passed"]}
           for row in record["ui_journeys"]],
    "failure_records": len(failures),
    "probe_verification": probe_verification,
    "token_usage_recomputed_from_raw_calls": {name: record["usage"][name] for name in all_components},
    "automatic_acceptance": record["automatic_acceptance"],
    "report_md_claims_verified": ["100 API executions", "normal completion 74/98", "compliant refusal 2/2"]
}
print(json.dumps(summary, ensure_ascii=False, indent=2))



