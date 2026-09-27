"""Pure turn semantics shared by the LangGraph chain.

Budget caps, the turn snapshot, request construction, gate evaluation and the
cooperative turn clock live here. Orchestration (the retired ``run_loop`` and
``GuideService``) is gone; only the symbols the graph and transport adapter still
need remain.
"""

from __future__ import annotations

import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.agent.goal_router import GateFacts, MutationView, decide_turn
from app.agent.protocol import (
    CandidateSet,
    SemanticProposal,
    SemanticProtocolError,
    proposal_schema,
)

#: No configuration may raise a request above this. A model call is the
#: expensive, failure-prone step; the request makes at most one understanding
#: call, plus one grounded answer call when a retrieve round ran. There is no
#: repair or re-planning loop.
HARD_MAX_MODEL_CALLS = 3

#: Optional provider capability, looked up by name and never probed with a
#: ``TypeError`` fallback — that would swallow a real bug raised inside
#: ``propose``. A provider that implements it is told how many seconds of the
#: turn's budget are left before each call, so its own transport timeout can be
#: shrunk to fit; one that does not keeps working through ``propose(request)``.
CALL_TIMEOUT_CAPABILITY = "set_call_timeout"

#: The turn's own time budget ran out. It is a server-side failure and is
#: reported as itself, all the way to the API response: never as a shopper
#: cancellation and never as a success. The turn entry, the read port and the
#: tool boundary all speak it, so it is defined here, where it is detected.
TIMEOUT_CODE = "TURN_DEADLINE_EXCEEDED"

#: Fallback for a missing, non-finite or non-positive turn budget. The setting
#: itself is the default; this only guards a bad configuration value.
DEFAULT_TURN_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True)
class TurnSnapshot:
    """Everything the model is allowed to be told, as plain values.

    Assembled by ``agent.context`` from the session, task and resolved context.
    Nothing here is an ORM object, and nothing here can write.
    """

    turn_mode: str
    message: str
    requirements: dict[str, Any] = field(default_factory=dict)
    #: Where the shopper entered from: ``page`` and, on a category page, the
    #: ``category_id``. It is server-owned context, not an instruction, and it is
    #: retained separately from subsequent navigation and has no decision chain.
    entry_context: dict[str, Any] = field(default_factory=dict)
    view_context: dict[str, Any] = field(default_factory=dict)
    current_plan: dict[str, Any] | None = None
    purchase_summary: dict[str, Any] | None = None
    pending_clarification: dict[str, Any] | None = None
    pending_clarifications: list[dict[str, Any]] = field(default_factory=list)
    displayed_candidates: list[dict[str, Any]] = field(default_factory=list)
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    #: The refs the model may name as ``focus_ref`` this turn (server-issued).
    focus_refs: list[dict[str, Any]] = field(default_factory=list)
    #: The goal under discussion, when the session holds one that is still bound
    #: to the current task and plan version. Plain data, never an ORM object.
    goal_candidate: dict[str, Any] | None = None


@dataclass(frozen=True)
class LoopBudget:
    """Hard limits for one request. The graph clamps these; it never exceeds them."""

    max_model_calls: int = 2
    max_lookups: int = 2


def _monotonic() -> float:
    """The turn clock. Indirection exists so a test can drive it without sleeping."""
    return time.monotonic()


def turn_deadline_at(now: float) -> float:
    """The absolute instant one semantic turn must stop starting new work.

    This is a *cooperative* budget: it is checked at the turn's checkpoints (before
    and after each model call, around reads, before the proposal is executed and
    before each plan mutation is persisted). It cannot interrupt a synchronous call
    that is already in flight — so it bounds the checkpoints, not the wall clock,
    and it is never reported as a shopper cancellation.
    """
    from app.core.config import get_settings

    seconds = float(
        getattr(get_settings(), "semantic_turn_timeout_seconds", DEFAULT_TURN_TIMEOUT_SECONDS)
    )
    if not math.isfinite(seconds) or seconds <= 0:
        seconds = DEFAULT_TURN_TIMEOUT_SECONDS
    return now + seconds


def clamp_limits(budget: LoopBudget) -> tuple[int, int]:
    """Clamp one request's budget to the hard ceilings.

    Returned as ``(max_model_calls, lookup_limit)``. Every node derives its
    limits here, so no caller can raise the caps.
    """
    max_calls = max(1, min(int(budget.max_model_calls), HARD_MAX_MODEL_CALLS))
    lookup_limit = max(0, int(budget.max_lookups))
    return max_calls, lookup_limit


