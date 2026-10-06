"""Shared pure authorization/compile rules for a turn's mutations.

These rules are *the* business implementation of "which mutation did the gate
authorize" and "what operation does the validated meaning compile to". They were
in ``GuideService`` and are extracted here so the legacy path and the Graph
commit chain call the exact same functions instead of keeping two copies.

Nothing here touches a database, a session or the network: it is decision +
proposal + candidate set in, mutations/reason codes out.
"""

from __future__ import annotations

from typing import Any

from app.agent.goal_router import (
    CONFLICT_REASONS,
    SLOT_FOCUS,
    SLOT_QUESTIONS,
    expected_ref_kinds,
    mutation_refusal,
)
from app.agent.protocol import CandidateSet, Mutation

#: Fields a goal-level ``amend`` may patch onto the plan already on screen.
PATCHABLE_PLAN_FIELDS = frozenset({"people"})


def inherit_candidate_constraints(mutation: Mutation, decision: Any) -> Mutation:
    """Carry the goal's own stated constraints onto the operation that builds it.

    A goal under discussion is the authority for *its* headcount, budget and
    exclusions. When the turn's operation does not restate them — the answer to a
    pending question, say — they are taken from the goal itself, never from the
    plan this goal is replacing.
    """
    candidate = getattr(decision, "candidate", None) if decision is not None else None
    if candidate is None or mutation.verb != "add":
        return mutation
    if candidate.target_ref and mutation.candidate_ref != candidate.target_ref:
        return mutation
    constraints = candidate.goal.constraints
    if mutation.people is None and constraints.people:
        mutation.people = constraints.people
    if mutation.budget_fen is None and constraints.budget_yuan is not None:
        mutation.budget_fen = int(round(constraints.budget_yuan * 100))
    if not mutation.excluded_ingredients and constraints.excluded_ingredients:
        mutation.excluded_ingredients = list(constraints.excluded_ingredients)
    if not mutation.specification and constraints.specification:
        mutation.specification = dict(constraints.specification)
    return mutation


def authorize_mutations(
    decision: Any, proposal: Any, candidates: CandidateSet
) -> tuple[list[Mutation], list[str], str | None]:
    """Which of this turn's mutations the validated decision authorizes.

    Returns the authorised list, the refusal reason codes, and a conflict code
    when the turn's writes contradict each other. A conflict refuses the batch
    whole: a request that changes two goals at once — or a switch that also
    edits the plan it replaces — is asked about, never half-executed.
    """
    mutations = list(getattr(proposal, "mutations", None) or [])
    if not mutations:
        return [], [], None
    authorized: list[Mutation] = []
    refusals: list[str] = []
    for mutation in mutations:
        code = mutation_refusal(
            decision,
            verb=mutation.verb,
            field=mutation.field,
            ref=mutation.candidate_ref or mutation.target_ref,
            ref_kind=getattr(
                candidates.resolve(mutation.candidate_ref or mutation.target_ref), "kind", ""
            ),
        )
        if code is None:
            authorized.append(mutation)
        else:
            refusals.append(code)
    conflict = None
    if any(code in CONFLICT_REASONS for code in refusals):
        # A contradictory write is not a partial success. Ask instead.
        conflict = next(code for code in refusals if code in CONFLICT_REASONS)
    understanding = getattr(proposal, "understanding", None)
    if decision is not None:
        goal_adds = [m for m in authorized if m.verb == "add"]
        goal = getattr(decision.candidate, "goal", None)
        if goal is not None and any(
            (m.people is not None and m.people != goal.constraints.people)
            or (
                m.budget_fen is not None
                and goal.constraints.budget_yuan is not None
                and m.budget_fen != round(goal.constraints.budget_yuan * 100)
            )
            or (
                bool(m.specification)
                and m.specification != goal.constraints.specification
            )
            for m in goal_adds
        ):
            conflict = "GOAL_CHANGE_CONFLICT"
        row_ops = [m for m in authorized if m.verb in ("change", "remove")]
        touched = {
            str(m.candidate_ref or m.target_ref)
            for m in row_ops
            if (m.candidate_ref or m.target_ref)
        }
        if (
            len(goal_adds) > 1
            or (goal_adds and len(authorized) != 1)
            # Two rows in one turn is a compound edit too: the turn declares
            # one change, and a half-applied list is worse than a question.
            or len(touched) > 1
        ):
            conflict = conflict or "MIXED_GOAL_CHANGES"
        declared = (
            understanding.changes.set.people
            if understanding is not None and understanding.changes is not None
            else None
        )
        if declared is not None and any(
            m.field == "people" and m.people not in (None, declared) for m in authorized
        ):
            conflict = conflict or "GOAL_CHANGE_CONFLICT"
    return authorized, refusals, conflict


