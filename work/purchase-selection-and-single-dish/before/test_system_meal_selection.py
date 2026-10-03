"""Server meal selection through the real recommendation, validation and SSE chain."""

import json

import pytest

from app.agent.protocol import CandidateSet, Query, SemanticProposal
from app.agent.goal_router import GateFacts, MutationView, decide_turn
from app.agent.tools.read import ReadTools
from app.schemas.goal import Goal, GoalConstraints, Understanding
from support import create_session, post_turn
from support.semantic_agent import Continuation, request_new
from test_semantic_phase1_purchase import indexed_client


def send(client, sid, text, previous=None):
    response = post_turn(client, sid, text, previous)
    assert response.status_code == 200, response.json()
    return response.json()


def meal(**constraints):
    return request_new("dish", "", constraints=constraints)


@pytest.fixture()
def recommendations(monkeypatch):
    calls = []
    original = ReadTools.serve

    def record(self, proposal, candidates, *, lookup_limit):
        results = original(self, proposal, candidates, lookup_limit=lookup_limit)
        calls.extend(result for result in results if result["kind"] == "recommend")
        return results

    monkeypatch.setattr(ReadTools, "serve", record)
    return calls


def test_unnamed_meal_asks_once_then_selects_and_read_only_interjection_does_not_buy(
    indexed_client, semantic_provider, recommendations
):
    provider = semantic_provider([
        meal(), {"reply": "不客气。"}, meal(),
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "今晚想做顿简单的饭")
    assert first["status"] == first["answer_status"] == "clarifying"
    assert first["plan"] is None and first["task_id"] is None
    assert first["missing_slots"] == ["meal_preferences"]
    assert "不说也可以" in first["message"]
    interjection = send(indexed_client, sid, "谢谢", first)
    assert interjection["plan"] is None
    assert interjection["pending_clarifications"] == first["pending_clarifications"]
    selected = send(indexed_client, sid, "随便，你帮我配吧", interjection)
    assert selected["status"] == "awaiting_confirmation", selected
    assert selected["plan"]["targets"][0]["selection_goal"]["kind"] == "meal_decision"
    assert selected["plan"]["targets"][0]["people_source"] == "default"
    assert not selected["pending_clarifications"]
    assert len(provider.requests) == 3
    assert len(recommendations) == 1
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_budget_selects_directly_and_real_other_candidates_are_displayed_in_order(
    indexed_client, semantic_provider, recommendations
):
    provider = semantic_provider([meal(budget_yuan=100)])
    sid = create_session(indexed_client)
    body = send(indexed_client, sid, "帮我配一餐，预算100")
    assert body["status"] == "awaiting_confirmation", body
    target = body["plan"]["targets"][0]
    assert target["selection_goal"]["constraints"]["budget_yuan"] == 100
    assert body["plan"]["selected_total_fen"] <= 10000
    options = recommendations[0]["buildable_dishes"]
    assert target["target_id"] == options[0]["dish_id"]
    others = [option for option in options if option["dish_id"] != target["target_id"]]
    assert "1. " + others[0]["name"] in body["message"]
    assert "2. " + others[1]["name"] in body["message"]
    assert len(provider.requests) == 1


def test_switch_another_system_selected_meal_excludes_current_before_recommendation(
    indexed_client, semantic_provider, recommendations
):
    def another(request):
        group = request["current_plan"]["groups"][0]
        assert "selection_goal" in group
        proposal = request_new("dish", "", relation="switch")
        proposal["focus"] = {"ref": group["ref"], "name": group["name"]}
        return proposal

    semantic_provider([meal(budget_yuan=100), another])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "预算100，你帮我配一餐")
    second = send(indexed_client, sid, "换一个", first)
    assert second["status"] == "awaiting_confirmation", second
    before = first["plan"]["targets"][0]
    after = second["plan"]["targets"][0]
    assert before["target_id"] != after["target_id"]
    assert before["target_id"] not in [row["dish_id"] for row in recommendations[1]["buildable_dishes"]]
    assert len(recommendations[1]["buildable_dishes"]) == 3
    assert after["selection_goal"]["constraints"]["budget_yuan"] == 100
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_active_goal_switch_inherits_constraints_and_excludes_the_real_current_dish(
    indexed_client, semantic_provider, recommendations
):
    def another(request):
        proposal = request_new("dish", "", relation="switch")
        proposal["focus"] = {"ref": "active-goal-1"}
        return proposal

    semantic_provider([
        meal(budget_yuan=100, excluded_ingredients=["鸡蛋"]),
        another,
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "预算100，不要鸡蛋，你帮我配一餐")
    second = send(indexed_client, sid, "换一个", first)

    assert second["status"] == "awaiting_confirmation", second
    before = first["plan"]["targets"][0]
    after = second["plan"]["targets"][0]
    assert before["target_id"] != after["target_id"]
    assert before["target_id"] not in [
        row["dish_id"] for row in recommendations[1]["buildable_dishes"]
    ]
    assert after["selection_goal"]["constraints"]["budget_yuan"] == 100
    assert after["selection_goal"]["constraints"]["excluded_ingredients"] == ["鸡蛋"]
    assert all("鸡蛋" not in row["name"] for row in second["plan"]["items"])
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_unnamed_system_replace_without_focus_inherits_constraints_and_excludes_current(
    indexed_client, semantic_provider, recommendations
):
    semantic_provider([
        meal(budget_yuan=100, excluded_ingredients=["鸡蛋"]),
        request_new("dish", "", relation="switch"),
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "预算100，不要鸡蛋，你帮我配一餐")
    second = send(indexed_client, sid, "换一个", first)

    assert second["status"] == "awaiting_confirmation", second
    before = first["plan"]["targets"][0]
    after = second["plan"]["targets"][0]
    assert before["target_id"] != after["target_id"]
    assert before["target_id"] not in [
        row["dish_id"] for row in recommendations[1]["buildable_dishes"]
    ]
    assert after["selection_goal"]["constraints"]["budget_yuan"] == 100
    assert after["selection_goal"]["constraints"]["excluded_ingredients"] == ["鸡蛋"]
    assert all("鸡蛋" not in row["name"] for row in second["plan"]["items"])
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_selecting_displayed_second_candidate_replaces_and_removes_system_marker(
    indexed_client, semantic_provider
):
    chosen = {}

    def pick_second(request):
        row = request["displayed_candidates"][1]
        chosen.update(row)
        return request_new("dish", row["name"], ref=row["ref"])

    def edit_budget(request):
        return {"focus": {"ref": "active-goal-1"}, "constraints": {"budget_yuan": 80}}

    semantic_provider([meal(budget_yuan=100), pick_second, edit_budget])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "你帮我配一餐，预算100")
    second = send(indexed_client, sid, "就第二个", first)
    assert second["status"] == "awaiting_confirmation", second
    target = second["plan"]["targets"][0]
    assert target["target_id"] == chosen["target_id"]
    assert "selection_goal" not in target
    assert second["plan"]["selected_total_fen"] <= 10000
    assert second["task_id"] != first["task_id"]
    third = send(indexed_client, sid, "预算改成80", second)
    saved = indexed_client.get(f"/api/v1/guide/sessions/{sid}").json()["plan"]
    assert saved["plan_id"] == second["plan"]["plan_id"]
    assert third["plan_effect"] == "keep"
    assert any(row["code"] == "UNSUPPORTED_CHANGE_FIELD" for row in third["action_results"])


def test_impossible_budget_is_degraded_and_recovery_uses_pending_goal(
    indexed_client, semantic_provider, recommendations
):
    semantic_provider([meal(budget_yuan=0.01), {"constraints": {"budget_yuan": 100}}])
    sid = create_session(indexed_client)
    failed = send(indexed_client, sid, "帮我配一餐，预算0.01元")
    assert failed["status"] == failed["answer_status"] == "degraded", failed
    assert failed["plan"] is None and failed["task_id"] is None
    assert any(row["code"] == "NO_FEASIBLE_MEAL" for row in failed["action_results"])
    assert len(recommendations[0]["buildable_dishes"]) == 3
    recovered = send(indexed_client, sid, "预算改成100", failed)
    assert recovered["status"] == "awaiting_confirmation", recovered
    assert recovered["plan"]["targets"][0]["selection_goal"]["constraints"]["budget_yuan"] == 100
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


def test_failed_reselection_keeps_the_actual_old_task_and_plan(
    indexed_client, semantic_provider
):
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    semantic_provider([meal(budget_yuan=100), {"constraints": {"budget_yuan": 0.01}}])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "你帮我配一餐，预算100")
    with SessionLocal() as db:
        plan_before = db.get(GuideTask, first["task_id"]).plan_json
    second = send(indexed_client, sid, "预算改成0.01元", first)
    assert second["status"] == second["answer_status"] == "degraded", second
    assert second["task_id"] == first["task_id"]
    assert second["plan"] is None
    assert second["plan_effect"] == "keep"
    with SessionLocal() as db:
        task = db.get(GuideTask, first["task_id"])
        assert task.current_step == "awaiting_confirmation"
        assert task.plan_json == plan_before


