"""Independent, offline checks of the P1 contract (not model-quality eval)."""
import uuid

import pytest

from app.agent.goal_router import GateFacts, MutationView, decide_turn, mutation_refusal
from app.agent.protocol import SemanticProtocolError, parse_proposal
from app.schemas.goal import Goal, GoalChanges, GoalChangeSet, Understanding
from support import post_turn
from support.semantic_agent import pick


def product_goal() -> Goal:
    return Goal(kind="product_purchase", items=["牛奶"])


def test_missing_understanding_is_not_write_authority():
    decision = decide_turn(Understanding(), GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
    assert decision.write_blocked


def test_missing_decision_is_not_executor_authority():
    assert mutation_refusal(None, verb="add", ref="p1", ref_kind="product") is not None


def test_an_unrelated_goal_with_a_plan_in_play_asks_rather_than_writes():
    """Old: an invented relation string. New: relation is a closed enum the
    parser derives, so the equivalent case is an unstated relation with
    something on screen to relate to (rule 5)."""
    decision = decide_turn(
        Understanding(goal_relation="unspecified", new_goal=product_goal()),
        GateFacts(has_active_plan=True),
        mutations=[MutationView(verb="add", ref="p1", ref_kind="product")],
    )
    assert decision.write_blocked


def test_clear_unknown_field_is_a_protocol_error():
    with pytest.raises(SemanticProtocolError) as exc:
        parse_proposal({"focus": {"ref": "g1"}, "constraints": {"clear": ["price_fen"]}})
    assert exc.value.code == "MALFORMED_PROPOSAL"


def test_patch_cannot_target_another_group_than_its_focus():
    understanding = Understanding(
        goal_relation="amend", focus_ref="g1", changes=GoalChanges(set=GoalChangeSet(people=3))
    )
    facts = GateFacts(has_active_plan=True, focus_refs=({"ref": "g1", "kind": "plan_target"}, {"ref": "g2", "kind": "plan_target"}))
    decision = decide_turn(understanding, facts, mutations=[MutationView(verb="change", field="people", ref="g2", ref_kind="group")])
    assert decision.write_blocked or mutation_refusal(decision, verb="change", field="people", ref="g2", ref_kind="group") is not None


def test_ready_made_meal_does_not_authorize_raw_dish_build():
    understanding = Understanding(
        goal_relation="unspecified",
        new_goal=Goal(kind="meal_plan", target_name="鸡翅", fulfillment_mode="ready_made", constraints={"people": 3}),
    )
    decision = decide_turn(understanding, GateFacts(), mutations=[MutationView(verb="add", ref="d1", ref_kind="dish")])
    assert decision.write_blocked or mutation_refusal(decision, verb="add", ref="d1", ref_kind="dish") is not None


def test_a_read_only_turn_blocks_ready_goal_and_mutation():
    """Old: ask_fact/chat speech acts. New: intent explore/none with a goal
    stated is impossible by construction (a goal implies intent=buy), so the
    equivalent case is the read-only path itself refusing a mutation it never
    authorized."""
    for intent in ("explore", "none"):
        understanding = Understanding(intent=intent)
        decision = decide_turn(understanding, GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
        assert decision.write_blocked


def test_eval_state_checks_fail_on_safety_regressions():
    from app.evaluation.runner import _check_turn_action
    before = {"task_id": "a", "plan": {"items": [{"sku_id": "cola", "quantity": 1}], "targets": [{"people": 2}]}, "pending_clarifications": [{"question_id": "q1"}], "_cart": {"items": []}}
    after = {"task_id": "b", "plan": {"items": [{"sku_id": "cola", "quantity": 6}], "targets": [{"people": 4}]}, "pending_clarifications": [], "_cart": {"items": [{"sku_id": "cola"}]}}
    for kind in ("turn_plan_unchanged", "turn_pending_unchanged", "turn_cart_unchanged", "turn_task_unchanged"):
        assert _check_turn_action({"type": kind, "turn": 2}, [before, after])
        assert _check_turn_action({"type": kind, "turn": 2}, [before, before]) is None
    assert _check_turn_action({"type": "turn_quantity_delta", "turn": 2, "sku_id": "cola", "value": 4}, [before, after])
    assert _check_turn_action({"type": "turn_people_is", "turn": 2, "value": 3}, [before, after])


def test_prompt_examples_obey_the_parser():
    from app.prompts.semantic import PROPOSAL_EXAMPLES
    for _, proposal in PROPOSAL_EXAMPLES:
        parse_proposal(proposal)


# API checks reuse the project's isolated database fixtures.


def send(client, sid, previous=None):
    previous = previous or {}
    response = post_turn(
        client, sid, "本轮需求", previous, request_id=str(uuid.uuid4())
    )
    assert response.status_code == 200, response.json()
    return response.json()


def plan_business_state(plan):
    return (
        plan["plan_id"], plan["plan_version"],
        [(row["sku_id"], row["quantity"], row["selected"]) for row in plan["items"]],
        [(target["target_id"], target["people"]) for target in plan["targets"]],
    )


def setup_wings(client, semantic_provider):
    provider = semantic_provider([{
        "reply": "我来准备可乐鸡翅的清单。",
        "target": {"kind": "meal", "name": "可乐鸡翅", "intent": "buy"},
        "constraints": {"people": 2},
        "lookups": [{"kind": "dish", "query": "可乐鸡翅"}],
    }])
    sid = client.post("/api/v1/guide/sessions", json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}}).json()["session_id"]
    first = send(client, sid)
    assert first.get("plan"), first
    return provider, sid, first


