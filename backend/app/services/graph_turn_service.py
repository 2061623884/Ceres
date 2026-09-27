"""HTTP/SSE transport adapter for the request-level Guide graph.

Owns only turn *transport* concerns: provider/read wiring, cooperative stop and
deadline, progress callbacks, trace id allocation and view-context persistence.
Business routing, idempotency, receipt replay and state mutation all live in
``run_graph_turn`` and the graph's ``respond`` node.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agent.context_resolver import ContextResolver
from app.agent.graph.coordinator import run_graph_turn
from app.agent.graph.response_contract import new_trace_id
from app.agent.turn_primitives import (
    HARD_MAX_MODEL_CALLS,
    TIMEOUT_CODE,
    LoopBudget,
    turn_deadline_at,
)
from app.agent.state import TaskState
from app.agent.tools.read import ReadTools
from app.agent.turn_progress import TurnProgressSink, noop_progress_sink
from app.core.config import get_settings
from app.core.errors import AppError
from app.llm.errors import LLMProviderError
from app.models.session import GuideSession, GuideTask
from app.services.trace_service import TraceService


def _monotonic() -> float:
    """The one turn clock, shared with ``turn_primitives._monotonic``."""
    from app.agent import turn_primitives as turn_module

    return float(turn_module._monotonic())


def _uncommitted_timeout(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """The timeout receipt of a turn that committed nothing (or ``None``).

    A spent budget whose write really happened is a partial success and must stay
    the ordinary 200 with ``answer_status=failed``. Only a budget that ended the
    turn with no business effect at all is the legacy 503 failure — so this looks
    at both the receipt codes and what was actually saved.
    """
    if not isinstance(response, dict):
        return None
    rows = list(response.get("action_results") or [])
    timed_out_rows = [row for row in rows if row.get("code") == TIMEOUT_CODE]
    if not timed_out_rows:
        return None
    if response.get("committed") or response.get("plan"):
        return None
    if any(row.get("saved") or row.get("status") == "committed" for row in rows):
        return None
    return timed_out_rows[0]


def _uncommitted_guard_conflict(response: dict[str, Any] | None) -> str | None:
    """The conflict code of a turn whose guard denied it and wrote nothing.

    ``STALE_STATE`` is the loop entry's 409: the client held an anchor that moved
    under it. If any part of the turn really committed, it is a partial result and
    stays the ordinary 200 — only a turn with no business effect is the conflict.
    """
    if not isinstance(response, dict):
        return None
    rows = list(response.get("action_results") or [])
    codes = {row.get("code") for row in rows}
    if response.get("guard_code"):
        codes.add(response.get("guard_code"))
    if "STALE_STATE" not in codes:
        return None
    if response.get("committed") or response.get("plan"):
        return None
    if any(row.get("saved") or row.get("status") == "committed" for row in rows):
        return None
    return "STALE_STATE"


class GraphTurnService:
    """The sole production entry for Guide turns over the request-level graph."""

    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
        self.trace = TraceService(db)

    def _provider(self) -> Any:
        from app.llm.provider import get_semantic_provider

        provider = get_semantic_provider()
        if not callable(getattr(provider, "propose", None)):
            raise AppError(
                503,
                "SEMANTIC_PROVIDER_UNAVAILABLE",
                "语义链路需要支持 propose 的 provider；不会回退到旧的文本匹配链路。",
            )
        return provider

    def _budget(self) -> LoopBudget:
        settings = get_settings()
        return LoopBudget(
            max_model_calls=max(1, min(int(settings.semantic_max_steps), HARD_MAX_MODEL_CALLS)),
            max_lookups=max(0, int(settings.semantic_lookup_budget)),
        )

    def _reads(self, session: GuideSession, deadline_expired: Any) -> ReadTools:
        ctx = ContextResolver(self.db, self.owner_id).resolve(session.session_id)
        store = getattr(ctx, "store_id", "") or "store-demo-01"
        zone = getattr(ctx, "delivery_zone_id", "") or "zone-default"
        task = (
            self.db.get(GuideTask, session.current_task_id) if session.current_task_id else None
        )
        state = (
            TaskState.from_db(task, entry_context=json.loads(session.entry_context_json or "{}"))
            if task is not None
            else None
        )
        requirements = self._requirements(session, state)
        return ReadTools(
            self.db,
            store_id=store,
            delivery_zone_id=zone,
            active_template_id=getattr(state, "active_template_id", None) if state else None,
            purchase_summary=getattr(ctx, "purchase_summary", None),
            deadline_expired=deadline_expired,
            requirements=requirements,
        )

    def _requirements(self, session: GuideSession, state: TaskState | None) -> Any:
        """The task's requirements unioned with the session's durable facts.

        A taskless query that stated an exclusion is honoured by later reads even
        though no task exists yet.
        """
        from app.agent import context as turn_context
        from app.agent.state import Requirements

        persisted = turn_context.load_context(self.db, session) or {}
        constraints = dict(persisted.get("session_constraints") or {})
        if not constraints:
            return getattr(state, "requirements", None) if state else None
        base = (
            state.requirements.to_dict()
            if state is not None and state.requirements
            else {}
        )
        exclusions = list(
            dict.fromkeys(
                [
                    *(base.get("excluded_ingredients") or []),
                    *(constraints.get("excluded_ingredients") or []),
                ]
            )
        )
        if exclusions:
            base["excluded_ingredients"] = exclusions
        budgets = [
            value
            for value in (base.get("budget_fen"), constraints.get("budget_fen"))
            if value is not None
        ]
        if budgets:
            base["budget_fen"] = min(budgets)
        return Requirements.from_dict(base)

    def process_turn(
        self,
        *,
        session_id: str,
        message: str,
        request_id: str,
        expected_task_id: str | None,
        expected_state_version: int,
        expected_session_version: int | None = None,
        view_context: dict[str, Any] | None = None,
        progress: TurnProgressSink | None = None,
        should_stop: Any = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.db.get(GuideSession, session_id)
        if session is None or session.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")

        settings = get_settings()
        sink = progress or noop_progress_sink()
        effective_trace = trace_id or new_trace_id()
        now = _monotonic()
        deadline = turn_deadline_at(now)
        # The sink is the turn's cooperative-stop seam, exactly as it is on the
        # loop entry: an explicit ``should_stop`` (SSE) wins, otherwise the sink's
        # own check is used. Without an SSE sink the no-op sink returns False; a
        # caller that supplies a real sink (or a test that drives that seam)
        # really stops the turn.
        stop_fn = should_stop or sink.should_stop
        expired = lambda: _monotonic() >= deadline

        #: The model-call telemetry sink: the same `model_call_*` trace phases the
        #: loop entry writes, flushed independently so a later rollback cannot
        #: erase the record of a call that really happened.
        state_holder = {"task_id": session.current_task_id}

        def record_model_call(event: dict[str, Any]) -> None:
            sink_hook = getattr(sink, "on_model_call", None)
            if callable(sink_hook):
                sink_hook(event)
            self._record_event_independent(
                trace_id=effective_trace,
                request_id=request_id,
                session_id=session_id,
                task_id=state_holder["task_id"],
                phase="model_call_" + str(event.get("status") or "unknown"),
                output_summary=json.dumps(event, ensure_ascii=False),
                error=event.get("code"),
                duration_ms=event.get("duration_ms"),
            )

        def record_phase(phase: str) -> None:
            # The phase the turn really reached (understanding/retrieve/validate)
            # is a trace event in its own right, exactly as the loop entry writes
            # it; the transport sink still receives the phase unchanged.
            sink.on_phase(phase)
            self._record_event_independent(
                trace_id=effective_trace,
                request_id=request_id,
                session_id=session_id,
                task_id=state_holder["task_id"],
                phase=str(phase),
            )

        try:
            result = run_graph_turn(
                self.db,
                owner_id=self.owner_id,
                session_id=session_id,
                message=message,
                request_id=request_id,
                provider=self._provider(),
                reads=self._reads(session, expired),
                budget=self._budget(),
                should_stop=stop_fn,
                deadline=deadline,
                clock=_monotonic,
                expected_task_id=expected_task_id,
                expected_state_version=expected_state_version,
                expected_session_version=expected_session_version,
                view_context=view_context,
                trace_id=effective_trace,
                model_mode=settings.llm_mode,
                business_data_mode=settings.business_data_mode,
                on_phase=record_phase,
                on_model_call=record_model_call,
                progress_sink=sink,
            )
        except LLMProviderError as exc:
            # A provider failure that is not repaired inside the graph is a
            # transport failure of the turn, mapped exactly as the loop entry
            # maps it: retryable -> 502, otherwise 400, with the provider's own
            # business code preserved on SSE and on replay of a recorded failure.
            self._record_failure(effective_trace, session_id, request_id, exc)
            raise AppError(
                502 if exc.retryable else 400,
                exc.code,
                exc.message,
                retryable=exc.retryable,
            ) from exc
        timed_out = _uncommitted_timeout(result)
        if timed_out is not None:            # A spent budget with *nothing* committed is the legacy 503 failure:
            # the turn is reported as itself, is not a purchase step, and carries
            # no partial result. A timeout that did commit earlier work stays the
            # ordinary 200 with ``answer_status=failed`` (see the response
            # contract), never this error.
            raise AppError(
                503,
                TIMEOUT_CODE,
                str(timed_out.get("message") or "本轮处理超时，未执行的修改没有写入。"),
                retryable=True,
            )
        conflict = _uncommitted_guard_conflict(result)
        if conflict is not None:
            # A stale/authorization conflict that wrote nothing is the loop's own
            # 409, not an in-band refusal: the client must re-anchor explicitly.
            raise AppError(409, conflict, str((result.get("action_results") or [{}])[0].get("message") or "本轮改动未执行。"))
        # A replay carries the original trace id and must not write another
        # trace row for a request that did not execute this time.
        if result.get("trace_id") == effective_trace:
            self._record_trace(effective_trace, session_id, request_id, result)
        return result

    def _record_event_independent(self, *, trace_id: str, **fields: Any) -> None:
        """Write one trace row on a truly independent session, then close it.

        Telemetry must never roll back or commit the caller's business session
        (the Graph's transaction). A short-lived session that commits and closes
        keeps the record durable and the business transaction untouched.
        """
        from app.core.database import SessionLocal

        telemetry = SessionLocal()
        try:
            TraceService(telemetry).record(
                trace_id=trace_id,
                owner_id=self.owner_id,
                model_mode=get_settings().llm_mode,
                **fields,
            )
            telemetry.commit()
        except Exception:
            # Tracing must never mask a real turn failure.
            telemetry.rollback()
        finally:
            telemetry.close()

    def _record_failure(
        self,
        trace_id: str,
        session_id: str,
        request_id: str,
        error: Exception,
    ) -> None:
        """Record a failed turn in the trace, the same phase the loop entry uses."""
        code = getattr(error, "code", type(error).__name__)
        self._record_event_independent(
            trace_id=trace_id,
            session_id=session_id,
            request_id=request_id,
            phase="turn_failed",
            output_summary=json.dumps({"code": code}, ensure_ascii=False),
            error=code,
        )

    def _record_trace(
        self,
        trace_id: str,
        session_id: str,
        request_id: str,
        response: dict[str, Any],
    ) -> None:
        # Committed independently: an uncommitted trace write would hold a lock on
        # the business database after the turn's own transaction closed.
        self._record_event_independent(
            trace_id=trace_id,
            phase="turn_result",
            session_id=session_id,
            task_id=response.get("task_id"),
            request_id=request_id,
            output_summary=json.dumps(
                {
                    "status": response.get("status"),
                    "plan_effect": response.get("plan_effect"),
                    "actions": [
                        {k: row[k] for k in ("type", "status", "code") if row.get(k)}
                        for row in response.get("action_results") or []
                    ],
                },
                ensure_ascii=False,
            ),
        )


__all__ = ["GraphTurnService"]
