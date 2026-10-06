"""Pure adapters between the Graph commit receipt and the HTTP turn contract.

The response builders are **pure**: no database access, no trace write, no
transaction, no clock, no model. They produce the single response saved as the
receipt and published by the SSE transport:

``build_graph_response``
    Assemble the complete HTTP response body from the same inputs
    ``turn_commit._build_full_response`` already has, delegating every wording and
    plan decision to the shared ``app.agent.responses`` builders. It fixes three
    contract bugs the receipt used to carry (see below) without duplicating any
    business rule.

``prepare_graph_message``
    Compose the turn's assistant wording with the *existing* server-authored
    helpers (``plan_summary_message``, which itself carries the gap wording and
    the headcount note) instead of re-inventing a summary. It is the single
    source for the string that must reach **both** the response body and the
    persisted assistant message, so the two can never differ.

Contract fixes carried here (review findings #1/#2/#5):

* ``status``/``purchase_step`` come from the real task step via
  ``build_response``; the vocabulary the rest of the system uses is preserved:
  a stopped turn is ``stopped`` (HTTP and SSE both key on it), a spent deadline
  is ``answer_status="failed"`` with the real ``status``/``purchase_step``, and
  a plain business refusal keeps the real task step. The literal ``refused``
  (outside ``Step``/``AnswerStatus``) is never emitted.
* ``trace_id`` is always a real id: the runtime's own when R4 supplies one, else
  generated once here and written back onto the runtime, so the receipt and the
  eventual trace row share it. No trace row is written by this module.
* ``model_mode``/``business_data_mode`` keep the legacy precedence
  (runtime override, else configuration).

Wiring order (owned by the integration step, not here)::

    message = prepare_graph_message(kind=staged["kind"], ...)
    body = build_graph_response(..., message=message, ...)
    # persist the assistant message with content=message -- the same string
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agent.turn_primitives import TIMEOUT_CODE
from app.agent.responses import build_response, plan_summary_message
from app.agent.goal_router import REASON_MEAL_PREFERENCES
from app.schemas.goal import TurnDecision
from app.services.session_actions import available_actions_for_task

#: The refusal code the guard records for a stopped generation.
STOPPED_CODE = "STOPPED"

#: The transport-level value of that outcome. ``Step``, ``AnswerStatus`` and the
#: SSE ``turn.stopped`` event all speak this lowercase form; ``STOPPED`` above is
#: an internal refusal code and is never a response value.
STOPPED_STATUS = "stopped"

#: Statuses a plan write may report on an action receipt.
_COMMITTED_ACTION_STATUSES = ("committed", "completed")

#: Stable keys every SSE ``turn.completed`` / recovery ``result`` must carry.
TERMINAL_PAYLOAD_FIELDS: tuple[str, ...] = (
    "request_id",
    "session_id",
    "task_id",
    "state_version",
    "session_version",
    "status",
    "answer_status",
    "message",
    "plan",
    "plan_effect",
    "pending_clarifications",
    "available_actions",
)


def ensure_terminal_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Guarantee the frozen terminal field set; values may be empty or null."""
    pending = body.get("pending_clarifications")
    if pending is None:
        pending_single = body.get("pending_clarification")
        pending = [pending_single] if pending_single else []
    normalized = {
        "request_id": body.get("request_id", ""),
        "session_id": body.get("session_id", ""),
        "task_id": body.get("task_id"),
        "state_version": body.get("state_version", 0),
        "session_version": body.get("session_version", 0),
        "status": body.get("status", "understanding"),
        "answer_status": body.get("answer_status", "accepted"),
        "message": body.get("message", ""),
        "plan": body.get("plan"),
        "plan_effect": body.get("plan_effect", "keep"),
        "pending_clarifications": list(pending),
        "available_actions": body.get("available_actions") or ["send_message"],
    }
    merged = dict(body)
    merged.update(normalized)
    return merged


def new_trace_id() -> str:
    """A fresh trace id in the legacy format (``workflow.py`` mints the same shape)."""
    return f"trace-{uuid4().hex[:12]}"


def resolve_trace_id(runtime: Any) -> str:
    """The turn's trace id, generated once and pinned on the runtime if absent.

    The response body and the trace row must name the same id, and the id must be
    stable across a replay, so it is fixed here rather than re-derived per call.
    """
    trace_id = getattr(runtime, "trace_id", None)
    if trace_id:
        return str(trace_id)
    trace_id = new_trace_id()
    try:
        runtime.trace_id = trace_id
    except Exception:  # pragma: no cover - a frozen context object keeps the value local
        pass
    return trace_id


