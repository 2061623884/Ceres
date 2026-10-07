import importlib.util
import json
import sys
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location("eval_v4_negative_audit", root / "scripts/eval_v4.py")
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)
old_doc = json.loads((root / "work/ceres-v4-evaluation/run-03/cases.json").read_text(encoding="utf-8"))
new_doc = json.loads((root / "evals/v4/cases.json").read_text(encoding="utf-8"))
old_cases = {case["case_id"]: case for case in old_doc["cases"]}
new_cases = {case["case_id"]: case for case in new_doc["cases"]}
changed = []
audit = []
for cid in sorted(new_cases):
    old_case, new_case = old_cases[cid], new_cases[cid]
    modified_steps = []
    for i, (old_step, new_step) in enumerate(zip(old_case["steps"], new_case["steps"])):
        if {k: v for k, v in old_step.items() if k != "expect"} != {k: v for k, v in new_step.items() if k != "expect"}:
            raise AssertionError(f"{cid} step {i}: non-expect fields changed")
        if old_step["expect"] != new_step["expect"]:
            added = [item for item in new_step["expect"] if item not in old_step["expect"]]
            removed = [item for item in old_step["expect"] if item not in new_step["expect"]]
            modified_steps.append((i, added, removed))
    if modified_steps:
        changed.append(cid)
    if cid not in {"R17", "H03", "H12"}:
        if modified_steps:
            raise AssertionError(f"unexpected changed case: {cid}")
        continue
    if len(modified_steps) != 1:
        raise AssertionError(f"{cid}: expected one updated step, got {len(modified_steps)}")
    index, added, removed = modified_steps[0]
    added_paths = {item["path"] for item in added}
    needed = {"after.guide.plan.can_confirm", "after.guide.plan.items", "after.guide.plan.selected_total_fen"}
    if not needed.issubset(added_paths) or not any(item["kind"] == "fields" and item["value"] == {"selected": True} for item in added):
        raise AssertionError(f"{cid}: missing v2 plan assertions in delta")
    expected_qty = next(item["value"] for item in added if item["kind"] == "quantities")
    sku, qty = next(iter(expected_qty.items()))
    expected_total = next(item["value"] for item in added if item["path"].endswith("selected_total_fen"))
    budget = next((item["value"] for item in new_case["steps"][index]["expect"] if item["path"].endswith("budget_fen")), 0)
    def row_for(items=None, selected_total=expected_total, can_confirm=True):
        if items is None:
            items = [{"sku_id": sku, "quantity": qty, "selected": True}]
        return {"after": {"guide": {"plan": {"can_confirm": can_confirm, "items": items,
                    "selected_total_fen": selected_total}, "constraints_summary": {"budget_fen": budget}}}}
    positive = ev.check(added, row_for())
    if not all(item["passed"] for item in positive):
        raise AssertionError(f"{cid}: valid control row failed: {positive}")
    mutations = {
        "empty": row_for(items=[], selected_total=0, can_confirm=False),
        "wrong_sku": row_for(items=[{"sku_id": "wrong:sku", "quantity": qty, "selected": True}]),
        "wrong_quantity": row_for(items=[{"sku_id": sku, "quantity": qty + 1, "selected": True}]),
        "not_selected": row_for(items=[{"sku_id": sku, "quantity": qty, "selected": False}]),
        "wrong_selected_amount": row_for(selected_total=expected_total + 1),
        "not_confirmable": row_for(can_confirm=False),
    }
    mutation_results = {}
    for label, row in mutations.items():
        checks = ev.check(added, row)
        failed = [item["path"] for item in checks if not item["passed"]]
        if not failed:
            raise AssertionError(f"{cid}/{label}: negative row passed all added assertions")
        mutation_results[label] = {"failed_paths": failed}
    audit.append({"case_id": cid, "step_index": index, "added_expectations": added,
                  "removed_expectations": removed, "positive_control": "passed",
                  "negative_mutations": mutation_results})
if sorted(changed) != ["H03", "H12", "R17"]:
    raise AssertionError(f"unexpected expectation delta: {changed}")
print(json.dumps({"old_case_version": old_doc["version"], "new_case_version": new_doc["version"],
                  "changed_cases": changed, "negative_case_count": sum(len(row["negative_mutations"]) for row in audit),
                  "audit": audit}, ensure_ascii=False, indent=2))
