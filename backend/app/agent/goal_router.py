"""Pure goal routing and the turn's decision gate.

Given a validated ``Goal`` this decides the one next step and the slots that
still block preparation. Given a whole ``Understanding`` it decides the turn:
which route, which slots block it, and whether writes are allowed at all. Both
are pure functions: no model call, no retrieval, no database, no plan, no cart,
no environment read. The same inputs always produce the same decision — which is
what makes the gate testable offline, and what keeps the model from deciding its
own route.

Deliberate rules (see ``docs/plans/2026-09-19-purchase-intent-p1-implementation.md``
and ``docs/plans/2026-09-20-p1-planner-decision-layer-review.md``):

* an unrecognised kind never becomes a purchase route;
* ``meal_decision`` always clarifies — the goal is undecided, so no plan is
  prepared even when the user is happy for the system to suggest options;
* a ``meal_plan`` whose ``fulfillment_mode`` is ``unspecified`` and has a named
  target prepares an ingredient list first; it does not ask self-cook vs
  ready-made before showing a plan;
* ``fulfillment_mode`` on a non-meal route is ``none``: product/category/
  replenishment are not meal-fulfilment questions and never ask about people;
* the only combination that prepares a plan is ``readiness="ready"`` with an
  empty ``missing_slots``;
* the gate never reads the raw sentence and never calls a model: it checks
  structure, references and capability only;
* a turn with no goal and no edit only reads: it may answer, retrieve or ask,
  but it never writes;
* a goal under discussion is a *candidate*, kept apart from the plan on screen;
  filling its slots keeps its original switch/append intent.

This module prepares nothing and writes nothing. Preparing a plan, retrieving
supply or confirming a purchase are later, separately authorized steps.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.schemas.goal import (
    Goal,
    GoalCandidate,
    RouteDecision,
    TurnDecision,
    Understanding,
)

#: Slot names are stable strings, not display text: they are what a later
#: clarification step keys on, so they must not drift with wording.
SLOT_MEAL_TARGET = "meal_target"
SLOT_FULFILLMENT_MODE = "fulfillment_mode"
SLOT_ITEMS = "items"
SLOT_CATEGORY = "category"
SLOT_FOCUS = "focus"
SLOT_GOAL_RELATION = "goal_relation"
SLOT_GOAL = "goal"
SLOT_MIXED = "mixed_goal_changes"
SLOT_PEOPLE = "people"
SLOT_PARTIAL_REPLACE = "partial_replace"

#: Goal-level fields an amend may patch on the plan already on screen.
_PATCHABLE_PLAN_FIELDS = frozenset({"people"})

#: Server-owned wording for the slots the gate itself can find missing. It is
#: keyed by a *structured* slot name, never by anything read out of the user's
#: sentence, and it is only a question — never a claim about the catalogue.
SLOT_QUESTIONS: dict[str, str] = {
    SLOT_FULFILLMENT_MODE: "这一餐是想自己做，还是买现成的？",
    SLOT_MEAL_TARGET: "想吃或想做的是什么？",
    SLOT_ITEMS: "想买什么？",
    SLOT_CATEGORY: "想买哪一类？",
    SLOT_FOCUS: "你是在说清单里的哪一项？可以说一下目标或商品名。",
    SLOT_GOAL_RELATION: "这是要换掉现在这份清单，还是在它上面加一份？",
    SLOT_GOAL: "想换成什么目标？",
    SLOT_MIXED: "这一轮里有多个目标改动，先处理哪一个？",
    SLOT_PEOPLE: "几个人吃？",
    SLOT_PARTIAL_REPLACE: "现在还不能一步只换掉清单里的一项。可以先说删掉哪一项，再说要加什么。",
}

#: Refusal reasons that mean "this write contradicts the validated decision"
#: rather than "this reference or name is wrong". They abort the whole batch: a
#: mixed or contradictory turn is asked about, never partially executed.
CONFLICT_REASONS = frozenset(
    {
        "GOAL_CHANGE_CONFLICT",
        "MIXED_GOAL_CHANGES",
        "CANDIDATE_GOAL_CONFLICT",
        #: A goal that cannot be built from its own declared target, and a
        #: ready-made meal expressed as a raw-material build, are contradictions
        #: rather than bad references: they abort the batch.
        "GOAL_TARGET_MISMATCH",
        "READY_MADE_NOT_RAW",
        "UNSUPPORTED_CHANGE_FIELD",
    }
)

#: Why a turn was decided the way it was. Internal diagnostics, never user copy.
REASON_NO_PEOPLE = "PEOPLE_REQUIRED"
REASON_TARGET_MISMATCH = "GOAL_TARGET_MISMATCH"
REASON_READY_MADE = "READY_MADE_NOT_RAW"
REASON_CHAT = "CHAT_ONLY"
REASON_READ_ONLY = "READ_ONLY"
REASON_MODEL_QUESTION = "MODEL_QUESTION"
REASON_PLAN_CONFIRM = "PLAN_CONFIRM_IN_CHAT"
REASON_PLAN_ABANDON = "PLAN_ABANDON_IN_CHAT"
REASON_PLAN_NOTHING = "PLAN_ACT_WITHOUT_PLAN"
REASON_PARTIAL_REPLACE = "PARTIAL_REPLACE"
REASON_UNRESOLVED_FOCUS = "UNRESOLVED_FOCUS"
REASON_UNDECIDED_RELATION = "UNDECIDED_GOAL_RELATION"
REASON_MISSING_GOAL = "MISSING_GOAL_STATEMENT"
REASON_GOAL_READY = "GOAL_READY"
REASON_GOAL_NOT_READY = "GOAL_NEEDS_CLARIFICATION"
REASON_UNSUPPORTED = "UNSUPPORTED_GOAL"
REASON_CANDIDATE_READY = "CANDIDATE_READY"
REASON_CANDIDATE_SLOT = "CANDIDATE_NEEDS_CLARIFICATION"
REASON_CANDIDATE_MISSING = "CANDIDATE_NOT_FOUND"
REASON_ACTIVE_AMEND = "ACTIVE_GOAL_AMEND"
REASON_LOCATED_ACTION = "LOCATED_ACTION"
REASON_UNLOCATED = "UNLOCATED_CORRECTION"
REASON_MIXED = "MIXED_GOAL_CHANGES"

#: Server-owned wording for a plan act chat cannot carry out yet. The model's own
#: reply is never used for these: it could claim a purchase that did not happen.
PLAN_ACT_REPLIES: dict[str, str] = {
    REASON_PLAN_CONFIRM: "聊天里还不能直接加购。清单没问题的话，点清单上的确认就会加入购物车。",
    REASON_PLAN_ABANDON: "这份清单还没有加购，不确认就不会买。只想去掉其中一项的话，告诉我是哪一项。",
    REASON_PLAN_NOTHING: "现在还没有清单。想买什么可以直接告诉我。",
}


@dataclass(frozen=True)
class MutationView:
    """One proposed mutation, reduced to what the gate is allowed to check.

    ``ref_kind`` is the *server* kind of the referenced candidate (resolved by
    the caller from its own candidate set); ``ref`` is the opaque ref itself.
    """

    verb: str
    field: str | None = None
    ref_kind: str = ""
    ref: str | None = None
    #: The business id and the server-issued label behind ``ref``, resolved by the
    #: caller: a target that is replayed later must be the same target the goal
    #: named, not merely a ref the model happened to emit.
    ref_target_id: str = ""
    ref_name: str = ""


@dataclass(frozen=True)
class GateFacts:
    """The server's own facts for one turn. Plain values only."""

    has_active_plan: bool = False
    task_terminal: bool = False
    #: The goal under discussion, already checked against its version binding.
    candidate: GoalCandidate | None = None
    #: Every ref the model may name as ``focus_ref``, with its server-side kind.
    focus_refs: Sequence[dict[str, Any]] = ()
    #: The refs of the plan's own target groups (a plan target the model named).
    plan_target_refs: Sequence[str] = ()
    has_pending_question: bool = False


