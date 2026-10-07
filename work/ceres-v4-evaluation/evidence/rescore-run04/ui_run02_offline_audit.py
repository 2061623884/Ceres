import difflib
import hashlib
import json
from pathlib import Path

root = Path.cwd()
current_path = root / "scripts/eval_v4_ui.mjs"
frozen_path = root / "work/ceres-v4-evaluation/ui/eval_v4_ui.run02.frozen.mjs"
result_path = root / "work/ceres-v4-evaluation/ui/run-02/result.json"
current = current_path.read_text(encoding="utf-8").splitlines(keepends=True)
frozen = frozen_path.read_text(encoding="utf-8").splitlines(keepends=True)
diff = list(difflib.unified_diff(frozen, current, fromfile="run02-frozen", tofile="current"))
added = [line[1:].rstrip("\r\n") for line in diff if line.startswith("+") and not line.startswith("+++")]
removed = [line[1:].rstrip("\r\n") for line in diff if line.startswith("-") and not line.startswith("---")]
expected_added = [
    "    assert.equal(selected[0].line_total_fen, quantity * unitPrice);",
    "    assert.equal(guide.plan.selected_total_fen, quantity * unitPrice);",
    "    if (name === 'snack-bubble') assert.equal(guide.constraints_summary.budget_fen, 2000);",
]
if removed or added != expected_added:
    raise AssertionError({"added": added, "removed": removed})
report = json.loads(result_path.read_text(encoding="utf-8"))
journeys = {row["name"]: row for row in report["journeys"]}
activity = journeys["activity-salad"]
activity_plan = activity["plan_before_confirm"]["plan"]
selected = [item for item in activity_plan["items"] if item["selected"]]
if len(selected) != 1:
    raise AssertionError(f"activity selected row count {len(selected)}")
item = selected[0]
if item["line_total_fen"] != item["quantity"] * item["unit_price_fen"]:
    raise AssertionError("activity item line_total_fen differs from quantity * unit_price_fen")
selected_total = sum(row["line_total_fen"] for row in selected)
if activity_plan["selected_total_fen"] != selected_total:
    raise AssertionError("activity selected_total_fen differs from selected line total")
snack = journeys["snack-bubble"]
snack_plan = (snack.get("plan_before_confirm") or {}).get("plan")
if snack_plan is not None:
    raise AssertionError("snack unexpectedly reached a plan")
if snack["status"] != "failed":
    raise AssertionError("snack failure was not preserved")
payload = {
    "current_runner_sha256": hashlib.sha256(current_path.read_bytes()).hexdigest(),
    "run02_frozen_runner_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
    "runner_diff_added_only": added,
    "activity": {
        "status": activity["status"], "stage": activity["stage"], "sku_id": item["sku_id"],
        "quantity": item["quantity"], "unit_price_fen": item["unit_price_fen"],
        "line_total_fen": item["line_total_fen"], "selected_total_fen": activity_plan["selected_total_fen"],
        "selected_sum_fen": selected_total, "checks_passed": True
    },
    "snack": {
        "status": snack["status"], "stage": snack["stage"], "plan_reached": False,
        "error": snack.get("error"), "visible_text": snack.get("visible_text"),
        "new_budget_assertion_evaluated": False, "failure_preserved": True
    }
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
