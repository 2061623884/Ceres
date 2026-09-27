"""Three-layer checks for removing ``speech_act=stop`` and the slim prompt.

Model layer: prompt/schema no longer teach ``stop``; examples parse; optional live
model check for「我不想要了」with a clear 红烧肉 plan.

Decision layer: a located ``request_action`` + ``remove`` routes to ``mutation``.

Execution layer: the same proposal removes the group through the real loop.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.agent.goal import parse_understanding
from app.agent.goal_router import GateFacts, MutationView, decide_turn
from app.agent.protocol import parse_proposal, proposal_schema
from app.prompts.semantic import PROPOSAL_EXAMPLES, SYSTEM_PROMPT
from app.schemas.goal import SPEECH_ACTS
from support import create_session, post_turn
from support.semantic_agent import request_amend


def lookup_then_add(kind, query, *, people=None):
    goal = {"kind": "meal_plan", "target_name": query}
    if people:
        goal["constraints"] = {"people": people}
    return [{
        "understanding": {
            "speech_act": "request_action",
            "goal_relation": "new",
            "new_goal": goal,
        },
        "lookups": [{"kind": kind, "query": query}],
    }]


def turn_ok(client, session_id, message, previous=None):
    previous = previous or {}
    response = post_turn(
        client, session_id, message, previous, request_id=str(uuid.uuid4())
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ model layer


def test_speech_act_vocabulary_excludes_stop():
    assert "stop" not in SPEECH_ACTS


def test_proposal_schema_excludes_stop_speech_act():
    schema = proposal_schema()
    speech_act_enum = (
        schema["properties"]["understanding"]["properties"]["speech_act"]["enum"]
    )
    assert "stop" not in speech_act_enum


def test_system_prompt_does_not_teach_stop_speech_act():
    assert not re.search(r"\bstop\b", SYSTEM_PROMPT, flags=re.IGNORECASE)


def test_remove_prompt_examples_parse():
    from app.agent.protocol import parse_proposal

    for request, proposal in PROPOSAL_EXAMPLES:
        if request.get("user_message") != "我不想要了":
            continue
        parsed = parse_proposal(proposal)
        if request.get("current_plan", {}).get("groups"):
            assert parsed.understanding.speech_act == "request_action"
            assert any(m.verb == "remove" for m in parsed.mutations or [])
        else:
            assert parsed.understanding.speech_act == "ask_fact"
            assert parsed.uncertainties


def test_live_model_unwanted_with_clear_plan_is_request_action_remove():
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
    assert proposal.understanding.speech_act == "request_action"
    assert proposal.understanding.speech_act != "stop"
    assert any(m.verb == "remove" for m in proposal.mutations or [])


# ------------------------------------------------------------------ decision layer


def test_located_remove_decision_is_mutation_not_stop_refusal():
    group_ref = "dish:dish-hongshao-rou"
    understanding = parse_understanding({
        "speech_act": "request_action",
        "goal_relation": "amend",
        "focus_ref": group_ref,
    })
    decision = decide_turn(
        understanding,
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


# ------------------------------------------------------------------ execution layer


def test_unwanted_removes_the_located_group_in_one_turn(client, semantic_provider):
    def remove_hongshao(request):
        groups = request["current_plan"]["groups"]
        assert len(groups) == 1
        group = groups[0]
        return {
            "understanding": request_amend(focus=group["ref"]),
            "mutations": [
                {"verb": "remove", "target_ref": group["ref"], "name": group["name"]},
            ],
        }

    semantic_provider([*lookup_then_add("dish", "红烧肉", people=2), remove_hongshao])
    sid = create_session(client)
    first = turn_ok(client, sid, "我想吃红烧肉")
    assert first["plan_effect"] == "replace"
    groups_before = {t["group_id"] for t in first["plan"]["targets"]}
    assert len(groups_before) == 1

    second = turn_ok(client, sid, "我不想要了", first)
    assert second["route"] == "apply_mutation"
    assert second["plan_effect"] == "replace"
    assert second.get("reason_code") != "STOP_REQUESTED"
    groups_after = {t["group_id"] for t in (second.get("plan") or {}).get("targets", [])}
    assert groups_after == set()
    assert not any(
        row.get("code") == "STOP_REQUESTED" for row in second.get("action_results", [])
    )
