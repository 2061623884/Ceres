"""Ceres Next 04: actual guide requests use the current category behavior."""

import json
from types import SimpleNamespace

import httpx

from app.core.config import get_settings
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport
from support import create_session, post_turn

from test_semantic_phase1_purchase import indexed_client  # noqa: F401


def test_category_exploration_sends_type_first_guidance_to_the_model(
    indexed_client, kev_api, internal_trace_headers, monkeypatch
):
    """A broad category prompt must agree with the API's current type choice."""
    kev_api["choices"]["capability"] = "category_exploration"
    sent_requests = []

    def respond(request):
        body = json.loads(request.content)
        sent_requests.append(body)
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
