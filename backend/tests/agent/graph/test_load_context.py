"""``load_context``: the graph's reader of stored state.

Every assertion here is about what the node hands the rest of the graph: the real
task/plan references read from the database, the derived turn mode, a loud
failure when the session does not exist, and no write ever. The node now reads
through the request's own database session (``runtime.db``) and additionally
builds the turn's provider inputs (candidates/snapshot); those stay on the
runtime, not in the state.
"""

from __future__ import annotations

import json

import pytest

from app.agent.graph.nodes.context import load_context
from app.agent.graph.runtime import TurnRuntime
from app.agent.graph.state import initial_state

PLAN = {"plan_id": "plan-1", "plan_version": 1, "items": [{"sku_id": "demo:tomato"}]}
PENDING = [
    {
        "question_id": "q-1",
        "slot": "people",
        "question": "几个人吃？",
        "options": [{"label": "2 人", "ref": "people:2"}],
    }
]


def _turn(session_id: str, owner_id: str = "owner-1") -> dict:
    state = initial_state(
        session_id=session_id,
        owner_id=owner_id,
        turn_id="turn-1",
        user_input="来一份番茄炒蛋",
    )
    state["session"]["turn_mode"] = "active"
    return state


def _runtime(db, session_id: str) -> TurnRuntime:
    return TurnRuntime(
        db=db,
        owner_id="owner-1",
        session_id=session_id,
        request_id="req-1",
        store_id="store-demo-01",
        delivery_zone_id="zone-default",
    )


def test_load_context_reads_the_real_stored_references(seed_session, graph_sessions):
    seeded = seed_session(plan=PLAN, state_version=7, session_version=4, pending=PENDING)
    db = graph_sessions()
    try:
        update = load_context(_turn(seeded["session_id"]), _runtime(db, seeded["session_id"]))
    finally:
        db.close()

    authoritative = update["authoritative"]
    assert authoritative["task_id"] == "task-1"
    assert authoritative["plan_id"] == "plan-1"
    assert authoritative["plan_version"] == 1
    assert authoritative["state_version"] == 7
    assert authoritative["session_version"] == 4
    # The live pending questions travel as real stored context, not a projection.
    assert authoritative["pending"] == PENDING
    # The real target the session is built on is exposed by kind/id/name.
    assert set(authoritative) >= {"target_kind", "target_id", "target_name"}
    # The dispatch mode is derived from the same authoritative read, and the
    # whole session partition is echoed (a partition write replaces, not merges).
    assert update["session"]["turn_mode"] == "active"
    assert update["session"]["session_id"] == seeded["session_id"]
    assert update["session"]["owner_id"] == "owner-1"


def test_load_context_dispatches_taskless_and_terminal_turns(seed_session, graph_sessions):
    taskless = seed_session(session_id="sess-none", task_id=None)
    terminal = seed_session(session_id="sess-done", task_id="task-done", status="completed")

    db = graph_sessions()
    try:
        assert (
            load_context(_turn(taskless["session_id"]), _runtime(db, taskless["session_id"]))[
                "session"
            ]["turn_mode"]
            == "taskless"
        )
        assert (
            load_context(_turn(terminal["session_id"]), _runtime(db, terminal["session_id"]))[
                "session"
            ]["turn_mode"]
            == "completed"
        )
    finally:
        db.close()


def test_load_context_reports_empty_references_without_a_task(seed_session, graph_sessions):
    seeded = seed_session(task_id=None, session_version=2)
    db = graph_sessions()
    try:
        authoritative = load_context(
            _turn(seeded["session_id"]), _runtime(db, seeded["session_id"])
        )["authoritative"]
    finally:
        db.close()

    assert authoritative["task_id"] is None
    assert authoritative["plan_id"] is None
    assert authoritative["plan_version"] is None
    assert authoritative["state_version"] == 0
    assert authoritative["session_version"] == 2
    assert authoritative["pending"] == []


def test_load_context_refuses_a_missing_and_a_foreign_session_alike(
    seed_session, graph_sessions
):
    """Both are the same 403: a caller cannot learn that an id exists elsewhere."""
    from app.core.errors import AppError

    seed_session(session_id="sess-1", owner_id="owner-alice")
    db = graph_sessions()
    try:
        for session_id, owner in (("sess-missing", "owner-1"), ("sess-1", "owner-bob")):
            state = _turn(session_id, owner_id=owner)
            runtime = TurnRuntime(
                db=db,
                owner_id=owner,
                session_id=session_id,
                request_id="req-1",
            )
            with pytest.raises(AppError) as caught:
                load_context(state, runtime)
            assert caught.value.status_code == 403
            assert caught.value.detail["error"]["code"] == "SESSION_FORBIDDEN"
    finally:
        db.close()


def test_load_context_writes_nothing(seed_session, graph_sessions):
    seeded = seed_session(plan=PLAN, state_version=7, session_version=4, pending=PENDING)

    db = graph_sessions()
    try:
        load_context(_turn(seeded["session_id"]), _runtime(db, seeded["session_id"]))
    finally:
        db.close()

    from app.models.session import GuideSemanticContext, GuideSession, GuideTask

    check = graph_sessions()
    try:
        session = check.get(GuideSession, seeded["session_id"])
        task = check.get(GuideTask, "task-1")
        context = check.get(GuideSemanticContext, seeded["session_id"])
        assert (session.session_version, task.state_version) == (4, 7)
        assert json.loads(task.plan_json) == PLAN
        assert json.loads(context.context_json)["pending_clarifications"] == PENDING
    finally:
        check.close()


def test_load_context_requires_owner_id(seed_session, graph_sessions):
    seed_session(session_id="sess-1")
    state = _turn("sess-1")
    del state["session"]["owner_id"]
    db = graph_sessions()
    try:
        with pytest.raises(ValueError, match="OWNER_ID_REQUIRED"):
            load_context(state, _runtime(db, "sess-1"))
    finally:
        db.close()