def outcome_codes(
    guard: dict[str, Any] | None,
    staged: dict[str, Any] | None,
    action_results: list[dict[str, Any]] | None,
) -> set[str]:
    """Every refusal code this turn carries, wherever the commit chain recorded it.

    The guard verdict, the staged error (``refuse_prepare``) and the action
    receipts (the blocked mutation) each carry a code; the transport mapping below
    must see all of them, exactly as ``service.py`` reads the codes off its
    failures.
    """
    codes: set[str] = set()
    guard_code = (guard or {}).get("code")
    if guard_code:
        codes.add(str(guard_code))
    staged = staged or {}
    error = staged.get("error") or {}
    if error.get("code"):
        codes.add(str(error["code"]))
    for result in action_results or []:
        if result.get("code"):
            codes.add(str(result["code"]))
    return codes


def _turn_result_fields(
    base: dict[str, Any],
    codes: set[str],
) -> tuple[str, str]:
    """``(status, answer_status)`` for this turn, from the shared builder.

    ``build_response`` already computed the honest defaults: the real task step
    (``understanding``/``awaiting_confirmation``/…) for both fields, or
    ``accepted`` for a taskless answer. Only the two transport-level outcomes are
    refined, with the same precedence legacy ``service.py`` uses:

    * stopped generation -> ``status`` and ``answer_status`` are ``stopped``;
    * spent deadline -> ``answer_status`` is ``failed`` (the real step stays in
      ``status``/``purchase_step``).

    A plain business refusal is *not* rewritten: it keeps the task's real step,
    so no client sees a status outside ``Step``/``AnswerStatus``.
    """
    status = str(base["status"])
    answer_status = str(base["answer_status"])
    if STOPPED_CODE in codes:
        return STOPPED_STATUS, STOPPED_STATUS
    if TIMEOUT_CODE in codes:
        return status, "failed"
    return status, answer_status


