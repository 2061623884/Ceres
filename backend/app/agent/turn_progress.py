"""Transport-independent progress and cooperative-stop callbacks for a turn."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

TurnPhase = Literal["understanding", "retrieve", "validate"]

ALLOWED_TURN_PHASES: frozenset[str] = frozenset({"understanding", "retrieve", "validate"})


def validate_turn_phase(phase: str) -> TurnPhase:
    if phase not in ALLOWED_TURN_PHASES:
        raise ValueError(f"invalid turn phase: {phase!r}")
    return phase  # type: ignore[return-value]


class TurnProgressSink(Protocol):
    def on_phase(self, phase: str) -> None: ...

    def on_clarification(self, payload: dict[str, Any]) -> None: ...

    def on_plan_ready(self, plan: dict[str, Any]) -> None: ...

    def on_answer_delta(self, delta: str, *, final: bool = False, replace: bool = False) -> None: ...

    def should_stop(self) -> bool: ...

    def wants_answer_deltas(self) -> bool:
        """Whether incremental answer text has a real consumer (SSE only)."""
        ...


class NoOpTurnProgressSink:
    """Default sink when no SSE consumer is attached."""

    def on_phase(self, phase: str) -> None:
        validate_turn_phase(phase)

    def on_clarification(self, payload: dict[str, Any]) -> None:
        pass

    def on_plan_ready(self, plan: dict[str, Any]) -> None:
        pass

    def on_answer_delta(self, delta: str, *, final: bool = False, replace: bool = False) -> None:
        del delta, final, replace

    def should_stop(self) -> bool:
        return False

    def wants_answer_deltas(self) -> bool:
        return False


def noop_progress_sink() -> TurnProgressSink:
    return NoOpTurnProgressSink()


class CallbackTurnProgressSink:
    """Bridge TurnProgressSink callbacks to caller-supplied handlers (e.g. SSE)."""

    def __init__(
        self,
        *,
        on_phase: Callable[[str], None] | None = None,
        on_clarification: Callable[[dict[str, Any]], None] | None = None,
        on_plan_ready: Callable[[dict[str, Any]], None] | None = None,
        on_answer_delta: Callable[[str, bool, bool], None] | None = None,
        on_should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._on_phase = on_phase
        self._on_clarification = on_clarification
        self._on_plan_ready = on_plan_ready
        self._on_answer_delta = on_answer_delta
        self._on_should_stop = on_should_stop

    def on_phase(self, phase: str) -> None:
        validate_turn_phase(phase)
        if self._on_phase is not None:
            self._on_phase(phase)

    def on_clarification(self, payload: dict[str, Any]) -> None:
        if self._on_clarification is not None:
            self._on_clarification(payload)

    def on_plan_ready(self, plan: dict[str, Any]) -> None:
        if self._on_plan_ready is not None:
            self._on_plan_ready(plan)

    def on_answer_delta(self, delta: str, *, final: bool = False, replace: bool = False) -> None:
        if self._on_answer_delta is not None:
            self._on_answer_delta(delta, final, replace)

    def should_stop(self) -> bool:
        return bool(self._on_should_stop and self._on_should_stop())

    def wants_answer_deltas(self) -> bool:
        return self._on_answer_delta is not None
