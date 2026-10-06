"""SSE transport for one request-level Graph turn.

One HTTP POST starts exactly one :meth:`GraphTurnService.process_turn` on a
short-lived worker thread and streams that run's progress and its terminal event
as SSE. Nothing about the run is persisted as an execution record: there is no
``GuideOperation`` row, no recovery query, no polling endpoint and no run
lifecycle across requests. Multi-turn continuity comes from the business session
store and request-level idempotency from ``TurnReceiptService`` (a completed
``request_id`` replays its stored receipt without executing; a live duplicate is
``TURN_IN_PROGRESS``; a different body is ``IDEMPOTENCY_CONFLICT``).

A dropped SSE connection is *not* a cancellation: the worker keeps running so
its business transaction and receipt still commit. Only the explicit stop
endpoint sets the in-process stop flag for the current worker.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncGenerator
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent.turn_progress import CallbackTurnProgressSink
from app.core.errors import AppError
from app.models.session import GuideSession
from app.services.graph_turn_service import GraphTurnService

PROTOCOL_VERSION = 1
#: Bounded so a stalled consumer can never grow the queue without limit. The
#: producer blocks briefly and then gives up once the client is known to be gone.
EVENT_QUEUE_MAXSIZE = 256
QUEUE_PUT_TIMEOUT_S = 0.05


class TurnCancellationRegistry:
    """In-process stop flags for the currently running worker of one request.

    A flag is created when a request's worker starts and released when it
    finishes. Only the explicit stop endpoint sets it; a dropped SSE connection
    does not. Nothing here is persisted.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str, str], threading.Event] = {}

    def register_new(self, owner_id: str, session_id: str, request_id: str) -> threading.Event | None:
        """Create the flag for a new worker, or ``None`` when one already runs.

        Returning ``None`` is what lets the transport refuse a duplicate request
        without starting a second worker or touching the running worker's flag.
        """
        with self._lock:
            key = (owner_id, session_id, request_id)
            if key in self._events:
                return None
            event = threading.Event()
            self._events[key] = event
            return event

    def get(self, owner_id: str, session_id: str, request_id: str) -> threading.Event | None:
        with self._lock:
            return self._events.get((owner_id, session_id, request_id))

    def request_stop(self, owner_id: str, session_id: str, request_id: str) -> bool:
        event = self.get(owner_id, session_id, request_id)
        if event is None:
            return False
        event.set()
        return True

    def release(self, owner_id: str, session_id: str, request_id: str) -> None:
        with self._lock:
            self._events.pop((owner_id, session_id, request_id), None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


cancellation_registry = TurnCancellationRegistry()


def _error_payload(exc: Exception) -> dict[str, Any]:
    """The business error the SSE ``error`` event carries, from any error shape."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None)
    retryable = getattr(exc, "retryable", None)
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        nested = detail["error"]
        code = code or nested.get("code")
        message = message or nested.get("message")
        if retryable is None:
            retryable = nested.get("retryable")
    return {
        "code": str(code or type(exc).__name__),
        "message": str(message if isinstance(message, str) else exc)[:200],
        "retryable": bool(retryable),
    }


class TurnStreamService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    # ---------------------------------------------------------------- envelope

    def _envelope(
        self,
        *,
        run_id: str,
        sequence: int,
        event_type: str,
        session_id: str,
        target_task_id: str | None = None,
        message_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "run_id": run_id,
            "sequence": sequence,
            "type": event_type,
            "session_id": session_id,
            "target_task_id": target_task_id,
            "message_id": message_id,
            "payload": payload or {},
        }

    def _require_session(self, session_id: str) -> GuideSession:
        """Ownership is validated before a run is started."""
        session = self.db.get(GuideSession, session_id)
        if not session or session.owner_id != self.owner_id:
            raise AppError(403, "SESSION_FORBIDDEN", "Session not found")
        return session

    # ------------------------------------------------------------- progress sink

    def _build_stream_sink(
        self,
        *,
        run_id: str,
        session_id: str,
        event_queue: queue.Queue,
        seq_holder: dict[str, int],
        task_id_holder: dict[str, str | None],
        message_id_holder: dict[str, str | None],
        plan_effect_holder: dict[str, str],
        stop_event: threading.Event,
        client_gone: threading.Event | None = None,
    ) -> CallbackTurnProgressSink:
        gone = client_gone or threading.Event()

        def bump_sequence() -> int:
            seq_holder["value"] += 1
            return seq_holder["value"]

        def enqueue(event: dict[str, Any]) -> None:
            # Never block forever: a dropped consumer would otherwise deadlock
            # the worker thread holding the queue.
            while not gone.is_set():
                try:
                    event_queue.put(event, timeout=QUEUE_PUT_TIMEOUT_S)
                    return
                except queue.Full:
                    continue

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            sequence = bump_sequence()
            enqueue(
                self._envelope(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=event_type,
                    session_id=session_id,
                    target_task_id=task_id_holder.get("task_id"),
                    message_id=message_id_holder.get("message_id"),
                    payload=payload,
                )
            )

        def on_phase(phase: str) -> None:
            emit("progress", {"phase": phase})

        def on_clarification(payload: dict[str, Any]) -> None:
            emit("clarification", payload)

        def on_plan_ready(plan: dict[str, Any]) -> None:
            # ``keep`` is the neutral default: a plan.ready event on a turn whose
            # terminal effect is "keep" must not be advertised as a replacement.
            plan_effect = plan.get("plan_effect", plan_effect_holder.get("plan_effect", "keep"))
            emit("plan.ready", {"plan": plan, "plan_effect": plan_effect})

        def on_answer_delta(delta: str, final: bool = False, replace: bool = False) -> None:
            if not delta and not final and not replace:
                return
            emit("answer.delta", {"delta": delta, "final": final, "replace": replace})

        return CallbackTurnProgressSink(
            on_phase=on_phase,
            on_clarification=on_clarification,
            on_plan_ready=on_plan_ready,
            on_answer_delta=on_answer_delta,
            on_should_stop=stop_event.is_set,
        )

    # ------------------------------------------------------------------- worker

    def _run_turn_worker(
        self,
        *,
        run_id: str,
        session_id: str,
        message: str,
        request_id: str,
        expected_task_id: str | None,
        expected_state_version: int,
        expected_session_version: int | None,
        view_context: dict[str, Any] | None,
        plan_selection: dict[str, Any] | None,
        handoff_recent_messages: list[dict[str, str]] | None,
        clarification_answer: dict[str, Any] | None,
        event_queue: queue.Queue,
        seq_holder: dict[str, int],
        task_id_holder: dict[str, str | None],
        message_id_holder: dict[str, str | None],
        plan_effect_holder: dict[str, str],
        stop_event: threading.Event,
        client_gone: threading.Event,
        registry_key: tuple[str, str, str],
        result_holder: dict[str, Any],
        error_holder: dict[str, Any],
        engine_bind: Any,
    ) -> None:
        db = _session_for(engine_bind)
        try:
            progress = self._build_stream_sink(
                run_id=run_id,
                session_id=session_id,
                event_queue=event_queue,
                seq_holder=seq_holder,
                task_id_holder=task_id_holder,
                message_id_holder=message_id_holder,
                plan_effect_holder=plan_effect_holder,
                stop_event=stop_event,
                client_gone=client_gone,
            )
            result = GraphTurnService(db, self.owner_id).process_turn(
                session_id=session_id,
                message=message,
                request_id=request_id,
                expected_task_id=expected_task_id,
                expected_state_version=expected_state_version,
                expected_session_version=expected_session_version,
                view_context=view_context,
                plan_selection=plan_selection,
                clarification_answer=clarification_answer,
                handoff_recent_messages=handoff_recent_messages,
                progress=progress,
                should_stop=stop_event.is_set,
            )
            task_id_holder["task_id"] = result.get("task_id")
            message_id_holder["message_id"] = result.get("assistant_message_id")
            plan_effect_holder["plan_effect"] = result.get("plan_effect", "keep")
            result_holder["result"] = result
            result_holder["terminal_sequence"] = seq_holder["value"] + 1
            result_holder["stopped"] = result.get("status") == "stopped"
        except Exception as exc:
            error_holder["error"] = exc
        finally:
            cancellation_registry.release(*registry_key)
            _offer(event_queue, None, client_gone)
            db.close()

        result = result_holder.get("result")
        if result and result["answer_status"] == "accepted" and not any(
            row["type"] == "memory" for row in result["action_results"]
        ):
            from app.services.automatic_memory_service import AutomaticMemoryService

            # The queue sentinel releases the SSE response before this worker
            # continues with an independent memory transaction.
            with _session_for(engine_bind) as memory_db:
                AutomaticMemoryService(memory_db, self.owner_id).process_turn(
                    session_id=session_id, request_id=request_id, trace_id=result["trace_id"],
                    message=message, reply=result["message"],
                )

    # ------------------------------------------------------------------ streaming

    async def stream_turn(
        self,
        session_id: str,
        message: str,
        request_id: str,
        expected_task_id: str | None,
        expected_state_version: int,
        expected_session_version: int | None,
        view_context: dict[str, Any] | None,
        plan_selection: dict[str, Any] | None = None,
        handoff_recent_messages: list[dict[str, str]] | None = None,
        clarification_answer: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        # Ownership check happens before any work is started; the request-level
        # receipt decides replay/conflict/in-progress inside the worker.
        self._require_session(session_id)
        run_id = f"run-{uuid4().hex[:12]}"
        registry_key = (self.owner_id, session_id, request_id)
        stop_event = cancellation_registry.register_new(*registry_key)
        if stop_event is None:
            # A worker for this request is already running in this process. The
            # transport starts no second worker and does not touch the running
            # worker's stop flag; the duplicate is refused explicitly.
            yield self._envelope(
                run_id=run_id,
                sequence=0,
                event_type="error",
                session_id=session_id,
                payload={
                    "code": "TURN_IN_PROGRESS",
                    "message": "Turn already in progress",
                    "retryable": True,
                },
            )
            return
        seq_holder = {"value": 0}
        task_id_holder: dict[str, str | None] = {"task_id": expected_task_id}
        message_id_holder: dict[str, str | None] = {"message_id": None}
        plan_effect_holder: dict[str, str] = {"plan_effect": "keep"}
        client_gone = threading.Event()
        event_queue: queue.Queue = queue.Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, Any] = {}

        worker = threading.Thread(
            target=self._run_turn_worker,
            kwargs={
                "run_id": run_id,
                "session_id": session_id,
                "message": message,
                "request_id": request_id,
                "expected_task_id": expected_task_id,
                "expected_state_version": expected_state_version,
                "expected_session_version": expected_session_version,
                "view_context": view_context,
                "plan_selection": plan_selection,
                "clarification_answer": clarification_answer,
                "handoff_recent_messages": handoff_recent_messages,
                "event_queue": event_queue,
                "seq_holder": seq_holder,
                "task_id_holder": task_id_holder,
                "message_id_holder": message_id_holder,
                "plan_effect_holder": plan_effect_holder,
                "stop_event": stop_event,
                "client_gone": client_gone,
                "registry_key": registry_key,
                "result_holder": result_holder,
                "error_holder": error_holder,
                "engine_bind": self.db.get_bind(),
            },
            daemon=True,
        )
        worker.start()

        try:
            yield self._envelope(
                run_id=run_id,
                sequence=0,
                event_type="accepted",
                session_id=session_id,
            )
            async for event in self._drain(event_queue, worker):
                yield event
        finally:
            # The client going away is *not* a cancellation: the worker keeps
            # running so its business transaction and receipt still commit. The
            # stop flag itself is released by the worker when it finishes.
            client_gone.set()

        terminal_sequence = result_holder.get("terminal_sequence") or (seq_holder["value"] + 1)
        if error_holder.get("error") is not None:
            yield self._envelope(
                run_id=run_id,
                sequence=terminal_sequence,
                event_type="error",
                session_id=session_id,
                payload=_error_payload(error_holder["error"]),
            )
            return

        result = result_holder.get("result")
        if not result:
            return
        if result_holder.get("stopped"):
            yield self._envelope(
                run_id=run_id,
                sequence=terminal_sequence,
                event_type="turn.stopped",
                session_id=session_id,
                target_task_id=result.get("task_id"),
                message_id=result.get("assistant_message_id"),
                payload=result,
            )
            return
        yield self._envelope(
            run_id=run_id,
            sequence=terminal_sequence,
            event_type="turn.completed",
            session_id=session_id,
            target_task_id=result.get("task_id"),
            message_id=result.get("assistant_message_id"),
            payload=result,
        )

    async def _drain(
        self,
        event_queue: queue.Queue,
        worker: threading.Thread,
    ) -> AsyncGenerator[dict[str, Any], None]:
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                if not worker.is_alive() and event_queue.empty():
                    return
                await asyncio.sleep(0.02)
                continue
            if event is None:
                return
            yield event

    # ---------------------------------------------------------------- stop API

    def request_stop(self, session_id: str, request_id: str) -> dict[str, Any]:
        """Set the in-process stop flag of the current worker for this request.

        There is no persisted run to look up and no recovery: a request that is
        not running right now is simply not found.
        """
        self._require_session(session_id)
        signalled = cancellation_registry.request_stop(self.owner_id, session_id, request_id)
        return {
            "session_id": session_id,
            "request_id": request_id,
            "status": "stopping" if signalled else "not_found",
            "cancelled": signalled,
        }


def _offer(
    event_queue: queue.Queue,
    item: Any,
    client_gone: threading.Event,
) -> None:
    """Best-effort terminal sentinel; never block a finishing worker forever."""
    while not client_gone.is_set():
        try:
            event_queue.put(item, timeout=QUEUE_PUT_TIMEOUT_S)
            return
        except queue.Full:
            continue


def _session_for(bind: Any) -> Session:
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=bind)()


__all__ = ["PROTOCOL_VERSION", "TurnCancellationRegistry", "TurnStreamService", "cancellation_registry"]