def build_graph_response(
    task_state: Any,
    session: Any,
    task: Any,
    runtime: Any,
    run_state: dict[str, Any] | None,
    staged: dict[str, Any] | None,
    guard: dict[str, Any] | None,
    *,
    user_msg: Any,
    assistant: Any,
    plan: dict[str, Any] | None,
    message: str,
    committed: bool,
    allowed: bool,
    action_results: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """The complete HTTP body for one Graph turn. Pure: no DB, no trace write.

    Same inputs as ``turn_commit._build_full_response``: the post-commit task
    state/session/task rows, the runtime (for ids, modes and the trace id), the
    run state (for the read-only decision echo), the staged effect and the guard
    verdict. ``message`` must be the string ``prepare_graph_message`` produced and
    the same one persisted as the assistant message.
    """
    from app.core.config import get_settings

    settings = get_settings()
    decision = None
    raw_decision = ((run_state or {}).get("turn") or {}).get("decision")
    if raw_decision:
        decision = TurnDecision.model_validate(raw_decision)

    staged = staged or {}
    guard = guard or {}
    pending = list(staged.get("pending") or [])
    pending_payload = next(iter(pending), None)
    effect = (
        "clear"
        if guard.get("allowed") and staged.get("plan_effect") == "clear"
        else "replace" if plan else "keep"
    )
    codes = outcome_codes(guard, staged, action_results)
    constrained_validation_failed = (
        "VALIDATION_FAILED" in codes
        and decision is not None
        and decision.goal is not None
        and bool(decision.goal.constraints.specification)
    )
    status_override = (
        "degraded" if "NO_FEASIBLE_MEAL" in codes or constrained_validation_failed else
        "clarifying" if decision and decision.reason_code == REASON_MEAL_PREFERENCES else None
    )

    response = build_response(
        task_state,
        session,
        message,
        plan_effect=effect,
        pending_clarification=pending_payload,
        decision=decision,
        status_override=status_override,
    )
    status, answer_status = _turn_result_fields(
        response, codes
    )

    receipts = [dict(result) for result in (action_results or [])]
    for index, receipt in enumerate(receipts):
        # Same server-owned action identity the loop path assigns.
        receipt.setdefault("action_id", f"a{index + 1}")

    response.update(
        {
            "request_id": runtime.request_id,
            "session_id": runtime.session_id,
            "task_id": session.current_task_id,
            "state_version": getattr(task_state, "state_version", 0),
            "session_version": session.session_version,
            "status": status,
            "answer_status": answer_status,
            "purchase_step": response.get("purchase_step", "none"),
            "committed": committed,
            "allowed": allowed,
            "guard_code": guard.get("code"),
            "plan": response.get("plan") or (plan if plan else None),
            "plan_effect": effect,
            "pending_clarification": pending_payload,
            "pending_clarifications": pending,
            "action_results": receipts,
            "available_actions": available_actions_for_task(task) if task else ["send_message"],
            "user_message_id": getattr(user_msg, "message_id", None),
            "assistant_message_id": getattr(assistant, "message_id", None),
            "message_sequence": getattr(assistant, "sequence", None),
            "trace_id": resolve_trace_id(runtime),
            "model_mode": getattr(runtime, "model_mode", None) or settings.llm_mode,
            "business_data_mode": getattr(runtime, "business_data_mode", None)
            or settings.business_data_mode,
            "current_editable_task_id": session.current_task_id,
        }
    )
    return ensure_terminal_payload(response)


def prepare_graph_message(
    *,
    kind: str,
    model_reply: str = "",
    plan: dict[str, Any] | None = None,
    plan_effect: str = "keep",
    action_results: list[dict[str, Any]] | None = None,
    pending: list[dict[str, Any]] | None = None,
    displayed: list[dict[str, Any]] | None = None,
    new_group_ids: set[str] | None = None,
    refusal_message: str | None = None,
) -> str:
    """The turn's assistant wording, composed with the existing helpers.

    The composition follows ``service.py::_execute_proposal``: what the server
    really did is what the shopper is told, and the model's prose is only kept
    where the turn carried no write claim.

    * ``mutation``/``refuse`` (a turn that claimed a write, or was refused):
      the model's reply is dropped. The receipts' own messages, the shared
      ``plan_summary_message`` (item count, total, gaps and the headcount note)
      carry the turn.
    * ``clarify``/``answer``: the model's reply/question is kept, followed by the
      server-authored question text, numbered options and the displayed names.
    * ``refusal_message``: the server's own refusal wording, used verbatim —
      never the prepared success sentence.

    ``new_group_ids`` scopes the headcount note to the groups this turn really
    committed; when omitted it is derived from the receipts' ``add`` actions, the
    same rule ``service.py`` applies.
    """
    parts: list[str] = []
    claimed_write = kind in ("mutation", "refuse") or bool(refusal_message)
    reply = "" if claimed_write else str(model_reply or "").strip()
    if reply:
        parts.append(reply)

    for item in pending or []:
        question = str((item or {}).get("question") or "").strip()
        if question:
            parts.append(question)
        options = list((item or {}).get("options") or [])
        if options:
            parts.append(
                "\n".join(
                    f"{index + 1}. {option.get('label') or option.get('id')}"
                    for index, option in enumerate(options)
                )
            )

    names = [
        str(entry.get("name"))
        for entry in displayed or []
        if entry and entry.get("name")
    ]
    if names:
        parts.append("\n".join(f"{index + 1}. {name}" for index, name in enumerate(names)))

    if refusal_message:
        parts.append(str(refusal_message).strip())

    receipts = action_results or []
    parts.extend(
        str(receipt.get("message"))
        for receipt in receipts
        if receipt.get("type") == "mutation"
        and receipt.get("status") in _COMMITTED_ACTION_STATUSES
        and receipt.get("message")
    )

    if plan and (plan_effect or "keep") == "replace":
        if new_group_ids is None:
            new_group_ids = {
                str(receipt.get("group_id"))
                for receipt in receipts
                if receipt.get("verb") == "add" and receipt.get("group_id")
            }
        parts.append(plan_summary_message(plan, new_group_ids=set(new_group_ids)))

    return "\n".join(part for part in parts if part)


__all__ = [
    "STOPPED_CODE",
    "STOPPED_STATUS",
    "TERMINAL_PAYLOAD_FIELDS",
    "build_graph_response",
    "ensure_terminal_payload",
    "new_trace_id",
    "outcome_codes",
    "prepare_graph_message",
    "resolve_trace_id",
]
