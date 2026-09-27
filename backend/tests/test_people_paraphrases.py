"""U02 Chinese people paraphrase tests."""

from __future__ import annotations

import pytest

import uuid
from support import post_turn

PHRASES = ["我需要两人份", "换成两人份", "改为二人份", "两个人吃"]


def _flow(client, message):
    sid = client.post(
        "/api/v1/guide/sessions",
        json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}},
    ).json()["session_id"]
    first = post_turn(client, sid, "我想吃番茄炒蛋，四个人").json()
    return post_turn(client, sid, message, first)


def test_people_paraphrases_keep_template(client):
    for phrase in PHRASES:
        resp = _flow(client, phrase)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "awaiting_confirmation"
        names = " ".join(i.get("name") or "" for i in body["plan"]["items"])
        assert "番茄" in names or "鸡蛋" in names


@pytest.fixture(autouse=True)
def _offline_agent(reactive_agent):
    """Run this suite against the controlled agent without live credentials.

    The model provider is injected; every business assertion is unchanged.
    """
    return reactive_agent
