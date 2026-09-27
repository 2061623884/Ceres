"""``mutation``: resolve the real target, prepare (never execute) the change.

The node reuses the existing authorization, matching, packaging and adjustment
functions (``authorization.authorize_mutations`` / ``compile_decision`` and
``PlanChangeExecutor.prepare``) and produces the staged plan result / plan patch
plus the business result text. It performs **no** business write: the single
commit transaction in ``respond`` is the only place a plan, task, version or cart
row changes.

The route is the gate's business intent, not "did the model emit a complete
mutation". A named dish or product is resolved here: the node runs the read-only
requests the understanding carried (``lookups``/``queries``) so the real
candidate set is populated, then binds the exact real id from the read results.
A fuzzy/lexical/similar candidate is never treated as the named target — it
becomes a real clarification with the real candidates as options. ``changes``-only
turns on an existing target (a headcount patch) and pending-candidate slot fills
compile through the same shared functions with no extra model call and no loop.
"""

from __future__ import annotations

from typing import Any

from app.agent import authorization
from app.agent import context as turn_context
from app.agent.graph.nodes.staging import (
    anchor_for,
    base,
    mutation_payload,
    plan_context,
)
from app.agent.graph.nodes.understand import timeout_error
from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, merge_state, update_partition
from app.agent.protocol import SemanticProtocolError, Uncertainty
from app.agent.tools.change_plan import PlanChangeExecutor
from app.agent.turn_context_plan import gate_pending
from app.agent.turn_primitives import clamp_limits
from app.schemas.goal import TurnDecision

#: A hit the shopper really named (an exact name or a registered alias).
_EXACT_MATCH_KINDS = ("exact", "alias")
#: A merely similar candidate: it may be offered, never built unasked.
_SIMILAR_MATCH_KINDS = ("fuzzy", "lexical", "semantic", "fused")


def _norm(text: Any) -> str:
    return "".join(str(text or "").split()).lower()


