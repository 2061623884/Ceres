import importlib.util
import json
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "scripts"))
spec = importlib.util.spec_from_file_location("eval_v4_hard_audit", root / "scripts/eval_v4.py")
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)
def read(base, eid):
    return json.loads((root / f"work/ceres-v4-evaluation/{base}/{eid}/result.json").read_text(encoding="utf-8"))
def produced(row):
    return any((step.get("after", {}).get("guide", {}).get("plan") or {}).get("can_confirm") for step in row.get("steps", []))
def hard_parts(row):
    stored_hard = [check for step in row["steps"] for check in step.get("hard_constraint_checks", [])]
    summary_checks = [check for check in row["checks"] if check.get("kind") == "quantities" or "constraints_summary" in check.get("path", "")]
    return {
        "stored_hard_pass": all(check["passed"] for check in stored_hard),
        "summary_checks_pass": all(check["passed"] for check in summary_checks),
        "stored_hard": stored_hard,
        "summary_checks": summary_checks,
    }
differences = []
stale_rows = []
for path in sorted((root / "work/ceres-v4-evaluation/run-03").glob("*/result.json")):
    eid = path.parent.name
    old = read("run-03", eid)
    new = read("run-04", eid)
    if produced(old) != produced(new):
        raise AssertionError(f"{eid}: produced-plan denominator changed")
    if produced(new):
        before, after = hard_parts(old), hard_parts(new)
        old_ok = before["stored_hard_pass"] and before["summary_checks_pass"]
        new_ok = after["stored_hard_pass"] and after["summary_checks_pass"]
        if old_ok != new_ok:
            differences.append({"execution_id": eid, "old_satisfied": old_ok, "new_satisfied": new_ok,
                                "old_hard_pass": before["stored_hard_pass"], "new_hard_pass": after["stored_hard_pass"],
                                "old_secondary_pass": before["summary_checks_pass"], "new_secondary_pass": after["summary_checks_pass"],
                                "new_failed_secondary": [check for check in after["summary_checks"] if not check["passed"]]})
    for index, row in enumerate(new["steps"]):
        recomputed = ev.plan_constraints(row["after"], new["facts"])
        stored = row.get("hard_constraint_checks", [])
        if recomputed != stored:
            stale_rows.append({"execution_id": eid, "step_index": index, "stored_hard_constraint_checks": stored,
                               "recomputed_from_after": recomputed,
                               "row_checks_plan_constraint_subset": [check for check in row.get("checks", [])
                                   if check.get("kind") in {"quoted_selected_amount", "budget", "stock"}]})
old_summary=json.loads((root / "work/ceres-v4-evaluation/run-03/summary.json").read_text(encoding="utf-8"))
new_summary=json.loads((root / "work/ceres-v4-evaluation/run-04/summary.json").read_text(encoding="utf-8"))
output={"run03_hard_constraints":old_summary["hard_constraints"],"run04_hard_constraints":new_summary["hard_constraints"],
        "satisfaction_deltas":differences,"stale_step_count":len(stale_rows),"stale_steps":stale_rows}
print(json.dumps(output,ensure_ascii=False,indent=2))
