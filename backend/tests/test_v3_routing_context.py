"""Same utterance, existing dialogue, new requests and owner-bound objects."""
from support import post_turn
from test_v3_policy_consultation import controlled_memory_and_join_workers
from test_v3_routing_handoff import events, kev, new_order, opening, send


def test_list_cancellation_uses_guide_history_without_order_action(client, kev, semantic_provider):
    semantic_provider([{"reply": "你要移除采购清单里的可乐吗？"}, {"reply": "可以继续调整采购清单。"}])
    chat = opening(client)
    post_turn(client, chat["guide_session_id"], "清单里的可乐不要了")
    kev[0].append("stay_current")
    result = events(send(client, chat, "取消一下", "r06"))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert "清单里的可乐不要了" in str(kev[1][0]["state"]["recent_dialogue"])
    assert client.get("/api/v1/orders").json()["items"] == []


def test_new_shopping_request_invalidates_old_order_handoff(client, kev, semantic_provider):
    chat = opening(client)
    order = new_order(client)
    kev[0].extend(["suggest_switch", "stay_current"])
    first = events(send(client, chat, "这单到哪了", "old-order", order_id=order["order_id"]))[0]["payload"]
    semantic_provider([{"reply": "我们先选无糖可乐。"}])
    result = events(send(client, chat, "现在先帮我选无糖可乐", "r10"))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert kev[1][-1]["state"]["utterance"] == "现在先帮我选无糖可乐"
    stale = client.post(f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream", json={
        "target_role": "momo", "handoff_id": first["handoff_id"], "accept": True})
    assert stale.status_code == 409 and "HANDOFF_STALE" in stale.text


def test_foreign_opening_and_order_are_rejected_before_model(client, kev):
    chat = opening(client)
    order = new_order(client)
    original_cookies = dict(client.cookies)
    client.cookies.clear()
    assert client.get(f"/api/v1/chat/openings/{chat['opening_id']}").status_code == 404
    other = opening(client)
    # This rejection occurs at the object boundary, before Kev or target processing.
    kev[0].append("suggest_switch")
    response = send(client, other, "这单到哪了", "foreign", order_id=order["order_id"])
    assert response.status_code in (403, 404)
    assert kev[1] == []
    client.cookies.clear()
    client.cookies.update(original_cookies)
    assert client.get(f"/api/v1/orders/{order['order_id']}").json() == order