def _decision(
    goal: Goal,
    *,
    readiness: str,
    fulfillment_mode: str,
    route: str,
    missing_slots: Iterable[str] = (),
    reason: str = "",
) -> RouteDecision:
    return RouteDecision(
        kind=goal.kind,
        readiness=readiness,  # type: ignore[arg-type]
        fulfillment_mode=fulfillment_mode,  # type: ignore[arg-type]
        route=route,  # type: ignore[arg-type]
        missing_slots=list(missing_slots),
        reason=reason,
    )


def _has_meal_target(goal: Goal) -> bool:
    """A named dish/cuisine, or explicitly named meal items."""
    return bool(goal.target_name or goal.items)


def _has_item_target(goal: Goal) -> bool:
    """A named product, however the model chose to express it."""
    return bool(goal.items or goal.target_name)


def _route_meal_plan(goal: Goal) -> RouteDecision:
    mode = goal.fulfillment_mode
    if not _has_meal_target(goal):
        return _decision(
            goal,
            readiness="needs_clarification",
            fulfillment_mode=mode,
            route="clarify_goal",
            missing_slots=(SLOT_MEAL_TARGET,),
            reason="还没确定要做/吃什么，先澄清。",
        )
    if mode == "unspecified":
        # Default recommendation is ingredients, not a claim that the shopper
        # said they will cook. Headcount is optional on the first list.
        return _decision(
            goal,
            readiness="ready",
            fulfillment_mode="unspecified",
            route="prepare_meal_plan",
            reason="目标明确，先按食材推荐准备清单。",
        )
    return _decision(
        goal,
        readiness="ready",
        fulfillment_mode=mode,
        route="prepare_meal_plan",
        reason="目标明确，进入一餐方案准备。",
    )


def route_goal(goal: Goal) -> RouteDecision:
    """Resolve the next step for one validated goal.

    The result is structured, not a sentence: callers branch on ``route`` and
    report ``missing_slots``. ``reason`` is diagnostic wording only.
    """
    kind = goal.kind

    if kind == "unsupported":
        return _decision(
            goal,
            readiness="unsupported",
            fulfillment_mode="none",
            route="refuse_unsupported",
            reason="当前能力不支持这个目标，不生成采购方案。",
        )

    if kind == "information_only":
        return _decision(
            goal,
            readiness="information",
            fulfillment_mode="none",
            route="answer_information",
            reason="只读问题：只回答，不准备采购清单。",
        )

    if kind == "meal_decision":
        # Undecided goal: offer options / ask. This never prepares a plan, so
        # it cannot smuggle a purchase out of an A-class "help me choose" ask.
        return _decision(
            goal,
            readiness="needs_clarification",
            fulfillment_mode=goal.fulfillment_mode,
            route="clarify_goal",
            missing_slots=(SLOT_MEAL_TARGET,),
            reason="目标还没确定，先给出可选项或澄清，不准备清单。",
        )

    if kind == "meal_plan":
        return _route_meal_plan(goal)

    if kind == "product_purchase":
        if not _has_item_target(goal):
            return _decision(
                goal,
                readiness="needs_clarification",
                fulfillment_mode="none",
                route="clarify_goal",
                missing_slots=(SLOT_ITEMS,),
                reason="还没说要买什么商品，先澄清。",
            )
        return _decision(
            goal,
            readiness="ready",
            fulfillment_mode="none",
            route="prepare_product_purchase",
            reason="明确了商品，进入商品采购准备。",
        )

    if kind == "category_purchase":
        if not (goal.category_id or goal.category_name or goal.target_name):
            return _decision(
                goal,
                readiness="needs_clarification",
                fulfillment_mode="none",
                route="clarify_goal",
                missing_slots=(SLOT_CATEGORY,),
                reason="还没说要买哪个类目，先澄清。",
            )
        return _decision(
            goal,
            readiness="ready",
            fulfillment_mode="none",
            route="prepare_category_purchase",
            reason="明确了类目，进入类目采购准备。",
        )

    if kind == "replenishment":
        if not _has_item_target(goal):
            return _decision(
                goal,
                readiness="needs_clarification",
                fulfillment_mode="none",
                route="clarify_goal",
                missing_slots=(SLOT_ITEMS,),
                reason="还没说要补什么，先澄清。",
            )
        return _decision(
            goal,
            readiness="ready",
            fulfillment_mode="none",
            route="prepare_replenishment",
            reason="明确了补货对象，进入补货准备。",
        )

    # Kinds are a closed Literal, so this only guards a value that bypassed
    # validation; refusing is the honest response and keeps the function total.
    return _decision(
        goal,
        readiness="unsupported",
        fulfillment_mode="none",
        route="refuse_unsupported",
        reason="无法识别的目标类型，不生成采购方案。",
    )


# ------------------------------------------------------------- the turn's gate


def _blocked(
    *,
    route: str,
    readiness: str,
    reason_code: str,
    missing_slots: Iterable[str] = (),
    goal: Goal | None = None,
    relation: str = "unspecified",
    focus_ref: str | None = None,
    focus_kind: str = "none",
    changed_fields: Iterable[str] = (),
    candidate: GoalCandidate | None = None,
) -> TurnDecision:
    return TurnDecision(
        route=route,  # type: ignore[arg-type]
        readiness=readiness,  # type: ignore[arg-type]
        missing_slots=list(missing_slots),
        write_blocked=True,
        reason_code=reason_code,
        relation=relation,  # type: ignore[arg-type]
        focus_ref=focus_ref,
        focus_kind=focus_kind,  # type: ignore[arg-type]
        goal=goal,
        changed_fields=list(changed_fields),
        candidate=candidate,
    )


def _unblocked(
    *,
    route: str,
    reason_code: str,
    goal: Goal | None,
    relation: str,
    focus_ref: str | None,
    focus_kind: str,
    changed_fields: Iterable[str] = (),
    candidate: GoalCandidate | None = None,
    mutation_action: str | None = None,
) -> TurnDecision:
    return TurnDecision(
        route=route,  # type: ignore[arg-type]
        mutation_action=mutation_action,  # type: ignore[arg-type]
        readiness="ready",
        missing_slots=[],
        write_blocked=False,
        reason_code=reason_code,
        relation=relation,  # type: ignore[arg-type]
        focus_ref=focus_ref,
        focus_kind=focus_kind,  # type: ignore[arg-type]
        goal=goal,
        changed_fields=list(changed_fields),
        candidate=candidate,
    )


def _resolve_focus(
    facts: GateFacts, ref: str | None
) -> tuple[str, str | None, str | None]:
    """Where ``focus_ref`` points, per the server's own ref table.

    The third value is the goal a pending question belongs to, when there is one:
    a question is only an answer about *that* candidate, never about whichever
    candidate happens to be under discussion now.
    """
    if not ref:
        return "none", None, None
    for entry in facts.focus_refs:
        if entry.get("ref") == ref:
            return (
                str(entry.get("kind") or "none"),
                ref,
                str(entry.get("candidate_ref") or "") or None,
            )
    return "none", None, None


def _read_only(
    understanding: Understanding,
    facts: GateFacts,
    *,
    has_read_requests: bool,
    has_questions: bool,
) -> TurnDecision:
    """A turn that states no goal and no edit: it answers, reads or asks, never writes."""

    def blocked(route: str, reason_code: str, readiness: str = "information") -> TurnDecision:
        return _blocked(route=route, readiness=readiness, reason_code=reason_code)

    if understanding.plan_act != "none":
        # Chat cannot confirm or drop a plan yet; the server says so in its own
        # words, so the reply can never claim a purchase that did not happen.
        if not facts.has_active_plan:
            return blocked("answer", REASON_PLAN_NOTHING)
        if understanding.plan_act == "confirm":
            return blocked("answer", REASON_PLAN_CONFIRM)
        return blocked("answer", REASON_PLAN_ABANDON)
    if has_questions:
        return blocked("clarify", REASON_MODEL_QUESTION, "needs_clarification")
    if has_read_requests:
        return blocked("retrieve", REASON_READ_ONLY)
    if understanding.intent == "explore":
        return blocked("answer", REASON_READ_ONLY)
    return blocked("chat", REASON_CHAT)


