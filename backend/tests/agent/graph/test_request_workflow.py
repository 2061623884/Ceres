"""The request-level workflow's core business assertions.

Migrated from the retired R2/R3 orchestration suite to the surviving entry
points, without any graph invoke, model call or checkpoint:

* the production graph passes through parse/validation and the single decision;
* the route out of ``decide_turn`` comes only from ``TurnDecision.route``;
* one HTTP request is one idempotent business step: a completed ``request_id``
  replays without executing or writing, a recorded failure replays its original
  error, a reused id with another body conflicts, and a live reservation is
  reported as in progress;
* the in-transaction guard refuses a stale session/anchor and a late stop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.agent.graph.graph import PRODUCTION_NODES, get_graph
from app.agent.graph.nodes.understand import route_from
from app.agent.graph.runtime import TurnRuntime
from app.agent.graph.turn_commit import final_guard
from app.core.errors import AppError
from app.services.turn_receipt_service import TurnReceiptService

OWNER = "owner-1"


# ------------------------------------------------------------------- topology


def test_production_graph_routes_only_after_decision():
    graph = get_graph().get_graph()
    nodes = sorted(n for n in graph.nodes if not n.startswith("__"))
    assert nodes == sorted(PRODUCTION_NODES)
    assert nodes == ["answer", "decide_turn", "load_context", "mutation", "parse_validate", "respond", "retrieve", "understand"]

    plain = {(e.source, e.target) for e in graph.edges if not getattr(e, "conditional", False)}
    conditional = {
        (e.source, e.target) for e in graph.edges if getattr(e, "conditional", False)
    }
    assert ("__start__", "load_context") in plain
    assert ("load_context", "understand") in plain
    assert ("understand", "parse_validate") in plain
    assert ("parse_validate", "decide_turn") in plain
    assert ("retrieve", "answer") in plain
    assert ("mutation", "answer") in plain
    assert ("answer", "respond") in plain
    assert ("respond", "__end__") in plain
    assert conditional == {
        ("decide_turn", "retrieve"),
        ("decide_turn", "mutation"),
        ("decide_turn", "answer"),
    }


# ------------------------------------------------------------ intent routing


def _decision(route: str, *, write_blocked: bool = False):
    return SimpleNamespace(route=route, write_blocked=write_blocked)


def test_route_from_only_returns_decision_route():
    for route in ("chat", "retrieve", "mutation", "answer", "clarify", "refuse"):
        assert route_from(_decision(route, write_blocked=True)) == route


# ------------------------------------------------------- request idempotency


def _receipts(factory) -> TurnReceiptService:
    return TurnReceiptService(factory, OWNER)


def test_completed_request_replays_without_executing_again(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-receipt-1")
    receipts = _receipts(graph_sessions)

    reservation = receipts.reserve(seeded["session_id"], "req-1", "digest-a")
    assert reservation.token is not None and not reservation.is_completed

    db = graph_sessions()
    try:
        receipts.assert_owned(db, reservation)
        receipts.complete(db, reservation, {"ok": True, "request_id": "req-1"})
        db.commit()
    finally:
        db.close()

    replayed = receipts.lookup_completed(seeded["session_id"], "req-1", "digest-a")
    assert replayed == {"ok": True, "request_id": "req-1"}

    again = receipts.reserve(seeded["session_id"], "req-1", "digest-a")
    assert again.is_completed
    assert again.token is None
    assert again.completed_receipt == {"ok": True, "request_id": "req-1"}


def test_same_request_id_with_another_body_conflicts(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-receipt-2")
    receipts = _receipts(graph_sessions)
    receipts.reserve(seeded["session_id"], "req-2", "digest-a")

    with pytest.raises(AppError) as caught:
        receipts.reserve(seeded["session_id"], "req-2", "digest-b")
    assert caught.value.detail["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_a_live_reservation_is_in_progress(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-receipt-3")
    receipts = _receipts(graph_sessions)
    receipts.reserve(seeded["session_id"], "req-3", "digest-a")

    with pytest.raises(AppError) as caught:
        receipts.lookup_completed(seeded["session_id"], "req-3", "digest-a")
    assert caught.value.detail["error"]["code"] == "TURN_IN_PROGRESS"


def test_a_recorded_failure_replays_its_original_error(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-receipt-4")
    receipts = _receipts(graph_sessions)
    first = receipts.reserve(seeded["session_id"], "req-4", "digest-a")
    assert (
        receipts.fail(
            seeded["session_id"],
            "req-4",
            token=first.token,
            error={
                "code": "MODEL_TIMEOUT",
                "message": "模型超时",
                "retryable": False,
                "http_status": 400,
            },
        )
        is True
    )

    # The same request id replays that exact error and never re-executes.
    for call in (
        lambda: receipts.lookup_completed(seeded["session_id"], "req-4", "digest-a"),
        lambda: receipts.reserve(seeded["session_id"], "req-4", "digest-a"),
    ):
        with pytest.raises(AppError) as caught:
            call()
        error = caught.value.detail["error"]
        assert error["code"] == "MODEL_TIMEOUT"
        assert error["message"] == "模型超时"
        assert caught.value.status_code == 400


# --------------------------------------------------------------- final guard


def _runtime(db, session_id: str) -> TurnRuntime:
    return TurnRuntime(
        db=db,
        owner_id=OWNER,
        session_id=session_id,
        request_id="req-guard",
    )


def _staged(session_id: str, session_version: int = 4) -> dict:
    return {
        "kind": "answer",
        "preconditions": {
            "session_id": session_id,
            "task_id": None,
            "state_version": 0,
            "session_version": session_version,
        },
    }


def test_guard_allows_an_unchanged_request(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-guard-1", task_id=None, session_version=4)
    db = graph_sessions()
    try:
        runtime = _runtime(db, seeded["session_id"])
        verdict = final_guard(db, runtime, _staged(seeded["session_id"]), None)
    finally:
        db.close()
    assert verdict["allowed"] is True


def test_guard_refuses_a_session_that_moved_since_the_request(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-guard-2", task_id=None, session_version=4)
    db = graph_sessions()
    try:
        runtime = _runtime(db, seeded["session_id"])
        assert final_guard(db, runtime, _staged(seeded["session_id"]), None)["allowed"] is True
        db.rollback()

        other = graph_sessions()
        try:
            other.execute(
                text(
                    "UPDATE guide_sessions SET session_version = session_version + 3 "
                    "WHERE session_id = :sid"
                ),
                {"sid": seeded["session_id"]},
            )
            other.commit()
        finally:
            other.close()

        verdict = final_guard(db, runtime, _staged(seeded["session_id"]), None)
    finally:
        db.close()
    assert verdict["allowed"] is False
    assert verdict["code"] == "STALE_STATE"


def test_guard_refuses_a_stop_that_arrived_after_the_prepare(seed_session, graph_sessions):
    seeded = seed_session(session_id="sess-guard-3", task_id=None, session_version=4)
    db = graph_sessions()
    try:
        runtime = _runtime(db, seeded["session_id"])
        runtime.should_stop = lambda: True
        verdict = final_guard(db, runtime, _staged(seeded["session_id"]), None)
    finally:
        db.close()
    assert verdict["allowed"] is False
    assert verdict["code"] == "STOPPED"
