"""N04 trace persistence and client event policy."""

from __future__ import annotations

import pytest

import uuid

from app.models.trace import BusinessEvent, TraceEvent
from support import post_turn


def test_client_forged_success_event_rejected(client):
    resp = client.post(
        "/api/v1/events",
        json={
            "events": [
                {
                    "event_type": "cart_add_succeeded",
                    "client_event_id": "client-forged-1",
                    "payload": {"sku_id": "demo:x"},
                }
            ]
        },
    )
    assert resp.status_code == 422


def test_client_event_dedup(client):
    payload = {
        "events": [
            {
                "event_type": "guide_opened",
                "client_event_id": "dedup-test-1",
                "payload": {},
            }
        ]
    }
    first = client.post("/api/v1/events", json=payload)
    second = client.post("/api/v1/events", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(BusinessEvent).filter_by(client_event_id="dedup-test-1").all()
        assert len(rows) == 1
        assert rows[0].source == "client"
    finally:
        db.close()


def test_model_timeout_keeps_failure_trace(client, semantic_provider):
    """A provider failure is receipted as a refusal with its real error code."""
    from support.reactive_semantic import provider_error

    semantic_provider([provider_error("MODEL_TIMEOUT", retryable=True)])

    sid = client.post(
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

    request_id = str(uuid.uuid4())
    resp = post_turn(client, sid, "帮我选蛋糕面粉", None, request_id=request_id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["route"] == "refuse"
    assert any(row.get("code") == "MODEL_TIMEOUT" for row in resp.json()["action_results"])

    from app.core.database import SessionLocal
    from app.models.cart import TurnRequestRecord

    db = SessionLocal()
    try:
        events = db.query(TraceEvent).filter(TraceEvent.phase == "model_call_failed").all()
        assert len(events) >= 1

        record = (
            db.query(TurnRequestRecord)
            .filter_by(session_id=sid, request_id=request_id)
            .one()
        )
        assert record.status == "completed"
        assert "MODEL_TIMEOUT" in (record.response_json or "")
    finally:
        db.close()