def decide_turn(
    understanding: Understanding,
    facts: GateFacts,
    *,
    mutations: Sequence[MutationView] = (),
    has_read_requests: bool = False,
    has_questions: bool = False,
) -> TurnDecision:
    """The one next step for this turn, plus what blocks it and why.

    ``understanding`` is the parser's reading of the model's independent
    dimensions; ``facts`` is what the server knows. No rule branches on a label
    the model chose for the whole turn: each checks whether a dimension is filled,
    joined with the server's facts. The decision is the only thing that
    authorizes a plan or cart write for the turn.
    """
    goal = understanding.new_goal
    relation = understanding.goal_relation
    if goal is None and relation != "amend":
        return _read_only(
            understanding, facts, has_read_requests=has_read_requests, has_questions=has_questions
        )
    if has_questions:
        # The model met an ambiguity it cannot resolve: nothing is written.
        return _blocked(
            route="clarify", readiness="needs_clarification", reason_code=REASON_MODEL_QUESTION
        )
    if goal is not None and goal.kind == "unsupported":
        return _blocked(
            route="refuse", readiness="unsupported", reason_code=REASON_UNSUPPORTED, goal=goal
        )

    focus_kind, focus_ref, focus_candidate = _resolve_focus(facts, understanding.focus_ref)
    if understanding.focus_ref and focus_kind == "none":
        # R7/R8: a reference the server never issued cannot be repaired by
        # guessing which goal or row the shopper meant.
        return _blocked(
            route="clarify",
            readiness="needs_clarification",
            reason_code=REASON_UNRESOLVED_FOCUS,
            missing_slots=(SLOT_FOCUS,),
        )

    changes = understanding.changes
    changed_fields = changes.changed_fields() if changes is not None else []
    if relation == "unspecified" and goal is not None:
        candidate = facts.candidate
        if (
            candidate is not None
            and facts.has_pending_question
            and candidate.relation in ("new", "append", "switch")
        ):
            # A named answer to the question about the goal under discussion
            # completes that goal and keeps its own switch/append intent.
            from app.agent.goal import answer_goal_candidate

            relation = candidate.relation
            goal = answer_goal_candidate(candidate, goal)
        elif (not facts.has_active_plan or facts.task_terminal) and candidate is None:
            # With nothing to relate to, an unstated relation is trivially ``new``;
            # only an editable plan or a candidate makes "how does this relate?" a
            # question. A finished or cancelled list can be neither added to nor
            # replaced, so a new purchase after it simply starts its own list.
            relation = "new"

    if relation == "switch" and focus_kind == "plan_target" and len(facts.plan_target_refs) > 1:
        # Replacing one entry of a multi-entry list would silently drop the rest.
        return _blocked(
            route="clarify",
            readiness="needs_clarification",
            reason_code=REASON_PARTIAL_REPLACE,
            missing_slots=(SLOT_PARTIAL_REPLACE,),
            goal=goal,
            relation=relation,
            focus_ref=focus_ref,
            focus_kind=focus_kind,
        )

    if relation in ("new", "append", "switch"):
        if goal is None:  # guarded by the contract; kept total
            return _blocked(
                route="clarify",
                readiness="needs_clarification",
                reason_code=REASON_MISSING_GOAL,
                missing_slots=(SLOT_GOAL,),
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
            )
        goal_decision = route_goal(goal)
        declared = next((m for m in mutations if m.verb == "add" and m.ref), None)
        if declared is not None and not _target_matches_goal(goal, declared):
            # The ref the model pointed at is not the goal it described. Refusing
            # keeps a switch from silently building some other target.
            return _blocked(
                route="clarify",
                readiness="needs_clarification",
                reason_code=REASON_TARGET_MISMATCH,
                missing_slots=(SLOT_GOAL,),
                goal=goal,
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
            )
        if (
            declared is not None
            and goal.fulfillment_mode == "ready_made"
            and declared.ref_kind in ("dish", "scenario")
        ):
            # A ready-made goal is not a recipe: it must never be compiled into a
            # raw-material purchase behind the shopper's back.
            return _blocked(
                route="clarify",
                readiness="needs_clarification",
                reason_code=REASON_READY_MADE,
                goal=goal,
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
            )
        target_ref = declared.ref if declared is not None else None
        candidate = GoalCandidate(
            ref=_candidate_handle(goal, target_ref, relation),
            goal=goal,
            relation=relation,  # type: ignore[arg-type]
            target_ref=target_ref,
            target_id=declared.ref_target_id if declared is not None else "",
            target_name=str(goal.target_name or (goal.items[0] if goal.items else "")),
            target_kind=(
                declared.ref_kind
                if declared is not None and declared.ref_kind
                else _target_kind_for(goal, target_ref)
            ),
            missing_slots=list(goal_decision.missing_slots),
            # The task/plan binding is recorded by whoever persists the
            # candidate, from the state it was agreed on.
        )
        if goal_decision.readiness == "ready" and goal_decision.route.startswith("prepare"):
            return _unblocked(
                route="mutation",
                mutation_action="prepare",
                reason_code=REASON_GOAL_READY,
                goal=goal,
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
                candidate=candidate,
            )
        if goal_decision.route == "refuse_unsupported":
            return _blocked(
                route="refuse",
                readiness="unsupported",
                reason_code=REASON_UNSUPPORTED,
                missing_slots=goal_decision.missing_slots,
                goal=goal,
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
            )
        return _blocked(
            route="clarify",
            readiness="needs_clarification",
            reason_code=REASON_GOAL_NOT_READY,
            missing_slots=goal_decision.missing_slots,
            goal=goal,
            relation=relation,
            focus_ref=focus_ref,
            focus_kind=focus_kind,
            changed_fields=changed_fields,
            candidate=candidate,
        )

    if relation == "amend":
        candidate = facts.candidate
        if focus_kind == "pending_question" and (
            candidate is None or focus_candidate != candidate.ref
        ):
            return _blocked(
                route="clarify", readiness="needs_clarification",
                reason_code=REASON_CANDIDATE_MISSING, missing_slots=(SLOT_FOCUS,),
                relation=relation,
                focus_ref=focus_ref, focus_kind=focus_kind,
            )
        if changes is not None and not changes.is_empty():
            question_matches = focus_kind != "pending_question" or (
                focus_candidate is not None
                and candidate is not None
                and focus_candidate == candidate.ref
            )
            located_candidate = (
                focus_kind == "pending_goal"
                or (focus_kind == "none" and facts.has_pending_question)
            ) or (focus_kind == "pending_question" and question_matches)
            if focus_kind == "pending_question" and not question_matches:
                # The question belonged to another goal (or to none): filling this
                # one from it would bind an old answer to a new candidate.
                return _blocked(
                    route="clarify",
                    readiness="needs_clarification",
                    reason_code=REASON_CANDIDATE_MISSING,
                    missing_slots=(SLOT_FOCUS,),
                    relation=relation,
                    focus_ref=focus_ref,
                    focus_kind=focus_kind,
                    changed_fields=changed_fields,
                )
            if located_candidate and candidate is not None:
                # A slot answer for the goal under discussion: the candidate is
                # completed in place, and only the *server* decides whether it is
                # now ready to be built.
                from app.agent.goal import merge_goal_candidate

                merged = merge_goal_candidate(candidate, understanding) or candidate
                goal_decision = route_goal(merged.goal)
                ready = (
                    goal_decision.readiness == "ready"
                    and goal_decision.route.startswith("prepare")
                )
                missing = list(goal_decision.missing_slots)
                updated = merged.model_copy(
                    update={"missing_slots": [] if ready else missing}
                )
                if ready:
                    return _unblocked(
                        route="mutation",
                        mutation_action="prepare",
                        reason_code=REASON_CANDIDATE_READY,
                        goal=updated.goal,
                        relation=relation,
                        focus_ref=focus_ref,
                        focus_kind=focus_kind,
                        changed_fields=changed_fields,
                        candidate=updated,
                    )
                return _blocked(
                    route="clarify",
                    readiness="needs_clarification",
                    reason_code=REASON_CANDIDATE_SLOT,
                    missing_slots=missing,
                    goal=updated.goal,
                    relation=relation,
                    focus_ref=focus_ref,
                    focus_kind=focus_kind,
                    changed_fields=changed_fields,
                    candidate=updated,
                )
            if focus_kind in ("active_goal", "plan_target"):
                # The plan on screen is amended. The low-level mutation carries
                # the concrete row edit; the gate only checks that the fields
                # agree, so "改成三个人" cannot become an unrelated rewrite.
                return _unblocked(
                    route="mutation",
                    mutation_action="apply_mutation",
                    reason_code=REASON_ACTIVE_AMEND,
                    goal=None,
                    relation=relation,
                    focus_ref=focus_ref,
                    focus_kind=focus_kind,
                    changed_fields=changed_fields,
                )
            if (
                focus_kind == "none"
                and facts.has_active_plan
                and changed_fields
                and all(field in _PATCHABLE_PLAN_FIELDS for field in changed_fields)
            ):
                # A headcount patch on the plan already on screen does not need
                # the model to re-lookup or re-add the whole target.
                return _unblocked(
                    route="mutation",
                    mutation_action="apply_mutation",
                    reason_code=REASON_ACTIVE_AMEND,
                    goal=None,
                    relation=relation,
                    focus_ref="active-goal-1",
                    focus_kind="active_goal",
                    changed_fields=changed_fields,
                )
            return _blocked(
                route="clarify",
                readiness="needs_clarification",
                reason_code=REASON_CANDIDATE_MISSING,
                missing_slots=(SLOT_FOCUS,),
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
            )
        if focus_kind in ("pending_goal", "pending_question", "plan_target", "active_goal"):
            if candidate is not None and focus_kind in ("pending_goal", "pending_question"):
                readiness = route_goal(candidate.goal)
                missing = list(readiness.missing_slots)
                if missing or readiness.readiness != "ready":
                    return _blocked(
                        route="clarify", readiness="needs_clarification",
                        reason_code=REASON_CANDIDATE_SLOT, missing_slots=missing,
                        relation=relation,
                        focus_ref=focus_ref, focus_kind=focus_kind,
                        candidate=candidate, goal=candidate.goal,
                    )
            # A located low-level row operation (a quantity delta): the goal
            # itself does not move. The goal under discussion still travels with
            # it, so an operation that turns out to complete the candidate keeps
            # the candidate's own switch/append intent.
            return _unblocked(
                route="mutation",
                mutation_action="apply_mutation",
                reason_code=REASON_LOCATED_ACTION,
                goal=None,
                relation=relation,
                focus_ref=focus_ref,
                focus_kind=focus_kind,
                changed_fields=changed_fields,
                candidate=facts.candidate,
            )
        return _blocked(
            route="clarify",
            readiness="needs_clarification",
            reason_code=(
                REASON_UNLOCATED if facts.candidate is None else REASON_CANDIDATE_MISSING
            ),
            missing_slots=(SLOT_FOCUS,),
            relation=relation,
            focus_ref=focus_ref,
            focus_kind=focus_kind,
        )

    # A named goal whose relation to the plan or candidate on screen was not
    # stated: it could add or replace, so asking is the only safe answer.
    return _blocked(
        route="clarify",
        readiness="needs_clarification",
        reason_code=REASON_UNDECIDED_RELATION,
        missing_slots=(SLOT_GOAL_RELATION,),
        focus_ref=focus_ref,
        focus_kind=focus_kind,
    )


