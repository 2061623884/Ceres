"""Public V3 chat requests, consent, ownership and original-message delivery."""
import json
from types import SimpleNamespace

import httpx
import pytest

from support import create_session
from test_v3_policy_consultation import controlled_memory_and_join_workers


@pytest.fixture
def kev(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("KEV_BASE_URL", "http://kev-controlled.invalid")
    get_settings.cache_clear()
    calls, choices = [], []
    original = httpx.Client.send

    def send(self, request, **kwargs):
        if request.url.host != "kev-controlled.invalid":
            return original(self, request, **kwargs)
        calls.append(json.loads(request.content))
        item = choices.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, request=request, json={"model": "kev-latest", "answers": {
            "service": {"type": "choice", "choice": item, "probabilities": {
                option: float(option == item) for option in ("stay_current", "suggest_switch", "clarify")}}}})

    monkeypatch.setattr(httpx.Client, "send", send)
    return choices, calls


def opening(client, role="keke", **extra):
    guide = create_session(client)
    momo = client.post("/api/v1/mercury/sessions").json()["session_id"]
    response = client.post("/api/v1/chat/openings", json={"guide_session_id": guide,
        "mercury_session_id": momo, "role": role, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def send(client, chat, message, request_id, **extra):
    return client.post(f"/api/v1/chat/openings/{chat['opening_id']}/turns/stream", json={
        "message": message, "request_id": request_id, "expected_state_version": 0, **extra})


def events(response):
    rows = []
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        data = next((line[6:] for line in block.splitlines() if line.startswith("data: ")), None)
        if data is not None:
            body = json.loads(data)
            name = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), None)
            rows.append(body if name is None else {"type": name, "payload": body})
    return rows


def new_order(client):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 1}).json()
    return client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"]


def test_shopping_continues_existing_guide_with_observable_route(client, kev, semantic_provider):
    choices, calls = kev
    choices.append("stay_current")
    semantic_provider([{"reply": "想要哪种规格的无糖可乐？"}])
    chat = opening(client)
    result = events(send(client, chat, "想买两瓶无糖可乐", "r01"))
    route = result[0]["payload"]
    assert result[0]["type"] == "service.route"
    assert route["decision"] == "stay_current"
    assert route["raw_choice"] == "stay_current" and route["probabilities"]
    assert route["route_ms"] >= 0 and route["criteria_version"]
    assert result[-1]["type"] == "turn.completed"
    assert calls[0]["state"]["utterance"] == "想买两瓶无糖可乐"
    assert client.get("/api/v1/orders").json()["items"] == []


