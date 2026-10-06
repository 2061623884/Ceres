"""The cart write, assistant result and turn receipt commit as one Graph batch."""

from __future__ import annotations

import json
import uuid

import pytest

from app.core import database as db_module
from app.core.errors import AppError
from app.models.cart import Cart, CartItem, CartOperation, TurnRequestRecord
from app.models.conversation import GuideMessage
from app.models.session import GuideSemanticContext, GuideSession, GuideTask
from support import create_session, stream_turn
from support.semantic_agent import lookup_then_add


def _terminal(client, session_id, message, previous, request_id):
    events = stream_turn(
        client, session_id, message, previous, request_id=request_id
    )
    terminal = [
        row for row in events
        if row.get("type") in {"turn.completed", "turn.stopped", "error"}
    ]
    assert len(terminal) == 1, events
    return terminal[0]


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
        messages = (
            db.query(GuideMessage).filter_by(session_id=session_id)
            .order_by(GuideMessage.sequence).all()
        )
        operations = (
            db.query(CartOperation).filter_by(owner_id=session.owner_id)
            .order_by(CartOperation.created_at, CartOperation.operation_id).all()
        )
        return {
            "session_version": session.session_version,
            "task_id": session.current_task_id,
            "task_status": task.status,
            "current_step": task.current_step,
            "state_version": task.state_version,
            "plan_json": task.plan_json,
            "cart_result_json": task.cart_result_json,
            "user_confirmed": task.user_confirmed,
            "confirmation_id": task.confirmation_id,
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
                    "idempotency_key": row.idempotency_key,
                    "status": row.status,
                    "result_json": row.result_json,
                }
                for row in operations
            ],
            "receipt": None if receipt is None else {
                "status": receipt.status,
                "response_json": receipt.response_json,
            },
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


def _new_plan(client, semantic_provider):
    session_id = create_session(client)
    semantic_provider([*lookup_then_add("dish", "番茄炒蛋")])
    events = stream_turn(client, session_id, "我要番茄炒蛋")
    terminal = next(row for row in events if row.get("type") == "turn.completed")
    return session_id, terminal["payload"]


def _request_confirm(semantic_provider):
    return semantic_provider([{"plan_act": "confirm"}])


