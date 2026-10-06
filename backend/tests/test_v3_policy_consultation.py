"""General policy consultation through the role chat APIs."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import get_settings
from app.core.config import Settings
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport
from support import create_session, post_turn
from support.semantic_agent import Continuation
from support.v2_fixture import source_database_path


@pytest.fixture(autouse=True)
def controlled_memory_and_join_workers(monkeypatch):
    """Only the external memory model is controlled; drain real worker traces."""
    import threading
    from app.llm.memory_provider import MemoryProvider, MemoryOutput
    from app.services.turn_stream_service import TurnStreamService

    monkeypatch.setattr(MemoryProvider, "complete", lambda self, mode, context: MemoryOutput(memories=[]))
    workers = []
    run = TurnStreamService._run_turn_worker

    def tracked(self, *args, **kwargs):
        workers.append(threading.current_thread())
        return run(self, *args, **kwargs)

    monkeypatch.setattr(TurnStreamService, "_run_turn_worker", tracked)
    yield
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive(), "Real turn/memory worker did not finish before test teardown"


def test_keke_reads_return_policy_before_any_mercury_session(client, semantic_provider):
    def answer(request):
        facts = request["query_results"][0]
        policies = {p["policy_id"]: p for p in facts["policies"]}
        assert "签收后 7 天内" in policies["P-RET-01"]["content"]
        assert "不可退货" in policies["P-RET-02"]["content"]
        return {"reply": "模拟门店：签收后7天内，可退货商品可按件申请；生鲜等不可退货商品除外。来源 P-RET-01 签收后退货、P-RET-02 不支持退货的商品。"}

    semantic_provider([
        {"reads": [{"kind": "policy", "topic": "这个商品不喜欢能退吗"}]},
        Continuation(answer),
    ])
    sid = create_session(client)
    response = post_turn(client, sid, "这个商品不喜欢能退吗")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert "P-RET-01" in json.dumps(body, ensure_ascii=False)
    assert body["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []
    assert client.get("/api/v1/orders").json()["items"] == []


def test_keke_policy_answer_uses_conditions_instead_of_product_recommendation(
    client, monkeypatch, kev_api
):
    kev_api["choices"]["capability"] = "facts_qa"
    calls = []

    def model(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            system_prompt = payload["messages"][0]["content"].split("\nprotocol:\n", 1)[0]
            assert "能力：回答商品、门店或政策事实。" in system_prompt
            assert "一般退换货、退款、配送规则用 reads policy" in system_prompt
            result = {"reads": [{"kind": "policy", "topic": "一般配送时间"}]}
        else:
            assert len(payload["messages"][0]["content"]) <= 2000
            assert "reply 只说明这款商品" not in payload["messages"][0]["content"]
            assert "policy_id" in payload["messages"][0]["content"]
            context = json.loads(payload["messages"][-2]["content"])["server_context"]
            policies = context["query_results"][0]["policies"]
            assert any(p["policy_id"] == "P-DEL-01" for p in policies)
            result = {"reply": "模拟门店当天下单配送，预计送达以物流信息为准。来源 P-DEL-01 配送时间。", "display_refs": []}
        content = json.dumps(result, ensure_ascii=False)
        if payload.get("stream"):
            frame = {"choices": [{"index": 0, "delta": {"content": content}}]}
            return httpx.Response(200, text="data: " + json.dumps(frame, ensure_ascii=False) + "\n\ndata: [DONE]\n\n",
                                  headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(_env_file=None, openai_base_url="http://controlled.invalid/v1",
                        openai_api_key="test-only", llm_model="controlled-policy")
    provider = LiveSemanticProvider(settings, OpenAICompatTransport(settings, httpx.MockTransport(model)))
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)
    response = post_turn(client, create_session(client), "一般配送时间")
    assert response.status_code == 200
    assert "P-DEL-01" in json.dumps(response.json(), ensure_ascii=False)
    assert len(calls) == 2
    assert response.json()["task_id"] is None
    assert client.get("/api/v1/cart").json()["items"] == []
    assert client.get("/api/v1/orders").json()["items"] == []


def test_momo_can_consult_policy_without_selecting_an_order(client, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()

    def create(**kwargs):
        assert {t["function"]["name"] for t in kwargs["tools"]} == {"search_after_sales_policy"}
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                id="policy", function=SimpleNamespace(name="search_after_sales_policy",
                arguments=json.dumps({"query": "一般签收后几天内能退", "category": "return"})))])
        else:
            facts = json.loads(messages[-1]["content"])
            policies = {p["policy_id"]: p for p in facts["data"]}
            assert "签收后 7 天内" in policies["P-RET-01"]["content"]
            message = SimpleNamespace(content="模拟门店签收后7天内，可退商品按件申请。来源 P-RET-01 签收后退货；不可退商品除外。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **settings:
                        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    session = client.post("/api/v1/mercury/sessions").json()
    response = client.post(f"/api/v1/mercury/sessions/{session['session_id']}/turns/stream",
                           json={"message": "一般签收后几天内能退", "request_id": "general-policy"})
    assert response.status_code == 200
    assert "P-RET-01" in response.text
    assert "请选择" not in response.text
    assert client.get("/api/v1/orders").json()["items"] == []


@pytest.mark.parametrize("order_tool", ["get_order_details", "create_refund", "create_return"])
def test_unselected_policy_chat_rejects_even_unsolicited_order_tools(client, monkeypatch, order_tool):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 1}).json()
    order = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"]
    sid = client.post("/api/v1/mercury/sessions").json()["session_id"]
    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()
    rejected = []

    def create(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            args = {"order_id": order["order_id"], "item_id": order["items"][0]["item_id"]}
            message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="unsolicited",
                function=SimpleNamespace(name=order_tool, arguments=json.dumps(args)))])
        else:
            result = json.loads(messages[-1]["content"])
            assert result["error"] == "ORDER_NOT_SELECTED"
            rejected.append(result)
            message = SimpleNamespace(content="具体订单业务请先选择订单；一般政策仍可咨询。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **settings:
                        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    response = client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream",
                           json={"message": "一般退货政策是什么", "request_id": "policy-tool-boundary"})
    assert "请先选择" in response.text
    assert len(rejected) == 1
    assert client.get(f"/api/v1/orders/{order['order_id']}").json() == order


def test_greetings_and_life_comments_do_not_create_a_purchase_task(client, semantic_provider):
    semantic_provider([{"reply": "你好，想了解选购或政策都可以聊。"},
                       {"reply": "可以先休息一下。"},
                       {"reply": "我主要帮助超市选购和门店政策咨询。"}])
    sid = create_session(client)
    previous = None
    for message in ("你好", "今天有点累", "我们继续聊无关的游戏吧"):
        result = post_turn(client, sid, message, previous).json()
        assert result["task_id"] is None
        previous = result
    assert client.get("/api/v1/cart").json()["items"] == []


def test_policy_reinitialization_keeps_existing_facts_and_unknown_query_is_honest(client, semantic_provider):
    from sqlalchemy import text
    from app.core import database as db_module

    client.post("/api/v1/mercury/sessions")
    with db_module.SessionLocal() as db:
        db.execute(text("UPDATE policies SET content='演示更新：次日配送，具体以物流为准。' WHERE policy_id='P-DEL-01'"))
        db.commit()

    def updated_answer(request):
        policies = request["query_results"][0]["policies"]
        assert next(p["content"] for p in policies if p["policy_id"] == "P-DEL-01") == "演示更新：次日配送，具体以物流为准。"
        return {"reply": "模拟门店更新为次日配送，具体以物流为准。来源 P-DEL-01 配送时间。"}

    def unknown_answer(request):
        assert request["query_results"][0]["empty"] is True
        assert request["query_results"][0]["policies"] == []
        return {"reply": "现有门店政策中未找到保修十年的依据，不能确认这个承诺。"}

    semantic_provider([{"reads": [{"kind": "policy", "topic": "一般配送时间"}]}, Continuation(updated_answer),
                       {"reads": [{"kind": "policy", "topic": "保修十年吗"}]}, Continuation(unknown_answer)])
    sid = create_session(client)
    first = post_turn(client, sid, "一般配送时间").json()
    second = post_turn(client, sid, "保修十年吗", first).json()
    assert "未找到" in second["message"]
    assert second["task_id"] is None