def test_order_request_waits_for_consent_and_replays_exactly_once(client, kev, monkeypatch):
    choices, calls = kev
    choices.append("suggest_switch")
    order_a, order_b = new_order(client), new_order(client)
    chat = opening(client)
    client.post(f"/api/v1/mercury/sessions/{chat['mercury_session_id']}/order", json={"order_id": order_b["order_id"]})
    tool_calls = []

    def model(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] == "user":
            assert messages[-1]["content"] == "这单到哪了"
            assert order_a["order_id"] in messages[0]["content"]
            msg = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="read", function=SimpleNamespace(
                name="get_order_details", arguments=json.dumps({"order_id": order_a["order_id"]})))])
        else:
            tool_calls.append(json.loads(messages[-1]["content"]))
            msg = SimpleNamespace(content="已重新查询这张模拟订单。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    response = send(client, chat, "这单到哪了", "r04", order_id=order_a["order_id"])
    route = events(response)[0]["payload"]
    assert route["decision"] == "suggest_switch" and route["prompt_mode"] == "automatic"
    assert not tool_calls
    assert client.get(f"/api/v1/chat/openings/{chat['opening_id']}").json()["role"] == "keke"
    assert client.post(f"/api/v1/chat/openings/{chat['opening_id']}/prompt-displayed", json={"handoff_id": route["handoff_id"]}).status_code == 200
    path = f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream"
    body = {"target_role": "momo", "handoff_id": route["handoff_id"], "accept": True}
    first, repeat = client.post(path, json=body), client.post(path, json=body)
    assert first.text == repeat.text
    assert len(tool_calls) == 1
    assert client.get(f"/api/v1/chat/openings/{chat['opening_id']}").json()["role"] == "momo"
    assert calls[0]["state"]["selected_object"]["order_id"] == order_a["order_id"]
    assert client.get(f"/api/v1/orders/{order_a['order_id']}").json() == order_a


def test_unknown_object_clarifies_without_role_business_or_order_mutation(client, kev):
    kev[0].append("clarify")
    chat = opening(client)
    result = events(send(client, chat, "取消一下", "r07"))
    assert result[0]["payload"]["decision"] == "clarify"
    completion = result[-1]["payload"]
    assert completion["business_not_run"] is True
    assert "取消" not in completion["message"]
    assert "采购清单项" in completion["message"] and "已下单订单" in completion["message"]
    assert client.get(f"/api/v1/chat/openings/{chat['opening_id']}").json()["role"] == "keke"
    assert client.get("/api/v1/orders").json()["items"] == []


def test_route_unavailable_is_failure_but_current_role_still_operates(client, kev, semantic_provider):
    kev[0].append(httpx.ConnectError("Controlled Kev unavailable"))
    semantic_provider([{"reply": "可以继续选购。"}])
    result = events(send(client, opening(client), "帮我选饮料", "f01"))
    route = result[0]["payload"]
    assert route["status"] == "unavailable" and route["decision"] is None
    assert "Controlled Kev unavailable" in route["error"]
    assert route["manual_switch_available"] is True
    assert result[-1]["type"] == "turn.completed"


def test_failed_handoff_replays_failure_without_reexecuting(client, kev, monkeypatch):
    kev[0].append("suggest_switch")
    chat = opening(client)
    order = new_order(client)
    count = []

    def unavailable(**kwargs):
        count.append(1)
        raise RuntimeError("Controlled Mercury generation failure")

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=unavailable))))
    route = events(send(client, chat, "这单到哪了", "failed-handoff", order_id=order["order_id"]))[0]["payload"]
    path = f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream"
    body = {"target_role": "momo", "handoff_id": route["handoff_id"], "accept": True}
    first, repeat = client.post(path, json=body), client.post(path, json=body)
    assert events(first)[-1]["type"] == "error"
    assert repeat.status_code == 200 and repeat.text == first.text
    assert count == [1]


def test_after_manual_switch_router_receives_actual_momo_role_and_order(client, kev, monkeypatch):
    chat = opening(client)
    order = new_order(client)
    client.post(f"/api/v1/mercury/sessions/{chat['mercury_session_id']}/order", json={"order_id": order["order_id"]})
    client.post(f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream", json={"target_role": "momo", "accept": True})
    kev[0].append("stay_current")
    message = SimpleNamespace(content="可以在这里咨询这张订单。", tool_calls=[])
    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:
            SimpleNamespace(choices=[SimpleNamespace(message=message)])))))
    assert send(client, chat, "这单到哪了", "momo-current-role").status_code == 200
    state = kev[1][0]["state"]
    assert state["current_role"] == "Momo after-sales"
    assert state["selected_object"]["order_id"] == order["order_id"]


def test_momo_explicit_order_matches_router_and_business_instead_of_old_selection(client, kev, monkeypatch):
    chat = opening(client)
    order_a, order_b = new_order(client), new_order(client)
    client.post(f"/api/v1/mercury/sessions/{chat['mercury_session_id']}/order", json={"order_id": order_b["order_id"]})
    client.post(f"/api/v1/chat/openings/{chat['opening_id']}/switches/stream", json={"target_role": "momo", "accept": True})
    kev[0].append("stay_current")
    seen = []

    def answer(**kwargs):
        assert order_a["order_id"] in kwargs["messages"][0]["content"]
        seen.append(1)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="只咨询指定的模拟订单A。", tool_calls=[]))])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=answer))))
    response = send(client, chat, "这单到哪了", "explicit-order-a", order_id=order_a["order_id"])
    assert events(response)[-1]["type"] == "turn.completed"
    assert seen == [1]
    assert kev[1][0]["state"]["selected_object"]["order_id"] == order_a["order_id"]
    assert client.get(f"/api/v1/orders/{order_b['order_id']}").json() == order_b
