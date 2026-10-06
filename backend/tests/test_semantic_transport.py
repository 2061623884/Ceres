"""Real semantic JSON adapter with a deterministic HTTP transport, no network."""
import json

import httpx
import pytest

from app.agent.protocol import parse_proposal
from app.core.config import Settings
from app.llm.errors import LLMProviderError
from app.llm.live_semantic_provider import LiveSemanticProvider
from app.llm.openai_transport import OpenAICompatTransport
from app.prompts.semantic import PROPOSAL_EXAMPLES


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
    # Rule 10: the live provider no longer narrows the schema itself; the caller
    # (``build_request``) sends ``answer_schema`` once query_results are present.
    from app.agent.protocol import answer_schema
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"hello"}'}}]})
    provider(handler).propose({"user_message": "推荐一下", "protocol": answer_schema(),
        "read_only": True, "query_results": [{"kind": "recommend", "status": "completed"}]})
    schema = json.loads(received[0]["messages"][0]["content"].split("\nprotocol:\n")[1])
    assert not {"lookups", "reads", "questions", "target", "edit"}.intersection(schema["properties"])


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


def test_purchase_prompt_preserves_clarification_resolution_at_model_boundary():
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})

    provider(handler).propose({
        "user_message": "我想吃番茄炒蛋",
        "capability": "purchase_modify",
    })
    messages = received[0]["messages"]
    capability_prompt = messages[0]["content"].split("\nprotocol:\n", 1)[0]

    assert (
        "用户本轮明确回答 pending_clarifications 中的问题时，必须把该问题的真实 question_id 填入 resolved_questions"
        in capability_prompt
    )
    assert (
        "若 current_plan 缺失或 groups 为空，普通 ACK 只简短接话并等待用户明确选择或提出需求"
        in capability_prompt
    )
    assert (
        "「自己做」填写 fulfillment_mode=self_cook，「买现成」填写 fulfillment_mode=ready_made；"
        "只说「想吃」等未明确制作方式时不填，不要自己补"
        in capability_prompt
    )
    proposal_examples = json.dumps(messages[1:-2], ensure_ascii=False)
    assert "买一盒牛奶" in proposal_examples
    assert "请记住我平时偏好小包装零食" not in proposal_examples


def test_named_dish_add_example_marks_append_and_self_cook():
    request, raw_proposal = next(
        (request, proposal)
        for request, proposal in PROPOSAL_EXAMPLES
        if request.get("user_message") == "再加一道蛋炒饭，自己做"
    )

    assert request["current_plan"]["groups"]
    parsed = parse_proposal(raw_proposal)
    goal = parsed.understanding.new_goal
    assert parsed.understanding.goal_relation == "append"
    assert goal.target_name == "蛋炒饭"
    assert goal.fulfillment_mode == "self_cook"
    assert [(lookup.kind, lookup.query) for lookup in parsed.lookups] == [
        ("dish", "蛋炒饭")
    ]


def test_category_answer_prompt_keeps_candidates_and_result_fact_boundaries():
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"reply":"ok"}'}}]})

    p = provider(handler)
    schema = {"type": "object", "properties": {}}
    p.propose({
        "user_message": "来点零食",
        "capability": "category_exploration",
        "protocol": schema,
    })
    p.propose({
        "user_message": "来点零食",
        "capability": "category_exploration",
        "protocol": schema,
        "query_results": [{"kind": "lookup", "status": "completed"}],
    })
    answer_phase = received[1]["messages"][0]["content"]
    capability_prompt = answer_phase.split("\nprotocol:\n", 1)[0]
    assert "同类有多个匹配候选时直接展示比较" in capability_prompt
    assert "只主推一款" not in capability_prompt
    assert "stock_verified=true 只表示可售核验通过，不代表库存充足或具体数量" in capability_prompt
    assert "模拟价格和供给不得表述为门店真实数据" in capability_prompt
    assert "unknown_constraints 标为未知不代表满足条件" in capability_prompt


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
