"""Remaining fixed public V3 cases through actual role/API/business paths."""
import json
from types import SimpleNamespace

import pytest

from test_v3_policy_consultation import controlled_memory_and_join_workers  # noqa: F401
from test_v3_routing_handoff import events, kev, opening, send, new_order
from support.semantic_agent import Continuation, request_new
from support.v2_fixture import source_database_path  # noqa: F401
from test_semantic_phase1_purchase import indexed_client  # noqa: F401


@pytest.mark.parametrize("role,message,decision,quantity", [
    ("keke", "想买两瓶无糖可乐", "stay_current", 2),
    ("momo", "想买无糖可乐", "suggest_switch", 1),
])
def test_fixed_shopping_utterance_reaches_real_plan_after_required_consent(
    indexed_client, kev, semantic_provider, role, message, decision, quantity
):
    product = "可口可乐零度无糖汽水500ml瓶装"
    provider = semantic_provider([{
        **request_new("product", product, quantity=quantity),
        "lookups": [{"kind": "product", "query": product}],
    }])
    chat = opening(indexed_client, role=role)
    if role == "momo":
        order = new_order(indexed_client)
        selected = indexed_client.post(
            f"/api/v1/mercury/sessions/{chat['mercury_session_id']}/order",
            json={"order_id": order["order_id"]},
        )
        assert selected.status_code == 200, selected.text
    before_orders = indexed_client.get("/api/v1/orders").json()
    kev[0].append(decision)
    result = events(send(indexed_client, chat, message, "fixed-shopping"))
    assert result[0]["payload"]["decision"] == decision
    if role == "momo":
        assert provider.requests == []
        assert result[-1]["payload"]["business_not_run"] is True
        path = f"/api/v1/chat/openings/{chat['opening_id']}"
        assert indexed_client.get(path).json()["role"] == "momo"
        result = events(indexed_client.post(f"{path}/switches/stream", json={
            "target_role": "keke", "accept": True,
            "handoff_id": result[0]["payload"]["handoff_id"],
        }))
    completed = next(event["payload"] for event in result
                     if event["type"] == "turn.completed" and "plan" in event["payload"])
    assert completed["plan"] is not None, completed
    item = completed["plan"]["items"][0]
    assert item["sku_id"] == "demo:cn-coke-zero-500ml-bottle"
    assert item["quantity"] == quantity
    assert provider.requests[0]["user_message"] == message
    assert indexed_client.get("/api/v1/orders").json() == before_orders
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("case_id,message,topic,policy_id", [
    ("R02", "这个商品不喜欢能退吗", "这个商品不喜欢能退吗", "P-RET-01"),
    ("P01", "一般配送时间", "一般配送时间", "P-DEL-01"),
])
def test_keke_policy_stays_and_answers_with_source(client, kev, semantic_provider,
                                                  case_id, message, topic, policy_id):
    def answer(context):
        facts = context["query_results"][0]["policies"]
        fact = next(row for row in facts if row["policy_id"] == policy_id)
        return {"reply": f"模拟门店：{fact['content']} 来源 {fact['policy_id']} {fact['title']}。"}

    semantic_provider([{"reads": [{"kind": "policy", "topic": topic}]}, Continuation(answer)])
    chat = opening(client)
    kev[0].append("stay_current")
    before = client.get("/api/v1/orders").json()
    extra = {"view_context": {"page": "product", "product_id": "demo:cn-coke-zero-500ml-bottle"}} if case_id == "R02" else {}
    result = events(send(client, chat, message, case_id, **extra))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert policy_id in result[-1]["payload"]["message"]
    assert result[-1]["payload"]["task_id"] is None
    assert client.get("/api/v1/orders").json() == before
    assert client.get("/api/v1/cart").json()["items"] == []


def test_r03_unselected_momo_reads_shared_policy_without_order(client, kev, monkeypatch):
    chat = opening(client, role="momo")
    kev[0].append("stay_current")
    reads = []

    def model(**kwargs):
        assert {t["function"]["name"] for t in kwargs["tools"]} == {"search_after_sales_policy"}
        if kwargs["messages"][-1]["role"] == "tool":
            facts = json.loads(kwargs["messages"][-1]["content"])
            row = next(p for p in facts["data"] if p["policy_id"] == "P-RET-01")
            reads.append(facts)
            message = SimpleNamespace(content=f"模拟门店：{row['content']} 来源 P-RET-01。", tool_calls=[])
        else:
            message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="policy", function=SimpleNamespace(
                name="search_after_sales_policy", arguments=json.dumps({"query": "一般签收后几天内能退", "category": "return"})))])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    result = events(send(client, chat, "一般签收后几天内能退", "R03"))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert "P-RET-01" in result[-1]["payload"]["final_text"]
    assert len(reads) == 1
    assert client.get("/api/v1/orders").json()["items"] == []


def test_r05_order_eligibility_stays_and_reads_actual_owned_order(client, kev, monkeypatch):
    order = new_order(client)
    chat = opening(client, role="momo")
    kev[0].append("stay_current")
    reads = []

    def model(**kwargs):
        if kwargs["messages"][-1]["role"] == "tool":
            reads.append(json.loads(kwargs["messages"][-1]["content"]))
            message = SimpleNamespace(content="这是模拟订单，可退资格须按商品及签收时间判断；本轮未提交申请。", tool_calls=[])
        else:
            message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="read", function=SimpleNamespace(
                name="check_return_eligibility", arguments=json.dumps({"order_id": order["order_id"]})))])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=model))))
    result = events(send(client, chat, "这单还能退吗", "R05", order_id=order["order_id"]))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert result[0]["payload"]["current_role"] == "momo"
    assert len(reads) == 1
    assert order["order_id"] in json.dumps(reads)
    assert reads[0]["ok"] is True
    assert reads[0]["data"]["order_eligible"] is False  # Fresh checkout has not been delivered.
    assert client.get(f"/api/v1/orders/{order['order_id']}").json() == order


def test_r09_life_comment_stays_without_creating_task(client, kev, semantic_provider):
    chat = opening(client)
    kev[0].append("stay_current")
    semantic_provider([{"reply": "可以先休息一下。"}])
    result = events(send(client, chat, "今天有点累", "R09"))
    assert result[0]["payload"]["decision"] == "stay_current"
    assert result[-1]["payload"]["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []
