"""Turn context: everything the loop is told, assembled from real stored state.

This module is the ORM-side adapter. It reads the session, the task, the resolved
context and the durable semantic context, and produces:

* a bounded **candidate set** — the opaque refs the model may reference, built
  from the catalog, the scenario fixture and the plan actually on screen;
* a **snapshot** — plain values handed to the pure loop (``agent.loop``);
* the **displayed-candidate** restoration, so "第二个" keeps pointing at what the
  shopper really saw;
* the durable **pending questions**: loading them, merging this turn's new ones,
  and saving the result.

Two lists stay deliberately separate: the *model candidates* of this turn and the
*candidates the shopper was actually shown*. Collapsing them is how a model ends
up numbering options the user never saw.

Pending questions have exactly one persistence source — this module — and the API
restores from the same functions, so a resumed session sees the questions the
turn actually asked.

Nothing here is imported by the loop: the loop receives plain data, never an ORM
object and never a session.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent.clarification_state import PendingClarification
from app.agent.turn_primitives import TurnSnapshot
from app.agent.protocol import (
    MAX_GROUPS,
    MAX_ITEMS,
    MAX_SCENARIOS,
    CandidateSet,
    SemanticProtocolError,
    Uncertainty,
)
from app.models.session import GuideSemanticContext, GuideSession, GuideTask
from app.schemas.goal import GoalCandidate
from app.services.catalog_service import CatalogService
from app.services.session_actions import effective_status
from app.services.shopping_plan_service import load_scenarios
from app.services.template_matcher import dish_display_name


def build_candidate_set(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    state: Any = None,
) -> CandidateSet:
    """Assemble the candidate list from real, *earned* server data only.

    Nothing a shopper could act on is handed over just because of its position in
    a table: there is no "first N dishes / first N products" seeding. An item
    becomes referenceable only by being

    * the plan the shopper is already looking at,
    * the recipe this task is actually built on,
    * something the shopper was really shown before, or
    * a row a read-only lookup retrieved this turn.

    Scenario metadata is the one exception, and only because it is a small
    closed fixture with no prices and no stock: it exists so the server can offer
    the open scenario (e.g. 火锅) as a real target.
    """
    del delivery_zone_id  # reserved: supply context is already resolved upstream
    candidates = CandidateSet()

    cancelled = state is not None and state.current_step == "cancelled"
    active_id = getattr(state, "active_template_id", None) if not cancelled else None
    if active_id:
        # The dish the shopper is already working on is the one most likely to be
        # referenced again, so it must never fall off the list.
        dish = _dish_by_id(db, str(active_id))
        if dish:
            candidates.allocate("dish", str(active_id), dish_display_name(dish))

    for scenario in load_scenarios()[:MAX_SCENARIOS]:
        scenario_id = scenario.get("scenario_id")
        if not scenario_id:
            continue
        candidates.allocate(
            "scenario", str(scenario_id), str(scenario.get("name") or scenario_id)
        )

    plan = getattr(state, "plan", None) if state is not None and not cancelled else None
    if isinstance(plan, dict):
        for target in (plan.get("targets") or [])[:MAX_GROUPS]:
            group_id = target.get("group_id")
            if not group_id:
                continue
            candidates.allocate(
                "group",
                str(target.get("target_id") or group_id),
                str(target.get("name") or group_id),
                group_id=str(group_id),
                scope=str(plan.get("plan_id") or ""),
                target_kind=str(target.get("kind") or ""),
            )
        for item in (plan.get("items") or [])[:MAX_ITEMS]:
            sku_id = item.get("sku_id")
            if not sku_id:
                continue
            candidates.allocate("item", str(sku_id), str(item.get("name") or sku_id),
                                scope=str(plan.get("plan_id") or ""))

    return candidates


def restore_displayed_references(
    db: Session,
    candidates: CandidateSet,
    *,
    context: dict[str, Any],
    store_id: str,
) -> None:
    """Re-issue refs for the things the shopper was actually shown.

    Only real, still-sellable dishes/products are restored. Groups, items and
    scenarios must come from the *current* plan or the server fixture —
    an old target is never resurrected from saved text.

    The target of the goal under discussion is restored the same way: it is a
    real, still-sellable target this turn, or the candidate cannot be built.
    """
    remembered = list(context.get("displayed_candidates", []))
    for question in context.get("pending_clarifications", []):
        remembered.extend(question.get("candidates", []))
    candidate = context.get("goal_candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("target_id"), str):
        remembered.append(
            {
                "kind": candidate.get("target_kind") or "",
                "target_id": candidate["target_id"],
            }
        )
    catalog = CatalogService(db, store_id)
    for item in remembered:
        kind, target_id = item.get("kind"), item.get("target_id")
        if kind == "dish":
            dish = _dish_by_id(db, target_id)
            if dish:
                candidates.allocate(kind, target_id, dish_display_name(dish))
        elif kind == "product":
            product = catalog.get_product(target_id)
            if product and product.get("sellable"):
                candidates.allocate(kind, product.get("sku_id") or target_id,
                                    product.get("name_zh") or product.get("name") or "")


def goal_candidate_from_context(
    context: dict[str, Any],
    *,
    task_id: str | None,
    plan_version: int | None,
) -> GoalCandidate | None:
    """The goal under discussion, if it is still bound to this task and plan.

    A candidate carries the task and plan version it was agreed against. When
    either has moved on the candidate is stale: a stale candidate may not fill
    slots or activate, so it is dropped here rather than trusted later.
    """
    raw = context.get("goal_candidate")
    if not isinstance(raw, dict):
        return None
    try:
        candidate = GoalCandidate.model_validate(raw)
    except Exception:
        return None
    if candidate.is_stale(task_id=task_id, plan_version=plan_version):
        return None
    return candidate


def build_focus_refs(
    candidates: CandidateSet,
    *,
    state: Any = None,
    context: dict[str, Any] | None = None,
    task_id: str | None = None,
    plan_version: int | None = None,
) -> list[dict[str, Any]]:
    """Every ref the model may name as ``focus_ref``, with its server-side kind.

    The model points at one of these; it never invents a ref, and an unknown ref
    is refused by the gate rather than resolved by guessing which goal or row the
    shopper meant.
    """
    context = context or {}
    refs: list[dict[str, Any]] = []
    plan = (
        getattr(state, "plan", None)
        if state is not None and state.current_step != "cancelled"
        else None
    )
    if isinstance(plan, dict) and plan.get("items"):
        names = [str(t.get("name")) for t in plan.get("targets") or [] if t.get("name")]
        refs.append(
            {
                "ref": "active-goal-1",
                "kind": "active_goal",
                "label": "、".join(dict.fromkeys(names)) or "当前清单",
            }
        )
    for candidate_ref in candidates.by_kind("group", "item"):
        refs.append(
            {
                "ref": candidate_ref.ref,
                "kind": "plan_target",
                "label": candidate_ref.name or candidate_ref.target_id,
            }
        )
    candidate = goal_candidate_from_context(
        context, task_id=task_id, plan_version=plan_version
    )
    if candidate is not None:
        refs.append(
            {
                "ref": candidate.ref,
                "kind": "pending_goal",
                "label": candidate.target_name or candidate.goal.target_name or "待确认目标",
            }
        )
    for question in context.get("pending_clarifications", []):
        if question.get("candidate_ref") and (
            candidate is None or question["candidate_ref"] != candidate.ref
            or question.get("base_state_version", plan_version) != plan_version
        ):
            continue
        question_id = question.get("question_id")
        if question_id:
            refs.append(
                {
                    "ref": question_id,
                    "kind": "pending_question",
                    "label": str(question.get("question") or ""),
                    "candidate_ref": question.get("candidate_ref"),
                }
            )
    return refs


def build_turn_snapshot(
    *,
    turn_mode: str,
    message: str,
    candidates: CandidateSet,
    state: Any = None,
    ctx: Any = None,
    context: dict[str, Any] | None = None,
    focus_refs: list[dict[str, Any]] | None = None,
    goal_candidate: dict[str, Any] | None = None,
) -> TurnSnapshot:
    """Plain values for one loop turn. No ORM object survives this call."""
    context = context or {}
    requirements = getattr(state, "requirements", None)
    pending = list(context.get("pending_clarifications", []))
    return TurnSnapshot(
        turn_mode=turn_mode,
        message=message,
        current_step=state.current_step if state is not None else None,
        requirements=requirements.to_dict() if requirements else {},
        # The page the shopper entered from. Every page runs this same turn, so
        # the page travels as context rather than as a route.
        entry_context=dict(getattr(ctx, "entry", None) or {}),
        view_context=dict(getattr(ctx, "view", None) or {}),
        # Only the plan is snapshotted here. The model's candidate view is rebuilt
        # from the live set on every loop round, so a ref found by a read-only
        # lookup is usable immediately.
        current_plan=(
            None
            if state is not None and state.current_step == "cancelled"
            else candidates.model_view(state).get("current_plan")
        ),
        purchase_summary=getattr(ctx, "purchase_summary", None),
        pending_clarification=next(iter(pending), None),
        pending_clarifications=pending,
        displayed_candidates=list(context.get("displayed_candidates", [])),
        recent_messages=list(getattr(ctx, "recent_messages", None) or []),
        focus_refs=list(focus_refs or []),
        goal_candidate=goal_candidate,
    )


def _dish_by_id(db: Session, dish_id: str) -> dict[str, Any] | None:
    from app.services.template_matcher import get_template_by_id

    return get_template_by_id(db, dish_id)


# ------------------------------------------------------- durable turn context


def load_context(db: Session, session: GuideSession) -> dict[str, Any]:
    """The stored context, or ``{}`` when it no longer describes this session."""
    record = db.get(GuideSemanticContext, session.session_id)
    if not record or record.owner_id != session.owner_id:
        return {}
    context = json.loads(record.context_json or "{}")
    # Starting/cancelling a task invalidates references, never the actual cart.
    if context.get("task_id") != session.current_task_id:
        return {}
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    if task and effective_status(task) == "superseded":
        return {}
    if (
        task
        and effective_status(task) == "cancelled"
        and context.get("task_status") != "cancelled"
    ):
        return {}
    # Confirming the task ends the plan this context describes: questions and
    # displayed refs written while it was still active belong to a purchase the
    # shopper has already settled. A context written *after* completion (ordinary
    # chat on a finished task) stays valid, so those clarifications persist.
    if task and effective_status(task) == "completed" and context.get("task_status") != "completed":
        return {}
    return context


def save_context(db: Session, session: GuideSession, context: dict[str, Any]) -> None:
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    value = {
        **context,
        "task_id": session.current_task_id,
        #: The status the context was written under. A context saved on an active
        #: task is not re-read once that task is completed.
        "task_status": effective_status(task) if task else None,
    }
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    record = db.get(GuideSemanticContext, session.session_id)
    if record and record.context_json == serialized:
        return
    if record is None:
        record = GuideSemanticContext(session_id=session.session_id, owner_id=session.owner_id)
        db.add(record)
    record.context_json = serialized
    db.flush()


def pending_for_session(db: Session, session: GuideSession) -> list[dict[str, Any]]:
    """The questions this session is still waiting on, from the one source."""
    context = load_context(db, session)
    if "pending_clarifications" in context:
        return context["pending_clarifications"]
    task = db.get(GuideTask, session.current_task_id) if session.current_task_id else None
    if task and effective_status(task) == "active" and task.pending_clarification_json:
        return [json.loads(task.pending_clarification_json)]
    return []


# --------------------------------------------------------- pending resolution


def build_pending(uncertainty: Uncertainty, candidates: CandidateSet) -> dict[str, Any]:
    """One real question, with only real candidates as its options."""
    options: list[dict[str, str]] = []
    stored: list[dict[str, Any]] = []
    for ref in uncertainty.option_refs:
        candidate = candidates.resolve(ref)
        if candidate is None:
            # A silently dropped option would show the shopper a question with
            # fewer choices than the model intended.
            raise SemanticProtocolError(
                "UNKNOWN_CANDIDATE_REF", f"澄清选项引用了未知候选: {ref}"
            )
        options.append({"id": candidate.ref, "label": candidate.name or candidate.ref})
        stored.append(asdict(candidate))
    return PendingClarification(
        question_id="q-" + uuid4().hex[:12],
        question=uncertainty.question,
        options=options,
        slot=uncertainty.slot,
        candidates=stored,
    ).to_dict()


def resolve_display_refs(
    display_refs: list[str], candidates: CandidateSet
) -> list[dict[str, Any]]:
    """The rows the model wants shown, in its stated order."""
    displayed: list[dict[str, Any]] = []
    for ref in display_refs:
        candidate = candidates.resolve(ref)
        if candidate is None:
            raise SemanticProtocolError("UNKNOWN_CANDIDATE_REF", f"展示引用无效：{ref}")
        displayed.append(asdict(candidate))
    return displayed


def check_resolved_questions(
    resolved_questions: list[str], context: dict[str, Any]
) -> None:
    """A question that was never asked cannot be answered."""
    pending_ids = {p["question_id"] for p in context.get("pending_clarifications", [])}
    if not set(resolved_questions) <= pending_ids:
        raise SemanticProtocolError("UNKNOWN_QUESTION_REF", "不能结束不存在的澄清问题")


def merge_pending(
    *,
    context: dict[str, Any],
    new_pending: list[dict[str, Any]],
    resolved_questions: list[str],
    committed_refs: set[Any],
    task_switched: bool,
) -> list[dict[str, Any]]:
    """This turn's question list: what survives, plus what was just asked.

    A question is dropped when the shopper answered it or when its candidate was
    actually committed. A new task inherits nothing it did not produce itself —
    only a taskless conversation keeps its questions when the first plan is
    created here.
    """
    resolved = set(resolved_questions)
    base = [] if task_switched else list(context.get("pending_clarifications", []))
    pending_list: list[dict[str, Any]] = []
    for item in base:
        refs = {c.get("ref") for c in item.get("candidates", [])}
        if item.get("question_id") not in resolved and not refs.intersection(committed_refs):
            pending_list.append(item)
    for item in new_pending:
        # One live question per slot: a re-asked slot replaces its predecessor.
        pending_list = [p for p in pending_list if p.get("slot") != item.get("slot")]
        pending_list.append(item)
    return pending_list


__all__ = [
    "build_candidate_set",
    "build_focus_refs",
    "build_pending",
    "build_turn_snapshot",
    "check_resolved_questions",
    "goal_candidate_from_context",
    "load_context",
    "merge_pending",
    "pending_for_session",
    "resolve_display_refs",
    "restore_displayed_references",
    "save_context",
]
