"""Pure planning of a turn's durable conversation context.

The rules that decide "what questions are still open", "which refs were shown"
and "which goal is under discussion" are the existing ``agent.context`` helpers.
This module adds the *ordering and the decisions around them* — resolve display
refs, validate resolved questions, compile the gate's own questions, store or
drop the goal candidate, and merge the pending list once. It is pure: it returns
a plan and never writes.

``GuideService._execute_proposal`` and the Graph prepare nodes call the same
``plan_context_writes``; only the commit transaction calls ``apply_context_plan``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.agent import context as turn_context
from app.agent.clarification_state import PendingClarification
from app.agent.goal_router import (
    SLOT_FOCUS,
    SLOT_GOAL_RELATION,
    SLOT_MIXED,
    SLOT_QUESTIONS,
    SLOT_SUPPLY_GAP_CHOICE,
)
from app.agent.protocol import CandidateSet
from app.agent.state import TaskState


def gate_pending(
    decision: Any,
    proposal: Any,
    candidates: CandidateSet,
    *,
    conflict: str | None,
    focus_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The gate's own questions for the slots that blocked this turn.

    Wording is server-owned and keyed by the structured slot, and it is only
    asked once per slot. A question the model already asked for the same slot
    is kept as-is instead of being duplicated.
    """
    if decision is None:
        return []
    covered = {u.slot for u in getattr(proposal, "uncertainties", None) or []}
    slots = list(decision.missing_slots)
    if conflict:
        slots.append(SLOT_MIXED)
    pending: list[dict[str, Any]] = []
    for slot in dict.fromkeys(slots):
        if slot in covered:
            continue
        question = SLOT_QUESTIONS.get(slot)
        if not question:
            continue
        options: list[dict[str, str]] = []
        stored: list[dict[str, Any]] = []
        if slot == SLOT_FOCUS:
            for entry in focus_refs or []:
                ref = str(entry.get("ref") or "")
                label = str(entry.get("label") or "当前清单")
                options.append({"id": ref, "label": label})
                stored.append({"kind": "focus", "target_id": ref, "ref": ref, "name": label})
        item = PendingClarification(
            question_id="q-" + uuid4().hex[:12],
            question=question,
            options=options,
            slot=slot,
            candidates=stored,
        ).to_dict()
        candidate = getattr(decision, "candidate", None)
        item["candidate_ref"] = candidate.ref if candidate is not None else None
        pending.append(item)
    return pending


@dataclass
class ContextPlan:
    decision: Any = None
    new_pending: list[dict[str, Any]] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    displayed: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    candidate_to_store: dict[str, Any] | None = None
    clear_goal_candidate: bool = False
    clear_displayed: bool = False
    task_switched: bool = False
    changed: bool = False
    session_version_already_bumped: bool = False
    answer_parts: list[str] = field(default_factory=list)
    clarification_results: list[dict[str, Any]] = field(default_factory=list)
    base_state_version: int = 0


def _supply_gap_answer(
    context: dict[str, Any], proposal: Any, decision: Any
) -> tuple[bool, set[str]]:
    """Bind an explicit partial-supply choice to its original target and question."""
    previous = context.get("goal_candidate") or {}
    candidate = getattr(decision, "candidate", None)
    understanding = getattr(proposal, "understanding", None)
    if (
        not previous
        or candidate is None
        or understanding is None
        or understanding.intent != "buy"
        or understanding.new_goal is None
        or not previous.get("target_id")
        or candidate.target_id != previous.get("target_id")
        or candidate.target_kind != previous.get("target_kind")
    ):
        return False, set()

    pending = [
        item
        for item in context.get("pending_clarifications", [])
        if item.get("slot") == SLOT_SUPPLY_GAP_CHOICE
        and item.get("candidate_ref") == previous.get("ref")
    ]
    question_ids = {
        item["question_id"]
        for item in pending
        if item.get("question_id") in proposal.resolved_questions
    }
    return bool(pending), question_ids