def compile_decision(
    *,
    decision: Any,
    state: Any,
    candidates: CandidateSet,
    authorized: list[Mutation],
    proposal: Any,
) -> tuple[list[Mutation], str, str]:
    """Turn a validated decision into the business operation it implies.

    The model states what it means and points at a server candidate; the server
    compiles the operation. Only two compiles exist, both structural: a ready goal
    becomes an ``add`` of its own target, and a headcount patch on the plan on
    screen becomes a ``change.people`` on the focused group.
    """
    if decision is None:
        return [], "", ""
    if any(m.verb == "add" for m in authorized):
        return [], "", ""
    if getattr(decision, "mutation_action", None) == "prepare" and decision.candidate is not None:
        # A ready goal — whether it was stated this turn or completed by an
        # amendment — is compiled here, once, from the server candidate it was
        # bound to. Nothing is inferred from the sentence.
        mutation = goal_target_mutation(decision.candidate, candidates)
        if mutation is None:
            if decision.candidate.goal.fulfillment_mode == "ready_made":
                return (
                    [],
                    f"没有找到与「{decision.candidate.goal.target_name}」名称相符的成品商品，原清单保持不变。",
                    "GOAL_TARGET_UNRESOLVED",
                )
            return (
                [],
                "我还不确定要准备哪一份清单，请再说一次目标名称。",
                "GOAL_TARGET_UNRESOLVED",
            )
        resolved = candidates.resolve(mutation.candidate_ref)
        decision.candidate.target_ref = resolved.ref
        decision.candidate.target_id = resolved.target_id
        decision.candidate.target_kind = resolved.kind
        return [mutation], "", ""
    if getattr(decision, "mutation_action", None) == "patch_meal_mode":
        group = focused_group(decision, candidates)
        if group is None:
            return [], SLOT_QUESTIONS[SLOT_FOCUS], SLOT_FOCUS
        return (
            [
                Mutation(
                    verb="change",
                    target_ref=group.ref,
                    name=group.name,
                    field="fulfillment_mode",
                )
            ],
            "",
            "",
        )
    understanding = getattr(proposal, "understanding", None)
    changes = understanding.changes if understanding is not None else None
    if getattr(decision, "mutation_action", None) == "apply_mutation" and decision.relation == "amend" and changes:
        unsupported = [
            field
            for field in decision.changed_fields
            if field not in PATCHABLE_PLAN_FIELDS or field in changes.clear
        ]
        if unsupported:
            labels = {
                "specification": "小包装要求",
            }
            # Rewriting an existing plan's budget or exclusions needs a whole
            # re-plan. Saying so is required: silently dropping the patch would
            # leave a plan on screen that no longer matches what was asked.
            return (
                [],
                "已有清单的" + "、".join(labels.get(field, field) for field in unsupported)
                + "暂时不能就地改，本轮没有改动；"
                "可以说要换成什么，我会另建一份清单。",
                "UNSUPPORTED_CHANGE_FIELD",
            )
    if (
        getattr(decision, "mutation_action", None) == "apply_mutation"
        and decision.relation == "amend"
        and changes is not None
        and changes.set.people is not None
        and not any(m.verb == "change" and m.field == "people" for m in authorized)
    ):
        group = focused_group(decision, candidates)
        if group is None:
            return [], SLOT_QUESTIONS[SLOT_FOCUS], SLOT_FOCUS
        return (
            [
                Mutation(
                    verb="change",
                    target_ref=group.ref,
                    name=group.name,
                    field="people",
                    people=changes.set.people,
                )
            ],
            "",
            "",
        )
    return [], "", ""


def goal_target_mutation(candidate: Any, candidates: CandidateSet) -> Mutation | None:
    """The ``add`` a ready goal compiles to, from server-issued candidates only.

    The candidate recorded the target when the goal was stated; if that ref is
    not available this turn — or the name matches no server candidate — the
    goal is not buildable and nothing is written.
    """
    if candidate is None:
        return None
    resolved = candidates.resolve(candidate.target_ref) if candidate.target_ref else None
    if resolved is not None and resolved.kind not in expected_ref_kinds(candidate.goal):
        return None
    if resolved is None and candidate.target_name:
        wanted = candidate.target_name.strip()
        allowed = expected_ref_kinds(candidate.goal)
        for option in candidates.by_kind("dish", "product", "scenario"):
            if allowed and option.kind not in allowed:
                # A ready-made meal is never built from a recipe's raw
                # materials, however the names line up.
                continue
            if option.name.strip() == wanted:
                resolved = option
                break
    if resolved is None or resolved.kind not in ("dish", "product", "scenario"):
        return None
    goal = candidate.goal
    constraints = goal.constraints
    quantity = goal.quantity if resolved.kind == "product" else None
    return Mutation(
        verb="add",
        candidate_ref=resolved.ref,
        name=resolved.name,
        quantity_mode="set" if quantity is not None else None,
        quantity_value=quantity,
        people=constraints.people,
        excluded_ingredients=list(constraints.excluded_ingredients),
        budget_fen=(
            int(round(constraints.budget_yuan * 100))
            if constraints.budget_yuan is not None
            else None
        ),
        specification=dict(constraints.specification),
    )


def focused_group(decision: Any, candidates: CandidateSet) -> Any:
    """The one plan group a goal-level field change may be applied to.

    A ref the model pointed at is used as-is. Focusing the goal as a whole is
    only unambiguous while the plan holds a single dish/scenario group;
    anything else goes back as a question rather than a guess.
    """
    if decision.focus_kind == "plan_target" and decision.focus_ref:
        resolved = candidates.resolve(decision.focus_ref)
        if resolved is not None and resolved.kind == "group":
            return resolved
        return None
    if decision.focus_kind != "active_goal":
        return None
    groups = [g for g in candidates.by_kind("group") if g.target_kind in ("dish", "scenario")]
    return groups[0] if len(groups) == 1 else None


__all__ = [
    "PATCHABLE_PLAN_FIELDS",
    "authorize_mutations",
    "compile_decision",
    "focused_group",
    "goal_target_mutation",
    "inherit_candidate_constraints",
]
