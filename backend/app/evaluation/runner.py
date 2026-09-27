"""Shared evaluation helpers and an explicit live-endpoint CLI."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import cart, catalog, session as session_models, store, trace  # noqa: F401
from app.main import app

KNOWN_ACTIONS = {
    "has_plan",
    "no_plan",
    "status_is",
    "forbid_sku",
    "allow_sku",
    "cart_has_sku",
    "message_contains",
    "forbid_ingredient",
    "task_unchanged",
    #: Cross-turn assertions: the state *after* a numbered turn, not only after
    #: the last one. A multi-turn goal change is only verifiable this way.
    "turn_status_is",
    "turn_route_is",
    "turn_readiness_is",
    "turn_missing_slots",
    "turn_plan_has_sku",
    "turn_plan_lacks_sku",
    "turn_task_changes",
    "turn_task_unchanged",
    "turn_plan_unchanged",
    "turn_pending_unchanged",
    "turn_cart_unchanged",
    "turn_people_is",
    "turn_quantity_delta",
}

#: Action fields that name a turn or a read-only decision echo.
TURN_ACTION_FIELDS = {
    "type",
    "turn",
    "value",
    "sku_id",
    "text",
    "ingredient_id",
}

#: Per-turn actions only make sense in their dict form: a bare string has no turn.
TURN_ONLY_ACTIONS = frozenset(
    {a for a in KNOWN_ACTIONS if a.startswith("turn_")}
)


class EvalConfigError(Exception):
    pass


def load_cases(split: str | None = None) -> list[dict]:
    cases = []
    eval_dir = ROOT / "evals" / "v1"
    files = [
        "strong.jsonl",
        "dev.jsonl",
        "regression.jsonl",
        "holdout.jsonl",
        # The P1 planner/decision cases: multi-turn goal changes whose state must
        # be asserted per turn, not only at the end of the case.
        "purchase-intent-p1-planner.jsonl",
    ]
    for fname in files:
        path = eval_dir / fname
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                case = json.loads(line)
                if split and case.get("split") != split:
                    continue
                cases.append(case)
    return cases


def validate_case_config(case: dict) -> None:
    if not case.get("case_id"):
        raise EvalConfigError("case missing case_id")
    if not case.get("turns"):
        raise EvalConfigError(f"{case['case_id']}: empty turns")
    actions = case.get("expected_actions") or []
    if not actions:
        raise EvalConfigError(f"{case['case_id']}: empty expected_actions")
    for action in actions:
        if isinstance(action, (int, float)):
            raise EvalConfigError(f"{case['case_id']}: numeric action not allowed")
        if isinstance(action, str):
            if action in {"cart_has_sku", "status_is"} or action in TURN_ONLY_ACTIONS:
                raise EvalConfigError(
                    f"{case['case_id']}: action {action} must use dict form with type field"
                )
            if action not in KNOWN_ACTIONS and not action.startswith("status_is:"):
                raise EvalConfigError(f"{case['case_id']}: unknown action {action}")
        elif isinstance(action, dict):
            if "type" not in action:
                raise EvalConfigError(f"{case['case_id']}: action dict missing type")
            if action.get("type") not in KNOWN_ACTIONS:
                raise EvalConfigError(f"{case['case_id']}: unknown action type")
            unknown = set(action.keys()) - TURN_ACTION_FIELDS
            if unknown:
                raise EvalConfigError(f"{case['case_id']}: unknown action fields {sorted(unknown)}")
        else:
            raise EvalConfigError(f"{case['case_id']}: invalid action type {type(action)}")


def _check_action(
    action: str | dict, data: dict, cart: dict | None, turns: list[dict] | None = None
) -> str | None:
    if isinstance(action, dict):
        atype = action["type"]
        turn = action.get("turn")
        if atype.startswith("turn_"):
            return _check_turn_action(action, turns or [])
        if atype == "status_is":
            expected = action.get("value")
            if data["status"] != expected:
                return f"expected status {expected}, got {data['status']}"
        elif atype == "forbid_sku":
            plan = data.get("plan") or {}
            skus = {i["sku_id"] for i in plan.get("items", [])}
            if action["sku_id"] in skus:
                return f"forbidden sku {action['sku_id']} in plan"
        elif atype == "allow_sku":
            plan = data.get("plan") or {}
            skus = {i["sku_id"] for i in plan.get("items", [])}
            if action["sku_id"] not in skus:
                return f"missing allowed sku {action['sku_id']}"
        elif atype == "cart_has_sku":
            if not cart or not any(i["sku_id"] == action["sku_id"] for i in cart.get("items", [])):
                return f"cart missing sku {action['sku_id']}"
        elif atype == "message_contains":
            if action.get("text") not in data.get("message", ""):
                return f"message missing {action.get('text')}"
        return None

    if action == "has_plan" and not data.get("plan"):
        return "expected plan"
    if action == "no_plan" and data.get("plan"):
        return "unexpected plan"
    if action.startswith("status_is:"):
        expected = action.split(":", 1)[1]
        if data["status"] != expected:
            return f"expected status {expected}, got {data['status']}"
    if action not in KNOWN_ACTIONS or action in TURN_ONLY_ACTIONS:
        return f"unknown action {action}"
    return None


def _check_turn_action(action: dict, turns: list[dict]) -> str | None:
    """One assertion about the state after a numbered turn of the case."""
    atype = action["type"]
    index = action.get("turn")
    if not isinstance(index, int) or index < 1 or index > len(turns):
        return f"{atype}: turn {index} is out of range (have {len(turns)})"
    data = turns[index - 1]
    previous = turns[index - 2] if index >= 2 else {}
    plan = data.get("plan") or {}
    skus = {str(i.get("sku_id")) for i in plan.get("items", [])}
    if atype == "turn_status_is":
        if data.get("status") != action.get("value"):
            return f"turn {index}: expected status {action.get('value')}, got {data.get('status')}"
    elif atype == "turn_route_is":
        if data.get("route") != action.get("value"):
            return f"turn {index}: expected route {action.get('value')}, got {data.get('route')}"
    elif atype == "turn_readiness_is":
        if data.get("readiness") != action.get("value"):
            return (
                f"turn {index}: expected readiness {action.get('value')}, "
                f"got {data.get('readiness')}"
            )
    elif atype == "turn_missing_slots":
        expected = action.get("value") or []
        if list(data.get("missing_slots") or []) != list(expected):
            return (
                f"turn {index}: expected missing_slots {expected}, "
                f"got {data.get('missing_slots')}"
            )
    elif atype == "turn_plan_has_sku":
        if action.get("sku_id") not in skus:
            return f"turn {index}: plan missing {action.get('sku_id')}"
    elif atype == "turn_plan_lacks_sku":
        if action.get("sku_id") in skus:
            return f"turn {index}: plan still has {action.get('sku_id')}"
    elif atype == "turn_task_changes":
        if data.get("task_id") == previous.get("task_id"):
            return f"turn {index}: expected a new task, still on {data.get('task_id')}"
    elif atype == "turn_task_unchanged":
        if not previous.get("task_id") or data.get("task_id") != previous.get("task_id"):
            return f"turn {index}: task unexpectedly changed"
    elif atype in ("turn_plan_unchanged", "turn_pending_unchanged", "turn_cart_unchanged"):
        key = {"turn_plan_unchanged": "plan", "turn_pending_unchanged": "pending_clarifications", "turn_cart_unchanged": "_cart"}[atype]
        if index < 2 or data.get(key) != previous.get(key):
            return f"turn {index}: {key} unexpectedly changed"
    elif atype == "turn_people_is":
        targets = plan.get("targets") or []
        if not targets or any(t.get("people") != action.get("value") for t in targets):
            return f"turn {index}: expected headcount {action.get('value')}"
    elif atype == "turn_quantity_delta":
        sku = action.get("sku_id")
        quantities = lambda p: sum(int(row.get("quantity") or 0) for row in (p or {}).get("items", []) if row.get("sku_id") == sku)
        if sku not in skus or quantities(plan) - quantities(previous.get("plan")) != action.get("value"):
            return f"turn {index}: incorrect quantity delta for {sku}"
    return None


def run_case(client: TestClient, case: dict) -> dict:
    validate_case_config(case)
    result = {"case_id": case["case_id"], "passed": True, "failures": []}
    ctx = case.get(
        "entry_context",
        {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"},
    )
    sid = client.post("/api/v1/guide/sessions", json={"entry_context": ctx}).json()["session_id"]
    task_id = None
    version = 0
    last_data: dict | None = None
    turn_states: list[dict] = []
    result["turn_states"] = turn_states
    check_turn_cart = any(isinstance(a, dict) and a.get("type") == "turn_cart_unchanged" for a in case.get("expected_actions", []))
    for i, turn in enumerate(case.get("turns", [])):
        resp = client.post(
            f"/api/v1/guide/sessions/{sid}/turns",
            json={
                "request_id": str(uuid.uuid4()),
                "message": turn["message"],
                "expected_task_id": task_id,
                "expected_state_version": version,
            },
        )
        if resp.status_code != 200:
            result["passed"] = False
            result["failures"].append(f"turn {i} status {resp.status_code}")
            return result
        data = resp.json()
        if check_turn_cart:
            data["_cart"] = client.get("/api/v1/cart").json()
        last_data = data
        turn_states.append(data)
        task_id = data["task_id"]
        version = data["state_version"]
        if "expected_status" in turn and data["status"] != turn["expected_status"]:
            result["passed"] = False
            result["failures"].append(
                f"turn {i} expected status {turn['expected_status']}, got {data['status']}"
            )
    if case.get("confirm_plan") and last_data and last_data.get("plan"):
        plan = last_data["plan"]
        items = [
            {"sku_id": i["sku_id"], "quantity": i["quantity"]}
            for i in plan["items"]
            if i.get("role", "required") == "required"
        ]
        if plan.get("mode") == "alternatives" and items:
            items = [items[0]]
        prev_raise = getattr(client, "raise_server_exceptions", True)
        client.raise_server_exceptions = False
        try:
            confirm = client.post(
                f"/api/v1/guide/tasks/{task_id}/confirm",
                headers={"Idempotency-Key": f"eval-{case['case_id']}"},
                json={
                    "plan_id": plan["plan_id"],
                    "plan_version": plan["plan_version"],
                    "expected_state_version": version,
                    "selected_items": items,
                },
            )
        finally:
            client.raise_server_exceptions = prev_raise
        if confirm.status_code != 200:
            result["passed"] = False
            result["failures"].append(f"confirm status {confirm.status_code}")
    cart = client.get("/api/v1/cart").json() if case.get("check_cart") else None
    for action in case.get("expected_actions", []):
        err = _check_action(action, last_data or {}, cart, turn_states)
        if err:
            result["passed"] = False
            result["failures"].append(err)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Evaluate cases against the configured live endpoint.

    ``--mode`` is required, so a bare invocation prints usage instead of quietly
    picking a mode, and the retired ``mock`` mode is not accepted.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation.runner",
        description="Run the eval cases against the configured live endpoint (live only).",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["live"],
        help="required; the runner has no offline mode",
    )
    parser.add_argument("--allow-empty-actions", action="store_true")
    parser.add_argument(
        "--split",
        default=None,
        help="only run cases with this split (e.g. regression); default: every split",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    import tempfile
    import os

    os.environ["LLM_MODE"] = args.mode
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.sqlite3')}"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.core import database as db_module

    engine = create_engine(os.environ["DATABASE_URL"], connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    sys.path.insert(0, str(ROOT))
    from scripts.seed_runtime import (
        ensure_catalog_schema,
        seed_chinese_dish_templates,
        seed_demo_products,
        seed_reviews,
        seed_store_offers,
        seed_templates,
    )

    ensure_catalog_schema(engine)
    seed_demo_products(db)
    seed_reviews(db)
    seed_store_offers(db)
    seed_templates(db)
    seed_chinese_dish_templates(db)
    db.commit()
    db.close()

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    db_module.engine = engine
    db_module.SessionLocal = TestSession
    app.dependency_overrides[db_module.get_db] = override_get_db

    all_cases = load_cases(split=args.split)
    excluded = [c for c in all_cases if not c.get("expected_actions")]
    cases = [c for c in all_cases if c.get("expected_actions")]
    if args.split:
        print(f"Eval split filter: {args.split}")
    if not cases:
        print("Eval: no cases with expected_actions — failing")
        return 1

    invalid = []
    for case in cases:
        try:
            if not args.allow_empty_actions:
                validate_case_config(case)
        except EvalConfigError as exc:
            invalid.append(str(exc))
    if invalid:
        print("Eval config errors:")
        for msg in invalid[:10]:
            print(f"  - {msg}")
        return 1

    results = []
    passed = 0
    with TestClient(app) as client:
        for case in cases:
            if args.allow_empty_actions and not case.get("expected_actions"):
                continue
            try:
                r = run_case(client, case)
            except EvalConfigError as exc:
                r = {"case_id": case.get("case_id"), "passed": False, "failures": [str(exc)]}
            results.append(r)
            if r["passed"]:
                passed += 1

    report = {
        "mode": args.mode,
        "split": args.split,
        "note": "configured live endpoint evaluation; model provenance must be verified separately",
        "llm_mode": args.mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "excluded_empty_actions": len(excluded),
        "pass_rate": passed / len(results) if results else 0,
        "results": results,
    }
    reports_dir = ROOT / "evals" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = reports_dir / f"eval-{args.mode}-{stamp}.json"
    md_path = reports_dir / f"eval-{args.mode}-{stamp}.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    md_path.write_text(
        f"# Eval Report ({args.mode})\n\n"
        f"- Total: {report['total']}\n"
        f"- Passed: {report['passed']}\n"
        f"- Failed: {report['failed']}\n"
        f"- Pass rate: {report['pass_rate']:.1%}\n"
        f"- Excluded (empty actions): {report['excluded_empty_actions']}\n",
        encoding="utf-8",
    )
    print(f"Eval {args.mode}: {passed}/{len(results)} passed")
    print(f"Report: {md_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
