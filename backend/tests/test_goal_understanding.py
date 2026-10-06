"""Offline goal-understanding tests: structured ``Goal`` + route, no model, no I/O.

Each case starts from the kind of constrained payload the understanding layer
will eventually receive (a plain dict — this slice does not call a model), then
asserts the structured goal and the pure routing decision. Nothing here touches
the database, the network, an LLM or the existing agent loop.
"""

from __future__ import annotations

import pytest

from app.agent.goal import GoalParseError, parse_goal, parse_intent_state
from app.agent.goal_router import (
    SLOT_CATEGORY,
    SLOT_ITEMS,
    SLOT_MEAL_PREFERENCES,
    SLOT_MEAL_TARGET,
    route_goal,
)
from app.schemas.goal import (
    Goal,
    RouteDecision,
    normalize_fulfillment_mode,
    normalize_goal_kind,
    normalize_readiness,
    normalize_route,
)


def decide(raw: dict) -> tuple[Goal, RouteDecision]:
    """Parse then route one raw proposal, exactly as a later adapter would."""
    goal = parse_goal(raw)
    return goal, route_goal(goal)


def test_undecided_meal_routes_to_clarification() -> None:
    goal, decision = decide({"kind": "meal_decision", "description": "不知道吃什么"})

    assert goal.kind == "meal_decision"
    assert decision.kind == "meal_decision"
    assert decision.readiness == "needs_clarification"
    assert decision.route == "clarify_goal"
    assert decision.missing_slots == [SLOT_MEAL_PREFERENCES]


def test_light_flavor_constraint_is_kept_verbatim() -> None:
    goal, decision = decide(
        {"kind": "meal_decision", "constraints": {"dietary": ["清淡"]}}
    )

    assert goal.constraints.dietary == ["清淡"]
    assert decision.route == "clarify_goal"

    planned_goal, planned = decide(
        {
            "kind": "meal_plan",
            "fulfillment_mode": "self_cook",
            "target_name": "清蒸鲈鱼",
            "constraints": {"dietary": ["清淡"]},
        }
    )
    assert planned_goal.constraints.dietary == ["清淡"]
    assert planned.readiness == "ready"


def test_breakfast_category_purchase_is_a_ready_category_route() -> None:
    goal, decision = decide(
        {
            "kind": "category_purchase",
            "category_name": "早餐",
            "constraints": {"meal_time": "breakfast"},
        }
    )

    assert goal.category_name == "早餐"
    assert goal.constraints.meal_time == "breakfast"
    assert decision.readiness == "ready"
    assert decision.route == "prepare_category_purchase"
    assert decision.missing_slots == []
    assert decision.fulfillment_mode == "none"


def test_category_purchase_without_a_category_asks_first() -> None:
    _, decision = decide({"kind": "category_purchase"})

    assert decision.readiness == "needs_clarification"
    assert decision.route == "clarify_goal"
    assert decision.missing_slots == [SLOT_CATEGORY]


def test_hotpot_for_three_people_is_a_ready_self_cook_meal() -> None:
    goal, decision = decide(
        {
            "kind": "meal_plan",
            "fulfillment_mode": "self_cook",
            "target_name": "火锅",
            "constraints": {"people": 3},
        }
    )

    assert goal.constraints.people == 3
    assert decision.readiness == "ready"
    assert decision.route == "prepare_meal_plan"
    assert decision.fulfillment_mode == "self_cook"
    assert decision.missing_slots == []


def test_explicit_cooking_is_ready_self_cook() -> None:
    goal, decision = decide(
        {
            "kind": "meal_plan",
            "fulfillment_mode": "self_cook",
            "target_name": "可乐鸡翅",
        }
    )

    assert goal.target_name == "可乐鸡翅"
    assert decision.readiness == "ready"
    assert decision.fulfillment_mode == "self_cook"
    assert decision.route == "prepare_meal_plan"


def test_named_meal_without_fulfillment_mode_can_prepare_ingredients() -> None:
    _, decision = decide({"kind": "meal_plan", "target_name": "可乐鸡翅"})

    assert decision.readiness == "ready"
    assert decision.fulfillment_mode == "unspecified"
    assert decision.route == "prepare_meal_plan"
    assert decision.missing_slots == []


def test_meal_plan_without_a_target_asks_what_to_make() -> None:
    _, decision = decide({"kind": "meal_plan", "fulfillment_mode": "self_cook"})

    assert decision.readiness == "needs_clarification"
    assert decision.missing_slots == [SLOT_MEAL_TARGET]


