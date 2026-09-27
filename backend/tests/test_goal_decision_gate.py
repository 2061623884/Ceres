"""Offline gate tests: the decision is a pure function, so it is checked directly.

These cases cover the rule table (R1-R10) and the safety properties the contract
promises: an unknown or undecided reading never authorizes a write, a read-only
or chat turn blocks one, a contradictory mutation is refused, and a candidate
goal keeps its original switch/append intent while its slots are filled.

Nothing here touches the database, the network, a model or the loop — the same
function is exercised through the real runtime in
``tests/test_p1_planner_decision_layer.py``.
"""

from __future__ import annotations

import pytest

from app.agent.goal import (
    GoalParseError,
    apply_goal_changes,
    merge_goal_candidate,
    parse_understanding,
)
from app.agent.goal_router import (
    CONFLICT_REASONS,
    GateFacts,
    MutationView,
    REASON_LEGACY,
    SLOT_FOCUS,
    SLOT_FULFILLMENT_MODE,
    SLOT_GOAL_RELATION,
    SLOT_MEAL_TARGET,
    decide_turn,
    mutation_refusal,
)
from app.schemas.goal import Goal, GoalCandidate, GoalChanges, GoalChangeSet


def understanding(**payload):
    return parse_understanding(payload)


def facts(**overrides) -> GateFacts:
    return GateFacts(**overrides)


def add(ref: str, kind: str = "scenario") -> MutationView:
    return MutationView(verb="add", ref=ref, ref_kind=kind)


# ------------------------------------------------------------------ R1-R5, R7


def test_read_only_and_chat_speech_acts_block_every_write() -> None:
    for speech_act, route in (("ask_fact", "answer"), ("chat", "chat")):
        decision = decide_turn(
            understanding(speech_act=speech_act),
            facts(has_active_plan=True),
            mutations=[add("s1")],
        )
        assert decision.route == route
        assert decision.write_blocked is True
        assert decision.missing_slots == []


def test_a_located_remove_routes_to_mutation_not_stop_refusal() -> None:
    group_ref = "dish:dish-hongshao-rou"
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="amend",
            focus_ref=group_ref,
        ),
        facts(
            has_active_plan=True,
            focus_refs=(
                {"ref": group_ref, "kind": "plan_target", "label": "红烧肉"},
            ),
            plan_target_refs=(group_ref,),
        ),
        mutations=[
            MutationView(verb="remove", ref=group_ref, ref_kind="dish", ref_name="红烧肉")
        ],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "apply_mutation"
    assert decision.write_blocked is False
    assert decision.reason_code != "STOP_REQUESTED"


def test_unsupported_goals_are_refused_rather_than_planned() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="new",
            new_goal={"kind": "unsupported", "description": "帮我开处方药"},
        ),
        facts(),
    )
    assert decision.route == "refuse"
    assert decision.readiness == "unsupported"
    assert decision.write_blocked is True


def test_an_undecided_meal_asks_instead_of_preparing() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="new",
            new_goal={"kind": "meal_decision", "description": "不知道吃什么"},
        ),
        facts(),
    )
    assert decision.route == "clarify"
    assert decision.missing_slots == [SLOT_MEAL_TARGET]
    assert decision.write_blocked is True


def test_an_unstated_fulfillment_mode_prepares_ingredients_without_claiming_self_cook() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="new",
            new_goal={"kind": "meal_plan", "target_name": "可乐鸡翅"},
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


def test_a_ready_meal_goal_prepares_and_unblocks_the_write() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="new",
            new_goal={
                "kind": "meal_plan",
                "fulfillment_mode": "self_cook",
                "target_name": "火锅",
                "constraints": {"people": 3},
            },
        ),
        facts(),
        mutations=[add("s1")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.readiness == "ready"
    assert decision.write_blocked is False
    assert decision.candidate is not None
    assert decision.candidate.relation == "new"
    assert decision.candidate.target_ref == "s1"


def test_a_product_purchase_never_asks_about_people() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation="new",
            new_goal={"kind": "product_purchase", "items": ["牛奶"]},
        ),
        facts(),
        mutations=[add("p1", "product")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.write_blocked is False
    assert decision.missing_slots == []
    assert decision.goal.kind == "product_purchase"
    # A non-meal goal is not a meal-fulfilment question at all.
    from app.agent.goal_router import route_goal

    assert route_goal(decision.goal).fulfillment_mode == "none"


def test_an_undecided_relation_with_a_plan_in_play_asks_before_writing() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            new_goal={"kind": "meal_plan", "fulfillment_mode": "self_cook", "target_name": "火锅"},
        ),
        facts(has_active_plan=True),
        mutations=[add("s1")],
    )
    assert decision.route == "clarify"
    assert decision.missing_slots == [SLOT_GOAL_RELATION]
    assert decision.write_blocked is True


