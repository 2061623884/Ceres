import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

root = Path.cwd()
src = root / "work/ceres-v4-evaluation/run-03"
out = root / "work/ceres-v4-evaluation/run-04"
old_manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
new_manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
old_cases_doc = json.loads((src / "cases.json").read_text(encoding="utf-8"))
new_cases_doc = json.loads((out / "cases.json").read_text(encoding="utf-8"))
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def strip_scoring_only(data):
    row = copy.deepcopy(data)
    for key in ("checks", "status", "source_scoring_result", "scoring_runner_sha256"):
        row.pop(key, None)
    for step in row["steps"]:
        step.pop("checks", None)
        step.pop("status", None)
    return row
if sha(src / "manifest.json") != new_manifest["parent_manifest_sha256"]:
    raise AssertionError("parent manifest hash mismatch")
if new_manifest["execution_runner_sha256"] != old_manifest["runner_sha256"]:
    raise AssertionError("execution runner identity changed")
if new_manifest.get("product_tasks_reexecuted") != 0:
    raise AssertionError("rescore manifest does not prove zero product re-executions")
if sha(out / "cases.json") != new_manifest["cases_sha256"]:
    raise AssertionError("run04 case hash mismatch")
if new_manifest["case_version"] != new_cases_doc["version"] or new_cases_doc["version"] != "ceres1-v4-tasks-20261007-v2":
    raise AssertionError("run04 case version mismatch")
old_cases = {row["case_id"]: row for row in old_cases_doc["cases"]}
new_cases = {row["case_id"]: row for row in new_cases_doc["cases"]}
if set(old_cases) != set(new_cases) or len(new_cases) != 60:
    raise AssertionError("case ids/count changed")
changed_cases, changed_steps = [], {}
for cid in sorted(new_cases):
    old, new = old_cases[cid], new_cases[cid]
    if {k: v for k, v in old.items() if k != "steps"} != {k: v for k, v in new.items() if k != "steps"}:
        raise AssertionError(f"{cid}: non-step case fields changed")
    if len(old["steps"]) != len(new["steps"]):
        raise AssertionError(f"{cid}: step count changed")
    steps = []
    for i, (a, b) in enumerate(zip(old["steps"], new["steps"])):
        if {k: v for k, v in a.items() if k != "expect"} != {k: v for k, v in b.items() if k != "expect"}:
            raise AssertionError(f"{cid} step {i}: non-expect fields changed")
        if a["expect"] != b["expect"]:
            steps.append({"step_index": i,
                          "added": [x for x in b["expect"] if x not in a["expect"]],
                          "removed": [x for x in a["expect"] if x not in b["expect"]]})
    if steps:
        changed_cases.append(cid)
        changed_steps[cid] = steps
if changed_cases != ["H03", "H12", "R17"]:
    raise AssertionError(f"unexpected changed case ids {changed_cases}")
schedule = old_manifest["schedule"]
if len(schedule) != 100 or len(new_manifest["schedule"]) != 100:
    raise AssertionError("schedule count not 100")
source_status, rescored_status = Counter(), Counter()
source_status_changes, core_checks = [], []
timing_keys = {"elapsed_ms", "background_wait_ms", "first_useful_result_ms", "latency_target_ms", "latency_target_exceeded"}
def collect_timing(value, found=None):
    found = {} if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            if k in timing_keys:
                found.setdefault(k, []).append(v)
            collect_timing(v, found)
    elif isinstance(value, list):
        for v in value:
            collect_timing(v, found)
    return found
timing_samples = 0
case_definitions = {p.stem: read(p) for p in (out / "case-definitions").glob("*.json")}
if len(case_definitions) != 60:
    raise AssertionError(f"case definition count {len(case_definitions)}")
for cid, case in new_cases.items():
    if case_definitions.get(cid) != case:
        raise AssertionError(f"{cid}: case-definition copy differs")