def test_chat_reply_with_mutation_preserves_reply_without_write(client, semantic_provider):
    """Old: a ``chat`` speech_act alongside a low-level mutation. New: a
    proposal has no separate mutation dimension any more; the equivalent is a
    turn that states no goal and no edit (so it stays read-only chat) while
    still trying to look like it wrote something via the reply."""
    provider, sid, first = setup_wings(client, semantic_provider)

    def bad(request):
        return {"reply": "好的，我来帮你看看。"}

    provider.proposals = [bad]
    result = send(client, sid, first)
    assert result["message"] == "好的，我来帮你看看。"
    assert result.get("route") == "chat"
    assert not any(row.get("code") == "WRITE_BLOCKED" for row in result.get("action_results", []))
    after = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert plan_business_state(after) == plan_business_state(first["plan"])


def test_clear_people_must_not_report_ready_success_without_handling(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)

    def revoke(request):
        group = request["current_plan"]["groups"][0]
        return {
            "reply": "人数限制已取消。",
            "focus": {"ref": group["ref"]},
            "constraints": {"clear": ["people"]},
        }

    provider.proposals = [revoke]
    result = send(client, sid, first)
    assert "人数限制已取消" not in result["message"], result
    assert result.get("route") in ("clarify", "refuse") or any(x.get("status") in ("blocked", "failed") for x in result.get("action_results", [])), result


def test_multi_field_amend_is_not_partially_applied(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)

    def mixed(request):
        group = request["current_plan"]["groups"][0]
        return {
            "reply": "人数和预算都改好了。",
            "focus": {"ref": group["ref"]},
            "constraints": {"people": 3, "budget_yuan": 1},
        }

    provider.proposals = [mixed]
    send(client, sid, first)
    after = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert plan_business_state(after) == plan_business_state(first["plan"]), "unsupported budget patch must not leave a partial people update"


def hotpot_proposal(mode="self_cook", people=3):
    def build(request):
        row = next(x for x in request["candidates"]["scenarios"] if x["name"] == "火锅")
        return {
            "reply": "换成火锅",
            **pick("scenario", row, relation="switch", people=people, mode=mode),
        }

    return build


def test_high_level_candidate_switch_keeps_relation_without_initial_add(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)
    provider.proposals = [hotpot_proposal()]
    switched = send(client, sid, first)
    assert switched["plan"], switched
    assert switched["task_id"] != first["task_id"], switched
    assert len(switched["plan"]["targets"]) == 1
    assert switched["plan"]["targets"][0]["people"] == 3
    old_confirm = client.post(f"/api/v1/guide/tasks/{first['task_id']}/confirm", headers={"Idempotency-Key": str(uuid.uuid4())}, json={"plan_id": first["plan"]["plan_id"], "plan_version": first["plan"]["plan_version"], "expected_state_version": first["state_version"], "selected_items": [{"sku_id": row["sku_id"], "quantity": row["quantity"]} for row in first["plan"]["items"]]})
    assert old_confirm.status_code == 409, old_confirm.text
    assert client.get("/api/v1/cart").json()["items"] == []


def test_candidate_mode_answer_does_not_invent_people(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)
    provider.proposals = [hotpot_proposal(mode="unspecified", people=None)]
    result = send(client, sid, first)
    assert result["plan"], result
    assert result["plan"]["targets"][0]["people_source"] == "default"
    assert "people" not in (result.get("missing_slots") or [])
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]["plan_id"] == result["plan"]["plan_id"]


def test_failed_switch_merge_does_not_activate_or_supersede(client, semantic_provider, monkeypatch):
    provider, sid, first = setup_wings(client, semantic_provider)

    def fail(*args, **kwargs):
        raise SemanticProtocolError("BUILD_FAILED", "test build failure")

    monkeypatch.setattr("app.services.shopping_plan_service.ShoppingPlanService.merge_plan", fail)
    provider.proposals = [hotpot_proposal()]
    result = send(client, sid, first)
    persisted = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert persisted["task_id"] == first["task_id"], (result, persisted)
    assert plan_business_state(persisted["plan"]) == plan_business_state(first["plan"])


def test_a_scenario_add_cannot_carry_a_raw_quantity_override(client, semantic_provider):
    """Old: a scripted low-level ``mutations`` add that contradicted the goal's
    own headcount. New: the wire protocol carries only one add per turn (the
    goal's own ``target.ref``), so there is no separate channel left to
    contradict the goal's headcount with. What remains of the old protection is
    structural: a dish/scenario is sized by people, not by a raw ``quantity``
    (``app/agent/tools/change_plan.py::_prepare_add``), so declaring one on a
    scenario add is refused rather than silently building the wrong size."""
    provider, sid, first = setup_wings(client, semantic_provider)

    def contradict(request):
        row = next(x for x in request["candidates"]["scenarios"] if x["name"] == "火锅")
        return {
            "reply": "换成火锅",
            **pick("scenario", row, relation="switch", people=3, quantity=4),
        }

    provider.proposals = [contradict]
    response = send(client, sid, first)
    assert any(
        r.get("code") == "UNSUPPORTED_OPERATION" for r in response.get("action_results", [])
    ), response
    after = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert plan_business_state(after) == plan_business_state(first["plan"])
