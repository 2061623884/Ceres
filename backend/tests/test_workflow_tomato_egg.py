
import pytest
"""Workflow: 番茄炒蛋 template plan without budget clarification."""

import uuid
from support import post_turn


def _session(client):
    resp = client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "home",
                "category_id": None,
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    )
    return resp.json()["session_id"]


def _turn(client, session_id, message, task_id=None, version=0, request_id=None):
    previous = {"task_id": task_id, "state_version": version}
    return post_turn(
        client, session_id, message, previous, request_id=request_id or str(uuid.uuid4())
    )


def test_tomato_egg_plan_without_budget_clarification(client):
    sid = _session(client)
    resp = _turn(client, sid, "我想吃番茄炒蛋")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "awaiting_confirmation"
    assert "预算" not in body["message"]
    assert "budget" not in (body.get("missing_constraints") or [])

    plan = body["plan"]
    assert plan is not None
    sku_ids = {item["sku_id"] for item in plan["items"]}
    assert any(s.startswith("demo:") or s.isdigit() for s in sku_ids)
    assert "demo:eggs-fresh-6pack" in sku_ids or "demo:eggs-10pack" in sku_ids
    names = " ".join(item["name"] for item in plan["items"])
    assert "番茄" in names or "Tomato" in names
    assert "鸡蛋" in names or "Egg" in names
    assert plan["total_price_fen"] > 0


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent
