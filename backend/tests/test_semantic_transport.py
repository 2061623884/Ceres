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
    assert "输出 JSON 只能包含 protocol 当前 schema 声明的字段" in messages[0]["content"]
    assert (
        "用户本轮明确回答 pending_clarifications 中的问题时，必须把该问题的真实 question_id 填入 resolved_questions"
        in messages[0]["content"]
    )
    assert (
        "所有 reply（包括无新检索结果的追问）只能依据服务端上下文、检索结果或历史中已核实的商品/菜谱事实"
        in messages[0]["content"]
    )
    assert (
        "若 current_plan 缺失或 groups 为空，普通 ACK 只简短接话并等待用户明确选择或提出需求"
        in messages[0]["content"]
    )
    assert (
        "「自己做」填写 fulfillment_mode=self_cook，「买现成」填写 fulfillment_mode=ready_made；"
        "只说「想吃」等未明确制作方式时不填，不要自己补"
        in messages[0]["content"]
    )
    expected = [{"role": role, "content": json.dumps(content, ensure_ascii=False)}
                for example in semantic.PROPOSAL_EXAMPLES
                if not example[0].get("query_results")
                for role, content in zip(("user", "assistant"), example)]
    assert len(expected) > 0
    assert messages[1:1 + len(expected)] == expected


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
    assert "有匹配商品时只主推一款，并用 query_results 中明确给出的商品事实说明理由" in answer_phase
    assert "有匹配商品时只主推一款，并用 query_results 中明确给出的商品事实说明理由" not in open_phase
    assert "不得从商品类型或糖信息推断甜度" in answer_phase
    assert "品类/用途判断依据 query_results 的品类、商品类型和用途事实" in answer_phase
    assert "reply 只说明这款商品及事实支持的推荐理由，不得列出、提及或对比其他商品" in answer_phase
    assert "display_refs 仅填写这款商品的一个 ref" in answer_phase
    assert "没有匹配商品时 reply 如实说明、display_refs=[]" in answer_phase
    assert "推荐理由可用已提供的品类、用途、规格等字段；不得编造热销、销量、促销、口感、营养等信息；价格和库存仅按 query_results 明确给出的字段说明，未提供则不要提及" in answer_phase
    assert "stock_verified=true 只表示可售核验通过，不代表库存充足或具体数量；模拟价格和供给仅是演示数据，不得表述为店内真实价格或库存" in answer_phase
    assert "query_results 中果汁候选的 unknown_constraints 含 nutrition，用户问「想喝低糖的果汁，有糖含量数据吗？」时，只答「商品资料未提供糖含量，无法确认是否符合低糖要求。」并返回 display_refs=[]" in answer_phase


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
