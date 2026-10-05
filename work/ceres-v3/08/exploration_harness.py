"""Explicit, controlled V3 return-then-cola exploration; run only by request."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"
MERCURY = ROOT / "Mercury"
for _path in (BACKEND, TESTS, MERCURY):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _backend_fixture_plugin():
    name = "ceres_v3_08_backend_test_fixtures"
    spec = importlib.util.spec_from_file_location(name, TESTS / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def controlled_external_boundary(monkeypatch):
    """Block socket-backed httpx sync traffic without touching ASGI/MockTransport."""
    import httpx

    def deny_uncontrolled_http(self, request):
        raise AssertionError(f"Unexpected external HTTP request: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_uncontrolled_http)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://mercury-controlled.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "mercury-controlled")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def evidence(request):
    record = {"case": request.node.name, "api": [], "mercury": {}, "database": {}}
    try:
        yield record
    finally:
        print("CERES_V3_08_EVIDENCE=" + json.dumps(record, ensure_ascii=False, sort_keys=True))


def _sql_snapshot(db_url: str, order_id: str) -> dict:
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            order = dict(connection.execute(text(
                "SELECT order_id, user_id, status, delivered_at FROM orders WHERE order_id=:order_id"
            ), {"order_id": order_id}).mappings().one())
            items = [dict(row) for row in connection.execute(text(
                "SELECT item_id, order_id, sku_id, product_name, returnable FROM order_items WHERE order_id=:order_id ORDER BY item_id"
            ), {"order_id": order_id}).mappings().all()]
            returns = [dict(row) for row in connection.execute(text(
                "SELECT return_id, order_id, item_id, refund_amount_fen, status FROM returns WHERE order_id=:order_id ORDER BY return_id"
            ), {"order_id": order_id}).mappings().all()]
            refunds = [dict(row) for row in connection.execute(text(
                "SELECT order_id, amount_fen, status FROM refunds WHERE order_id=:order_id ORDER BY order_id"
            ), {"order_id": order_id}).mappings().all()]
        return {"order": order, "items": items, "returns": returns, "refunds": refunds}
    finally:
        engine.dispose()


def _mark_delivered_in_test_database(db_url: str, order_id: str) -> None:
    delivered_at = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat()
    engine = create_engine(db_url)
    try:
        with engine.begin() as connection:
            changed = connection.execute(text(
                "UPDATE orders SET status='delivered', delivered_at=:delivered_at WHERE order_id=:order_id"
            ), {"delivered_at": delivered_at, "order_id": order_id}).rowcount
            assert changed == 1
            changed = connection.execute(text(
                "UPDATE order_items SET returnable=1 WHERE order_id=:order_id"
            ), {"order_id": order_id}).rowcount
            assert changed >= 1
    finally:
        engine.dispose()


def _tool_call(name: str, arguments: dict, call_id: str):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
    )


def _install_real_return_tool_driver(monkeypatch, order_id: str, expected_order_status: str, trace: dict):
    """Script only the external LLM boundary; Mercury's real tools execute normally."""
    expected_success = expected_order_status == "delivered"
    trace.update({"selected_order_id": order_id, "tool_calls": [], "tool_results": [],
                  "tool_schemas": [], "model_messages": [], "client_config": []})
    pending_tool = None

    def choose_tool(name: str, arguments: dict):
        nonlocal pending_tool
        call_id = f"controlled-{len(trace['tool_calls']) + 1}"
        pending_tool = name
        trace["tool_calls"].append({"name": name, "arguments": arguments, "call_id": call_id})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="", tool_calls=[_tool_call(name, arguments, call_id)]))])

    def final_answer(content: str):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=content, tool_calls=[]))])

    def complete(**kwargs):
        nonlocal pending_tool
        names = [row["function"]["name"] for row in kwargs.get("tools", [])]
        trace["tool_schemas"].append(names)
        messages = kwargs["messages"]
        trace["model_messages"].append([{"role": row["role"], "content": row.get("content", "")}
                                        for row in messages if row["role"] in ("user", "tool")])
        last = messages[-1]
        if last["role"] == "user":
            assert order_id in messages[0]["content"]
            assert "get_order_details" in names and "create_return" in names
            assert "list_orders" not in names
            return choose_tool("get_order_details", {"order_id": order_id})

        assert last["role"] == "tool"
        tool_name = pending_tool
        result = json.loads(last["content"])
        trace["tool_results"].append({"name": tool_name, "result": result})
        if tool_name == "get_order_details":
            assert result["ok"] is True, result
            data = result["data"]
            assert data["order_id"] == order_id and data["status"] == expected_order_status
            item = next(row for row in data["items"] if "鸡蛋" in row["product_name"])
            assert item["returnable"] is True
            return choose_tool("create_return", {
                "order_id": order_id, "item_id": item["item_id"], "reason": "用户明确要求退货",
            })

        if tool_name == "create_return":
            if expected_success:
                assert result["ok"] is True, result
                assert result["data"]["status"] == "requested", result
                return choose_tool("get_return_status", {"order_id": order_id})
            assert result == {
                "ok": False,
                "error": "NOT_DELIVERED",
                "message": "订单还没有签收，签收后才能申请退货",
            }, result
            pending_tool = None
            return final_answer("退货申请未提交：订单尚未签收。是否仍要继续选一瓶可乐？")

        assert tool_name == "get_return_status"
        assert result["ok"] is True, result
        rows = result["data"]
        assert len(rows) == 1 and rows[0]["order_id"] == order_id
        assert rows[0]["status"] == "requested"
        pending_tool = None
        return final_answer("退货申请已提交，当前待审核；退货完成和退款到账尚未发生。")

    def controlled_openai(**kwargs):
        trace["client_config"].append({key: value for key, value in kwargs.items()
                                       if key in ("base_url", "model", "timeout")})
        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=complete)))

    monkeypatch.setattr("mercury.llm.OpenAI", controlled_openai)


