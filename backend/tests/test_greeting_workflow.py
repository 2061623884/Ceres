"""A greeting is answered, not turned into a headcount interrogation."""

import uuid

from support import create_session, post_turn
from support.semantic_agent import reply_only


def test_greeting_does_not_ask_people(client, semantic_provider):
    semantic_provider([reply_only("你好，我可以帮你搭配购买方案。说说想吃什么或想买什么吧。")])
    sid = create_session(client)

    resp = post_turn(client, sid, "你好", None, request_id=str(uuid.uuid4()))
    assert resp.status_code == 200
    body = resp.json()
    assert "几个人" not in body["message"]
    assert "你好" in body["message"]
    # A greeting opens a conversation; it does not pre-commit a purchase.
    assert body["plan"] is None
    assert body["plan_effect"] == "keep"


def test_a_greeting_turn_writes_nothing_to_the_cart(client, semantic_provider):
    semantic_provider([reply_only("你好。")])
    sid = create_session(client)
    post_turn(client, sid, "你好", None, request_id=str(uuid.uuid4()))
    assert client.get("/api/v1/cart").json()["items"] == []
