"""Ceres Next 04: actual guide requests use the current category behavior."""

import json
from types import SimpleNamespace

import httpx

from app.core.config import get_settings
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport
from support import create_session, post_turn, send_turn

from test_semantic_phase1_purchase import indexed_client  # noqa: F401


# Full request-body measurement from the same public fixture at frozen HEAD
# 481e750; see work/ceres-next-agent-experience/05/controlled-before.
FROZEN_CATEGORY_TYPE_FIRST_BODY_BYTES = 15385


def test_category_exploration_sends_type_first_guidance_to_the_model(
    indexed_client, kev_api, internal_trace_headers, monkeypatch
):
    """A broad category prompt must agree with the API's current type choice."""
    kev_api["choices"]["capability"] = "category_exploration"
    sent_requests = []
    sent_request_bodies = []

    def respond(request):
        body = json.loads(request.content)
        sent_requests.append(body)
        sent_request_bodies.append(request.content)
        if len(sent_requests) == 1:
            content = {
                "target": {"kind": "category", "name": "零食", "intent": "explore"},
                "lookups": [{"kind": "product", "query": "零食"}],
            }
        else:
            content = {"reply": "可以先选零食类型。", "display_refs": []}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
            request=request,
        )

    settings = get_settings()
    provider = LiveSemanticProvider(
        settings,
        OpenAICompatTransport(settings, httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)

    session_id = create_session(indexed_client)
    response = post_turn(indexed_client, session_id, "来点零食")

    assert response.status_code == 200
    body = response.json()
    question = body["pending_clarifications"][0]
    assert question["slot"] == "product_type"
    assert {option["label"] for option in question["options"]} == {"薯片", "饼干"}

    trace = indexed_client.get(
        f"/api/v1/internal/traces/{body['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200
    completed_calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert completed_calls[0]["capability"] == "category_exploration"

    actual_system_prompt = sent_requests[0]["messages"][0]["content"]
    assert "先推荐一款匹配商品并说明理由" not in actual_system_prompt
    assert len(sent_request_bodies[0]) < FROZEN_CATEGORY_TYPE_FIRST_BODY_BYTES, (
        f"full outbound request body did not shrink: {len(sent_request_bodies[0])} "
        f">= {FROZEN_CATEGORY_TYPE_FIRST_BODY_BYTES}"
    )


def test_guide_and_mercury_send_the_shared_reply_style_through_public_routes(
    indexed_client, kev_api, monkeypatch
):
    kev_api["choices"]["capability"] = "chat"
    sent_guide_requests = []

    def respond(request):
        sent_guide_requests.append(json.loads(request.content))
        content = {"reply": "你好，我可以帮你选购商品。"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
            request=request,
        )

    settings = get_settings()
    provider = LiveSemanticProvider(
        settings,
        OpenAICompatTransport(settings, httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)

    guide_session = create_session(indexed_client)
    guide_turn = post_turn(indexed_client, guide_session, "你好")
    assert guide_turn.status_code == 200
    assert guide_turn.json()["plan"] is None

    momo_session_response = indexed_client.post("/api/v1/mercury/sessions")
    assert momo_session_response.status_code == 200
    momo_session = momo_session_response.json()["session_id"]

    class CaptureMomo:
        def __init__(self):
            self.messages = None

        def chat(self, messages, tools=None):
            self.messages = [dict(message) for message in messages]
            return SimpleNamespace(content="你好，我可以帮你咨询售后。", tool_calls=None)

    momo_client = CaptureMomo()
    monkeypatch.setattr("app.api.mercury.OpenAIChatClient", lambda _settings: momo_client)
    momo_turn = indexed_client.post(
        f"/api/v1/mercury/sessions/{momo_session}/turns/stream",
        json={"message": "你好", "request_id": "prompt-module-shared-style"},
    )
    assert momo_turn.status_code == 200
    assert "event: turn.completed" in momo_turn.text

    guide_system_prompt = sent_guide_requests[0]["messages"][0]["content"]
    guide_capability_prompt = guide_system_prompt.split("\nprotocol:\n", 1)[0]
    momo_system_prompt = momo_client.messages[0]["content"]
    assert "问候" in guide_capability_prompt
    assert "自然回应" in guide_capability_prompt
    assert "只有明说「加入购物车 / 下单」" not in guide_capability_prompt
    for system_prompt, role in (
        (guide_system_prompt, "guide"),
        (momo_system_prompt, "Mercury"),
    ):
        assert "简短自然的中文" in system_prompt, f"{role} prompt lacks shared reply style"
        assert "先说明结果及下一步" in system_prompt, f"{role} prompt lacks shared reply style"


def test_purchase_modify_broad_category_preserves_type_choice_before_plan(
    indexed_client, kev_api, internal_trace_headers, monkeypatch
):
    kev_api["choices"]["capability"] = "purchase_modify"
    sent_requests = []

    def respond(request):
        payload = json.loads(request.content)
        sent_requests.append(payload)
        content = {
            "target": {
                "kind": "category",
                "name": "饮料",
                "intent": "buy",
                "quantity": 2,
            },
            "constraints": {
                "budget_yuan": 20,
                "specification": {"packaging": "bottle"},
            },
            "lookups": [{"kind": "product", "query": "饮料"}],
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
            request=request,
        )

    settings = get_settings()
    provider = LiveSemanticProvider(
        settings,
        OpenAICompatTransport(settings, httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)

    session_id = create_session(indexed_client)
    cart_before = indexed_client.get("/api/v1/cart").json()
    response = post_turn(indexed_client, session_id, "买点饮料，两瓶，预算20元")

    assert response.status_code == 200, response.text
    body = response.json()
    question = next(
        question for question in body["pending_clarifications"]
        if question["slot"] == "product_type"
    )
    assert len(question["options"]) >= 2
    assert body["plan"] is None
    assert indexed_client.get("/api/v1/cart").json() == cart_before
    capability_prompt = sent_requests[0]["messages"][0]["content"].split(
        "\nprotocol:\n", 1
    )[0]
    assert "未选具体商品的品类购买请求" in capability_prompt

    trace = indexed_client.get(
        f"/api/v1/internal/traces/{body['trace_id']}",
        headers=internal_trace_headers,
    )
    assert trace.status_code == 200, trace.text
    completed_calls = [
        json.loads(event["output_summary"])
        for event in trace.json()["events"]
        if event["phase"] == "model_call_completed"
    ]
    assert completed_calls[0]["capability"] == "purchase_modify"


def test_type_answer_uses_only_comparable_candidates_and_offers_real_filter_bubbles(
    indexed_client, kev_api, internal_trace_headers, monkeypatch
):
    kev_api["choices"]["capability"] = "purchase_modify"
    sent_requests = []

    def respond(request):
        payload = json.loads(request.content)
        sent_requests.append(payload)
        server_context = json.loads(payload["messages"][-2]["content"])["server_context"]
        query_results = server_context.get("query_results") or []
        if not query_results:
            content = {
                "target": {"kind": "category", "name": "饮料", "intent": "buy"},
                "constraints": {"budget_yuan": 20},
                "lookups": [{"kind": "product", "query": "饮料"}],
            }
        else:
            matches = [
                match
                for result in query_results
                if result.get("kind") == "lookup"
                and result.get("lookup_kind") == "product"
                for match in result.get("matches", [])
            ]
            content = {
                "reply": "这里没有价格信息。",
                "display_refs": [match["ref"] for match in matches],
            }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]},
            request=request,
        )

    settings = get_settings()
    provider = LiveSemanticProvider(
        settings,
        OpenAICompatTransport(settings, httpx.MockTransport(respond)),
    )
    monkeypatch.setattr("app.llm.provider.get_semantic_provider", lambda: provider)

    session_id = create_session(indexed_client)
    broad = send_turn(indexed_client, session_id, "买点饮料，预算20元")
    type_question = next(
        question for question in broad["pending_clarifications"]
        if question["slot"] == "product_type"
    )
    cola = next(option for option in type_question["options"] if option["label"] == "可乐")
    selected_type = send_turn(
        indexed_client,
        session_id,
        "可乐",
        broad,
        clarification_answer={
            "question_id": type_question["question_id"],
            "option_id": cola["id"],
        },
    )
    filter_question = next(
        question for question in selected_type["pending_clarifications"]
        if question["slot"] == "product_filter"
    )
    pepsi = next(
        option for option in filter_question["options"]
        if option["label"] == "品牌：百事可乐"
    )
    filtered = send_turn(
        indexed_client,
        session_id,
        pepsi["label"],
        selected_type,
        clarification_answer={
            "question_id": filter_question["question_id"],
            "option_id": pepsi["id"],
        },
    )

    assert {card["sku_id"] for card in selected_type["product_cards"]} == {
        "demo:cn-pepsi-original-330ml-can",
        "demo:cn-coke-original-330ml-can",
        "demo:cn-coke-original-500ml-bottle",
        "demo:cn-coke-zero-500ml-bottle",
    }
    assert all(card["price_fen"] is not None for card in selected_type["product_cards"])
    assert "没有价格信息" not in selected_type["message"]
    selected_type_context = json.loads(sent_requests[-2]["messages"][-2]["content"])[
        "server_context"
    ]
    assert "demo:cola-330ml" not in {
        match["target_id"]
        for result in selected_type_context["query_results"]
        for match in result.get("matches", [])
    }
    assert filtered["pending_clarifications"] == []
    assert {card["brand"] for card in filtered["product_cards"]} == {"百事可乐"}
    type_answer_prompt = sent_requests[-2]["messages"][0]["content"].split(
        "\nprotocol:\n", 1
    )[0]
    filter_answer_prompt = sent_requests[-1]["messages"][0]["content"].split(
        "\nprotocol:\n", 1
    )[0]
    type_answer_has_category_guidance = "同类有多个匹配候选时直接展示比较" in type_answer_prompt
    filter_answer_has_category_guidance = "本轮品类及已选筛选条件匹配" in filter_answer_prompt
    assert type_answer_has_category_guidance, "type answer omitted category candidate guidance"
    assert filter_answer_has_category_guidance, "filter answer omitted selected-category guidance"

    for response, expected_branch in (
        (selected_type, "direct_product_type_workflow"),
        (filtered, "direct_product_filter_workflow"),
    ):
        trace = indexed_client.get(
            f"/api/v1/internal/traces/{response['trace_id']}",
            headers=internal_trace_headers,
        )
        calls = [
            json.loads(event["output_summary"])
            for event in trace.json()["events"]
            if event["phase"] == "model_call_completed"
        ]
        assert calls[0]["capability"] == "purchase_modify"
        assert calls[0]["branch"] == expected_branch
