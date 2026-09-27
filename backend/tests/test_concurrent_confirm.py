"""N02 concurrent confirmation must execute at most once."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from app.core import database as db_module
from app.core.errors import AppError
from app.models.cart import CartItem
from app.models.session import GuideSession, GuideTask
from app.services.cart_service import CartService
from app.services.confirmation_service import ConfirmationService


def _seed_awaiting_task(client) -> tuple[str, dict, int, str]:
    """Seed awaiting_confirmation task directly; avoids workflow turn routing."""
    sid = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]

    db = db_module.SessionLocal()
    try:
        session = db.get(GuideSession, sid)
        assert session is not None
        owner_id = session.owner_id
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        items = [
            {
                "sku_id": "demo:tomato-fresh-500g",
                "name": "鲜番茄 500克",
                "quantity": 2,
                "unit_price_fen": 680,
                "line_total_fen": 1360,
                "role": "required",
                "selected": True,
            },
            {
                "sku_id": "demo:eggs-fresh-6pack",
                "name": "鲜鸡蛋 6枚装",
                "quantity": 1,
                "unit_price_fen": 980,
                "line_total_fen": 980,
                "role": "required",
                "selected": True,
            },
        ]
        plan = {
            "plan_id": plan_id,
            "plan_version": 1,
            "mode": "bundle",
            "items": items,
            "total_price_fen": 2340,
            "expires_at": expires_at,
            "validation_status": "passed",
            "can_confirm": True,
            "coverage_mode": "full",
        }
        state_version = 2
        task = GuideTask(
            task_id=task_id,
            session_id=sid,
            owner_id=owner_id,
            state_version=state_version,
            intent="purchase",
            current_step="awaiting_confirmation",
            status="active",
            plan_json=json.dumps(plan, ensure_ascii=False),
            requirements_json="{}",
        )
        session.current_task_id = task_id
        session.session_version = 1
        db.add(task)
        db.commit()
        return task_id, plan, state_version, owner_id
    finally:
        db.close()


def test_concurrent_confirm_barrier_single_cart_write(client):
    """Two DB sessions race confirm at a barrier; cart must be written once."""
    task_id, plan, state_version, owner_id = _seed_awaiting_task(client)
    items = [
        {"sku_id": i["sku_id"], "quantity": i["quantity"]}
        for i in plan["items"]
        if i.get("role", "required") == "required"
    ]
    digest = CartService.digest_request(
        {
            "plan_id": plan["plan_id"],
            "plan_version": plan["plan_version"],
            "expected_state_version": state_version,
            "selected_items": items,
        }
    )

    barrier = Barrier(2)

    def _confirm_worker(key_suffix: str) -> dict | AppError:
        db = db_module.SessionLocal()
        try:
            svc = ConfirmationService(db, owner_id)
            barrier.wait(timeout=10)
            return svc.confirm(
                task_id,
                plan["plan_id"],
                plan["plan_version"],
                state_version,
                items,
                f"key-{uuid.uuid4()}-{key_suffix}",
                digest,
            )
        except AppError as exc:
            return exc
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_confirm_worker, "a"),
            pool.submit(_confirm_worker, "b"),
        ]
        results = [f.result(timeout=30) for f in futures]

    completed = [r for r in results if isinstance(r, dict) and r.get("status") == "completed"]
    stale = [
        r
        for r in results
        if isinstance(r, AppError) and r.detail["error"]["code"] == "STALE_STATE"
    ]
    assert len(completed) == 1
    assert len(stale) == 1

    db = db_module.SessionLocal()
    try:
        cart_items = db.query(CartItem).all()
        total_qty = sum(i.quantity for i in cart_items)
        expected_qty = sum(i["quantity"] for i in items)
        assert total_qty == expected_qty
    finally:
        db.close()