def _record_api(evidence: dict, name: str, response, *, request_body=None, parsed=None):
    evidence["api"].append({"name": name, "status": response.status_code,
                            "request": request_body, "response": parsed if parsed is not None else response.text})


@pytest.mark.parametrize(
    ("delivered", "expected_status"),
    [(True, "delivered"), (False, "paid")],
    ids=["delivered-return-requested", "paid-return-rejected-then-explicit-continue"],
)
def test_return_then_cola_uses_real_public_tools_and_explicit_next_step(
    indexed_client, test_db_url, kev, semantic_provider, monkeypatch, evidence,
    delivered, expected_status,
):
    from support.semantic_agent import lookup_then_add_id
    from test_v3_routing_handoff import events, new_order, opening, send

    order = new_order(indexed_client)
    assert len(order["items"]) == 1
    if delivered:
        _mark_delivered_in_test_database(test_db_url, order["order_id"])
    before = _sql_snapshot(test_db_url, order["order_id"])
    evidence["database"]["before"] = before
    assert before["order"]["status"] == expected_status
    assert not before["returns"] and not before["refunds"]
    item_name = order["items"][0]["product_name"]
    item_id = order["items"][0]["item_id"]
    assert before["items"][0]["item_id"] == item_id
    if delivered:
        assert before["order"]["delivered_at"]
        assert before["items"][0]["returnable"] == 1

    trace = {}
    _install_real_return_tool_driver(monkeypatch, order["order_id"], expected_status, trace)
    evidence["mercury"] = trace
    provider = semantic_provider(lookup_then_add_id("product", "可乐 330毫升", "demo:cola-330ml"))
    choices, kev_calls = kev
    choices.extend(["stay_current", "suggest_switch"])

    chat = opening(indexed_client, role="momo")
    original_message = (
        f"先申请退货订单 {order['order_id']} 中的{item_name}，申请成功后再帮我选一瓶可乐；"
        "如果申请未提交，请先暂停并问我是否继续。"
    )
    first = send(indexed_client, chat, original_message, f"08-{expected_status}-return",
                 order_id=order["order_id"])
    first_events = events(first)
    _record_api(evidence, "POST chat turn: return", first,
                request_body={"message": original_message, "order_id": order["order_id"]},
                parsed=first_events)
    assert first.status_code == 200, first.text
    assert first_events[0]["type"] == "service.route"
    assert first_events[0]["payload"]["decision"] == "stay_current"
    assert first_events[-1]["type"] == "turn.completed", first_events
    assert not any(event["type"] == "error" for event in first_events)
    assert kev_calls[0]["state"]["selected_object"]["order_id"] == order["order_id"]
    assert kev_calls[0]["state"]["utterance"] == original_message

    after_return = _sql_snapshot(test_db_url, order["order_id"])
    evidence["database"]["after_return"] = after_return
    guide_before = indexed_client.get(f"/api/v1/guide/sessions/{chat['guide_session_id']}").json()
    cart_before = indexed_client.get("/api/v1/cart").json()
    evidence["database"]["guide_before_explicit_continue"] = {
        "task_id": guide_before["task_id"], "plan": guide_before["plan"],
        "cart_items": cart_before["items"],
    }
    assert guide_before["task_id"] is None and guide_before["plan"] is None
    assert cart_before["items"] == []
    if delivered:
        assert len(after_return["returns"]) == 1
        assert after_return["returns"][0]["item_id"] == item_id
        assert after_return["returns"][0]["status"] == "requested"
        assert after_return["refunds"] == []
        continue_message = "退货申请已提交，我现在继续要一瓶可乐，请帮我选购。"
    else:
        assert after_return["returns"] == []
        assert after_return["refunds"] == []
        final_text = first_events[-1]["payload"]["final_text"]
        assert "申请未提交" in final_text and "是否仍要继续" in final_text
        continue_message = "知道订单未签收、退货申请未提交；我仍要继续选一瓶可乐，请帮我选购。"

    routed = send(indexed_client, chat, continue_message, f"08-{expected_status}-continue")
    route_events = events(routed)
    _record_api(evidence, "POST chat turn: explicit continue", routed,
                request_body={"message": continue_message}, parsed=route_events)
    assert routed.status_code == 200, routed.text
    route = route_events[0]["payload"]
    assert route_events[0]["type"] == "service.route"
    assert route["decision"] == "suggest_switch" and route["target_role"] == "keke"
    assert route["prompt_mode"] == "automatic"
    assert route_events[-1]["type"] == "turn.completed"
    assert route_events[-1]["payload"]["business_not_run"] is True
    assert "是否切换" in route_events[-1]["payload"]["message"]
    assert any(row["role"] == "assistant" and
               ("申请已提交" in row["content"] if delivered else "申请未提交" in row["content"])
               for row in kev_calls[-1]["state"]["recent_dialogue"])
    evidence["route_context_before_continue"] = kev_calls[-1]["state"]
    assert continue_message != original_message
    opening_path = f"/api/v1/chat/openings/{chat['opening_id']}"
    displayed = indexed_client.post(f"{opening_path}/prompt-displayed",
                                   json={"handoff_id": route["handoff_id"]})
    _record_api(evidence, "POST prompt-displayed", displayed,
                request_body={"handoff_id": route["handoff_id"]},
                parsed=displayed.json() if displayed.status_code < 400 else displayed.text)
    assert displayed.status_code == 200, displayed.text
    accept_body = {"target_role": "keke", "handoff_id": route["handoff_id"], "accept": True}
    switched = indexed_client.post(f"{opening_path}/switches/stream", json=accept_body)
    switched_events = events(switched)
    _record_api(evidence, "POST switches/stream: explicit acceptance", switched,
                request_body=accept_body, parsed=switched_events)
    assert switched.status_code == 200, switched.text
    completed = next(event["payload"] for event in switched_events
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["route"] == "prepare" and completed["plan"] is not None, completed
    assert completed["plan"]["items"][0]["sku_id"] == "demo:cola-330ml", completed["plan"]
    assert provider.requests[0]["user_message"] == continue_message
    assert provider.requests[0]["user_message"] != original_message
    assert any(row["role"] == "assistant" and
               ("申请已提交" in row["content"] if delivered else "申请未提交" in row["content"])
               for row in provider.requests[0]["recent_messages"])
    assert len([call for call in trace["tool_calls"] if call["name"] == "create_return"]) == 1
    final_guide = indexed_client.get(f"/api/v1/guide/sessions/{chat['guide_session_id']}").json()
    assert final_guide["plan"]["items"][0]["sku_id"] == "demo:cola-330ml"
    assert indexed_client.get("/api/v1/cart").json()["items"] == []
    final_snapshot = _sql_snapshot(test_db_url, order["order_id"])
    evidence["database"]["after_explicit_continue"] = final_snapshot
    if delivered:
        assert len(final_snapshot["returns"]) == 1
        assert final_snapshot["returns"][0]["status"] == "requested"
    else:
        assert final_snapshot["returns"] == []
    assert final_snapshot["refunds"] == []


def _run() -> int:
    plugins = [
        _backend_fixture_plugin(),
        importlib.import_module("test_v3_routing_handoff"),
        importlib.import_module("test_semantic_phase1_purchase"),
    ]
    arguments = [str(Path(__file__).resolve()), "-q", "-s", *sys.argv[1:]]
    return int(pytest.main(arguments, plugins=plugins))


if __name__ == "__main__":
    raise SystemExit(_run())
