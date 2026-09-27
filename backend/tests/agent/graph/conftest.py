"""Fixtures for the graph adapter tests.

The node under test opens its own database session through the module-level
``app.core.database.SessionLocal``, exactly as the live request path does. The
fixture redirects that factory to a real SQLite file instead of injecting a
session the node would never see in production, so what runs here is the
production read path ??not a stand-in for it.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class ScriptedProvider:
    """A provider whose answers (and failures) are fixed, in order.

    It satisfies the real provider contract the nodes call: ``propose(request)``
    and the optional ``set_call_timeout`` capability. A step may be a payload
    dict or an exception to raise.
    """

    def __init__(self, steps: list[Any]):
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []
        self.timeouts: list[float] = []

    def set_call_timeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)

    def propose(self, request: dict[str, Any], **kwargs: Any) -> Any:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError("ScriptedProvider ran out of scripted steps")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        on_reply_delta = kwargs.get("on_reply_delta")
        if kwargs.get("reset_stream") and on_reply_delta is not None:
            on_reply_delta("", False, True)
        if on_reply_delta is not None and isinstance(step, dict):
            reply = step.get("reply")
            if isinstance(reply, str) and reply:
                on_reply_delta(reply, False, False)
        return step


class FakeReadPort:
    """A read port that records what it was asked and returns fixed facts."""

    def __init__(self, results: list[dict[str, Any]] | None = None):
        self.results = list(results or [])
        self.calls: list[dict[str, Any]] = []

    def serve(self, proposal: Any, candidates: Any, *, lookup_limit: int) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "lookups": [lookup.kind for lookup in proposal.lookups],
                "queries": [query.kind for query in proposal.queries],
                "lookup_limit": lookup_limit,
            }
        )
        if self.results:
            return list(self.results)
        return [{"kind": "lookup", "lookup_kind": "dish", "status": "completed", "matches": []}]


@pytest.fixture()
def make_runtime() -> Callable[..., Any]:
    """Build a :class:`TurnRuntime` for one graph run."""
    from app.agent.graph.runtime import TurnRuntime
    from app.agent.turn_primitives import LoopBudget, TurnSnapshot
    from app.agent.protocol import CandidateSet

    def _make(*, provider: Any = None, reads: Any = None, budget: Any = None, snapshot: Any = None, **kwargs: Any) -> Any:
        return TurnRuntime(
            provider=provider,
            reads=reads,
            budget=budget
            or LoopBudget(max_model_calls=3, max_lookups=2),
            snapshot=snapshot
            or TurnSnapshot(turn_mode="active", message="???????"),
            candidates=CandidateSet(),
            **kwargs,
        )

    return _make


@pytest.fixture()
def provider_factory() -> type[ScriptedProvider]:
    return ScriptedProvider


@pytest.fixture()
def reads_factory() -> type[FakeReadPort]:
    return FakeReadPort


@pytest.fixture()
def turn() -> Callable[..., dict[str, Any]]:
    """A fresh turn's initial state, nothing else."""
    from app.agent.graph.state import initial_state

    def _turn(
        session_id: str = "sess-graph-1",
        owner_id: str = "owner-1",
        user_input: str = "???????",
    ) -> dict[str, Any]:
        state = initial_state(
            session_id=session_id,
            owner_id=owner_id,
            turn_id="turn-1",
            user_input=user_input,
        )
        state["session"]["turn_mode"] = "active"
        return state

    return _turn


@pytest.fixture()
def graph_sessions(tmp_path, monkeypatch):
    """Point ``SessionLocal`` at a fresh, real business database."""
    from app.core import database
    from app.core.database import Base
    from app.models import cart as cart_models  # noqa: F401  (registers the tables)
    from app.models import conversation as conversation_models  # noqa: F401
    from app.models import session as session_models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'graph.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def seed_session(graph_sessions) -> Callable[..., dict[str, Any]]:
    """Write one session ? and optionally its task and semantic context ? to the DB."""
    from app.models.session import GuideSemanticContext, GuideSession, GuideTask

    def _seed(
        *,
        session_id: str = "sess-graph-1",
        owner_id: str = "owner-1",
        task_id: str | None = "task-1",
        plan: dict[str, Any] | None = None,
        state_version: int = 7,
        session_version: int = 4,
        pending: list[dict[str, Any]] | None = None,
        context_task_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        db = graph_sessions()
        try:
            db.add(
                GuideSession(
                    session_id=session_id,
                    owner_id=owner_id,
                    current_task_id=task_id,
                    session_version=session_version,
                    entry_context_json="{}",
                )
            )
            if task_id is not None:
                db.add(
                    GuideTask(
                        task_id=task_id,
                        session_id=session_id,
                        owner_id=owner_id,
                        intent="purchase",
                        state_version=state_version,
                        status=status,
                        plan_json=json.dumps(plan) if plan else None,
                    )
                )
            if pending is not None or context_task_id is not None:
                db.add(
                    GuideSemanticContext(
                        session_id=session_id,
                        owner_id=owner_id,
                        context_json=json.dumps(
                            {
                                "task_id": context_task_id if context_task_id is not None else task_id,
                                "task_status": status,
                                "pending_clarifications": pending or [],
                            }
                        ),
                    )
                )
            db.commit()
        finally:
            db.close()
        return {
            "session_id": session_id,
            "task_id": task_id,
            "plan": plan,
            "state_version": state_version,
            "session_version": session_version,
            "pending": pending or [],
        }

    return _seed