for entry in schedule:
    eid, cid = entry["execution_id"], entry["case_id"]
    original_path = src / eid / "result.json"
    rescored_path = out / eid / "result.json"
    if not original_path.is_file() or not rescored_path.is_file():
        raise AssertionError(f"{eid}: missing source or rescore result")
    original, rescored = read(original_path), read(rescored_path)
    source_status[original["status"]] += 1
    rescored_status[rescored["status"]] += 1
    if rescored.get("source_scoring_result") != {"path": str(original_path.resolve()), "sha256": sha(original_path)}:
        raise AssertionError(f"{eid}: source result path/hash mismatch")
    if original["model_calls"] != rescored["model_calls"]:
        raise AssertionError(f"{eid}: model_calls changed")
    before_timing, after_timing = collect_timing(original), collect_timing(rescored)
    if before_timing != after_timing:
        raise AssertionError(f"{eid}: timing fields changed")
    timing_samples += sum(len(values) for values in before_timing.values())
    if strip_scoring_only(original) != strip_scoring_only(rescored):
        raise AssertionError(f"{eid}: non-scoring product evidence changed")
    if original["status"] != rescored["status"]:
        source_status_changes.append({"execution_id": eid, "case_id": cid,
                                      "old": original["status"], "new": rescored["status"]})
    if cid in changed_steps:
        for changed in changed_steps[cid]:
            row = rescored["steps"][changed["step_index"]]
            for assertion in changed["added"]:
                match = [check for check in row["checks"] if check.get("kind") == assertion["kind"]
                         and check.get("path") == assertion.get("path")
                         and check.get("value") == assertion.get("value")]
                if not match:
                    raise AssertionError(f"{eid}: rescored output missing v2 assertion {assertion}")
                core_checks.append({"execution_id": eid, "case_id": cid,
                                    "kind": assertion["kind"], "path": assertion.get("path"),
                                    "expected": assertion.get("value"),
                                    "passed": all(check["passed"] for check in match),
                                    "actual": [check.get("actual") for check in match]})
badcases = read(out / "badcases.json")
badcase_paths = []
for badcase in badcases:
    argv = badcase["reproduce_argv"]
    case_arg = Path(argv[argv.index("--case") + 1])
    if not case_arg.is_file():
        raise AssertionError(f"{badcase['execution_id']}: missing reproduce case file {case_arg}")
    definition = read(case_arg)
    if definition["case_id"] != badcase["case_id"]:
        raise AssertionError(f"{badcase['execution_id']}: reproduce case id mismatch")
    if case_arg.parent.resolve() != (out / "case-definitions").resolve():
        raise AssertionError(f"{badcase['execution_id']}: reproduce path outside run04 definitions")
    badcase_paths.append({"execution_id": badcase["execution_id"], "case_id": badcase["case_id"],
                          "case_path": str(case_arg), "exists": True})
summary = {
    "case_version": new_manifest["case_version"],
    "cases_sha256": new_manifest["cases_sha256"],
    "parent_manifest_sha256": new_manifest["parent_manifest_sha256"],
    "execution_runner_sha256": new_manifest["execution_runner_sha256"],
    "rescore_runner_sha256": new_manifest["runner_sha256"],
    "product_tasks_reexecuted": new_manifest["product_tasks_reexecuted"],
    "execution_results_verified": 100,
    "result_hash_linkage_verified": 100,
    "model_calls_exactly_unchanged": 100,
    "timing_fields_exactly_unchanged": True,
    "timing_values_compared": timing_samples,
    "all_non_scoring_product_evidence_unchanged": True,
    "case_definitions_verified": len(case_definitions),
    "badcase_count": len(badcases),
    "badcase_reproduce_paths_exist": len(badcase_paths),
    "badcase_path_examples": badcase_paths[:5],
    "changed_cases": changed_cases,
    "changed_case_assertion_steps": changed_steps,
    "new_assertion_evaluation": {
        "checks": len(core_checks),
        "passed": sum(row["passed"] for row in core_checks),
        "failed": sum(not row["passed"] for row in core_checks),
        "by_execution": core_checks,
    },
    "source_status_counts": dict(source_status),
    "rescore_status_counts": dict(rescored_status),
    "execution_status_changed": source_status_changes,
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
