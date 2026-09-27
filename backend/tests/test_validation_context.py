"""N02 validation context and hard constraints."""

from __future__ import annotations

import pytest

import uuid

from app.agent.state import Requirements
from app.services.plan_validator import PlanValidator
from app.services.validation_context import ValidationContext
from support import post_turn


def test_excluded_egg_blocks_egg_skus(client):
    db = client.app.dependency_overrides  # noqa: not used
    from app.core.database import SessionLocal

    db_sess = SessionLocal()
    try:
        ctx = ValidationContext.from_requirements(
            Requirements(excluded_ingredients=["egg"]),
            store_id="store-demo-01",
            delivery_zone_id="zone-default",
        )
        validator = PlanValidator(db_sess, "store-demo-01", "zone-default")
        result = validator.validate_plan(
            [{"sku_id": "demo:eggs-fresh-6pack", "quantity": 1}],
            ["demo:eggs-fresh-6pack"],
            ctx=ctx,
        )
        assert result["validation_status"] == "failed"
    finally:
        db_sess.close()


def test_delivery_deadline_rejects_slow_eta(client):
    from app.core.database import SessionLocal

    db_sess = SessionLocal()
    try:
        ctx = ValidationContext.from_requirements(
            Requirements(delivery_deadline="10分钟内送达"),
            store_id="store-demo-01",
            delivery_zone_id="zone-default",
        )
        validator = PlanValidator(db_sess, "store-demo-01", "zone-default")
        result = validator.validate_plan(
            [{"sku_id": "demo:tomato-fresh-500g", "quantity": 1}],
            ["demo:tomato-fresh-500g"],
            ctx=ctx,
        )
        assert result["validation_status"] == "failed"
        assert any("deadline" in e.lower() or "ETA" in e for e in result.get("errors", []))
    finally:
        db_sess.close()


def _session(client):
    return client.post(
        "/api/v1/guide/sessions",
        json={
            "entry_context": {
                "page": "category",
                "category_id": "baking",
                "store_id": "store-demo-01",
                "delivery_zone_id": "zone-default",
            }
        },
    ).json()["session_id"]


def test_small_pack_flour_excludes_large_bag(client):
    sid = _session(client)
    resp = post_turn(client, sid, "蛋糕面粉，小包装", None, request_id=str(uuid.uuid4()))
    assert resp.status_code == 200
    body = resp.json()
    if body.get("plan"):
        for item in body["plan"]["items"]:
            assert item["sku_id"] != "demo:flour-allpurpose-1kg"


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent
