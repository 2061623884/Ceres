"""Real semantic JSON adapter with a deterministic HTTP transport, no network."""
import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.errors import LLMProviderError
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport


def provider(handler):
    settings = Settings(_env_file=None, openai_base_url="http://localhost/v1",
                        openai_api_key="test-only", llm_model="protocol-simulator")
    return LiveSemanticProvider(settings, OpenAICompatTransport(settings, httpx.MockTransport(handler)))


def test_real_json_adapter_projects_money_and_keeps_natural_reply():
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"reply": "也可以聊聊做法，原来的清单不动。"}, ensure_ascii=False)}}]})
    result = provider(handler).propose({"requirements": {"budget_fen": 1999}, "query_results": []})
    assert result["reply"] == "也可以聊聊做法，原来的清单不动。"
    context = json.loads(received[0]["messages"][-2]["content"])["server_context"]
    assert context["requirements"] == {"budget_yuan": 19.99}
    assert received[0]["response_format"] == {"type": "json_object"}


def test_latest_utterance_is_last_not_buried_before_history_or_protocol():
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}]})
    provider(handler).propose({"user_message": "再加一瓶可乐", "protocol": {"type": "object"},
        "recent_messages": [{"role": "assistant", "content": "推荐香蕉"}],
        "current_plan": {"items": []}})
    messages = received[0]["messages"]
    assert messages[-1] == {"role": "user", "content": "再加一瓶可乐"}
    context = json.loads(messages[-2]["content"])["server_context"]
    assert "recent_messages" not in context
    assert "protocol" not in context
    assert messages[-3] == {"role": "assistant", "content": "推荐香蕉"}


def test_answer_phase_does_not_advertise_more_reads_or_mutations():
    from app.agent.protocol import proposal_schema
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}]})
    provider(handler).propose({"user_message": "推荐一下", "protocol": proposal_schema(),
        "read_only": True, "query_results": [{"kind": "recommend", "status": "completed"}]})
    schema = json.loads(received[0]["messages"][0]["content"].split("\nprotocol:\n")[1])
    assert not {"lookups", "queries", "mutations"}.intersection(schema["properties"])


@pytest.mark.parametrize("content,code", [
    ("", "EMPTY_MODEL_RESPONSE"), ("not-json", "MODEL_OUTPUT_INVALID"),
    ([{"text": "unexpected-shape"}], "MODEL_OUTPUT_INVALID"),
])
def test_invalid_model_content_does_not_become_canned_success(content, code):
    p = provider(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(LLMProviderError) as error:
        p.propose({})
    assert error.value.code == code


def test_timeout_is_an_error_not_legacy_fallback():
    def handler(request):
        raise httpx.ReadTimeout("simulated", request=request)
    with pytest.raises(LLMProviderError) as error:
        provider(handler).propose({})
    assert error.value.code == "MODEL_TIMEOUT"


def test_output_is_bounded_and_truncated_proposals_never_execute():
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "length",
            "message": {"content": '{"reply":"truncated"}'}}]})
    with pytest.raises(LLMProviderError) as error:
        provider(handler).propose({})
    assert error.value.code == "MODEL_OUTPUT_TRUNCATED"
    assert received[0]["max_tokens"] == 1536


def test_answer_phase_examples_do_not_reopen_retrieval():
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})
    provider(handler).propose({"read_only": True, "query_results": [{"status": "completed"}]})
    for message in received[0]["messages"]:
        if message['role'] == 'assistant':
            assert not {'lookups', 'queries', 'purchase_requested', 'mutations'} & json.loads(message['content']).keys()


class _RecordingTransport:
    """Records the per-call budget the provider hands over."""

    def __init__(self):
        self.calls: list[float | None] = []

    def post_json(self, payload, *, timeout_s=None):
        self.calls.append(timeout_s)
        return {"choices": [{"message": {"content": '{"reply":"ok"}'}}]}


def _settings() -> Settings:
    return Settings(_env_file=None, openai_base_url="http://localhost/v1",
                    openai_api_key="test-only", llm_model="protocol-simulator")


def test_a_turn_budget_only_ever_shortens_the_transport_timeout():
    transport = OpenAICompatTransport(_settings())
    configured = transport.settings.llm_timeout

    # No budget: the configured timeout, unchanged.
    assert transport._timeout_for_call(None).read == pytest.approx(configured)
    # A budget inside it: the call is bounded by the turn.
    assert transport._timeout_for_call(5.0).read == pytest.approx(5.0)
    # A budget larger than it: never extended, only shrunk.
    assert transport._timeout_for_call(configured * 10).read == pytest.approx(configured)


def test_a_tiny_remaining_budget_is_not_rounded_up():
    """Ten milliseconds left means ten milliseconds, for reading *and* connecting."""
    transport = OpenAICompatTransport(_settings())

    tiny = transport._timeout_for_call(0.01)

    assert tiny.read <= 0.01, tiny
    assert tiny.connect <= 0.01, tiny
    assert tiny.read == pytest.approx(0.01)
    assert tiny.connect == pytest.approx(0.01)


def test_outbound_system_and_fewshots_come_from_the_prompts_module():
    """The adapter must not carry its own copy of the prompt text."""
    from app.llm import live_semantic_provider
    from app.prompts import semantic
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})

    provider(handler).propose({"user_message": "你好"})
    messages = received[0]["messages"]

    assert live_semantic_provider.SYSTEM_PROMPT is semantic.SYSTEM_PROMPT
    assert messages[0]["content"].startswith(semantic.SYSTEM_PROMPT)
    expected = [{"role": role, "content": json.dumps(content, ensure_ascii=False)}
                for example in semantic.PROPOSAL_EXAMPLES
                if not example[0].get("query_results")
                for role, content in zip(("user", "assistant"), example)]
    assert len(expected) > 0
    assert messages[1:1 + len(expected)] == expected


def test_retrieval_complete_prompt_is_appended_only_in_the_answer_phase():
    from app.prompts.semantic import RETRIEVAL_COMPLETE_PROMPT, SYSTEM_PROMPT
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})

    p = provider(handler)
    schema = {"type": "object", "properties": {}}
    p.propose({"user_message": "推荐一下", "protocol": schema})
    p.propose({"user_message": "推荐一下", "protocol": schema,
               "query_results": [{"kind": "recommend", "status": "completed"}]})
    open_phase = received[0]["messages"][0]["content"]
    answer_phase = received[1]["messages"][0]["content"]

    # Same protocol both times, so the only difference is the appended text.
    suffix = "\nprotocol:\n" + json.dumps(schema, ensure_ascii=False)
    assert RETRIEVAL_COMPLETE_PROMPT.startswith("\n")
    assert open_phase == SYSTEM_PROMPT + suffix
    assert answer_phase == SYSTEM_PROMPT + RETRIEVAL_COMPLETE_PROMPT + suffix


def test_the_provider_hands_its_remaining_budget_to_the_transport():
    transport = _RecordingTransport()
    p = LiveSemanticProvider(_settings(), transport)

    p.propose({})
    assert transport.calls == [None]

    p.set_call_timeout(7.5)
    p.propose({})
    assert transport.calls == [None, pytest.approx(7.5)]

    # The last hundredth of a second is handed over as it is.
    p.set_call_timeout(0.01)
    p.propose({})
    assert transport.calls == [None, pytest.approx(7.5), pytest.approx(0.01)]