def test_budget_can_increase_and_exclusion_can_be_cleared_without_old_union(
    indexed_client, semantic_provider
):
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    def check_budget(request):
        assert request["requirements"]["budget_fen"] == 20000
        assert request["requirements"]["excluded_ingredients"] == []
        return {"reply": "预算已经改为200。"}

    semantic_provider([
        meal(budget_yuan=100, excluded_ingredients=["花生"]),
        {"constraints": {"budget_yuan": 200, "clear": ["excluded_ingredients"]}},
        check_budget,
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "帮我配一餐，预算100，不要花生")
    second = send(indexed_client, sid, "预算200，撤销花生忌口", first)
    assert second["status"] == "awaiting_confirmation", second
    constraints = second["plan"]["targets"][0]["selection_goal"]["constraints"]
    assert constraints["budget_yuan"] == 200
    assert constraints["excluded_ingredients"] == []
    with SessionLocal() as db:
        saved = json.loads(db.get(GuideTask, second["task_id"]).requirements_json)
        assert saved["budget_fen"] == 20000
        assert saved["excluded_ingredients"] == []
    send(indexed_client, sid, "现在的预算呢", second)


@pytest.mark.parametrize("failure", ["stock", "budget"])
def test_first_recommendation_is_truly_validated_then_second_is_selected(
    indexed_client, semantic_provider, recommendations, monkeypatch, failure
):
    from sqlalchemy import text
    from app.agent.tools.change_plan import PlanChangeExecutor
    from app.agent.tools.prepare_purchase_plan import guarded_prepare_purchase_plan
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        options = ReadTools(db, store_id="store-demo-01", delivery_zone_id="zone-default").serve(
            SemanticProposal(queries=[Query(kind="recommend")]), CandidateSet(), lookup_limit=0,
        )[0]["buildable_dishes"]
        plans = [guarded_prepare_purchase_plan(
            db, store_id="store-demo-01", delivery_zone_id="zone-default",
            target_kind="dish", target_id=option["dish_id"], budget_fen=10000,
        ) for option in options]
        assert all(plan["status"] == "ok" for plan in plans)
        first_skus = {row["sku_id"] for row in plans[0]["items"] if row["role"] == "required"}
        other_skus = {row["sku_id"] for plan in plans[1:] for row in plan["items"]}
        unique = first_skus - other_skus
        assert unique
        sku_id = sorted(unique)[0]
        if failure == "stock":
            db.execute(text("UPDATE offers SET available_qty=0 WHERE sku_id=:sku"), {"sku": sku_id})
        else:
            db.execute(text("UPDATE offers SET price_fen=20000 WHERE sku_id=:sku"), {"sku": sku_id})
        db.commit()

    steps = []
    prepare = PlanChangeExecutor.prepare

    def record(self, **kwargs):
        staged = prepare(self, **kwargs)
        steps.append(staged)
        return staged

    monkeypatch.setattr(PlanChangeExecutor, "prepare", record)
    semantic_provider([meal(budget_yuan=100)])
    sid = create_session(indexed_client)
    selected = send(indexed_client, sid, "帮我配一餐，预算100")
    assert selected["status"] == "awaiting_confirmation", selected
    assert recommendations[-1]["buildable_dishes"][0]["dish_id"] == options[0]["dish_id"]
    if failure == "stock":
        assert steps[0]["status"] == "staged"
        assert steps[0]["plan_result"]["coverage_mode"] == "partial"
    else:
        assert steps[0]["status"] == "failed"
        assert steps[0]["code"] == "BUDGET_EXCEEDED"
    assert steps[1]["status"] == "staged"
    assert selected["plan"]["targets"][0]["target_id"] == options[1]["dish_id"]
    assert selected["plan"]["can_confirm"] is True


def test_exclusion_reselects_under_real_constraints_and_unsupported_flavor_is_reported(
    indexed_client, semantic_provider
):
    first_proposal = meal(budget_yuan=100)
    first_proposal["constraints"]["unsupported"] = ["清淡"]

    def exclude_tomato(request):
        group = request["current_plan"]["groups"][0]
        return {"focus": {"ref": group["ref"]},
                "constraints": {"excluded_ingredients": ["番茄"]}}

    semantic_provider([first_proposal, exclude_tomato])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "帮我配清淡的一餐，预算100")
    assert "清淡" in first["message"] and "没有用上" in first["message"]
    assert first["plan"]["targets"][0]["name"] == "番茄炒蛋"
    second = send(indexed_client, sid, "不要番茄", first)
    assert second["status"] == "awaiting_confirmation", second
    target = second["plan"]["targets"][0]
    assert target["name"] != "番茄炒蛋"
    assert target["selection_goal"]["constraints"]["excluded_ingredients"] == ["番茄"]
    assert all("番茄" not in row["name"] for row in second["plan"]["items"])