def test_a_goal_with_no_plan_to_relate_to_is_implicitly_new() -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            new_goal={
                "kind": "meal_plan",
                "fulfillment_mode": "self_cook",
                "target_name": "火锅",
                "constraints": {"people": 3},
            },
        ),
        facts(),
        mutations=[add("s1")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.write_blocked is False
    assert decision.relation == "new"


def test_an_unresolvable_focus_is_never_guessed() -> None:
    decision = decide_turn(
        understanding(
            speech_act="correct",
            goal_relation="amend",
            focus_ref="made-up",
            changes={"set": {"people": 3}},
        ),
        facts(has_active_plan=True, focus_refs=({"ref": "active-goal-1", "kind": "active_goal"},)),
    )
    assert decision.route == "clarify"
    assert decision.missing_slots == [SLOT_FOCUS]
    assert decision.write_blocked is True


def test_a_people_patch_on_an_active_plan_needs_no_explicit_focus() -> None:
    decision = decide_turn(
        understanding(
            speech_act="correct", goal_relation="amend", changes={"set": {"people": 3}}
        ),
        facts(has_active_plan=True),
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "apply_mutation"
    assert decision.write_blocked is False
    assert decision.focus_kind == "active_goal"


def test_a_located_low_level_row_operation_is_authorized() -> None:
    decision = decide_turn(
        understanding(speech_act="request_action", goal_relation="amend", focus_ref="i1"),
        facts(
            has_active_plan=True,
            focus_refs=({"ref": "i1", "kind": "plan_target"},),
        ),
        mutations=[MutationView(verb="change", field="quantity", ref="i1", ref_kind="item")],
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "apply_mutation"
    assert decision.write_blocked is False
    assert decision.relation == "amend"


# ------------------------------------------------------------ the amend path


def _hotpot_candidate() -> GoalCandidate:
    return GoalCandidate(
        ref="goal-1",
        goal=Goal(kind="meal_plan", fulfillment_mode="unspecified", target_name="火锅"),
        relation="switch",
        target_ref="s1",
        target_id="hotpot",
        target_name="火锅",
        target_kind="scenario",
        missing_slots=[SLOT_FULFILLMENT_MODE],
        task_id="t1",
        plan_version=2,
    )


def test_answering_the_candidate_question_fills_it_and_keeps_its_switch_intent() -> None:
    candidate = _hotpot_candidate()
    decision = decide_turn(
        understanding(
            speech_act="answer_clarification",
            goal_relation="amend",
            focus_ref="goal-1",
            changes={"set": {"fulfillment_mode": "self_cook", "people": 3}},
        ),
        facts(
            has_active_plan=True,
            candidate=candidate,
            focus_refs=({"ref": "goal-1", "kind": "pending_goal"},),
            has_pending_question=True,
        ),
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.write_blocked is False
    assert decision.candidate is not None
    assert decision.candidate.relation == "switch"
    assert decision.candidate.target_ref == "s1"
    assert decision.candidate.goal.constraints.people == 3
    assert decision.candidate.goal.fulfillment_mode == "self_cook"


def test_a_people_answer_on_a_named_candidate_can_prepare_without_mode_first() -> None:
    candidate = _hotpot_candidate()
    decision = decide_turn(
        understanding(
            speech_act="answer_clarification",
            goal_relation="amend",
            focus_ref="goal-1",
            changes={"set": {"people": 3}},
        ),
        facts(
            has_active_plan=True,
            candidate=candidate,
            focus_refs=({"ref": "goal-1", "kind": "pending_goal"},),
            has_pending_question=True,
        ),
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.write_blocked is False
    assert decision.candidate is not None
    assert decision.candidate.goal.constraints.people == 3


def test_an_amendment_without_focus_on_an_active_plan_patches_people() -> None:
    decision = decide_turn(
        understanding(
            speech_act="answer_clarification",
            goal_relation="amend",
            changes={"set": {"people": 3}},
        ),
        facts(has_active_plan=True),
    )
    assert decision.route == "mutation"
    assert decision.mutation_action == "apply_mutation"
    assert decision.write_blocked is False
    assert decision.focus_kind == "active_goal"


# ----------------------------------------------------- the contract's strictness


def test_unknown_keys_are_rejected_not_dropped() -> None:
    with pytest.raises(GoalParseError) as exc:
        parse_understanding({"speech_act": "request_action", "surprise": True})
    assert exc.value.code == "MALFORMED_UNDERSTANDING"
    with pytest.raises(GoalParseError):
        parse_understanding({"changes": {"set": {"stock": 5}}})


def test_server_owned_fields_cannot_be_authored() -> None:
    for payload in (
        {"route": "prepare"},
        {"readiness": "ready"},
        {"missing_slots": []},
        {"plan_version": 2},
    ):
        with pytest.raises(GoalParseError) as exc:
            parse_understanding(payload)
        assert exc.value.code == "FORBIDDEN_FIELD"


def test_new_goal_and_patch_are_mutually_exclusive() -> None:
    with pytest.raises(GoalParseError):
        parse_understanding(
            {
                "goal_relation": "switch",
                "new_goal": {"kind": "meal_plan", "fulfillment_mode": "self_cook"},
                "changes": {"set": {"people": 2}},
            }
        )


def test_a_relation_must_agree_with_its_payload() -> None:
    with pytest.raises(GoalParseError):
        parse_understanding({"goal_relation": "switch"})
    with pytest.raises(GoalParseError):
        parse_understanding(
            {"goal_relation": "amend", "new_goal": {"kind": "meal_plan"}}
        )


def test_set_and_clear_of_one_field_is_refused() -> None:
    with pytest.raises(GoalParseError) as exc:
        parse_understanding({"changes": {"set": {"people": 3}, "clear": ["people"]}})
    assert "同时 set 与 clear" in exc.value.message


def test_unknown_enum_values_normalize_conservatively() -> None:
    parsed = parse_understanding(
        {
            "speech_act": "make_dinner",
            "goal_relation": "replace_everything",
            "changes": {"set": {"fulfillment_mode": "delivery"}},
        }
    )
    assert parsed.speech_act == "unspecified"
    assert parsed.goal_relation == "unspecified"
    # An unrecognised fulfilment mode is "not said", and it blocks nothing by
    # itself; the goal it applies to decides.
    assert parsed.changes.set.fulfillment_mode == "unspecified"

    decision = decide_turn(parsed, facts(has_active_plan=True))
    assert decision.write_blocked is True


def test_clear_revokes_and_omission_keeps() -> None:
    goal = Goal(
        kind="meal_plan",
        fulfillment_mode="self_cook",
        target_name="火锅",
        constraints={"people": 3, "dietary": ["清淡"], "budget_yuan": 80},
    )
    kept = apply_goal_changes(goal, GoalChanges(set=GoalChangeSet(people=5)))
    assert kept.constraints.people == 5
    assert kept.constraints.budget_yuan == 80
    assert kept.constraints.dietary == ["清淡"]

    cleared = apply_goal_changes(
        goal, GoalChanges(clear=["people", "dietary", "budget_yuan", "fulfillment_mode"])
    )
    assert cleared.constraints.people is None
    assert cleared.constraints.dietary == []
    assert cleared.constraints.budget_yuan is None
    # Revoking the mode never turns into "assume self-cook".
    assert cleared.fulfillment_mode == "unspecified"


def test_merging_into_a_candidate_keeps_its_relation_and_target() -> None:
    candidate = _hotpot_candidate()
    merged = merge_goal_candidate(
        candidate,
        parse_understanding(
            {"goal_relation": "amend", "changes": {"set": {"fulfillment_mode": "self_cook"}}}
        ),
    )
    assert merged is not None
    assert merged.relation == "switch"
    assert merged.target_ref == "s1"
    assert merged.goal.fulfillment_mode == "self_cook"
    # A proposal that patched nothing does not touch the candidate at all.
    assert (
        merge_goal_candidate(
            candidate, parse_understanding({"goal_relation": "amend", "focus_ref": "goal-1"})
        )
        is None
    )


@pytest.mark.parametrize(
    ("relation", "verb", "field", "expected"),
    [
        ("switch", "add", None, None),
        ("switch", "change", "people", "GOAL_CHANGE_CONFLICT"),
        ("switch", "remove", None, "GOAL_CHANGE_CONFLICT"),
        ("append", "add", None, None),
        ("amend", "add", None, "GOAL_CHANGE_CONFLICT"),
        ("amend", "change", "people", None),
    ],
)
def test_only_the_authorized_operation_survives(
    relation: str, verb: str, field: str | None, expected: str | None
) -> None:
    decision = decide_turn(
        understanding(
            speech_act="request_action",
            goal_relation=relation,
            **(
                {
                    "new_goal": {
                        "kind": "meal_plan",
                        "fulfillment_mode": "self_cook",
                        "target_name": "火锅",
                        "constraints": {"people": 3},
                    }
                }
                if relation in ("switch", "append")
                else {"changes": {"set": {"people": 3}}, "focus_ref": "g1"}
            ),
        ),
        facts(
            has_active_plan=True,
            focus_refs=({"ref": "g1", "kind": "plan_target"},),
        ),
        mutations=[MutationView(verb="add", ref="s1", ref_kind="scenario")],
    )
    code = mutation_refusal(
        decision,
        verb=verb,
        field=field,
        ref="s1" if verb == "add" else "g1",
        switch_goal=False,
    )
    assert code == expected


def test_the_pending_candidate_blocks_an_edit_of_the_old_plan() -> None:
    decision = decide_turn(
        understanding(
            speech_act="answer_clarification", goal_relation="amend", focus_ref="goal-1",
            changes={"set": {"fulfillment_mode": "self_cook", "people": 3}},
        ),
        facts(
            has_active_plan=True,
            candidate=_hotpot_candidate(),
            focus_refs=(
                {"ref": "goal-1", "kind": "pending_goal"},
                {"ref": "g1", "kind": "plan_target"},
            ),
            has_pending_question=True,
        ),
        mutations=[MutationView(verb="add", ref="s1", ref_kind="scenario")],
    )
    assert decision.write_blocked is False
    code = mutation_refusal(
        decision, verb="change", field="people", ref="g1", switch_goal=False
    )
    assert code == "CANDIDATE_GOAL_CONFLICT"
    assert code in CONFLICT_REASONS


def test_a_legacy_switch_flag_no_longer_granted_by_itself() -> None:
    decision = decide_turn(
        None,
        facts(has_active_plan=True),
        mutations=[MutationView(verb="add", ref="s1", ref_kind="scenario", switch_goal=True)],
    )
    assert decision.write_blocked is True
    assert decision.missing_slots == ["understanding"]
    assert decision.legacy_protocol is True
    assert (
        mutation_refusal(decision, verb="add", ref="s1", switch_goal=True)
        == "SWITCH_REQUIRES_UNDERSTANDING"
    )
    # The reason is the missing statement; the outcome is the same blocked write.
    assert decision.reason_code == "MISSING_UNDERSTANDING"
    assert (
        mutation_refusal(decision, verb="add", ref="s1", switch_goal=False)
        == "WRITE_BLOCKED"
    )
    # With no decision at all the answer is the same: nothing is authorized.
    assert (
        mutation_refusal(None, verb="change", field="quantity", ref="i1")
        == "MISSING_UNDERSTANDING"
    )


def test_a_chat_turn_cannot_write_even_with_a_mutation() -> None:
    decision = decide_turn(
        understanding(speech_act="chat"),
        facts(has_active_plan=True),
        mutations=[add("s1")],
    )
    assert decision.write_blocked is True
    assert mutation_refusal(decision, verb="add", ref="s1") == "WRITE_BLOCKED"
