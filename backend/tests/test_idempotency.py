
import pytest
"""Idempotency tests."""

import uuid
from support import post_turn


def test_turn_idempotent_replay(client):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "category_id": None, "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]
    req_id = str(uuid.uuid4())
    body = {
        "request_id": req_id,
        "message": "今晚想做顿简单的饭",
        "expected_task_id": None,
        "expected_state_version": 0,
    }
    r1 = post_turn(client, sid, body["message"], None, request_id=req_id)
    r2 = post_turn(client, sid, body["message"], None, request_id=req_id)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["task_id"] == r2.json()["task_id"]
    assert r1.json()["state_version"] == r2.json()["state_version"]


def test_stale_task_id_rejected(client):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "category_id": None, "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]
    r1 = post_turn(client, sid, "hello", None, request_id=str(uuid.uuid4()))
    task_id = r1.json()["task_id"]
    fake_old = "task-deadbeef00"
    r2 = post_turn(client, sid, "more", {"task_id": fake_old, "state_version": 1}, request_id=str(uuid.uuid4()))
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "STALE_STATE"


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent
