"""Checks for the "I don't want it" case under the one-pass protocol (spec rule 2).

There is no whole-turn ``stop`` label any more. "I don't want it" is either:
* a located row edit — ``focus`` + ``edit{op: remove}`` on one group, or
* a whole-plan drop — ``plan_act: abandon``, answered read-only in the server's
  own words, with nothing written.

Model layer: the prompt examples for both phrasings parse into the right shape;
optional live model check for「我不想要了」with a clear 红烧肉 plan.

Decision layer: a located focus + ``edit.op=remove`` routes to ``mutation``;
``plan_act=abandon`` with an active plan is answered read-only, not written.

Execution layer: the real loop removes the located group in one turn.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.agent.goal_router import (
    GateFacts,
    MutationView,
    PLAN_ACT_REPLIES,
    REASON_PLAN_ABANDON,
    decide_turn,
)
from app.agent.protocol import parse_proposal, proposal_schema
from app.prompts.semantic import PROPOSAL_EXAMPLES, SYSTEM_PROMPT
from support import create_session, post_turn
from support.semantic_agent import request_new


def turn_ok(client, session_id, message, previous=None):
    previous = previous or {}
    response = post_turn(
        client, session_id, message, previous, request_id=str(uuid.uuid4())
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ model layer


def test_system_prompt_does_not_teach_a_whole_turn_stop_label():
    assert not re.search(r"\bstop\b", SYSTEM_PROMPT, flags=re.IGNORECASE)


def test_remove_prompt_example_parses_as_a_located_edit():
    for request, proposal in PROPOSAL_EXAMPLES:
        if request.get("user_message") != "红烧肉不要了":
            continue
        assert request.get("current_plan", {}).get("groups")
        parsed = parse_proposal(proposal)
        assert any(m.verb == "remove" for m in parsed.mutations or [])
        assert parsed.understanding.goal_relation == "amend"
        return
    raise AssertionError("没有找到「红烧肉不要了」的示例")


def test_abandon_prompt_example_parses_as_a_whole_plan_drop():
    for request, proposal in PROPOSAL_EXAMPLES:
        if request.get("user_message") != "算了，都不买了":
            continue
        parsed = parse_proposal(proposal)
        assert parsed.understanding.plan_act == "abandon"
        assert not parsed.mutations
        return
    raise AssertionError("没有找到「算了，都不买了」的示例")


def test_live_model_unwanted_with_clear_plan_is_a_located_remove():
    from app.core.config import get_settings
    from app.llm.live_semantic_provider import LiveSemanticProvider

    settings = get_settings()
    if not settings.is_live_llm_configured():
        pytest.skip("live LLM not configured")

    provider = LiveSemanticProvider(settings)
    raw = provider.propose({
        "user_message": "我不想要了",
        "protocol": proposal_schema(),
        "current_plan": {
            "groups": [
                {"ref": "dish:dish-hongshao-rou", "name": "红烧肉", "target_kind": "dish"},
            ],
        },
        "focus_refs": [
            {"ref": "dish:dish-hongshao-rou", "kind": "plan_target", "label": "红烧肉"},
        ],
    })
    proposal = parse_proposal(raw)
    assert any(m.verb == "remove" for m in proposal.mutations or [])


# ------------------------------------------------------------------ decision layer


def test_located_remove_decision_is_mutation_not_a_whole_turn_refusal():
    group_ref = "dish:dish-hongshao-rou"
    proposal = parse_proposal({
        "focus": {"ref": group_ref, "name": "红烧肉"},
        "edit": {"op": "remove"},
    })
    decision = decide_turn(
        proposal.understanding,
        GateFacts(
            has_active_plan=True,
            focus_refs=(
                {"ref": group_ref, "kind": "plan_target", "label": "红烧肉"},
            ),
            plan_target_refs=(group_ref,),
        ),
        mutations=[
            MutationView(
                verb="remove", ref=group_ref, ref_kind="dish", ref_name="红烧肉"
            )
        ],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "apply_mutation"
    assert decision.reason_code != "STOP_REQUESTED"


def test_abandon_with_an_active_plan_is_read_only_and_writes_nothing():
    proposal = parse_proposal({"plan_act": "abandon"})
    decision = decide_turn(
        proposal.understanding,
        GateFacts(has_active_plan=True),
    )
    assert decision.route == "answer"
    assert decision.write_blocked is True
    assert decision.reason_code == REASON_PLAN_ABANDON
    assert PLAN_ACT_REPLIES[REASON_PLAN_ABANDON]


# ------------------------------------------------------------------ execution layer


def test_unwanted_removes_the_located_group_in_one_turn(client, semantic_provider):
    def remove_hongshao(request):
        groups = request["current_plan"]["groups"]
        assert len(groups) == 1
        group = groups[0]
        return {
            "focus": {"ref": group["ref"], "name": group["name"]},
            "edit": {"op": "remove"},
        }

    semantic_provider([
        {
            **request_new("dish", "红烧肉", people=2),
            "lookups": [{"kind": "dish", "query": "红烧肉"}],
        },
        remove_hongshao,
    ])
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃红烧肉")
    assert first["plan_effect"] == "replace"
    groups_before = {t["group_id"] for t in first["plan"]["targets"]}
    assert len(groups_before) == 1

    second = turn_ok(client, sid, "红烧肉不要了", first)
    assert second["route"] == "apply_mutation"
    assert second["plan_effect"] == "replace"
    assert second.get("reason_code") != "STOP_REQUESTED"
    groups_after = {t["group_id"] for t in (second.get("plan") or {}).get("targets", [])}
    assert groups_after == set()
    assert not any(
        row.get("code") == "STOP_REQUESTED" for row in second.get("action_results", [])
    )
