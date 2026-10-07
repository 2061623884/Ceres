"""Evaluate the evaluator's failure semantics without calling a model."""
import importlib.util
from pathlib import Path
import sys
import unittest

spec = importlib.util.spec_from_file_location("eval_v4", Path(__file__).with_name("eval_v4.py"))
ev = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ev
spec.loader.exec_module(ev)


class ScoringTests(unittest.TestCase):
    def test_missing_budget_and_total_never_pass_as_zero(self):
        checks = ev.check([
            {"kind": "max", "path": "after.plan.selected_total_fen", "value": 1000},
            {"kind": "eq", "path": "after.constraints.budget_fen", "value": 1000},
        ], {"after": {"plan": {}, "constraints": {}}})
        self.assertTrue(all(not c["passed"] and "missing_evidence" in c for c in checks))

    def test_exact_quantity_and_budget_constraints(self):
        expect = [{"kind": "quantities", "path": "items", "value": {"cola": 2}},
                  {"kind": "max", "path": "total", "value": 1000}]
        self.assertTrue(all(c["passed"] for c in ev.check(expect, {"items": [{"sku_id": "cola", "quantity": 2}], "total": 600})))
        self.assertFalse(ev.check(expect, {"items": [{"sku_id": "cola", "quantity": 3}], "total": 600})[0]["passed"])
        self.assertFalse(ev.check(expect, {"items": [{"sku_id": "cola", "quantity": 2}], "total": 1200})[1]["passed"])

    def test_empty_candidates_cannot_satisfy_all_fields(self):
        self.assertFalse(ev.check([{"kind": "fields", "path": "cards", "value": {"brand": "百事"}}], {"cards": []})[0]["passed"])

    def test_preparation_failures_stay_in_denominator(self):
        plan = [{"case_id": "one"}, {"case_id": "two"}]
        rows = [{"case_id": "one", "core": False, "group": "shopping", "status": "passed", "performance_passed": True},
                {"case_id": "two", "core": False, "group": "shopping", "status": "preparation_failed", "performance_passed": False}]
        summary = ev.summarize(plan, rows)
        self.assertEqual(summary["business_pass_rate"], .5)
        self.assertEqual(summary["automatic_acceptance"], "not_passed")

    def test_three_successes_require_all_executions_and_latency(self):
        rows = [{"case_id": "one", "core": True, "group": "shopping", "status": "passed", "performance_passed": n != 2} for n in range(3)]
        self.assertEqual(ev.summarize(rows, rows)["core_pass3"]["passed"], 0)
        rows[2]["performance_passed"] = True
        self.assertEqual(ev.summarize(rows, rows)["core_pass3"]["passed"], 1)

    def test_unconfirmed_cart_write_and_false_amount_are_violations(self):
        before = {"cart": {"items": [], "total_price_fen": 0}, "orders": [], "refunds": [], "returns": [], "opening": {"role": "keke"}}
        after = {**before, "guide": {"plan": None}, "cart": {"items": [{"sku_id": "cola", "quantity": 2, "unit_price_fen": 300, "line_total_fen": 300}], "total_price_fen": 300}}
        kinds = {v["kind"] for v in ev.invariants({"op": "turn"}, before, after, {"cola": {"price_fen": 300}})}
        self.assertIn("unauthorized_write", kinds)
        self.assertIn("false_cart_amount", kinds)
        kinds = {v["kind"] for v in ev.invariants({"op": "confirm_plan", "authorized": ["cart"]}, before, after, {"cola": {"price_fen": 300}})}
        self.assertNotIn("unauthorized_write", kinds)
        self.assertIn("false_cart_amount", kinds)

    def test_real_suite_schedules_100_without_split_leakage(self):
        cases = ev.read(Path(__file__).parents[1] / "evals/v4/cases.json")["cases"]
        ev.validate(cases)
        self.assertEqual(len(ev.schedule(cases)), 100)
        self.assertTrue(all(c["core"] for c, repeat in ev.schedule(cases)[:20]))
        tampered = [dict(c) for c in cases]
        regression = next(c for c in tampered if c["split"] == "regression")
        acceptance = next(c for c in tampered if c["split"] == "acceptance")
        acceptance["scenario_family"] = regression["scenario_family"]
        with self.assertRaisesRegex(ValueError, "crosses splits"):
            ev.validate(tampered)

    def test_declined_switch_and_wrong_offer_price_are_critical(self):
        before = {"cart": {"items": [], "total_price_fen": 0}, "orders": [], "refunds": [], "returns": [], "opening": {"role": "keke"}}
        after = {**before, "opening": {"role": "momo"}, "guide": {"plan": None},
                 "cart": {"items": [{"sku_id": "cola", "quantity": 1, "unit_price_fen": 1, "line_total_fen": 1}], "total_price_fen": 1}}
        kinds = {v["kind"] for v in ev.invariants({"op": "switch", "accept": False}, before, after, {"cola": {"price_fen": 300}})}
        self.assertIn("unconsented_switch", kinds)
        self.assertIn("false_cart_price", kinds)

    def test_nonempty_wrong_dish_and_pantry_selection_fail(self):
        facts = {"tomato": {"ingredient_ids": ["tomato"]}, "egg": {"ingredient_ids": ["egg"]}, "salt": {"ingredient_ids": ["salt"]}}
        expected = [{"kind": "ingredient_ids", "path": "cart", "value": ["tomato", "egg"]},
                    {"kind": "role_selection", "path": "plan", "value": {"required": True, "pantry": False}}]
        data = {"catalog_facts": facts, "cart": [{"sku_id": "tomato"}],
                "plan": [{"sku_id": "tomato", "role": "required", "selected": True}, {"sku_id": "salt", "role": "pantry", "selected": True}]}
        self.assertTrue(all(not item["passed"] for item in ev.check(expected, data)))

    def test_absent_pantry_role_cannot_pass_default_selection(self):
        row = {"items": [{"role": "required", "selected": True}]}
        rule = [{"kind": "role_selection", "path": "items", "value": {"required": True, "pantry": False}}]
        self.assertFalse(ev.check(rule, row)[0]["passed"])


if __name__ == "__main__":
    unittest.main()
