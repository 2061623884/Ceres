"""Phase 2a: chat abandonment uses the task lifecycle without losing history."""

from __future__ import annotations

import json
import uuid

from app.core import database as db_module
from app.models.cart import Cart, CartItem, TurnRequestRecord
from app.models.conversation import GuideMessage, PlanSnapshot
from app.models.session import GuideSemanticContext, GuideSession, GuideTask
from support import create_session, stream_turn
from support.semantic_agent import lookup_then_add, pick, recommend_then, reply_only, request_new, topic_rows


def _turn(client, session_id, message, previous=None, *, request_id=None):
    events = stream_turn(
        client,
        session_id,
        message,
        previous,
        request_id=request_id or str(uuid.uuid4()),
    )
    terminal = [
        event for event in events
        if event.get("type") in {"turn.completed", "turn.stopped", "error"}
    ]
    assert len(terminal) == 1, events
    assert terminal[0]["type"] == "turn.completed", json.dumps(terminal[0], ensure_ascii=False)
    return terminal[0]["payload"], events


def _persisted(session_id, task_id=None):
    with db_module.SessionLocal() as db:
        session = db.get(GuideSession, session_id)
        task = db.get(GuideTask, task_id) if task_id else None
        context_row = db.get(GuideSemanticContext, session_id)
        task_count = db.query(GuideTask).filter_by(session_id=session_id).count()
        receipts = (
            db.query(TurnRequestRecord)
            .filter_by(session_id=session_id)
            .order_by(TurnRequestRecord.id)
            .all()
        )
        cart = db.query(Cart).filter_by(owner_id=session.owner_id).one_or_none()
        cart_items = (
            db.query(CartItem).filter_by(cart_id=cart.id).order_by(CartItem.sku_id).all()
            if cart else []
        )
        task_count = db.query(GuideTask).filter_by(session_id=session_id).count()
        snapshots = (
            db.query(PlanSnapshot).filter_by(task_id=task_id).order_by(PlanSnapshot.plan_version).all()
            if task_id else []
        )
        messages = (
            db.query(GuideMessage).filter_by(session_id=session_id).order_by(GuideMessage.sequence).all()
        )
        return {
            "session": {
                "task_id": session.current_task_id,
                "session_version": session.session_version,
                "candidate_dishes": json.loads(session.candidate_dishes_json or "[]"),
                "selected_dish_id": session.selected_dish_id,
            },
            "task_count": task_count,
            "task_count": task_count,
            "task": None if task is None else {
                "status": task.status,
                "current_step": task.current_step,
                "state_version": task.state_version,
                "plan": json.loads(task.plan_json) if task.plan_json else None,
                "plan_json": task.plan_json,
            },
            "context": json.loads(context_row.context_json) if context_row else {},
            "cart": {
                "version": cart.version if cart else None,
                "items": [
                    {"sku_id": row.sku_id, "quantity": row.quantity, "unit_price_fen": row.unit_price_fen}
                    for row in cart_items
                ],
            },
            "receipts": [
                {
                    "request_id": row.request_id,
                    "status": row.status,
                    "response_json": row.response_json,
                }
                for row in receipts
            ],
            "snapshots": [
                {
                    "plan_id": row.plan_id,
                    "plan_version": row.plan_version,
                    "plan": json.loads(row.plan_json),
                    "plan_json": row.plan_json,
                }
                for row in snapshots
            ],
            "messages": [
                {"message_id": row.message_id, "role": row.role, "request_id": row.request_id}
                for row in messages
            ],
        }


def _abandon_row(body):
    return next(
        row for row in body.get("action_results", [])
        if row.get("verb") == "cancel_task"
    )


