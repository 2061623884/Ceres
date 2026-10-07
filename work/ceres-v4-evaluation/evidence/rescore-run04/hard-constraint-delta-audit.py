import hashlib
import importlib.util
import json
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
spec = importlib.util.spec_from_file_location("eval_v4_constraint_delta", root / "scripts/eval_v4.py")
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)
def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
src, out = (root / "work/ceres-v4-evaluation/run-03", root / "work/ceres-v4-evaluation/run-04")
old_case_doc, new_case_doc = read(src / "cases.json"), read(out / "cases.json")
old_h04 = next(c for c in old_case_doc["cases"] if c["case_id"] == "H04")
new_h04 = next(c for c in new_case_doc["cases"] if c["case_id"] == "H04")
if old_h04 != new_h04:
    raise AssertionError("H04 case assertions changed between versions")
expect = old_h04["steps"][3]["expect"]
quantity_expectation = next(c for c in expect if c["kind"] == "quantities" and c["path"] == "after.cart.items")
old_result = read(src / "H04-r1/result.json")
new_result = read(out / "H04-r1/result.json")
old_step, new_step = old_result["steps"][3], new_result["steps"][3]
actual_cart = new_step["after"]["cart"]["items"]
actual_quantities = {row["sku_id"]: row["quantity"] for row in actual_cart}
if quantity_expectation["value"] == actual_quantities:
    raise AssertionError("H04 cart quantity unexpectedly matches the captured expectation")
def produced(row):
    return any((step.get("after", {}).get("guide", {}).get("plan") or {}).get("can_confirm") for step in row.get("steps", []))
def secondary_pass(row):
    return all(check["passed"] for check in row["checks"]
               if check.get("kind") == "quantities" or "constraints_summary" in check.get("path", ""))
current_pass, normalized_pass, produced_count = 0, 0, 0
mismatches = []
for path in sorted(src.glob("*/result.json")):
    eid = path.parent.name
    result = read(out / eid / "result.json")
    if not produced(result):
        continue
    produced_count += 1
    current_hard = all(check["passed"] for step in result["steps"] for check in step.get("hard_constraint_checks", []))
    current_ok = current_hard and secondary_pass(result)
    normalized_constraints = [check for step in result["steps"]
                              for check in ev.plan_constraints(step["after"], result["facts"])]
    normalized_ok = all(check["passed"] for check in normalized_constraints) and secondary_pass(result)
    current_pass += current_ok
    normalized_pass += normalized_ok
    for index, step in enumerate(result["steps"]):
        recomputed = ev.plan_constraints(step["after"], result["facts"])
        recorded = step.get("hard_constraint_checks", [])
        if recomputed != recorded:
            mismatches.append({"execution_id": eid, "step_index": index,
                               "hard_constraint_checks_key_present": "hard_constraint_checks" in step,
                               "stored_value": recorded, "recomputed_from_after": recomputed,
                               "all_recomputed_checks_pass": all(row["passed"] for row in recomputed)})
summary03, summary04 = read(src / "summary.json"), read(out / "summary.json")
if produced_count != 49 or current_pass != summary04["hard_constraints"]["all_satisfied"] or normalized_pass != current_pass:
    raise AssertionError("hard constraint count does not reconcile under stored and recomputed plan checks")
if len(mismatches) != 1 or mismatches[0]["execution_id"] != "H04-r1" or mismatches[0]["step_index"] != 3:
    raise AssertionError(f"unexpected stale hard constraint fields: {mismatches}")
target = {
    "case_id": "H04",
    "case_step_index": 3,
    "label": new_step["label"],
    "operation": new_step["op"],
    "captured_status_before_rescore": old_step["status"],
    "captured_status_after_rescore": new_step["status"],
    "expected_cart_quantities": quantity_expectation["value"],
    "actual_cart_quantities": actual_quantities,
    "can_confirm_plan_after_failed_step": (new_step["after"].get("guide", {}).get("plan") or {}).get("can_confirm"),
    "run03_step_checks_key_present": "checks" in old_step,
    "run03_step_hard_constraint_checks_key_present": "hard_constraint_checks" in old_step,
    "run04_step_hard_constraint_checks_key_present": "hard_constraint_checks" in new_step,
    "run04_step_checks": new_step["checks"],
    "source_result_sha256": sha(src / "H04-r1/result.json"),
    "rescore_result_sha256": sha(out / "H04-r1/result.json"),
}
report = {
    "run03_hard_constraints": summary03["hard_constraints"],
    "run04_hard_constraints": summary04["hard_constraints"],
    "all_satisfied_delta": summary04["hard_constraints"]["all_satisfied"] - summary03["hard_constraints"]["all_satisfied"],
    "only_execution_that_changed_hard_constraint_satisfaction": target,
    "missing_hard_constraint_checks_rows": mismatches,
    "current_report_method_satisfied_count": current_pass,
    "if_recomputed_hard_constraint_checks_were_populated_satisfied_count": normalized_pass,
    "effect_on_reported_39_of_49": "none; H04 quoted amount and stock pass, and the failing quantity assertion makes H04 unsatisfied in either calculation",
    "interpretation": "H04-r1 confirm step was execution_failed in run-03, so its after-state had no checks array. Offline rescore applies the existing expected quantities assertion to the retained after-state; requested 2 Pepsi cans but captured cart contains 1. It does not replay or alter the product execution."
}
print(json.dumps(report, ensure_ascii=False, indent=2))
