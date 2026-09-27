"""Independent, offline checks of the P1 contract (not model-quality eval)."""
import uuid

import pytest

from app.agent.goal import GoalParseError, parse_understanding
from app.agent.goal_router import GateFacts, MutationView, decide_turn, mutation_refusal
from support import post_turn


def product_goal():
    return {"kind": "product_purchase", "items": ["鐗涘ザ"]}


def test_missing_understanding_is_not_write_authority():
    decision = decide_turn(None, GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
    assert decision.write_blocked


def test_missing_decision_is_not_executor_authority():
    assert mutation_refusal(None, verb="add", ref="p1", ref_kind="product") is not None


@pytest.mark.parametrize("speech_act", ["invented_action", "unspecified"])
def test_unknown_speech_act_cannot_authorize_ready_goal(speech_act):
    proposal = parse_understanding({"speech_act": speech_act, "goal_relation": "new", "new_goal": product_goal()})
    decision = decide_turn(proposal, GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
    assert decision.write_blocked


def test_unknown_relation_is_not_implicit_purchase_permission():
    proposal = parse_understanding({"speech_act": "request_action", "goal_relation": "invented_relation", "new_goal": product_goal()})
    decision = decide_turn(proposal, GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
    assert decision.write_blocked


def test_clear_unknown_field_is_a_protocol_error():
    with pytest.raises(GoalParseError):
        parse_understanding({"speech_act": "correct", "goal_relation": "amend", "focus_ref": "g1", "changes": {"clear": ["price_fen"]}})


def test_patch_cannot_target_another_group_than_its_focus():
    proposal = parse_understanding({"speech_act": "correct", "goal_relation": "amend", "focus_ref": "g1", "changes": {"set": {"people": 3}}})
    facts = GateFacts(has_active_plan=True, focus_refs=({"ref": "g1", "kind": "plan_target"}, {"ref": "g2", "kind": "plan_target"}))
    decision = decide_turn(proposal, facts, mutations=[MutationView(verb="change", field="people", ref="g2", ref_kind="group")])
    assert decision.write_blocked or mutation_refusal(decision, verb="change", field="people", ref="g2", ref_kind="group") is not None


def test_ready_made_meal_does_not_authorize_raw_dish_build():
    proposal = parse_understanding({"speech_act": "request_action", "goal_relation": "new", "new_goal": {"kind": "meal_plan", "target_name": "楦＄繀", "fulfillment_mode": "ready_made", "constraints": {"people": 3}}})
    decision = decide_turn(proposal, GateFacts(), mutations=[MutationView(verb="add", ref="d1", ref_kind="dish")])
    assert decision.write_blocked or mutation_refusal(decision, verb="add", ref="d1", ref_kind="dish") is not None


@pytest.mark.parametrize("speech_act", ["ask_fact", "chat"])
def test_non_action_act_blocks_ready_goal_and_mutation(speech_act):
    proposal = parse_understanding({"speech_act": speech_act, "goal_relation": "new", "new_goal": product_goal()})
    decision = decide_turn(proposal, GateFacts(), mutations=[MutationView(verb="add", ref="p1", ref_kind="product")])
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
    from app.agent.protocol import parse_proposal
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
        "lookups": [{"kind": "dish", "query": "可乐鸡翅"}],
        "understanding": {
            "speech_act": "request_action", "goal_relation": "new",
            "new_goal": {"kind": "meal_plan", "target_name": "可乐鸡翅",
                         "fulfillment_mode": "self_cook", "constraints": {"people": 2}},
        },
    }])
    sid = client.post("/api/v1/guide/sessions", json={"entry_context": {"page": "home", "store_id": "store-demo-01", "delivery_zone_id": "zone-default"}}).json()["session_id"]
    first = send(client, sid)
    assert first.get("plan"), first
    return provider, sid, first


def test_chat_reply_with_mutation_preserves_reply_without_write(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)

    def bad(request):
        item = request["current_plan"]["items"][0]
        return {"reply": "好的，我来帮你看看。", "understanding": {"speech_act": "chat"}, "mutations": [{"verb": "change", "target_ref": item["ref"], "name": item["name"], "field": "quantity", "quantity": {"mode": "delta", "value": 4}}]}

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
        return {"reply": "人数限制已取消。", "understanding": {"speech_act": "correct", "goal_relation": "amend", "focus_ref": group["ref"], "changes": {"clear": ["people"]}}}

    provider.proposals = [revoke]
    result = send(client, sid, first)
    assert "人数限制已取消" not in result["message"], result
    assert result.get("route") in ("clarify", "refuse") or any(x.get("status") in ("blocked", "failed") for x in result.get("action_results", [])), result


def test_multi_field_amend_is_not_partially_applied(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)

    def mixed(request):
        group = request["current_plan"]["groups"][0]
        return {"reply": "人数和预算都改好了。", "understanding": {"speech_act": "correct", "goal_relation": "amend", "focus_ref": group["ref"], "changes": {"set": {"people": 3, "budget_yuan": 1}}}, "mutations": [{"verb": "change", "target_ref": group["ref"], "name": group["name"], "field": "people", "people": 3}]}

    provider.proposals = [mixed]
    send(client, sid, first)
    after = client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert plan_business_state(after) == plan_business_state(first["plan"]), "unsupported budget patch must not leave a partial people update"


def hotpot_semantics(mode="self_cook", people=3):
    goal = {"kind": "meal_plan", "target_name": "火锅", "fulfillment_mode": mode}
    if people is not None:
        goal["constraints"] = {"people": people}
    return {"reply": "换成火锅", "understanding": {"speech_act": "request_action", "goal_relation": "switch", "focus_ref": "active-goal-1", "new_goal": goal}}


def test_high_level_candidate_switch_keeps_relation_without_initial_add(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)
    provider.proposals = [hotpot_semantics()]
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
    provider.proposals = [hotpot_semantics("unspecified", people=None)]
    result = send(client, sid, first)
    assert result["plan"], result
    assert result["plan"]["targets"][0]["people_source"] == "default"
    assert "people" not in (result.get("missing_slots") or [])
    assert client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]["plan_id"] == result["plan"]["plan_id"]


def test_failed_switch_merge_does_not_activate_or_supersede(client, semantic_provider, monkeypatch):
    provider, sid, first = setup_wings(client, semantic_provider)
    from app.agent.protocol import SemanticProtocolError

    def fail(*args, **kwargs):
        raise SemanticProtocolError("BUILD_FAILED", "test build failure")

    monkeypatch.setattr("app.services.shopping_plan_service.ShoppingPlanService.merge_plan", fail)
    provider.proposals = [hotpot_semantics()]
    result = send(client, sid, first)
    persisted = client.get(f"/api/v1/guide/sessions/{sid}").json()
    assert persisted["task_id"] == first["task_id"], (result, persisted)
    assert plan_business_state(persisted["plan"]) == plan_business_state(first["plan"])


def test_goal_headcount_cannot_be_overridden_by_low_level_add(client, semantic_provider):
    provider, sid, first = setup_wings(client, semantic_provider)

    def contradict(request):
        scenario = next(x for x in request["candidates"]["scenarios"] if x["name"] == "火锅")
        proposal = hotpot_semantics(people=3)
        proposal["mutations"] = [{"verb": "add", "candidate_ref": scenario["ref"], "name": scenario["name"], "people": 4}]
        return proposal

    provider.proposals = [contradict]
    response = send(client, sid, first)
    assert response["plan_effect"] == "keep"
    assert plan_business_state(client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]) == plan_business_state(first["plan"])
