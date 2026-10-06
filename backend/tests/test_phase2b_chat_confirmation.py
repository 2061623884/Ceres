"""Phase 2b: explicit chat confirmation uses the current server snapshot."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core import database as db_module
from app.models.cart import Cart, CartItem, CartOperation, TurnRequestRecord
from app.models.conversation import GuideMessage
from app.models.session import GuideSemanticContext, GuideSession, GuideTask
from app.models.store import DeliveryQuote, Offer
from support import create_session, parse_sse_events, stream_turn
from support.semantic_agent import (
    lookup_then_add,
    plan_item_ref,
    recommend_then,
    request_amend,
    request_new,
    reply_only,
    topic_rows,
)
from test_semantic_phase1_purchase import indexed_client

TOMATO = "番茄炒蛋"
_ABSENT = object()


def _events_with_selection(
    client,
    session_id,
    message,
    previous=None,
    *,
    request_id=None,
    plan_selection=_ABSENT,
):
    previous = previous or {}
    body = {
        "request_id": request_id or str(uuid.uuid4()),
        "message": message,
        "expected_task_id": previous.get("task_id"),
        "expected_state_version": previous.get("state_version", 0),
        "expected_session_version": previous.get("session_version"),
    }
    if plan_selection is not _ABSENT:
        body["plan_selection"] = plan_selection
    with client.stream(
        "POST",
        f"/api/v1/guide/sessions/{session_id}/turns/stream",
        json=body,
    ) as response:
        response.raise_for_status()
        return parse_sse_events("".join(response.iter_text()))


def _terminal(events):
    terminal = [
        row for row in events
        if row.get("type") in {"turn.completed", "turn.stopped", "error"}
    ]
    assert len(terminal) == 1, events
    return terminal[0]


def _turn(client, session_id, message, previous=None, *, request_id=None, plan_selection=_ABSENT):
    if plan_selection is _ABSENT:
        events = stream_turn(client, session_id, message, previous, request_id=request_id)
    else:
        events = _events_with_selection(
            client, session_id, message, previous,
            request_id=request_id, plan_selection=plan_selection,
        )
    return _terminal(events), events


def _complete(client, session_id, message, previous=None, **kwargs):
    terminal, events = _turn(client, session_id, message, previous, **kwargs)
    assert terminal["type"] == "turn.completed", terminal
    return terminal["payload"], events


def _error(client, session_id, message, previous=None, **kwargs):
    terminal, events = _turn(client, session_id, message, previous, **kwargs)
    assert terminal["type"] == "error", terminal
    return terminal["payload"], events


def _new_plan(client, semantic_provider):
    session_id = create_session(client)
    semantic_provider([*lookup_then_add("dish", TOMATO)])
    first, _ = _complete(client, session_id, f"我要{TOMATO}")
    assert first["plan"] and first["plan"]["can_confirm"] is True
    return session_id, first


def _selected_outstanding(plan):
    return {
        row["sku_id"]: int(row.get("remaining_quantity", row["quantity"]))
        for row in plan["items"]
        if row.get("selected", True)
        and int(row.get("remaining_quantity", row["quantity"])) > 0
    }


def _persisted(session_id, task_id=None):
    with db_module.SessionLocal() as db:
        session = db.get(GuideSession, session_id)
        task = db.get(GuideTask, task_id) if task_id else None
        context = db.get(GuideSemanticContext, session_id)
        cart = db.query(Cart).filter_by(owner_id=session.owner_id).one_or_none()
        cart_items = (
            db.query(CartItem).filter_by(cart_id=cart.id).order_by(CartItem.sku_id).all()
            if cart else []
        )
        receipts = (
            db.query(TurnRequestRecord).filter_by(session_id=session_id)
            .order_by(TurnRequestRecord.id).all()
        )
        messages = (
            db.query(GuideMessage).filter_by(session_id=session_id)
            .order_by(GuideMessage.sequence).all()
        )
        operations = (
            db.query(CartOperation).filter_by(owner_id=session.owner_id)
            .order_by(CartOperation.created_at, CartOperation.operation_id).all()
        )
        return {
            "session": {
                "task_id": session.current_task_id,
                "session_version": session.session_version,
            },
            "task": None if task is None else {
                "status": task.status,
                "current_step": task.current_step,
                "state_version": task.state_version,
                "plan_json": task.plan_json,
                "requirements_json": task.requirements_json,
                "user_confirmed": task.user_confirmed,
                "confirmation_id": task.confirmation_id,
                "cart_result_json": task.cart_result_json,
            },
            "context": json.loads(context.context_json) if context else {},
            "cart": {
                "version": cart.version if cart else None,
                "items": [
                    {"sku_id": row.sku_id, "quantity": row.quantity, "unit_price_fen": row.unit_price_fen}
                    for row in cart_items
                ],
            },
            "cart_operations": [
                {
                    "task_id": row.task_id,
                    "idempotency_key": row.idempotency_key,
                    "request_digest": row.request_digest,
                    "status": row.status,
                    "result_json": row.result_json,
                }
                for row in operations
            ],
            "receipts": [
                {
                    "request_id": row.request_id,
                    "request_digest": row.request_digest,
                    "status": row.status,
                    "response_json": row.response_json,
                }
                for row in receipts
            ],
            "messages": [
                {
                    "role": row.role,
                    "kind": row.kind,
                    "content": row.content,
                    "request_id": row.request_id,
                }
                for row in messages
            ],
        }


def _plan_selection(plan, selected=None):
    selected = selected if selected is not None else _selected_outstanding(plan)
    return {
        "plan_id": plan["plan_id"],
        "plan_version": plan["plan_version"],
        "selected_items": [
            {"sku_id": sku_id, "quantity": quantity}
            for sku_id, quantity in selected.items()
        ],
    }


def _cart_quantities(client):
    return {
        row["sku_id"]: int(row["quantity"])
        for row in client.get("/api/v1/cart").json()["items"]
    }


def _revise_once(client, session_id, current, *, sequence=1):
    plan = current["plan"]
    first = plan["items"][0]
    rows = [
        {
            "sku_id": row["sku_id"],
            "quantity": int(row["quantity"]) + (1 if row["sku_id"] == first["sku_id"] else 0),
            "selected": row.get("selected", row.get("role") != "pantry"),
        }
        for row in plan["items"]
    ]
    response = client.post(
        f"/api/v1/guide/tasks/{current['task_id']}/plan-revisions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_session_version": current["session_version"],
            "expected_state_version": current["state_version"],
            "base_plan_id": plan["plan_id"],
            "base_plan_version": plan["plan_version"],
            "client_edit_sequence": sequence,
            "items": rows,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ack_is_read_only_then_chat_confirm_buys_only_current_outstanding_rows_and_replays(
    client, semantic_provider
):
    session_id, first = _new_plan(client, semantic_provider)
    task_id = first["task_id"]
    before_ack = _persisted(session_id, task_id)
    assert _cart_quantities(client) == {}

    ack_provider = semantic_provider([reply_only("好的，清单还在。")])
    ack, _ = _complete(client, session_id, "好的", first)
    assert ack["route"] == "chat"
    assert ack["plan_effect"] == "keep"
    assert ack["state_version"] == first["state_version"]
    after_ack = _persisted(session_id, task_id)
    assert after_ack["session"] == before_ack["session"]
    assert after_ack["task"] == before_ack["task"]
    assert after_ack["context"] == before_ack["context"]
    assert after_ack["cart"] == before_ack["cart"]
    assert after_ack["cart_operations"] == before_ack["cart_operations"]
    assert _cart_quantities(client) == {}
    assert ack_provider.remaining() == 0

    row = next(row for row in first["plan"]["items"] if row.get("selected", True))
    add_response = client.post(
        f"/api/v1/guide/tasks/{task_id}/items/{row['sku_id']}/add",
        json={
            "request_id": str(uuid.uuid4()),
            "quantity": row["quantity"],
            "expected_state_version": first["state_version"],
            "expected_session_version": first["session_version"],
        },
    )
    assert add_response.status_code == 200, add_response.text
    added = add_response.json()
    latest = {
        **first,
        "state_version": added["state_version"],
        "session_version": added["session_version"],
    }
    stored_before_confirm = _persisted(session_id, task_id)
    current_plan = json.loads(stored_before_confirm["task"]["plan_json"])
    expected = _selected_outstanding(current_plan)
    assert expected
    cart_before = _cart_quantities(client)
    expected_cart = dict(cart_before)
    for sku_id, quantity in expected.items():
        expected_cart[sku_id] = expected_cart.get(sku_id, 0) + quantity

    confirm_provider = semantic_provider([{
        "plan_act": "confirm",
        "reply": "MODEL_MUST_NOT_CLAIM_PURCHASE_91A7",
    }])
    request_id = str(uuid.uuid4())
    confirmed, confirm_events = _complete(
        client, session_id, "加入购物车", latest, request_id=request_id
    )
    assert confirmed["route"] == "confirm_plan", confirmed
    assert confirmed["plan_effect"] == "keep"
    assert confirmed["plan"] is None
    assert "plan.ready" not in [event.get("type") for event in confirm_events]
    assert _cart_quantities(client) == expected_cart
    assert confirmed["state_version"] == latest["state_version"] + 1
    assert confirmed["session_version"] == latest["session_version"] + 1
    actual_items = [
        {"sku_id": sku_id, "quantity": quantity}
        for sku_id, quantity in sorted(expected.items())
    ]
    action = next(
        row for row in confirmed["action_results"]
        if row.get("verb") == "confirm_plan"
    )
    assert action["status"] == "committed"
    assert sorted(action["items_added"], key=lambda row: row["sku_id"]) == actual_items
    assert "MODEL_MUST_NOT_CLAIM_PURCHASE_91A7" not in confirmed["message"]
    assert "plan_selection" not in json.dumps(confirm_provider.requests, ensure_ascii=False)
    assert confirm_provider.remaining() == 0

    after = _persisted(session_id, task_id)
    assert after["task"]["status"] == "completed"
    assert after["task"]["current_step"] == "completed"
    assert after["task"]["state_version"] == latest["state_version"] + 1
    assert after["session"]["session_version"] == latest["session_version"] + 1
    new_cart_operations = [
        row for row in after["cart_operations"]
        if row not in stored_before_confirm["cart_operations"]
    ]
    assert len(new_cart_operations) == 1
    assert new_cart_operations[0]["status"] == "completed"
    confirm_messages = [row for row in after["messages"] if row["request_id"] == request_id]
    assert [row["role"] for row in confirm_messages] == ["user", "assistant"]
    receipt = next(row for row in after["receipts"] if row["request_id"] == request_id)
    assert receipt["status"] == "completed"
    assert json.loads(receipt["response_json"]) == confirmed
    assert "plan_selection" not in json.dumps(after["context"], ensure_ascii=False)

    calls_before_replay = len(confirm_provider.requests)
    replayed, _ = _complete(
        client, session_id, "加入购物车", latest, request_id=request_id
    )
    assert replayed == confirmed
    assert len(confirm_provider.requests) == calls_before_replay
    assert _persisted(session_id, task_id) == after
    assert _cart_quantities(client) == expected_cart

    changed_packet, _ = _error(
        client,
        session_id,
        "加入购物车",
        latest,
        request_id=request_id,
        plan_selection=_plan_selection(current_plan, {}),
    )
    assert changed_packet["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(confirm_provider.requests) == calls_before_replay
    assert _persisted(session_id, task_id) == after
    assert _cart_quantities(client) == expected_cart


def test_model_cannot_turn_a_bare_ack_into_chat_confirmation(indexed_client, semantic_provider):
    session_id, first = _new_plan(indexed_client, semantic_provider)
    task_id = first["task_id"]
    before = _persisted(session_id, task_id)
    assert _cart_quantities(indexed_client) == {}

    provider = semantic_provider([{"plan_act": "confirm"}])
    ack, _ = _complete(indexed_client, session_id, "好的", first)

    assert ack["message"] == "如果要加入购物车，请明确说“确认加购”。"
    assert ack["plan_effect"] == "keep"
    assert ack["state_version"] == first["state_version"]
    after = _persisted(session_id, task_id)
    assert after["session"] == before["session"]
    assert after["task"] == before["task"]
    assert after["context"] == before["context"]
    assert after["cart"] == before["cart"]
    assert after["cart_operations"] == before["cart_operations"]
    assert _cart_quantities(indexed_client) == {}
    assert provider.remaining() == 0

    confirm_provider = semantic_provider([{"plan_act": "confirm"}])
    confirmed, _ = _complete(indexed_client, session_id, "确认加入购物车", ack)
    assert confirmed["route"] == "confirm_plan"
    assert confirmed["committed"] is True
    assert _cart_quantities(indexed_client) == _selected_outstanding(first["plan"])
    assert confirm_provider.remaining() == 0


def test_matching_runtime_selection_is_not_given_to_model_or_saved_as_context(
    client, semantic_provider
):
    session_id, first = _new_plan(client, semantic_provider)
    provider = semantic_provider([{"plan_act": "confirm"}])
    selection = _plan_selection(first["plan"])
    request_id = str(uuid.uuid4())
    confirmed, _ = _complete(
        client, session_id, "加入购物车", first,
        request_id=request_id,
        plan_selection=selection,
    )
    assert confirmed["route"] == "confirm_plan"
    assert _cart_quantities(client) == _selected_outstanding(first["plan"])
    assert "plan_selection" not in json.dumps(provider.requests, ensure_ascii=False)
    stored = _persisted(session_id, first["task_id"])
    assert "plan_selection" not in json.dumps(stored["context"], ensure_ascii=False)
    calls = len(provider.requests)
    replayed, _ = _complete(
        client, session_id, "加入购物车", first,
        request_id=request_id,
        plan_selection=selection,
    )
    assert replayed == confirmed
    assert len(provider.requests) == calls
    assert _persisted(session_id, first["task_id"]) == stored
    assert provider.remaining() == 0


@pytest.mark.parametrize("selected", [[], "subset"])
def test_explicit_nonmatching_selection_is_rejected_without_partial_cart_write(
    client, semantic_provider, selected
):
    session_id, first = _new_plan(client, semantic_provider)
    current = _persisted(session_id, first["task_id"])
    plan = json.loads(current["task"]["plan_json"])
    selected_map = _selected_outstanding(plan)
    assert len(selected_map) > 1
    if selected == "subset":
        selected_map.pop(next(iter(selected_map)))
    else:
        selected_map = {}
    selection = _plan_selection(plan, selected_map)
    before_cart = _cart_quantities(client)
    before = _persisted(session_id, first["task_id"])
    provider = semantic_provider([{"plan_act": "confirm"}])

    error, _ = _error(
        client, session_id, "加入购物车", first, plan_selection=selection
    )
    assert error["code"] == "CONSTRAINT_UNSATISFIED"
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["status"] == "active"
    assert after["task"]["current_step"] == "awaiting_confirmation"
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert after["context"] == before["context"]
    assert after["messages"] == before["messages"]
    assert _cart_quantities(client) == before_cart == {}
    assert provider.remaining() == 0


@pytest.mark.parametrize("mismatch", ["plan_id", "plan_version"])
def test_stale_runtime_selection_is_refused_without_using_the_current_plan(
    client, semantic_provider, mismatch
):
    session_id, first = _new_plan(client, semantic_provider)
    selection = _plan_selection(first["plan"])
    if mismatch == "plan_id":
        selection["plan_id"] = "old-plan"
    else:
        selection["plan_version"] += 1
    before = _persisted(session_id, first["task_id"])
    provider = semantic_provider([{"plan_act": "confirm"}])

    terminal, _ = _turn(
        client, session_id, "加入购物车", first, plan_selection=selection
    )
    assert terminal["type"] == "turn.completed", terminal
    refused = terminal["payload"]
    assert refused["route"] == "answer"
    assert not any(row.get("verb") == "confirm_plan" and row.get("saved") for row in refused["action_results"])
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert _cart_quantities(client) == {}
    assert "plan_selection" not in json.dumps(provider.requests, ensure_ascii=False)


def test_questions_block_a_chat_confirmation(client, semantic_provider):
    session_id, first = _new_plan(client, semantic_provider)
    before = _persisted(session_id, first["task_id"])
    provider = semantic_provider([{
        "plan_act": "confirm",
        "questions": [{"slot": "confirm_scope", "question": "需要确认这份清单吗？", "options": []}],
    }])

    result, _ = _complete(client, session_id, "加入购物车", first)

    assert result["route"] == "clarify"
    assert result["pending_clarifications"]
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["status"] == "active"
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert _cart_quantities(client) == {}
    assert provider.remaining() == 0


def test_edit_and_confirm_turn_only_revises_the_plan(client, semantic_provider):
    session_id, first = _new_plan(client, semantic_provider)

    def edit_and_confirm(request):
        item = request["current_plan"]["items"][0]
        return {
            **request_amend(
                focus=plan_item_ref(request, item["sku_id"]),
                name=item["name"],
                op="adjust_quantity",
                quantity=int(item["quantity"]) + 1,
            ),
            "plan_act": "confirm",
        }

    provider = semantic_provider([edit_and_confirm])
    before = _persisted(session_id, first["task_id"])
    revised, _ = _complete(client, session_id, "把这一项多加一份，同时加入购物车", first)

    assert revised["route"] == "apply_mutation", revised
    assert revised["plan_effect"] == "replace"
    assert revised["plan"]["plan_version"] == first["plan"]["plan_version"] + 1
    assert revised["state_version"] == first["state_version"] + 1
    assert not any(row.get("verb") == "confirm_plan" for row in revised["action_results"])
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["status"] == "active"
    assert after["task"]["plan_json"] != before["task"]["plan_json"]
    assert _cart_quantities(client) == {}
    assert provider.remaining() == 0


def test_buying_a_displayed_ref_and_confirm_in_one_turn_only_builds_the_plan(
    client, semantic_provider
):
    session_id = create_session(client)

    def display_first(request):
        rows = topic_rows(request)[:2]
        assert rows
        return {"reply": "这几道菜可以考虑。", "display_refs": [row["ref"] for row in rows]}

    provider = semantic_provider([*recommend_then(None, display_first)])
    shown, _ = _complete(client, session_id, "有什么菜推荐？")
    assert shown["plan"] is None
    assert shown["task_id"] is None

    def buy_first_displayed(request):
        row = request["displayed_candidates"][0]
        return {
            **request_new("dish", row["name"], ref=row["ref"]),
            "plan_act": "confirm",
        }

    provider = semantic_provider([buy_first_displayed])
    created, _ = _complete(client, session_id, "把第一个加入购物车", shown)
    assert created["plan_effect"] == "replace"
    assert created["route"] == "prepare"
    assert created["plan"] and created["plan"]["items"]
    assert not any(row.get("verb") == "confirm_plan" for row in created["action_results"])
    assert _cart_quantities(client) == {}

    provider = semantic_provider([{"plan_act": "confirm"}])
    confirmed, _ = _complete(client, session_id, "加入购物车", created)
    assert confirmed["route"] == "confirm_plan"
    assert _cart_quantities(client)
    assert provider.remaining() == 0


def test_confirm_without_a_plan_answers_honestly_and_does_not_create_a_task(
    client, semantic_provider
):
    session_id = create_session(client)
    provider = semantic_provider([{"plan_act": "confirm"}])
    before = _persisted(session_id)

    answer, _ = _complete(client, session_id, "加入购物车")

    assert answer["route"] == "answer"
    assert "清单" in answer["message"]
    after = _persisted(session_id)
    assert after["task"] is None
    assert after["session"]["task_id"] == before["session"]["task_id"] is None
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert _cart_quantities(client) == {}
    assert provider.remaining() == 0


def test_a_nonconfirmable_active_plan_is_not_sent_to_the_confirmation_core(
    client, semantic_provider, monkeypatch
):
    from app.services.confirmation_service import ConfirmationService

    session_id, first = _new_plan(client, semantic_provider)
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, first["task_id"])
        plan = json.loads(task.plan_json)
        plan["can_confirm"] = False
        task.plan_json = json.dumps(plan)
        db.commit()
    before = _persisted(session_id, first["task_id"])
    calls = []
    original = ConfirmationService.confirm_core

    def counted(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ConfirmationService, "confirm_core", counted)
    provider = semantic_provider([{"plan_act": "confirm"}])
    answer, _ = _complete(client, session_id, "加入购物车", first)

    assert answer["route"] == "answer"
    assert calls == []
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["status"] == "active"
    assert after["task"]["current_step"] == "awaiting_confirmation"
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert _cart_quantities(client) == {}
    assert provider.remaining() == 0


def test_button_confirmation_then_chat_confirmation_does_not_add_twice(
    client, semantic_provider, monkeypatch
):
    from app.services.confirmation_service import ConfirmationService

    session_id, first = _new_plan(client, semantic_provider)
    selection = _selected_outstanding(first["plan"])
    assert selection
    button = client.post(
        f"/api/v1/guide/tasks/{first['task_id']}/confirm",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "plan_id": first["plan"]["plan_id"],
            "plan_version": first["plan"]["plan_version"],
            "expected_state_version": first["state_version"],
            "expected_session_version": first["session_version"],
            "selected_items": [
                {"sku_id": sku_id, "quantity": quantity}
                for sku_id, quantity in selection.items()
            ],
        },
    )
    assert button.status_code == 200, button.text
    completed = button.json()
    after_button = _persisted(session_id, first["task_id"])
    before_cart = _cart_quantities(client)
    calls = []
    original = ConfirmationService.confirm_core

    def counted(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ConfirmationService, "confirm_core", counted)
    provider = semantic_provider([{"plan_act": "confirm"}])
    previous = {
        **first,
        "state_version": completed["state_version"],
        "session_version": completed["session_version"],
    }
    answer, _ = _complete(client, session_id, "加入购物车", previous)

    assert answer["route"] == "answer"
    assert calls == []
    assert _cart_quantities(client) == before_cart
    after_chat = _persisted(session_id, first["task_id"])
    assert after_chat["task"]["state_version"] == after_button["task"]["state_version"]
    assert after_chat["session"]["session_version"] == after_button["session"]["session_version"]
    assert after_chat["task"]["plan_json"] == after_button["task"]["plan_json"]
    assert provider.remaining() == 0


def test_stale_client_task_version_is_rejected_before_chat_confirmation(client, semantic_provider):
    session_id, first = _new_plan(client, semantic_provider)
    latest = _revise_once(client, session_id, first)
    previous = {
        **first,
        "state_version": first["state_version"],
        "session_version": latest["session_version"],
    }
    provider = semantic_provider([{"plan_act": "confirm"}])
    before = _persisted(session_id, first["task_id"])

    error, _ = _error(client, session_id, "加入购物车", previous)

    assert error["code"] == "STALE_STATE"
    after = _persisted(session_id, first["task_id"])
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert _cart_quantities(client) == {}
    assert provider.requests == []


def test_a_plan_revision_while_confirmation_model_runs_is_not_overwritten(
    client, semantic_provider
):
    session_id, first = _new_plan(client, semantic_provider)
    revision_response = []

    def revise_then_confirm(_request):
        revision_response.append(_revise_once(client, session_id, first))
        return {"plan_act": "confirm"}

    provider = semantic_provider([revise_then_confirm])
    before_cart = _cart_quantities(client)
    error, _ = _error(client, session_id, "加入购物车", first)

    assert error["code"] == "STALE_STATE"
    assert len(revision_response) == 1
    current = _persisted(session_id, first["task_id"])
    assert current["task"]["status"] == "active"
    assert current["task"]["state_version"] == revision_response[0]["state_version"]
    assert current["session"]["session_version"] == revision_response[0]["session_version"]
    assert json.loads(current["task"]["plan_json"])["plan_version"] == first["plan"]["plan_version"] + 1
    assert _cart_quantities(client) == before_cart == {}
    assert provider.remaining() == 0


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("price", "PRICE_CHANGED"),
        ("stock", "PRODUCT_UNAVAILABLE"),
        ("expired", "PLAN_EXPIRED"),
        ("budget", "CONSTRAINT_UNSATISFIED"),
        ("delivery", "CONSTRAINT_UNSATISFIED"),
    ],
)
def test_chat_confirmation_keeps_existing_supply_and_budget_guards(
    client, semantic_provider, mutation, expected_code
):
    session_id, first = _new_plan(client, semantic_provider)
    task_id = first["task_id"]
    first_item = next(row for row in first["plan"]["items"] if row.get("selected", True))
    with db_module.SessionLocal() as db:
        task = db.get(GuideTask, task_id)
        if mutation == "expired":
            plan = json.loads(task.plan_json)
            plan["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            task.plan_json = json.dumps(plan)
        elif mutation == "budget":
            requirements = json.loads(task.requirements_json)
            requirements["budget_fen"] = 1
            task.requirements_json = json.dumps(requirements)
        elif mutation == "delivery":
            quote = db.query(DeliveryQuote).filter_by(
                store_id="store-demo-01", zone_id="zone-default"
            ).one()
            quote.reachable = False
        else:
            offer = db.query(Offer).filter_by(
                store_id="store-demo-01", sku_id=first_item["sku_id"]
            ).one()
            if mutation == "price":
                offer.price_fen += 1
            else:
                offer.sellable = False
        db.commit()

    before = _persisted(session_id, task_id)
    before_cart = _cart_quantities(client)
    provider = semantic_provider([{"plan_act": "confirm"}])
    error, _ = _error(client, session_id, "加入购物车", first)

    assert error["code"] == expected_code
    after = _persisted(session_id, task_id)
    assert after["task"]["status"] == "active"
    assert after["task"]["current_step"] == "awaiting_confirmation"
    assert after["task"]["state_version"] == before["task"]["state_version"]
    assert after["session"]["session_version"] == before["session"]["session_version"]
    assert after["task"]["plan_json"] == before["task"]["plan_json"]
    assert after["context"] == before["context"]
    assert _cart_quantities(client) == before_cart == {}
    assert provider.remaining() == 0