def test_explicit_product_purchase_is_ready() -> None:
    goal, decision = decide({"kind": "product_purchase", "items": ["牛奶"]})

    assert goal.items == ["牛奶"]
    assert decision.readiness == "ready"
    assert decision.route == "prepare_product_purchase"
    assert decision.fulfillment_mode == "none"


def test_product_purchase_without_a_product_asks_first() -> None:
    _, decision = decide({"kind": "product_purchase"})

    assert decision.readiness == "needs_clarification"
    assert decision.route == "clarify_goal"
    assert decision.missing_slots == [SLOT_ITEMS]


def test_replenishment_routes_to_replenishment() -> None:
    _, decision = decide({"kind": "replenishment", "items": ["洗衣液"]})

    assert decision.readiness == "ready"
    assert decision.route == "prepare_replenishment"


def test_replenishment_without_an_item_asks_first() -> None:
    _, decision = decide({"kind": "replenishment"})

    assert decision.readiness == "needs_clarification"
    assert decision.missing_slots == [SLOT_ITEMS]


def test_information_only_is_read_only() -> None:
    _, decision = decide({"kind": "information_only", "description": "可乐鸡翅怎么做"})

    assert decision.readiness == "information"
    assert decision.route == "answer_information"
    assert decision.fulfillment_mode == "none"
    assert decision.missing_slots == []


def test_unsupported_is_refused_without_a_plan() -> None:
    _, decision = decide({"kind": "unsupported", "description": "帮我开处方药"})

    assert decision.readiness == "unsupported"
    assert decision.route == "refuse_unsupported"
    assert decision.fulfillment_mode == "none"


def test_unknown_enum_values_normalize_conservatively() -> None:
    assert normalize_goal_kind("make_dinner") == "unsupported"
    assert normalize_goal_kind("meal_plan") == "meal_plan"
    assert normalize_fulfillment_mode("delivery") == "unspecified"
    assert normalize_fulfillment_mode("self_cook") == "self_cook"
    assert normalize_readiness("almost") == "needs_clarification"
    assert normalize_route("just_do_it") == "clarify_goal"

    goal = parse_goal({"kind": "eat_something", "fulfillment_mode": "delivery"})
    assert goal.kind == "unsupported"
    assert goal.fulfillment_mode == "unspecified"
    assert route_goal(goal).route == "refuse_unsupported"


def test_server_owned_fields_are_rejected_not_dropped() -> None:
    for payload in (
        {"kind": "meal_plan", "plan_id": "plan-1"},
        {"kind": "meal_plan", "price_fen": 1200},
        {"kind": "meal_plan", "route": "prepare_meal_plan"},
        {"kind": "meal_plan", "ready": True},
    ):
        with pytest.raises(GoalParseError) as exc:
            parse_goal(payload)
        assert exc.value.code == "FORBIDDEN_FIELD"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(GoalParseError) as exc:
        parse_goal({"kind": "meal_plan", "surprise": True})

    assert exc.value.code == "MALFORMED_GOAL"
    with pytest.raises(GoalParseError):
        parse_goal({"kind": "meal_plan", "constraints": {"stock": 5}})


def test_malformed_constraint_shapes_are_rejected() -> None:
    with pytest.raises(GoalParseError):
        parse_goal({"kind": "meal_plan", "constraints": {"people": True}})
    with pytest.raises(GoalParseError):
        parse_goal({"kind": "meal_plan", "constraints": {"people": "三个人"}})
    with pytest.raises(GoalParseError):
        parse_goal({"kind": "meal_plan", "constraints": {"budget_yuan": -1}})
    with pytest.raises(GoalParseError):
        parse_goal({"kind": "meal_plan", "items": [1, 2]})


def test_parse_is_idempotent_and_routing_is_pure() -> None:
    raw = {
        "kind": "meal_plan",
        "fulfillment_mode": "self_cook",
        "target_name": "番茄炒蛋",
        "constraints": {"people": 2},
    }
    goal = parse_goal(raw)
    assert parse_goal(goal) is goal
    assert route_goal(goal) == route_goal(parse_goal(raw))
    # Two runs over the same input must not mutate the goal.
    assert goal.constraints.people == 2
    assert goal.items == []


def test_intent_state_combines_goal_and_server_route() -> None:
    state = parse_intent_state(
        {
            "kind": "product_purchase",
            "items": ["牛奶"],
        },
        source_turn_id="turn-7",
    )

    assert state.version == 1
    assert state.source_turn_id == "turn-7"
    assert state.goal.kind == "product_purchase"
    assert state.decision.route == "prepare_product_purchase"
    assert state.decision.readiness == "ready"
