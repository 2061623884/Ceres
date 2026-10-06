"""Cancellation effects share the Graph transaction and request receipt."""

from __future__ import annotations

import json
import uuid

import pytest

from app.core import database as db_module
from app.core.errors import AppError
from app.models.cart import Cart, CartItem, TurnRequestRecord
from app.models.conversation import GuideMessage
from app.models.session import GuideSemanticContext, GuideSession, GuideTask
from support import create_session, stream_turn
from support.semantic_agent import lookup_then_add


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
    return terminal[0], events


def _persisted(session_id, task_id, request_id):
    with db_module.SessionLocal() as db:
        session = db.get(GuideSession, session_id)
        task = db.get(GuideTask, task_id)
        context = db.get(GuideSemanticContext, session_id)
        cart = db.query(Cart).filter_by(owner_id=session.owner_id).one_or_none()
        cart_items = (
            db.query(CartItem).filter_by(cart_id=cart.id).order_by(CartItem.sku_id).all()
            if cart else []
        )
        receipt = (
            db.query(TurnRequestRecord)
            .filter_by(session_id=session_id, request_id=request_id)
            .one_or_none()
        )
        messages = db.query(GuideMessage).filter_by(session_id=session_id).all()
        return {
            "session_version": session.session_version,
            "task_id": session.current_task_id,
            "task_status": task.status,
            "current_step": task.current_step,
            "state_version": task.state_version,
            "plan_json": task.plan_json,
            "context": json.loads(context.context_json) if context else {},
            "cart": {
                "version": cart.version if cart else None,
                "items": [
                    {"sku_id": row.sku_id, "quantity": row.quantity, "unit_price_fen": row.unit_price_fen}
                    for row in cart_items
                ],
            },
            "message_count": len(messages),
            "receipt_status": receipt.status if receipt else None,
            "receipt": json.loads(receipt.response_json) if receipt and receipt.response_json else None,
        }


def _build_active_plan(client, semantic_provider, session_id):
    semantic_provider([*lookup_then_add("dish", "番茄炒蛋")])
    events = stream_turn(client, session_id, "我要番茄炒蛋")
    terminal = next(event for event in events if event.get("type") == "turn.completed")
    return terminal["payload"]


@pytest.mark.parametrize("failure_point", ["core_after_write", "assistant_message", "receipt_complete"])
def test_cancel_rolls_back_if_graph_commit_fails(
    client, semantic_provider, monkeypatch, failure_point
):
    from app.services.conversation_service import ConversationService
    from app.services.task_lifecycle_service import TaskLifecycleService
    from app.services.turn_receipt_service import TurnReceiptService

    session_id = create_session(client)
    first = _build_active_plan(client, semantic_provider, session_id)
    provider = semantic_provider([{"plan_act": "abandon"}])
    request_id = str(uuid.uuid4())
    before = _persisted(session_id, first["task_id"], request_id)
    failure = AppError(503, "INJECTED_PHASE2A_FAILURE", "injected transaction failure")

    if failure_point == "core_after_write":
        original = TaskLifecycleService.cancel_task_core

        def fail_after_cancel_core(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise failure

        monkeypatch.setattr(TaskLifecycleService, "cancel_task_core", fail_after_cancel_core)
    elif failure_point == "assistant_message":
        original = ConversationService.save_message

        def fail_assistant_message(self, session_id, **kwargs):
            if kwargs.get("role") == "assistant" and kwargs.get("request_id") == request_id:
                raise failure
            return original(self, session_id, **kwargs)

        monkeypatch.setattr(ConversationService, "save_message", fail_assistant_message)
    else:
        original = TurnReceiptService.complete

        def fail_receipt_complete(self, db, reservation, response):
            original(self, db, reservation, response)
            raise failure

        monkeypatch.setattr(TurnReceiptService, "complete", fail_receipt_complete)

    terminal, _ = _turn(client, session_id, "不买了", first, request_id=request_id)
    assert terminal["type"] == "error"
    assert terminal["payload"]["code"] == "INJECTED_PHASE2A_FAILURE"
    after_failure = _persisted(session_id, first["task_id"], request_id)
    assert after_failure["task_status"] == "active"
    assert after_failure["current_step"] == "awaiting_confirmation"
    assert after_failure["state_version"] == first["state_version"]
    assert after_failure["session_version"] == first["session_version"]
    assert after_failure["task_id"] == first["task_id"]
    assert after_failure["plan_json"] == before["plan_json"]
    assert after_failure["message_count"] == before["message_count"]
    assert after_failure["receipt_status"] == "failed"
    assert after_failure["receipt"]["error"]["code"] == "INJECTED_PHASE2A_FAILURE"

    calls_after_failure = len(provider.requests)
    replay, _ = _turn(client, session_id, "不买了", first, request_id=request_id)
    assert replay["type"] == "error"
    assert replay["payload"]["code"] == "INJECTED_PHASE2A_FAILURE"
    assert len(provider.requests) == calls_after_failure
    replayed = _persisted(session_id, first["task_id"], request_id)
    assert replayed["message_count"] == before["message_count"]
    assert replayed["context"] == before["context"]
    assert replayed["cart"] == before["cart"]


def test_stop_after_cancel_core_rolls_back_the_business_effect(
    client, semantic_provider, monkeypatch
):
    from app.services.task_lifecycle_service import TaskLifecycleService
    from app.services.turn_stream_service import cancellation_registry

    session_id = create_session(client)
    first = _build_active_plan(client, semantic_provider, session_id)
    semantic_provider([{"plan_act": "abandon"}])
    with db_module.SessionLocal() as db:
        owner_id = db.get(GuideSession, session_id).owner_id
    request_id = str(uuid.uuid4())
    before = _persisted(session_id, first["task_id"], request_id)
    original = TaskLifecycleService.cancel_task_core

    def stop_after_cancel_core(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        assert cancellation_registry.request_stop(owner_id, session_id, request_id)
        return result

    monkeypatch.setattr(TaskLifecycleService, "cancel_task_core", stop_after_cancel_core)
    terminal, _ = _turn(client, session_id, "不买了", first, request_id=request_id)

    assert terminal["type"] == "error"
    assert terminal["payload"]["code"] == "STOPPED"
    after = _persisted(session_id, first["task_id"], request_id)
    assert after["task_status"] == "active"
    assert after["current_step"] == "awaiting_confirmation"
    assert after["state_version"] == before["state_version"]
    assert after["session_version"] == before["session_version"]
    assert after["plan_json"] == before["plan_json"]
    assert after["context"] == before["context"]
    assert after["cart"] == before["cart"]
    assert after["message_count"] == before["message_count"]


def test_deadline_after_cancel_core_rolls_back_the_business_effect(
    client, semantic_provider, monkeypatch
):
    from app.agent import turn_primitives
    from app.core.config import get_settings
    from app.services.task_lifecycle_service import TaskLifecycleService

    monkeypatch.setenv("SEMANTIC_TURN_TIMEOUT_SECONDS", "30")
    get_settings.cache_clear()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(turn_primitives, "_monotonic", lambda: clock["now"])
    session_id = create_session(client)
    first = _build_active_plan(client, semantic_provider, session_id)
    semantic_provider([{"plan_act": "abandon"}])
    request_id = str(uuid.uuid4())
    before = _persisted(session_id, first["task_id"], request_id)
    original = TaskLifecycleService.cancel_task_core
    core_calls = []

    def expire_after_cancel_core(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        core_calls.append(True)
        clock["now"] += 31
        return result

    monkeypatch.setattr(TaskLifecycleService, "cancel_task_core", expire_after_cancel_core)
    try:
        terminal, _ = _turn(client, session_id, "不买了", first, request_id=request_id)
    finally:
        get_settings.cache_clear()

    assert core_calls == [True]
    assert terminal["type"] == "error", terminal
    assert terminal["payload"]["code"] == "TURN_DEADLINE_EXCEEDED", terminal
    after = _persisted(session_id, first["task_id"], request_id)
    assert after["task_status"] == "active"
    assert after["current_step"] == "awaiting_confirmation"
    assert after["state_version"] == before["state_version"]
    assert after["session_version"] == before["session_version"]
    assert after["plan_json"] == before["plan_json"]
    assert after["context"] == before["context"]
    assert after["cart"] == before["cart"]
    assert after["message_count"] == before["message_count"]


def test_stop_after_receipt_complete_rolls_back_the_business_effect(
    client, semantic_provider, monkeypatch
):
    from app.services.turn_receipt_service import TurnReceiptService
    from app.services.turn_stream_service import cancellation_registry

    session_id = create_session(client)
    first = _build_active_plan(client, semantic_provider, session_id)
    semantic_provider([{"plan_act": "abandon"}])
    with db_module.SessionLocal() as db:
        owner_id = db.get(GuideSession, session_id).owner_id
    request_id = str(uuid.uuid4())
    before = _persisted(session_id, first["task_id"], request_id)
    original = TurnReceiptService.complete

    def stop_after_receipt(self, db, reservation, response):
        result = original(self, db, reservation, response)
        assert cancellation_registry.request_stop(owner_id, session_id, request_id)
        return result

    monkeypatch.setattr(TurnReceiptService, "complete", stop_after_receipt)
    terminal, _ = _turn(client, session_id, "不买了", first, request_id=request_id)

    assert terminal["type"] == "error"
    assert terminal["payload"]["code"] == "STOPPED"
    after = _persisted(session_id, first["task_id"], request_id)
    assert after["task_status"] == "active"
    assert after["current_step"] == "awaiting_confirmation"
    assert after["state_version"] == before["state_version"]
    assert after["session_version"] == before["session_version"]
    assert after["plan_json"] == before["plan_json"]
    assert after["context"] == before["context"]
    assert after["cart"] == before["cart"]
    assert after["message_count"] == before["message_count"]


def test_deadline_after_receipt_complete_rolls_back_the_business_effect(
    client, semantic_provider, monkeypatch
):
    from app.agent import turn_primitives
    from app.core.config import get_settings
    from app.services.turn_receipt_service import TurnReceiptService

    monkeypatch.setenv("SEMANTIC_TURN_TIMEOUT_SECONDS", "30")
    get_settings.cache_clear()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(turn_primitives, "_monotonic", lambda: clock["now"])
    try:
        session_id = create_session(client)
        first = _build_active_plan(client, semantic_provider, session_id)
        semantic_provider([{"plan_act": "abandon"}])
        request_id = str(uuid.uuid4())
        before = _persisted(session_id, first["task_id"], request_id)
        original = TurnReceiptService.complete

        def expire_after_receipt(self, db, reservation, response):
            result = original(self, db, reservation, response)
            clock["now"] += 31
            return result

        monkeypatch.setattr(TurnReceiptService, "complete", expire_after_receipt)
        terminal, _ = _turn(client, session_id, "不买了", first, request_id=request_id)
    finally:
        get_settings.cache_clear()

    assert terminal["type"] == "error"
    assert terminal["payload"]["code"] == "TURN_DEADLINE_EXCEEDED"
    after = _persisted(session_id, first["task_id"], request_id)
    assert after["task_status"] == "active"
    assert after["current_step"] == "awaiting_confirmation"
    assert after["state_version"] == before["state_version"]
    assert after["session_version"] == before["session_version"]
    assert after["plan_json"] == before["plan_json"]
    assert after["context"] == before["context"]
    assert after["cart"] == before["cart"]
    assert after["message_count"] == before["message_count"]
