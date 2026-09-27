"""Process-local resources for one request's graph run.

A graph node may only look at the serializable state; everything that is *not*
serializable — the model provider, the read-only port, the database session
behind it, the stop signal, the callbacks and the turn's clock — arrives through
the runtime context instead. There is no checkpoint anymore: this context is the
graph's version of the loop's keyword-only arguments and it lives for exactly one
``graph.invoke``.

It carries no business truth: ``load_context`` re-reads that from the business
database, and a node that tried to reconstruct authority from here would be
reading a stale copy.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.turn_primitives import LoopBudget, TurnSnapshot


def _never() -> bool:
    return False


def _ignore(_name: str) -> None:
    return None


def _ignore_event(_event: dict[str, Any]) -> None:
    return None


@dataclass
class TurnRuntime:
    """Everything one request needs that must never enter persisted state."""

    provider: Any = None
    reads: Any = None
    budget: LoopBudget = field(default_factory=LoopBudget)
    #: The turn's server-owned inputs, assembled by ``load_context`` from the
    #: real business database and the resolved context.
    snapshot: TurnSnapshot | None = None
    candidates: Any = None
    should_stop: Callable[[], bool] = field(default=_never)
    on_phase: Callable[[str], None] = field(default=_ignore)
    on_model_call: Callable[[dict[str, Any]], None] = field(default=_ignore_event)
    deadline: float | None = None
    clock: Callable[[], float] = field(default=time.monotonic)
    #: The request's database session. It is the single business transaction the
    #: ``respond`` node commits.
    db: Any = None
    owner_id: str = ""
    session_id: str = ""
    request_id: str = ""
    #: The client's explicit version expectations, when the request carried them.
    expected_task_id: str | None = None
    expected_state_version: int | None = None
    expected_session_version: int | None = None
    #: Immutable server-side entry facts captured by ``load_context`` from the
    #: request's first live read. The final guard defends this anchor so a later
    #: load cannot move it.
    entry_anchor: dict[str, Any] | None = None
    #: The client's view context for THIS request, a pure runtime input; the
    #: commit node persists it atomically inside the business transaction.
    view_context: dict[str, Any] | None = None
    store_id: str = "store-demo-01"
    delivery_zone_id: str = "zone-default"
    #: The completed HTTP response for this request. Never persisted state.
    response: dict[str, Any] | None = None
    reservation: Any = None
    receipt_service: Any = None
    #: Optional SSE/progress sink for transport events (plan.ready, clarification).
    progress_sink: Any = None
    trace_id: str | None = None
    model_mode: str | None = None
    business_data_mode: str | None = None

    # ------------------------------------------------------------- derived facts

    def stop(self) -> bool:
        return bool(self.should_stop())

    def now(self) -> float:
        return self.clock()

    def expired(self) -> bool:
        return self.deadline is not None and self.now() >= self.deadline

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        return self.deadline - self.now()

    def snapshot_for(self, turn_mode: str) -> TurnSnapshot:
        """The turn's snapshot with the graph's own turn mode applied."""
        if self.snapshot is None:
            raise ValueError(
                "TURN_SNAPSHOT_REQUIRED: the runtime context must carry the turn snapshot"
            )
        if self.snapshot.turn_mode == turn_mode:
            return self.snapshot
        from dataclasses import replace

        return replace(self.snapshot, turn_mode=turn_mode)


def context_of(runtime: Any) -> TurnRuntime:
    """The :class:`TurnRuntime` behind a LangGraph ``Runtime`` (or the value itself).

    Nodes are also called directly in focused checks with the context object, so
    this accepts either shape and never invents a provider that is not there.
    """
    if isinstance(runtime, TurnRuntime):
        return runtime
    context = getattr(runtime, "context", None)
    return context if isinstance(context, TurnRuntime) else TurnRuntime()


__all__ = ["TurnRuntime", "context_of"]