def test_active_plan_cancel_clears_view_but_keeps_db_history_and_receipt(
    client, semantic_provider
):
    shown = []

    def display_two(request):
        rows = topic_rows(request)[:2]
        shown.extend(rows)
        return {"reply": "推荐两道菜。", "display_refs": [row["ref"] for row in rows]}

    def select_first(request):
        selected_ref = request["displayed_candidates"][0]["ref"]
        row = next(
            row for row in request["candidates"]["dishes"]
            if row["ref"] == selected_ref
        )
        return pick("dish", row)

    fresh_display = []

    def display_after_cancel(request):
        rows = topic_rows(request)[:2]
        fresh_display.extend(rows)
        return {"reply": "重新推荐两道菜。", "display_refs": [row["ref"] for row in rows]}

    fresh_selection = []

    def select_fresh_first(request):
        selected_ref = request["displayed_candidates"][0]["ref"]
        row = next(
            row for row in request["candidates"]["dishes"]
            if row["ref"] == selected_ref
        )
        fresh_selection.append(row)
        return pick("dish", row)

    provider = semantic_provider([
        *recommend_then(None, display_two),
        select_first,
        {"plan_act": "abandon"},
        reply_only("可以重新告诉我想买什么。"),
        *recommend_then(None, display_after_cancel),
        select_fresh_first,
    ])
    session_id = create_session(client)

    recommended, _ = _turn(client, session_id, "推荐几个菜")
    assert recommended["task_id"] is None
    assert recommended["plan"] is None
    assert [row["ref"] for row in shown]

    selected, _ = _turn(client, session_id, "就第一个", recommended)
    assert selected["plan_effect"] == "replace"
    task_id = selected["task_id"]
    original = _persisted(session_id, task_id)
    original_plan = original["task"]["plan"]
    assert original_plan["items"]
    assert original["context"].get("goal_candidate")
    cart_before = client.get("/api/v1/cart").json()
    cancel_request_id = str(uuid.uuid4())

    cancelled, events = _turn(
        client, session_id, "不买了", selected, request_id=cancel_request_id
    )
    assert cancelled["route"] == "cancel_task"
    assert cancelled["plan_effect"] == "clear"
    assert cancelled["plan"] is None
    assert cancelled["pending_clarifications"] == []
    assert cancelled["task_id"] == task_id
    assert _abandon_row(cancelled)["saved"] is True
    assert client.get(f"/api/v1/guide/sessions/{session_id}").json()["plan"] is None

    after_cancel = _persisted(session_id, task_id)
    assert after_cancel["task"]["status"] == "cancelled"
    assert after_cancel["task"]["current_step"] == "cancelled"
    assert after_cancel["task"]["state_version"] == selected["state_version"] + 1
    assert after_cancel["session"]["session_version"] == selected["session_version"] + 1
    assert after_cancel["task"]["plan_json"] == original["task"]["plan_json"]
    assert after_cancel["snapshots"] == original["snapshots"]
    assert after_cancel["session"]["task_id"] == task_id
    assert after_cancel["context"].get("pending_clarifications", []) == []
    assert after_cancel["context"].get("displayed_candidates", []) == []
    assert after_cancel["context"].get("goal_candidate") is None
    assert client.get("/api/v1/cart").json() == cart_before
    cancel_messages = [
        row for row in after_cancel["messages"] if row["request_id"] == cancel_request_id
    ]
    assert [row["role"] for row in cancel_messages] == ["user", "assistant"]
    assert any(event.get("type") == "turn.completed" for event in events)

    calls_after_cancel = len(provider.requests)
    messages_after_cancel = after_cancel["messages"]
    replayed, _ = _turn(
        client, session_id, "不买了", selected, request_id=cancel_request_id
    )
    assert replayed == cancelled
    assert len(provider.requests) == calls_after_cancel
    after_replay = _persisted(session_id, task_id)
    assert after_replay == after_cancel
    assert after_replay["messages"] == messages_after_cancel
    assert client.get("/api/v1/cart").json() == cart_before

    readonly, _ = _turn(client, session_id, "刚才显示的第二个菜是什么？", cancelled)
    readonly_request = provider.requests[-1]
    assert readonly["plan_effect"] == "keep"
    assert readonly["plan"] is None
    assert readonly["state_version"] == cancelled["state_version"]
    assert readonly_request["displayed_candidates"] == []
    assert not (readonly_request.get("current_plan") or {}).get("groups")

    fresh_recommendation, _ = _turn(client, session_id, "重新推荐几个菜", readonly)
    assert fresh_recommendation["task_id"] == task_id
    assert fresh_recommendation["plan"] is None
    assert [row["ref"] for row in fresh_display]
    assert [row["ref"] for row in provider.requests[-1]["displayed_candidates"]] == []

    new_plan, _ = _turn(client, session_id, "就第一个", fresh_recommendation)
    assert new_plan["task_id"] != task_id
    assert fresh_selection[0]["ref"] == fresh_display[0]["ref"]
    assert provider.requests[-1]["displayed_candidates"][0]["ref"] == fresh_selection[0]["ref"]
    assert new_plan["plan"]["targets"][0]["name"] == fresh_selection[0]["name"]
    final = _persisted(session_id, task_id)
    assert final["task"]["plan_json"] == original["task"]["plan_json"]
    assert final["task"]["status"] == "cancelled"
    assert client.get("/api/v1/cart").json() == cart_before
    assert provider.remaining() == 0


def test_active_task_without_a_plan_can_be_cancelled(client, semantic_provider):
    provider = semantic_provider([{"plan_act": "abandon"}])
    session_id = create_session(client)
    initial = client.get(f"/api/v1/guide/sessions/{session_id}").json()
    started_response = client.post(
        f"/api/v1/guide/sessions/{session_id}/tasks",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": initial["session_version"],
            "action": "start_new",
        },
    )
    assert started_response.status_code == 200, started_response.text
    started = started_response.json()
    assert started["task_id"]

    cancelled, _ = _turn(client, session_id, "不买了", started)
    assert cancelled["route"] == "cancel_task"
    assert cancelled["plan_effect"] == "clear"
    assert cancelled["plan"] is None
    saved = _persisted(session_id, started["task_id"])
    assert saved["task"]["status"] == "cancelled"
    assert saved["task"]["current_step"] == "cancelled"
    assert saved["task"]["plan"] is None
    assert saved["task"]["state_version"] == started["state_version"] + 1
    assert client.get(f"/api/v1/guide/sessions/{session_id}").json()["plan"] is None
    assert client.get("/api/v1/cart").json()["items"] == []
    assert provider.remaining() == 0


def test_taskless_pending_question_is_cleared_by_abandonment(client, semantic_provider):
    provider = semantic_provider([
        {"target": {"kind": "meal", "name": "", "intent": "buy"}},
        {"plan_act": "abandon"},
    ])
    session_id = create_session(client)
    asked, _ = _turn(client, session_id, "今晚想做顿简单的饭")
    assert asked["task_id"] is None
    assert asked["pending_clarifications"]
    raw_before = _persisted(session_id)
    assert raw_before["context"].get("pending_clarifications")

    cancelled, _ = _turn(client, session_id, "不买了", asked)
    assert cancelled["task_id"] is None
    assert cancelled["pending_clarifications"] == []
    after = _persisted(session_id)
    assert after["session"]["task_id"] is None
    assert after["task_count"] == 0
    assert after["session"]["session_version"] == raw_before["session"]["session_version"] + 1
    assert after["context"].get("pending_clarifications", []) == []
    assert client.get(f"/api/v1/guide/sessions/{session_id}").json()["pending_clarifications"] == []
    assert client.get("/api/v1/cart").json()["items"] == []
    assert provider.remaining() == 0


def test_abandon_clears_a_fresh_pending_question_after_old_task_was_cancelled(
    client, semantic_provider, monkeypatch
):
    provider = semantic_provider([*lookup_then_add("dish", "番茄炒蛋")])
    session_id = create_session(client)
    first, _ = _turn(client, session_id, "我要番茄炒蛋")
    old_task_id = first["task_id"]
    old_plan = _persisted(session_id, old_task_id)["task"]["plan_json"]
    cart_before = client.get("/api/v1/cart").json()

    provider = semantic_provider([{"plan_act": "abandon"}])
    cancelled, _ = _turn(client, session_id, "不买了", first)
    assert cancelled["plan_effect"] == "clear"
    assert cancelled["task_id"] == old_task_id
    assert _persisted(session_id, old_task_id)["task"]["status"] == "cancelled"

    provider = semantic_provider([request_new("dish", "")])
    asked, _ = _turn(client, session_id, "今晚想吃顿简单的饭", cancelled)
    assert asked["plan"] is None
    assert asked["pending_clarifications"]
    asked_state = _persisted(session_id, old_task_id)
    assert asked_state["task_count"] == 1
    assert asked_state["task"]["status"] == "cancelled"
    assert asked_state["task"]["plan_json"] == old_plan
    assert asked_state["context"].get("task_status") == "cancelled"
    assert asked_state["context"].get("pending_clarifications")
    assert client.get("/api/v1/cart").json() == cart_before

    from app.agent.graph.nodes import understand as understand_node

    decisions = []
    original_evaluate_gate = understand_node.evaluate_gate

    def record_decision(snapshot, proposal, candidates, *, plan_selection, explicit_confirmation):
        decision = original_evaluate_gate(snapshot, proposal, candidates,
                                         plan_selection=plan_selection, explicit_confirmation=explicit_confirmation)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(understand_node, "evaluate_gate", record_decision)
    provider = semantic_provider([{"plan_act": "abandon"}])
    cleared, _ = _turn(client, session_id, "算了，不买了", asked)
    after = _persisted(session_id, old_task_id)
    assert cleared["plan_effect"] == "clear", (
        f"input={provider.requests[-1]!r}\nresponse={cleared!r}\n"
        f"db_before={asked_state!r}\ndb_after={after!r}"
    )
    assert decisions[-1].reason_code == "TASK_CONTEXT_CLEAR_REQUESTED"
    assert decisions[-1].mutation_action == "cancel_task"
    assert cleared["route"] == "cancel_task"
    assert cleared["session_version"] == asked["session_version"] + 1
    assert cleared["state_version"] == asked["state_version"]
    assert cleared["pending_clarifications"] == []
    assert after["task_count"] == 1
    assert after["session"]["session_version"] == asked_state["session"]["session_version"] + 1
    assert after["task"]["status"] == "cancelled"
    assert after["task"]["plan_json"] == old_plan
    assert after["context"].get("pending_clarifications", []) == []
    assert after["context"].get("task_status") == "cancelled"
    assert client.get("/api/v1/cart").json() == cart_before
    assert provider.remaining() == 0


def test_abandon_without_a_task_answers_honestly_without_mutating(client, semantic_provider):
    semantic_provider([{"plan_act": "abandon", "reply": "现在还没有清单，想买什么可以告诉我。"}])
    session_id = create_session(client)
    before = client.get("/api/v1/cart").json()

    body, _ = _turn(client, session_id, "不买了")

    assert body["route"] == "chat"
    assert body["task_id"] is None
    assert body["state_version"] == 0
    assert body["plan"] is None
    assert "没有清单" in body["message"]
    assert not any(row.get("saved") for row in body["action_results"])
    assert client.get(f"/api/v1/guide/sessions/{session_id}").json()["task_id"] is None
    assert client.get("/api/v1/cart").json() == before


def test_questions_take_precedence_over_abandonment(client, semantic_provider):
    semantic_provider([
        *lookup_then_add("dish", "番茄炒蛋"),
        {
            "plan_act": "abandon",
            "questions": [{"slot": "cancel_scope", "question": "你想先澄清哪件事？", "options": []}],
        },
    ])
    session_id = create_session(client)
    first, _ = _turn(client, session_id, "我要番茄炒蛋")
    original_plan = first["plan"]

    body, _ = _turn(client, session_id, "不买了，你先问我一个问题", first)

    assert body["route"] == "clarify"
    assert body["plan_effect"] == "keep"
    assert body["pending_clarifications"]
    assert body["task_id"] == first["task_id"]
    assert body["state_version"] == first["state_version"]
    saved = _persisted(session_id, first["task_id"])
    assert saved["task"]["status"] == "active"
    assert saved["task"]["plan"] == original_plan
    assert client.get(f"/api/v1/cart").json()["items"] == []


def test_mixed_abandon_and_group_edit_clarifies_without_cancelling(client, semantic_provider):
    def abandon_and_remove_group(request):
        (group,) = request["current_plan"]["groups"]
        return {
            "plan_act": "abandon",
            "focus": {"ref": group["ref"], "name": group["name"]},
            "edit": {"op": "remove"},
        }

    semantic_provider([
        *lookup_then_add("dish", "番茄炒蛋"),
        abandon_and_remove_group,
    ])
    session_id = create_session(client)
    first, _ = _turn(client, session_id, "我要番茄炒蛋")

    body, _ = _turn(client, session_id, "不买了，然后删掉这个菜", first)

    assert body["route"] == "clarify"
    assert "mixed_goal_changes" in body["missing_slots"]
    assert body["plan_effect"] == "keep"
    assert body["state_version"] == first["state_version"]
    saved = _persisted(session_id, first["task_id"])
    assert saved["task"]["status"] == "active"
    assert saved["task"]["plan"] == first["plan"]
    assert len(saved["task"]["plan"]["targets"]) == 1


def test_abandon_plus_named_replace_switches_instead_of_cancelling(client, semantic_provider):
    replacement = lookup_then_add("dish", "宫保鸡丁", relation="switch")[0]

    def abandon_and_replace(request):
        return {**replacement(request), "plan_act": "abandon"}

    semantic_provider([
        *lookup_then_add("dish", "番茄炒蛋"),
        abandon_and_replace,
    ])
    session_id = create_session(client)
    first, _ = _turn(client, session_id, "我要番茄炒蛋")
    old = _persisted(session_id, first["task_id"])
    cart_before = client.get("/api/v1/cart").json()

    replaced, _ = _turn(client, session_id, "不买了，换成宫保鸡丁", first)

    assert replaced["plan_effect"] == "replace"
    assert replaced["task_id"] != first["task_id"]
    assert replaced["plan"]["targets"][0]["target_id"] != first["plan"]["targets"][0]["target_id"]
    assert "宫保鸡丁" in replaced["plan"]["targets"][0]["name"]
    old_after = _persisted(session_id, first["task_id"])
    assert old_after["task"]["status"] == "superseded"
    assert old_after["task"]["plan_json"] == old["task"]["plan_json"]
    assert client.get("/api/v1/cart").json() == cart_before


def test_completed_multigroup_plan_rejects_abandon_and_keeps_all_groups(client, semantic_provider):
    semantic_provider([
        *lookup_then_add("dish", "番茄炒蛋"),
        *lookup_then_add("product", "鸡蛋", relation="append"),
        {"plan_act": "abandon"},
    ])
    session_id = create_session(client)
    first, _ = _turn(client, session_id, "我要番茄炒蛋")
    second, _ = _turn(client, session_id, "再买鸡蛋", first)
    assert len(second["plan"]["targets"]) == 2
    groups_before = {row["group_id"] for row in second["plan"]["targets"]}
    confirm_items = [
        {"sku_id": row["sku_id"], "quantity": row["quantity"]}
        for row in second["plan"]["items"]
        if row.get("selected", row.get("role", "required") != "pantry")
    ]
    assert confirm_items
    confirmed_response = client.post(
        f"/api/v1/guide/tasks/{second['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": second["plan"]["plan_id"],
            "plan_version": second["plan"]["plan_version"],
            "expected_state_version": second["state_version"],
            "expected_session_version": second["session_version"],
            "selected_items": confirm_items,
        },
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["status"] == "completed"
    cart_after_confirm = client.get("/api/v1/cart").json()

    refused, _ = _turn(client, session_id, "不买了", confirmed)

    assert refused["plan_effect"] == "keep"
    assert any(row.get("code") == "TASK_NOT_WRITABLE" for row in refused["action_results"])
    assert "购物车" in refused["message"]
    saved = _persisted(session_id, second["task_id"])
    assert saved["task"]["status"] == "completed"
    assert saved["task"]["current_step"] == "completed"
    assert {row["group_id"] for row in saved["task"]["plan"]["targets"]} == groups_before
    view = client.get(f"/api/v1/guide/sessions/{session_id}").json()
    assert view["plan_read_only"] is True
    assert view["plan"]["plan_id"] == second["plan"]["plan_id"]
    assert client.get("/api/v1/cart").json() == cart_after_confirm