@pytest.mark.parametrize("failure_point", ["core_after_write", "assistant_message", "receipt_complete"])
def test_confirm_rolls_back_cart_and_graph_state_when_commit_fails(
    client, semantic_provider, monkeypatch, failure_point
):
    from app.services.confirmation_service import ConfirmationService
    from app.services.conversation_service import ConversationService
    from app.services.turn_receipt_service import TurnReceiptService

    session_id, first = _new_plan(client, semantic_provider)
    provider = _request_confirm(semantic_provider)
    request_id = str(uuid.uuid4())
    previous = {"task_id": first["task_id"], "state_version": first["state_version"],
                "session_version": first["session_version"]}
    client.get("/api/v1/cart").json()
    before = _persisted(session_id, first["task_id"], request_id)
    failure = AppError(503, "INJECTED_PHASE2B_FAILURE", "injected confirmation transaction failure")

    if failure_point == "core_after_write":
        original = ConfirmationService.confirm_core

        def fail_after_core(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise failure

        monkeypatch.setattr(ConfirmationService, "confirm_core", fail_after_core)
    elif failure_point == "assistant_message":
        original = ConversationService.save_message

        def fail_assistant(self, session_id, **kwargs):
            if kwargs.get("role") == "assistant" and kwargs.get("request_id") == request_id:
                raise failure
            return original(self, session_id, **kwargs)

        monkeypatch.setattr(ConversationService, "save_message", fail_assistant)
    else:
        original = TurnReceiptService.complete

        def fail_receipt(self, db, reservation, response):
            original(self, db, reservation, response)
            raise failure

        monkeypatch.setattr(TurnReceiptService, "complete", fail_receipt)

    terminal = _terminal(client, session_id, "加入购物车", previous, request_id)
    assert terminal["type"] == "error", terminal
    assert terminal["payload"]["code"] == "INJECTED_PHASE2B_FAILURE"
    after = _persisted(session_id, first["task_id"], request_id)
    assert after["task_status"] == "active"
    assert after["current_step"] == "awaiting_confirmation"
    assert after["state_version"] == first["state_version"]
    assert after["session_version"] == first["session_version"]
    assert after["task_id"] == first["task_id"]
    assert after["plan_json"] == before["plan_json"]
    assert after["cart_result_json"] == before["cart_result_json"]
    assert after["user_confirmed"] is False
    assert after["confirmation_id"] is None
    assert after["cart"] == before["cart"]
    assert after["cart_operations"] == before["cart_operations"]
    assert after["context"] == before["context"]
    assert after["messages"] == before["messages"]
    assert after["receipt"]["status"] == "failed"
    assert json.loads(after["receipt"]["response_json"])["error"]["code"] == "INJECTED_PHASE2B_FAILURE"

    calls_after_failure = len(provider.requests)
    replay = _terminal(client, session_id, "加入购物车", previous, request_id)
    assert replay["type"] == "error"
    assert replay["payload"]["code"] == "INJECTED_PHASE2B_FAILURE"
    assert len(provider.requests) == calls_after_failure
    assert _persisted(session_id, first["task_id"], request_id) == after


@pytest.mark.parametrize(
    ("failure_point", "interrupt"),
    [
        ("core", "stop"),
        ("core", "deadline"),
        ("receipt", "stop"),
        ("receipt", "deadline"),
    ],
)
def test_stop_or_deadline_after_core_or_receipt_rolls_back_confirmation(
    client, semantic_provider, monkeypatch, failure_point, interrupt
):
    from app.services.confirmation_service import ConfirmationService
    from app.services.turn_receipt_service import TurnReceiptService
    from app.services.turn_stream_service import cancellation_registry

    if interrupt == "deadline":
        from app.agent import turn_primitives
        from app.core.config import get_settings

        monkeypatch.setenv("SEMANTIC_TURN_TIMEOUT_SECONDS", "30")
        get_settings.cache_clear()
        clock = {"now": 1_000.0}
        monkeypatch.setattr(turn_primitives, "_monotonic", lambda: clock["now"])

    try:
        session_id, first = _new_plan(client, semantic_provider)
        provider = _request_confirm(semantic_provider)
        with db_module.SessionLocal() as db:
            owner_id = db.get(GuideSession, session_id).owner_id
        request_id = str(uuid.uuid4())
        previous = {"task_id": first["task_id"], "state_version": first["state_version"],
                    "session_version": first["session_version"]}
        client.get("/api/v1/cart").json()
        before = _persisted(session_id, first["task_id"], request_id)

        def interrupt_after(result):
            if interrupt == "stop":
                assert cancellation_registry.request_stop(owner_id, session_id, request_id)
            else:
                clock["now"] += 31
            return result

        if failure_point == "core":
            original = ConfirmationService.confirm_core

            def interrupt_after_core(self, *args, **kwargs):
                return interrupt_after(original(self, *args, **kwargs))

            monkeypatch.setattr(ConfirmationService, "confirm_core", interrupt_after_core)
        else:
            original = TurnReceiptService.complete

            def interrupt_after_receipt(self, db, reservation, response):
                return interrupt_after(original(self, db, reservation, response))

            monkeypatch.setattr(TurnReceiptService, "complete", interrupt_after_receipt)

        terminal = _terminal(client, session_id, "加入购物车", previous, request_id)
        assert terminal["type"] == "error", terminal
        expected_code = "STOPPED" if interrupt == "stop" else "TURN_DEADLINE_EXCEEDED"
        assert terminal["payload"]["code"] == expected_code
        after = _persisted(session_id, first["task_id"], request_id)
        assert after["task_status"] == "active"
        assert after["current_step"] == "awaiting_confirmation"
        assert after["state_version"] == before["state_version"]
        assert after["session_version"] == before["session_version"]
        assert after["task_id"] == before["task_id"]
        assert after["plan_json"] == before["plan_json"]
        assert after["cart_result_json"] == before["cart_result_json"]
        assert after["user_confirmed"] is False
        assert after["confirmation_id"] is None
        assert after["cart"] == before["cart"]
        assert after["cart_operations"] == before["cart_operations"]
        assert after["context"] == before["context"]
        assert after["messages"] == before["messages"]
        assert after["receipt"]["status"] == "failed"
        assert json.loads(after["receipt"]["response_json"])["error"]["code"] == expected_code

        calls_after_failure = len(provider.requests)
        replay = _terminal(client, session_id, "加入购物车", previous, request_id)
        assert replay["type"] == "error"
        assert replay["payload"]["code"] == expected_code
        assert len(provider.requests) == calls_after_failure
        assert _persisted(session_id, first["task_id"], request_id) == after
    finally:
        if interrupt == "deadline":
            get_settings.cache_clear()
