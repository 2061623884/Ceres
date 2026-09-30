"""Contract tests for the first-list-then-adjust product behaviour."""

from __future__ import annotations

from app.agent.goal_router import SLOT_FULFILLMENT_MODE, decide_turn
from app.schemas.goal import Goal
from support import create_session, post_turn

from tests.test_goal_decision_gate import add, facts, understanding
from tests.test_shopping_workflow import TOMATO, _snapshot

def turn(client, session_id, message, previous=None):
    return post_turn(client, session_id, message, previous)


def test_named_dish_without_fulfillment_mode_prepares_instead_of_clarifying() -> None:
    decision = decide_turn(
        understanding(
            goal_relation="unspecified",
            new_goal=Goal(kind="meal_plan", target_name="清蒸鲈鱼"),
        ),
        facts(),
        mutations=[add("d1", "dish")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.write_blocked is False
    assert SLOT_FULFILLMENT_MODE not in decision.missing_slots
    assert decision.candidate is not None
    assert decision.candidate.goal.fulfillment_mode == "unspecified"


def test_named_dish_without_people_prepares_instead_of_clarifying() -> None:
    decision = decide_turn(
        understanding(
            goal_relation="unspecified",
            new_goal=Goal(
                kind="meal_plan",
                target_name="番茄炒蛋",
                fulfillment_mode="unspecified",
            ),
        ),
        facts(),
        mutations=[add("d1", "dish")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert "people" not in decision.missing_slots


def test_amend_people_only_on_active_plan_applies_without_focus(client, semantic_provider):
    """The server resolves the current plan; the model only supplies people."""
    semantic_provider(
        [
            {
                "target": {"kind": "meal", "name": "番茄炒蛋", "intent": "buy"},
                "lookups": [{"kind": "dish", "query": "番茄炒蛋"}],
            },
            lambda request: {
                "reply": "按两个人份调整。",
                "constraints": {"people": 2},
            },
        ]
    )
    sid = create_session(client)
    first = turn(client, sid, "我想吃番茄炒蛋").json()
    assert first["plan"], first
    plan_id = first["plan"]["plan_id"]
    assert first["plan"]["targets"][0]["people_source"] == "default", first["plan"]["targets"]

    second = turn(client, sid, "两个人", first).json()
    assert second.get("plan"), second
    assert second["plan"]["plan_id"] == plan_id, second
    assert second["plan"]["targets"][0]["people"] == 2, second["plan"]["targets"]
    assert second["plan"]["targets"][0]["people_source"] == "user", second["plan"]["targets"]
    assert _snapshot(client, sid)["constraints_summary"].get("people") == 2


def test_chat_does_not_build_a_plan(client, semantic_provider):
    semantic_provider([{"reply": "哈哈，今天想吃点什么呢？"}])
    sid = create_session(client)
    body = turn(client, sid, "哈哈哈哈").json()
    assert body["plan"] is None, body
    assert body.get("plan_effect") == "keep", body