def _match_index(read_results: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for result in read_results:
        for match in result.get("matches") or []:
            ref = match.get("ref")
            if ref:
                index[str(ref)] = match
    return index


def _resolve_named_target(
    decision: TurnDecision,
    read_results: list[dict[str, Any]],
    candidates: Any,
) -> Any:
    """The real candidate the named target means, or ``None``.

    Exact/alias hits are the named target; a similar hit is never it. A legacy
    (unindexed) lookup carries no ``match_kind``, so only an exact name-equality
    is accepted there.
    """
    candidate = getattr(decision, "candidate", None)
    if candidate is None:
        return None
    allowed = authorization.expected_ref_kinds(candidate.goal)
    matches = _match_index(read_results)
    wanted = _norm(candidate.target_name or "")
    name_hit = None
    for option in candidates.by_kind("dish", "product", "scenario"):
        if allowed and option.kind not in allowed:
            continue
        match = matches.get(option.ref)
        match_kind = match.get("match_kind") if match else None
        if match_kind in _EXACT_MATCH_KINDS:
            return option
        if match_kind in _SIMILAR_MATCH_KINDS:
            continue
        if wanted and _norm(option.name) == wanted and name_hit is None:
            name_hit = option
    return name_hit


def _similar_options(
    decision: TurnDecision,
    read_results: list[dict[str, Any]],
    candidates: Any,
) -> list[str]:
    candidate = getattr(decision, "candidate", None)
    if candidate is None:
        return []
    allowed = authorization.expected_ref_kinds(candidate.goal)
    refs: list[str] = []
    for result in read_results:
        for match in result.get("matches") or []:
            ref = match.get("ref")
            if not ref:
                continue
            resolved = candidates.resolve(str(ref))
            if resolved is None:
                continue
            if allowed and resolved.kind not in allowed:
                continue
            if str(ref) not in refs:
                refs.append(str(ref))
    return refs[:5]


def _serve_reads(
    state: GraphState, runtime: TurnRuntime, proposal: Any
) -> dict[str, Any] | None:
    """Consume this request's read-only requests once, before preparing."""
    if not (proposal.lookups or proposal.queries):
        return None
    if runtime.reads is None:
        raise ValueError("READ_PORT_REQUIRED: the runtime context must carry a read port")
    _max_calls, lookup_limit = clamp_limits(runtime.budget)
    runtime.on_phase("retrieve")
    if runtime.stop():
        return update_partition(state, "turn", halt="stopped")
    if runtime.expired():
        return update_partition(
            state, "turn", halt="timed_out", error=timeout_error()
        )
    results = runtime.reads.serve(proposal, runtime.candidates, lookup_limit=lookup_limit)
    return update_partition(
        state,
        "turn",
        read_results=[*(state["turn"].get("read_results") or []), *results],
    )


def mutation(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Resolve the real target and compute what this request would write."""
    runtime = context_of(runtime)
    if runtime.db is None:
        raise ValueError("DB_REQUIRED: the runtime context must carry a database session")
    proposal = state["turn"]["parsed_proposal"]
    turn_update = _serve_reads(state, runtime, proposal)
    if turn_update and turn_update["turn"].get("halt"):
        return turn_update
    if turn_update:
        state = merge_state(state, turn_update)
    result = _prepare(state, runtime, proposal)
    if turn_update:
        result = {**result, **turn_update}
    return result


def _prepare(
    state: GraphState, runtime: TurnRuntime, proposal: Any
) -> dict[str, Any]:
    turn = state["turn"]
    decision = TurnDecision.model_validate(turn["decision"])
    read_results = list(turn.get("read_results") or [])
    session, task_state = _load(runtime)

    # A named target the model did not point at: bind the exact real candidate
    # the reads really returned. A similar candidate is offered, never built.
    if (
        decision.mutation_action == "prepare"
        and decision.candidate is not None
        and not decision.candidate.target_ref
    ):
        resolved = _resolve_named_target(decision, read_results, runtime.candidates)
        if resolved is not None:
            decision.candidate.target_ref = resolved.ref
            decision.candidate.target_id = resolved.target_id
            decision.candidate.target_kind = resolved.kind
        else:
            options = _similar_options(decision, read_results, runtime.candidates)
            if options:
                name = decision.candidate.target_name or ""
                question = f"本次没找到完全同名的“{name}”，找到了这些相似候选，你要哪一个？"
                kind = decision.candidate.goal.kind
                slot = "dish" if kind in ("meal_plan", "meal_decision", "category_purchase") else "item"
                pending = [
                    turn_context.build_pending(
                        Uncertainty(slot=slot, question=question, option_refs=options),
                        runtime.candidates,
                    )
                ]
                result = base(
                    state, runtime, kind="clarify", pending=pending, message=question
                )
                return _attach_plan(
                    result,
                    state,
                    runtime,
                    proposal,
                    decision,
                    business_pending=pending,
                )

    authorized, refusals, conflict = authorization.authorize_mutations(
        decision, proposal, runtime.candidates
    )
    if conflict:
        # Nothing of this turn is executed: a mixed or contradictory request is
        # asked about, not half-done. The question is persisted as a pending and
        # the receipt is a blocked row.
        conflict_message = (
            "这一轮里有互相矛盾或多个目标改动，我先不动清单。"
            "请分开说，或先告诉我要处理哪一个。"
        )
        focus_refs = (
            list(runtime.snapshot.focus_refs or []) if runtime.snapshot is not None else []
        )
        pending = gate_pending(
            decision, proposal, runtime.candidates, conflict=conflict, focus_refs=focus_refs
        )
        result = base(
            state,
            runtime,
            kind="refuse",
            pending=pending,
            message=conflict_message,
            error={"code": conflict, "message": conflict_message, "conflict": True},
        )
        return _attach_plan(
            result, state, runtime, proposal, decision, business_pending=pending
        )

    compiled, compile_message, compile_code = authorization.compile_decision(
        decision=decision,
        state=task_state,
        candidates=runtime.candidates,
        authorized=authorized,
        proposal=proposal,
    )
    if compile_code:
        kind = "clarify" if compile_code.startswith("SLOT_") else "refuse"
        return base(
            state,
            runtime,
            kind=kind,
            message=compile_message or "本轮没有可执行的修改。",
            error={"code": compile_code, "message": compile_message},
        )
    authorized = [*authorized, *compiled]
    for item in authorized:
        authorization.inherit_candidate_constraints(item, decision)

    if not authorized:
        return base(
            state,
            runtime,
            kind="refuse",
            message=str((turn.get("proposal") or {}).get("reply") or "本轮没有产生可执行的修改。"),
            error={"code": refusals[0] if refusals else "NO_AUTHORIZED_MUTATION"},
        )

    executor = PlanChangeExecutor(runtime.db, runtime.owner_id)
    executor.anchor = anchor_for(state, runtime)
    executor.decision = decision
    executor.goal_candidate = decision.candidate if decision.candidate is not None else None
    for _item in authorized:
        runtime.on_phase("validate")
    try:
        if len(authorized) == 1:
            prepared = [
                executor.prepare(
                    state=task_state,
                    mutation=authorized[0],
                    candidates=runtime.candidates,
                    store=runtime.store_id,
                    zone=runtime.delivery_zone_id,
                )
            ]
        else:
            prepared = executor.prepare_many(
                state=task_state,
                mutations=authorized,
                candidates=runtime.candidates,
                store=runtime.store_id,
                zone=runtime.delivery_zone_id,
            )
    except SemanticProtocolError as exc:
        return base(
            state,
            runtime,
            kind="refuse",
            message=exc.message,
            error={
                "code": exc.code,
                "message": exc.message,
                "retryable": bool(exc.retryable),
            },
        )

    staged = prepared[0]
    status = staged.get("status")
    if status == "needs_clarification":
        result = base(
            state,
            runtime,
            kind="clarify",
            pending=list(staged.get("pending") or []),
            message="",
        )
        return _attach_plan(
            result,
            state,
            runtime,
            proposal,
            decision,
            business_pending=list(staged.get("pending") or []),
        )
    if status != "staged":
        return base(
            state,
            runtime,
            kind="refuse",
            message=staged.get("message") or "这个修改没有执行。",
            error={"code": staged.get("code"), "message": staged.get("message")},
        )

    result = base(
        state,
        runtime,
        kind="mutation",
        verb=staged.get("verb"),
        target_kind=staged.get("target_kind"),
        target_id=staged.get("target_id"),
        operation=staged.get("operation"),
        switching=bool(staged.get("switching")),
        plan_result=staged.get("plan_result"),
        args=staged.get("args"),
        plan_patch=staged.get("plan_patch"),
        group_id=staged.get("group_id") or (staged.get("plan_result") or {}).get("group_id"),
        sku_id=staged.get("sku_id"),
        quantity=staged.get("quantity"),
        mutations=[mutation_payload(item) for item in authorized],
        message=staged.get("message"),
    )
    batch = []
    for step in prepared:
        clean = {key: value for key, value in step.items() if key != "plan_after"}
        clean.setdefault("group_id", (step.get("plan_result") or {}).get("group_id"))
        batch.append(clean)
    result["staged"]["batch"] = batch
    committed_refs = {staged.get("candidate_ref")} if staged.get("candidate_ref") else set()
    return _attach_plan(
        result,
        state,
        runtime,
        proposal,
        decision,
        committed_refs=committed_refs,
        activated=True,
    )


def _load(runtime: TurnRuntime) -> tuple[Any, Any]:
    from app.agent.graph.nodes.staging import load_state

    return load_state(runtime.db, runtime.session_id, runtime.owner_id)


def _attach_plan(
    result: dict[str, Any],
    state: GraphState,
    runtime: TurnRuntime,
    proposal: Any,
    decision: TurnDecision,
    **kwargs: Any,
) -> dict[str, Any]:
    plan = plan_context(state, runtime, proposal, decision, **kwargs)
    if plan and plan.get("__error__"):
        return base(
            state,
            runtime,
            kind="refuse",
            message=plan["__error__"]["message"],
            error=plan["__error__"],
        )
    if plan is not None:
        result["staged"]["context_plan"] = plan
    return result


__all__ = ["mutation"]