def build_request(
    snapshot: TurnSnapshot,
    candidates: CandidateSet,
    *,
    previous_error: SemanticProtocolError | None = None,
    query_results: list[dict[str, Any]] | None = None,
    read_only: bool = False,
) -> dict[str, Any]:
    """The exact, bounded payload one model call receives.

    Facts the server already fetched this turn travel as ``query_results`` with
    an explicit outcome for each; the model answers from them in its own words.

    The candidate view is rebuilt from the live ``CandidateSet`` on every round,
    so a ref the read-only port just allocated is referenceable in the very next
    request. The plan and the displayed order are not rebuilt: they come from the
    snapshot and are copied out, so a later round can never rewrite what the
    shopper saw.
    """
    view = candidates.model_view()
    return {
        "turn_mode": snapshot.turn_mode,
        "read_only": read_only,
        "user_message": snapshot.message,
        "requirements": deepcopy(snapshot.requirements or {}),
        "entry_context": deepcopy(snapshot.entry_context or {}),
        "view_context": deepcopy(snapshot.view_context or {}),
        "current_plan": deepcopy(snapshot.current_plan),
        "query_results": list(query_results or []),
        # The live candidate view, minus the plan (which is its own field above).
        "candidates": {key: value for key, value in view.items() if key != "current_plan"},
        # Server-issued references, and the goal under discussion. Both are
        # server-owned: the model may point at one, never invent one.
        "focus_refs": deepcopy(list(snapshot.focus_refs or [])),
        "goal_candidate": deepcopy(snapshot.goal_candidate),
        "purchase_summary": deepcopy(snapshot.purchase_summary),
        "pending_clarification": deepcopy(snapshot.pending_clarification),
        "pending_clarifications": deepcopy(list(snapshot.pending_clarifications or [])),
        "displayed_candidates": deepcopy(list(snapshot.displayed_candidates or [])),
        "recent_messages": [
            {"role": m.get("role"), "content": m.get("content")}
            for m in (snapshot.recent_messages or [])[-6:]
        ],
        "previous_error": (
            {"code": previous_error.code, "message": previous_error.message}
            if previous_error
            else None
        ),
        "protocol": proposal_schema(),
    }


def gate_facts(snapshot: TurnSnapshot) -> GateFacts:
    """The server's own facts for the gate, from the turn's snapshot.

    Pure and total: a candidate that cannot be read back (an old shape, a
    corrupted payload) simply is not a candidate.
    """
    from app.schemas.goal import GoalCandidate

    candidate = None
    if snapshot.goal_candidate:
        try:
            candidate = GoalCandidate.model_validate(snapshot.goal_candidate)
        except Exception:  # pragma: no cover - defensive: an unusable candidate
            candidate = None
    plan = snapshot.current_plan or {}
    groups = [str(g.get("ref")) for g in (plan.get("groups") or []) if g.get("ref")]
    return GateFacts(
        has_active_plan=bool(plan.get("items")),
        candidate=candidate,
        focus_refs=tuple(snapshot.focus_refs or ()),
        plan_target_refs=tuple(groups),
        has_pending_question=bool(snapshot.pending_clarifications),
    )


def evaluate_gate(
    snapshot: TurnSnapshot,
    proposal: SemanticProposal,
    candidates: CandidateSet,
) -> Any:
    """The turn's decision: what may happen next, and what may not.

    The mutation summary is built from the *server's* candidate kinds, so a model
    cannot describe an add of a plan row as a new goal (or the reverse) and have
    the gate believe it.
    """
    views = []
    for mutation in proposal.mutations:
        ref = mutation.candidate_ref or mutation.target_ref
        resolved = candidates.resolve(ref) if ref else None
        views.append(
            MutationView(
                verb=mutation.verb,
                field=mutation.field,
                ref=ref,
                ref_kind=(resolved.kind if resolved is not None else ""),
                ref_target_id=(resolved.target_id if resolved is not None else ""),
                ref_name=(resolved.name if resolved is not None else ""),
                switch_goal=bool(mutation.switch_goal),
            )
        )
    return decide_turn(
        proposal.understanding,
        gate_facts(snapshot),
        mutations=views,
        has_read_requests=bool(proposal.lookups or proposal.queries),
        has_questions=bool(proposal.uncertainties),
    )


__all__ = [
    "CALL_TIMEOUT_CAPABILITY",
    "DEFAULT_TURN_TIMEOUT_SECONDS",
    "HARD_MAX_MODEL_CALLS",
    "LoopBudget",
    "TIMEOUT_CODE",
    "TurnSnapshot",
    "build_request",
    "clamp_limits",
    "evaluate_gate",
    "gate_facts",
    "turn_deadline_at",
]
