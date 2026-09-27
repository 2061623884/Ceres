"""HTTP response contract for the request-level graph.

These are the still-valid business assertions of the old R2 response suite,
migrated to the surviving helpers: the terminal field set, the transport mapping
(stopped / deadline / plain refusal), the answer wording rules, and the
terminal response schema. None of them needs the retired graph nodes.
"""

from __future__ import annotations

import pytest

from app.agent.graph.response_contract import (
    TERMINAL_PAYLOAD_FIELDS,
    ensure_terminal_payload,
    outcome_codes,
    prepare_graph_message,
)
from app.agent.turn_primitives import TIMEOUT_CODE
from app.schemas.guide import TurnResponse


def _turn_response_body(**overrides):
    body = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "task_id": None,
        "state_version": 0,
        "session_version": 3,
        "status": "understanding",
        "answer_status": "accepted",
        "message": "你好呀",
        "plan": None,
        "plan_effect": "keep",
        "pending_clarifications": [],
        "available_actions": ["send_message"],
        "trace_id": "trace-1",
        "model_mode": "live",
        "business_data_mode": "demo",
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------- terminal fields


def test_terminal_payload_always_carries_the_frozen_field_set():
    body = ensure_terminal_payload({"message": "hi"})
    for field in TERMINAL_PAYLOAD_FIELDS:
        assert field in body
    assert body["pending_clarifications"] == []
    assert body["available_actions"] == ["send_message"]


def test_terminal_payload_accepts_a_single_pending_clarification():
    body = ensure_terminal_payload(
        {"message": "几个人？", "pending_clarification": {"question_id": "q-1"}}
    )
    assert body["pending_clarifications"] == [{"question_id": "q-1"}]


# --------------------------------------------------------------- outcome codes


def test_outcome_codes_union_covers_guard_staged_and_receipts():
    codes = outcome_codes(
        {"allowed": False, "code": "STALE_STATE"},
        {"error": {"code": "WRITE_BLOCKED"}},
        [{"code": "STOPPED"}, {"code": TIMEOUT_CODE}],
    )
    assert {"STALE_STATE", "WRITE_BLOCKED", "STOPPED", TIMEOUT_CODE} <= codes


# ------------------------------------------------------------------ wording


@pytest.mark.parametrize("kind", ["mutation", "refuse"])
def test_message_helper_never_publishes_the_prepared_success_wording(kind):
    message = prepare_graph_message(
        kind=kind,
        model_reply="已经帮你加好了，还下了一单",
        plan={"items": []},
        plan_effect="keep",
        action_results=[],
        refusal_message="本轮没有执行修改。",
    )
    assert "已经帮你加好了" not in message
    assert "本轮没有执行修改。" in message


def test_message_helper_keeps_a_plain_reply_where_no_write_was_claimed():
    message = prepare_graph_message(kind="answer", model_reply="  你好呀  ")
    assert message == "你好呀"


def test_message_helper_keeps_the_question_and_its_options():
    message = prepare_graph_message(
        kind="clarify",
        model_reply="你几个人吃？",
        pending=[
            {
                "question": "要几个人份？",
                "options": [{"id": "people:2", "label": "2 人"}],
            }
        ],
    )
    assert "要几个人份？" in message
    assert "2 人" in message


# ----------------------------------------------------------- response schema


def test_schema_accepts_a_normalized_single_pending_question():
    pending = {"question_id": "q-1", "question": "想选哪一道？"}
    result = TurnResponse.model_validate(
        ensure_terminal_payload(_turn_response_body(
            pending_clarification=pending,
            pending_clarifications=None,
        ))
    )
    assert isinstance(result, TurnResponse)
    assert result.pending_clarification["question_id"] == "q-1"
    assert result.pending_clarifications == [pending]


def test_schema_keeps_the_pending_list_when_present():
    result = TurnResponse.model_validate(
        _turn_response_body(
            pending_clarifications=[
                {"question_id": "q-1"},
                {"question_id": "q-2"},
            ]
        ),
    )
    assert [p["question_id"] for p in result.pending_clarifications] == ["q-1", "q-2"]


def test_schema_keeps_actions_for_a_taskless_turn():
    result = TurnResponse.model_validate(_turn_response_body())
    assert result.available_actions == ["send_message"]
    assert result.status == "understanding"