def _norm(text: str) -> str:
    return "".join(str(text or "").split()).lower()


def expected_ref_kinds(goal: Goal) -> tuple[str, ...]:
    """Which server candidate kinds can build this goal at all.

    Public because the executor compiles a goal into an operation with it: a
    ready-made meal must not be compiled from a dish, whoever asks.
    """
    if goal.kind in ("product_purchase", "replenishment"):
        return ("product",)
    if goal.kind == "meal_plan":
        if goal.fulfillment_mode == "ready_made":
            return ("product",)
        return ("dish", "scenario", "product")
    if goal.kind == "category_purchase":
        return ("dish", "product", "scenario")
    return ()


def _target_matches_goal(goal: Goal, mutation: MutationView) -> bool:
    """Is the referenced candidate really the target the goal describes?

    Two independent checks, both structural: the candidate's kind must be able to
    build this goal, and the goal's own name must agree with the server-issued
    label of the ref. A ref emitted while describing something else is refused
    rather than adopted as the goal's target.
    """
    kinds = expected_ref_kinds(goal)
    if kinds and mutation.ref_kind and mutation.ref_kind not in kinds:
        return False
    wanted = _norm(goal.target_name or "")
    got = _norm(mutation.ref_name)
    if wanted and got and wanted not in got and got not in wanted:
        return False
    return True