def plan_context_writes(
    *,
    context: dict[str, Any],
    session: Any,
    proposal: Any,
    candidates: CandidateSet,
    decision: Any,
    state: TaskState | None,
    previous_task_id: str | None,
    action_results: list[dict[str, Any]],
    business_pending: list[dict[str, Any]] | None = None,
    gate_pending_items: list[dict[str, Any]] | None = None,
    committed_status: str = "committed",
    new_pending: list[dict[str, Any]] | None = None,
) -> ContextPlan:
    """Compute everything the commit transaction must persist for the context.

    ``new_pending`` is the prepare-computed uncertainty questions (the legacy
    caller builds them just above); the gate's own questions are appended below,
    in the same order as the original block.
    """
    displayed = turn_context.resolve_display_refs(proposal.display_refs, candidates)
    turn_context.check_resolved_questions(proposal.resolved_questions, context)
    same_supply_target, supply_gap_answers = _supply_gap_answer(
        context, proposal, decision
    )
    new_pending = list(new_pending or [])
    activated = any(
        r.get("status") == committed_status and r.get("verb") == "add"
        for r in action_results
    )
    candidate_to_store = None
    if decision is not None and decision.candidate is not None:
        stored = decision.candidate.model_copy(
            update={
                "task_id": getattr(state, "task_id", None) or previous_task_id,
                "plan_version": getattr(state, "state_version", None),
                "missing_slots": [] if activated else list(decision.candidate.missing_slots),
            }
        )
        if (
            not activated
            and proposal.understanding is not None
            and proposal.understanding.new_goal is not None
            and not same_supply_target
        ):
            stored.ref = "goal-" + uuid4().hex[:12]
        decision = decision.model_copy(update={"candidate": stored})
        candidate_to_store = stored

    committed_refs = {
        r.get("candidate_ref")
        for r in action_results
        if r.get("status") == committed_status
    }
    task_switched = bool(previous_task_id) and session.current_task_id != previous_task_id
    resolved = set(proposal.resolved_questions)
    for question in context.get("pending_clarifications", []):
        if (
            question.get("slot") == SLOT_SUPPLY_GAP_CHOICE
            and question.get("question_id") not in supply_gap_answers
        ):
            resolved.discard(question["question_id"])
    understanding = proposal.understanding
    if decision is not None and decision.candidate is not None:
        answered_slots: set[str] = set()
        if understanding is not None and understanding.changes is not None:
            answered_slots = set(understanding.changes.changed_fields()) - set(
                decision.missing_slots
            )
        for question in context.get("pending_clarifications", []):
            if (
                question.get("slot") != SLOT_SUPPLY_GAP_CHOICE
                and question.get("candidate_ref") == decision.candidate.ref and (
                activated or question.get("slot") in answered_slots
                )
            ):
                resolved.add(question["question_id"])
    if activated:
        # An add can resolve an unbound focus question because it determines
        # the target. An explicit append/switch add also resolves the unbound
        # relation question. Failed or ambiguous turns never reach this branch.
        for question in context.get("pending_clarifications", []):
            if question.get("candidate_ref") is None and (
                question.get("slot") == SLOT_FOCUS
                or (
                    decision is not None
                    and decision.relation in ("append", "switch")
                    and question.get("slot") == SLOT_GOAL_RELATION
                )
            ):
                resolved.add(question["question_id"])
    base_pending = [] if task_switched else list(context.get("pending_clarifications", []))
    new_pending.extend(business_pending or [])
    new_pending.extend(gate_pending_items or [])
    if candidate_to_store is not None:
        for item in new_pending:
            item["candidate_ref"] = candidate_to_store.ref
    previous_candidate = context.get("goal_candidate") or {}
    candidate_changed = bool(
        candidate_to_store is not None
        and previous_candidate.get("ref") != candidate_to_store.ref
    )
    pending_context = context
    if candidate_changed:
        pending_context = {
            **context,
            "pending_clarifications": [
                item
                for item in context.get("pending_clarifications", [])
                if not item.get("candidate_ref")
                or (
                    same_supply_target
                    and item.get("slot") == SLOT_SUPPLY_GAP_CHOICE
                    and item.get("question_id") not in resolved
                )
            ],
        }
    pending_list = turn_context.merge_pending(
        context=pending_context,
        new_pending=new_pending,
        resolved_questions=list(resolved),
        committed_refs=committed_refs,
        task_switched=task_switched,
    )
    answer_parts: list[str] = []
    clarification_results: list[dict[str, Any]] = []
    for item in new_pending:
        answer_parts.append(item["question"])
        if item.get("options"):
            answer_parts.append(
                "\n".join(f"{i + 1}. {opt['label']}" for i, opt in enumerate(item["options"]))
            )
        clarification_results.append(
            {
                "type": "clarification",
                "slot": item.get("slot"),
                "status": "needs_clarification",
                "saved": True,
                "reply_ok": True,
            }
        )
    clear_displayed = bool(context.get("displayed_candidates")) and not displayed and any(
        query.kind == "compare" for query in proposal.queries
    )
    changed = bool(
        clear_displayed
        or new_pending
        or resolved
        or displayed
        or pending_list != base_pending
        or task_switched
        or candidate_to_store is not None
        or activated
    )
    return ContextPlan(
        decision=decision,
        new_pending=new_pending,
        pending=pending_list,
        displayed=displayed,
        resolved=sorted(resolved),
        candidate_to_store=(
            candidate_to_store.model_dump() if candidate_to_store is not None else None
        ),
        clear_goal_candidate=bool(task_switched),
        clear_displayed=clear_displayed,
        task_switched=task_switched,
        changed=changed,
        answer_parts=answer_parts,
        clarification_results=clarification_results,
        base_state_version=int(getattr(state, "state_version", 0) or 0),
    )


def apply_context_plan(
    *,
    db: Any,
    session: Any,
    context: dict[str, Any],
    plan: ContextPlan,
    session_version_already_bumped: bool = False,
) -> dict[str, Any]:
    """Persist a plan's conversation state. Called only inside the commit txn."""
    if not plan.changed:
        return context
    if not session_version_already_bumped:
        session.session_version = int(session.session_version or 0) + 1
    for item in plan.pending:
        item["base_session_version"] = session.session_version
        item["base_state_version"] = plan.base_state_version
    context = dict(context)
    context["pending_clarifications"] = plan.pending
    if plan.clear_displayed:
        context["displayed_candidates"] = []
    elif plan.displayed:
        context["displayed_candidates"] = plan.displayed
    elif plan.task_switched:
        context["displayed_candidates"] = []
    if plan.candidate_to_store is not None:
        context["goal_candidate"] = plan.candidate_to_store
    elif plan.clear_goal_candidate:
        context.pop("goal_candidate", None)
    turn_context.save_context(db, session, context)
    return context


__all__ = [
    "ContextPlan",
    "apply_context_plan",
    "gate_pending",
    "plan_context_writes",
]