@pytest.mark.parametrize(
    ("constraints", "read_message", "expected_saved", "expected_plan"),
    [
        (
            {"budget_yuan": 50}, "预算50，推荐几道菜",
            {"budget_fen": 5000}, {"budget_yuan": 50},
        ),
        (
            {"excluded_ingredients": ["鸡蛋"]},
            "推荐几道菜，不吃鸡蛋",
            {"excluded_ingredients": ["鸡蛋"]},
            {"excluded_ingredients": ["鸡蛋"]},
        ),
    ],
)
def test_saved_taskless_read_preferences_skip_the_next_meal_question(
    indexed_client, semantic_provider, recommendations,
    constraints, read_message, expected_saved, expected_plan,
):
    from app.core.database import SessionLocal
    from app.models.session import GuideSemanticContext

    semantic_provider([
        {"reads": [{"kind": "recommend"}], "constraints": constraints},
        Continuation(lambda request: {"reply": "这些是没有鸡蛋的候选。", "display_refs": []}),
        meal(),
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, read_message)
    assert first["plan"] is None
    with SessionLocal() as db:
        saved = json.loads(db.get(GuideSemanticContext, sid).context_json)["session_constraints"]
    assert saved == expected_saved

    selected = send(indexed_client, sid, "帮我配一餐", first)
    assert selected["status"] == "awaiting_confirmation", selected
    actual = selected["plan"]["targets"][0]["selection_goal"]["constraints"]
    for name, value in expected_plan.items():
        assert actual[name] == value
    if "budget_yuan" in expected_plan:
        assert selected["plan"]["selected_total_fen"] <= 5000
    if "excluded_ingredients" in expected_plan:
        assert all("鸡蛋" not in row["name"] for row in selected["plan"]["items"])
        assert all(
            row["name"] not in ("番茄炒蛋", "蛋炒饭")
            for row in recommendations[-1]["buildable_dishes"]
        )


def test_reselection_updates_prior_read_constraints_for_the_next_round(
    indexed_client, semantic_provider
):
    def check_next(request):
        assert request["requirements"]["budget_fen"] == 10000
        assert request["requirements"]["excluded_ingredients"] == []
        return {"reads": [{"kind": "recommend"}]}

    semantic_provider([
        {"reads": [{"kind": "recommend"}],
         "constraints": {"budget_yuan": 50, "excluded_ingredients": ["鸡蛋"]}},
        Continuation(lambda request: {"reply": "这些是候选。", "display_refs": []}),
        meal(budget_yuan=50),
        {"constraints": {"budget_yuan": 100, "clear": ["excluded_ingredients"]}},
        check_next,
        Continuation(lambda request: {"reply": "当前候选已按新条件查好。", "display_refs": []}),
    ])
    sid = create_session(indexed_client)
    read = send(indexed_client, sid, "预算50，推荐不要鸡蛋的菜")
    first = send(indexed_client, sid, "帮我配一餐，预算50", read)
    second = send(indexed_client, sid, "预算100，取消鸡蛋忌口", first)
    assert second["status"] == "awaiting_confirmation", second
    send(indexed_client, sid, "再看看有什么菜", second)


def test_append_with_new_exclusion_does_not_bypass_the_existing_plan_guard(
    indexed_client, semantic_provider
):
    from app.core.database import SessionLocal
    from app.models.session import GuideTask

    semantic_provider([
        {**request_new("dish", "宫保鸡丁"),
         "lookups": [{"kind": "dish", "query": "宫保鸡丁"}]},
        request_new("dish", "", relation="append", constraints={"excluded_ingredients": ["花生"]}),
    ])
    sid = create_session(indexed_client)
    first = send(indexed_client, sid, "我要宫保鸡丁")
    assert any("花生" in row["name"] for row in first["plan"]["items"])
    with SessionLocal() as db:
        previous = db.get(GuideTask, first["task_id"])
        plan_before, requirements_before = previous.plan_json, previous.requirements_json
    second = send(indexed_client, sid, "再帮我配一个菜，不吃花生", first)
    assert second["plan_effect"] == "keep"
    assert second["task_id"] == first["task_id"]
    assert any(row["code"] == "UNSUPPORTED_OPERATION" for row in second["action_results"])
    with SessionLocal() as db:
        task = db.get(GuideTask, first["task_id"])
        assert task.plan_json == plan_before
        assert task.requirements_json == requirements_before
    assert indexed_client.get("/api/v1/cart").json()["items"] == []


@pytest.mark.parametrize("displayed", [True, False])
def test_only_an_actual_displayed_ref_can_replace_a_system_selected_meal(displayed):
    selected_goal = Goal(kind="meal_decision", constraints=GoalConstraints(budget_yuan=50))
    choice = Goal(kind="meal_plan", target_name="蛋炒饭")
    decision = decide_turn(
        Understanding(intent="buy", new_goal=choice),
        GateFacts(
            has_active_plan=True, system_selection_goal=selected_goal,
            system_selection_ref="group", displayed_refs=("choice",) if displayed else (),
        ),
        mutations=[MutationView(verb="add", ref="choice", ref_kind="dish",
                                ref_target_id="dish-dan-chao-fan", ref_name="蛋炒饭")],
    )
    if displayed:
        assert decision.relation == "switch"
        assert decision.route == "mutation"
        assert decision.goal.constraints.budget_yuan == 50
    else:
        assert decision.route == "clarify"
        assert decision.reason_code == "UNDECIDED_GOAL_RELATION"


def test_active_goal_focus_resolves_to_single_system_selected_meal_target():
    selected_goal = Goal(
        kind="meal_decision",
        constraints=GoalConstraints(budget_yuan=50, excluded_ingredients=["鸡蛋"]),
    )
    decision = decide_turn(
        Understanding(
            intent="buy",
            goal_relation="switch",
            focus_ref="active-goal-1",
            new_goal=Goal(kind="meal_decision"),
        ),
        GateFacts(
            has_active_plan=True,
            focus_refs=({"ref": "active-goal-1", "kind": "active_goal"},),
            plan_target_refs=("group",),
            system_selection_goal=selected_goal,
            system_selection_ref="group",
        ),
    )

    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.focus_kind == "plan_target"
    assert decision.focus_ref == "group"
    assert decision.relation == "switch"
    assert decision.goal.constraints.budget_yuan == 50
    assert decision.goal.constraints.excluded_ingredients == ["鸡蛋"]


def test_unnamed_system_replace_without_focus_uses_single_selected_meal_target():
    selected_goal = Goal(
        kind="meal_decision",
        constraints=GoalConstraints(budget_yuan=50, excluded_ingredients=["鸡蛋"]),
    )
    decision = decide_turn(
        Understanding(
            intent="buy",
            goal_relation="switch",
            new_goal=Goal(kind="meal_decision"),
        ),
        GateFacts(
            has_active_plan=True,
            plan_target_refs=("group",),
            system_selection_goal=selected_goal,
            system_selection_ref="group",
        ),
    )

    assert decision.route == "mutation"
    assert decision.mutation_action == "prepare"
    assert decision.focus_kind == "plan_target"
    assert decision.focus_ref == "group"
    assert decision.relation == "switch"
    assert decision.goal.constraints.budget_yuan == 50
    assert decision.goal.constraints.excluded_ingredients == ["鸡蛋"]