def _candidate_handle(goal: Goal, target_ref: str | None, relation: str = "") -> str:
    from app.agent.goal import candidate_ref_for

    return candidate_ref_for(goal, target_ref, relation)


def _target_kind_for(goal: Goal, target_ref: str | None) -> str:
    """The business kind this goal will be built from, when it is knowable.

    For a dish/scenario/product goal the caller resolves the real kind from the
    ref; ``goal.kind`` is only the fallback and never becomes a write by itself.
    """
    if goal.kind == "product_purchase":
        return "product"
    if goal.kind == "meal_plan":
        return "dish"
    return ""


def mutation_refusal(
    decision: TurnDecision | None,
    *,
    verb: str,
    field: str | None = None,
    ref: str | None = None,
    ref_kind: str = "",
) -> str | None:
    """Whether this mutation is authorized by the turn's decision.

    Returns a reason code when it is not, ``None`` when it is. The check is
    structural: relation against verb, goal field against the patch the turn
    declared, and the candidate's own target. It never re-reads the sentence.
    """
    if decision is None:
        # No understanding, no authority. This is not a compatibility switch: a
        # proposal that never said what it meant cannot change a plan.
        return "MISSING_UNDERSTANDING"
    if decision.write_blocked:
        return "WRITE_BLOCKED"

    goal = decision.goal
    if (
        verb == "add"
        and goal is not None
        and goal.fulfillment_mode == "ready_made"
        and ref_kind in ("dish", "scenario")
    ):
        # 成品 must not be compiled into a raw-material build.
        return "READY_MADE_NOT_RAW"

    relation = decision.relation
    target_ref = decision.candidate.target_ref if decision.candidate else None

    if verb == "add":
        if relation in ("new", "switch"):
            return None if (target_ref is None or ref == target_ref) else "GOAL_CHANGE_CONFLICT"
        if relation == "append":
            return None if (target_ref is None or ref == target_ref) else "GOAL_CHANGE_CONFLICT"
        if relation == "amend":
            if decision.focus_kind in ("pending_goal", "pending_question"):
                # Completing the goal under discussion: the add may only point at
                # that goal's own target, never at something else.
                return None if (target_ref is None or ref == target_ref) else (
                    "CANDIDATE_GOAL_CONFLICT"
                )
            return "GOAL_CHANGE_CONFLICT"
        return "GOAL_CHANGE_CONFLICT"

    # change / remove
    if relation in ("new", "switch"):
        # Rule: a switch must not execute an edit of the plan it is replacing.
        return "GOAL_CHANGE_CONFLICT"
    if relation == "amend":
        if decision.focus_kind == "pending_goal":
            # The goal under discussion is not on screen yet; editing the old
            # plan in the same turn is exactly the accident this gate prevents.
            return "CANDIDATE_GOAL_CONFLICT"
        if (
            decision.focus_kind == "plan_target"
            and decision.focus_ref
            and ref is not None
            and ref != decision.focus_ref
        ):
            # A patch and the row it names must be the same target: a focus the
            # model pointed at is the authority, not the ref it typed beside it.
            return "GOAL_CHANGE_CONFLICT"
        if (
            verb == "change"
            and decision.changed_fields
            and field is not None
            and field not in decision.changed_fields
        ):
            return "GOAL_CHANGE_CONFLICT"
        return None
    return "GOAL_CHANGE_CONFLICT"


__all__ = [
    "CONFLICT_REASONS",
    "PLAN_ACT_REPLIES",
    "GateFacts",
    "MutationView",
    "SLOT_CATEGORY",
    "SLOT_FOCUS",
    "SLOT_FULFILLMENT_MODE",
    "SLOT_GOAL",
    "SLOT_GOAL_RELATION",
    "SLOT_ITEMS",
    "SLOT_MEAL_TARGET",
    "SLOT_QUESTIONS",
    "decide_turn",
    "expected_ref_kinds",
    "mutation_refusal",
    "route_goal",
]
