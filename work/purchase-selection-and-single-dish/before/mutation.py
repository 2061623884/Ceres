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
Products bind to the first real lookup hit in the existing retrieval order.
Similar dish/category candidates become a clarification with real options. ``changes``-only
turns on an existing target (a headcount patch) and pending-candidate slot fills
compile through the same shared functions with no extra model call and no loop.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.agent import authorization
from app.agent import context as turn_context
from app.agent.goal_router import (
    REASON_TASK_CONTEXT_CLEAR,
    MutationView,
    _target_matches_goal,
)
from app.agent.request_contract import request_digest
from app.agent.graph.nodes.staging import (
    anchor_for,
    base,
    mutation_payload,
    plan_context,
    preconditions,
)
from app.agent.graph.nodes.understand import timeout_error
from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, merge_state, update_partition
from app.agent.protocol import Lookup, Query, SemanticProposal, SemanticProtocolError, Uncertainty
from app.agent.state import Requirements
from app.agent.tools.change_plan import PlanChangeExecutor
from app.agent.turn_context_plan import gate_pending
from app.agent.turn_primitives import clamp_limits
from app.schemas.goal import TurnDecision
from app.services.template_plan_service import expand_ingredient_terms

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

    Products use the lookup's ranking, so common names need no extra question.
    Dishes/categories require exact/alias hits, or exact name equality for an
    unindexed lookup.
    """
    candidate = getattr(decision, "candidate", None)
    if candidate is None:
        return None
    if candidate.goal.fulfillment_mode == "ready_made":
        for result in read_results:
            if result.get("lookup_kind") != "product":
                continue
            for match in result["matches"]:
                option = candidates.resolve(match["ref"])
                if (
                    option.kind == "product"
                    and _target_matches_goal(
                        candidate.goal,
                        MutationView(
                            verb="add",
                            ref_kind=option.kind,
                            ref=option.ref,
                            ref_target_id=option.target_id,
                            ref_name=option.name,
                        ),
                    )
                ):
                    return option
    if candidate.goal.kind == "product_purchase":
        for result in read_results:
            if result.get("lookup_kind") == "product" and result["matches"]:
                return candidates.resolve(result["matches"][0]["ref"])
    allowed = authorization.expected_ref_kinds(candidate.goal)
    matches = _match_index(read_results)
    wanted = _norm(candidate.target_name or "")
    name_hit = None
    for option in candidates.by_kind("dish", "product", "scenario"):
        if allowed and option.kind not in allowed:
            continue
        if candidate.goal.fulfillment_mode == "ready_made" and not _target_matches_goal(
            candidate.goal,
            MutationView(
                verb="add",
                ref_kind=option.kind,
                ref=option.ref,
                ref_target_id=option.target_id,
                ref_name=option.name,
            ),
        ):
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
            if candidate.goal.fulfillment_mode == "ready_made" and not _target_matches_goal(
                candidate.goal,
                MutationView(
                    verb="add",
                    ref_kind=resolved.kind,
                    ref=resolved.ref,
                    ref_target_id=resolved.target_id,
                    ref_name=resolved.name,
                ),
            ):
                continue
            if str(ref) not in refs:
                refs.append(str(ref))
    return refs[:5]


def _serve_reads(
    state: GraphState, runtime: TurnRuntime, proposal: Any
) -> dict[str, Any] | None:
    """Consume this request's read-only requests once, before preparing."""
    decision = TurnDecision.model_validate(state["turn"]["decision"])
    reads = proposal
    if (
        decision.mutation_action == "prepare"
        and decision.relation == "switch"
        and "fulfillment_mode" in decision.changed_fields
        and decision.goal is not None
        and decision.goal.target_name
    ):
        kind = "product" if decision.goal.fulfillment_mode == "ready_made" else "dish"
        if not any(
            lookup.kind == kind and lookup.query == decision.goal.target_name
            for lookup in proposal.lookups
        ):
            reads = replace(
                proposal,
                lookups=[
                    *proposal.lookups,
                    Lookup(kind=kind, query=decision.goal.target_name),
                ],
            )
    if not (reads.lookups or reads.queries):
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
    results = runtime.reads.serve(reads, runtime.candidates, lookup_limit=lookup_limit)
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
        result = {**turn_update, **result}
    return result


def _prepare(
    state: GraphState, runtime: TurnRuntime, proposal: Any
) -> dict[str, Any]:
    turn = state["turn"]
    decision = TurnDecision.model_validate(turn["decision"])
    read_results = list(turn.get("read_results") or [])
    session, task_state = _load(runtime)
    if decision.mutation_action == "confirm_plan":
        pre = preconditions(state, runtime)
        plan = runtime.snapshot.current_plan
        selected_items = (
            runtime.plan_selection["selected_items"]
            if runtime.plan_selection is not None
            else [
                {"sku_id": item["sku_id"], "quantity": item["remaining_quantity"]}
                for item in plan["items"]
                if item["selected"]
                and item["remaining_quantity"] > 0
            ]
        )
        message = ""
        result = base(
            state,
            runtime,
            kind="mutation",
            verb="confirm_plan",
            plan_effect="keep",
            message=message,
        )
        result["staged"]["batch"] = [
            {
                "verb": "confirm_plan",
                "message": message,
                "args": {
                    "task_id": pre["task_id"],
                    "plan_id": plan["plan_id"],
                    "plan_version": plan["plan_version"],
                    "expected_state_version": pre["state_version"],
                    "expected_session_version": pre["session_version"],
                    "selected_items": selected_items,
                    "idempotency_key": runtime.request_id,
                    "request_digest": request_digest(
                        message=state["turn"]["user_input"],
                        expected_task_id=runtime.expected_task_id,
                        expected_state_version=runtime.expected_state_version,
                        expected_session_version=runtime.expected_session_version,
                        view_context=runtime.view_context,
                        plan_selection=runtime.plan_selection,
                    ),
                },
            }
        ]
        return _attach_plan(result, state, runtime, proposal, decision)
    if decision.mutation_action == "cancel_task":
        pre = preconditions(state, runtime)
        task_id = (
            None
            if decision.reason_code == REASON_TASK_CONTEXT_CLEAR
            else pre["task_id"]
        )
        message = (
            "已取消当前任务。"
            if task_id is not None
            else "已清除待答问题。当前没有进行中的任务。"
        )
        result = base(
            state,
            runtime,
            kind="mutation",
            message=message,
            plan_effect="clear",
        )
        result["staged"]["batch"] = [
            {
                "verb": "cancel_task",
                "message": message,
                "args": {
                    "task_id": task_id,
                    "request_id": runtime.request_id,
                    "expected_session_version": pre["session_version"],
                    "expected_state_version": pre["state_version"],
                    "request_digest": request_digest(
                        message=state["turn"]["user_input"],
                        expected_task_id=runtime.expected_task_id,
                        expected_state_version=runtime.expected_state_version,
                        expected_session_version=runtime.expected_session_version,
                        view_context=runtime.view_context,
                        plan_selection=runtime.plan_selection,
                    ),
                },
            }
        ]
        return _attach_plan(result, state, runtime, proposal, decision)
    system_selection = bool(
        decision.candidate is not None and decision.candidate.goal.kind == "meal_decision"
    )

    # Bind an unreferenced target to the reads: products keep lookup ranking;
    # dishes/categories require a named match.
    if (
        decision.mutation_action == "prepare"
        and decision.candidate is not None
        and not decision.candidate.target_ref
        and not system_selection
    ):
        for read in read_results:
            conflict = read.get("conflict") or {}
            if (
                read.get("kind") == "lookup"
                and _norm(read.get("query")) == _norm(decision.candidate.target_name)
                and set(conflict.get("constraint_fields", [])).intersection(
                    ("specification",)
                )
            ):
                result = base(
                    state, runtime, kind="refuse", message=conflict["message"], error=conflict,
                )
                return _attach_plan(result, state, runtime, proposal, decision)
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

    if system_selection:
        try:
            return _prepare_system_meal(state, runtime, proposal, decision, task_state)
        except SemanticProtocolError as exc:
            return base(
                state, runtime, kind="refuse", message=exc.message,
                error={"code": exc.code, "message": exc.message, "retryable": bool(exc.retryable)},
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
    context = turn_context.load_context(runtime.db, session) or {}
    saved = dict(context.get("session_constraints") or {})
    changes = proposal.understanding.changes
    clear = changes.clear if changes is not None else []
    for item in authorized:
        authorization.inherit_candidate_constraints(item, decision)
        if item.verb == "add":
            if not item.specification and "specification" not in clear:
                item.specification = dict(saved.get("specification") or {})
        if (task_state is not None and task_state.plan is not None
                and any("selection_goal" in target for target in task_state.plan["targets"])):
            item.excluded_ingredients = sorted(expand_ingredient_terms(item.excluded_ingredients))

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

    return _stage_prepared(state, runtime, proposal, decision, prepared, authorized)


def _prepare_system_meal(
    state: GraphState, runtime: TurnRuntime, proposal: Any,
    decision: TurnDecision, task_state: Any,
) -> dict[str, Any]:
    goal = decision.candidate.goal
    if task_state is None or task_state.plan is None or not any(
        "selection_goal" in target for target in task_state.plan["targets"]
    ):
        saved = runtime.snapshot.requirements
        exclusions = list(dict.fromkeys([
            *(saved.get("excluded_ingredients") or []), *goal.constraints.excluded_ingredients,
        ]))
        budget = goal.constraints.budget_yuan
        if budget is None and saved.get("budget_fen") is not None:
            budget = saved["budget_fen"] / 100
        changes = proposal.understanding.changes
        clear = changes.clear if changes is not None else []
        specification = dict(goal.constraints.specification)
        pending_answer = (
            runtime.snapshot.goal_candidate is not None
            and bool(runtime.snapshot.pending_clarifications)
            and proposal.understanding.goal_relation in ("amend", "unspecified")
        )
        if not specification and "specification" not in clear and not pending_answer:
            specification = dict(saved.get("specification") or {})
        goal = goal.model_copy(update={"constraints": goal.constraints.model_copy(update={
            "budget_yuan": budget, "excluded_ingredients": exclusions,
            "specification": specification,
        })})
        decision.candidate.goal = goal
    constraints = goal.constraints
    requirements = Requirements(
        people=constraints.people,
        budget_fen=(round(constraints.budget_yuan * 100) if constraints.budget_yuan is not None else None),
        excluded_ingredients=sorted(expand_ingredient_terms(constraints.excluded_ingredients)),
        specification=dict(constraints.specification),
    )
    runtime.reads.requirements = requirements
    if decision.relation == "switch" and decision.focus_kind == "plan_target" and not decision.changed_fields:
        current = runtime.candidates.resolve(decision.focus_ref)
        runtime.reads.excluded_dish_ids = {current.target_id}
    runtime.on_phase("retrieve")
    if runtime.stop():
        return update_partition(state, "turn", halt="stopped")
    if runtime.expired():
        return update_partition(state, "turn", halt="timed_out", error=timeout_error())
    reads = runtime.reads.serve(
        SemanticProposal(queries=[Query(kind="recommend")]), runtime.candidates, lookup_limit=0,
    )
    if runtime.stop():
        return update_partition(state, "turn", halt="stopped")
    if runtime.expired():
        return update_partition(state, "turn", halt="timed_out", error=timeout_error())
    read_update = update_partition(
        state, "turn", read_results=[*(state["turn"].get("read_results") or []), *reads],
    )
    state = merge_state(state, read_update)
    projected = task_state
    if task_state is not None and decision.candidate.relation != "append":
        projected = replace(task_state, requirements=requirements, plan=None)
    executor = PlanChangeExecutor(runtime.db, runtime.owner_id)
    executor.anchor = anchor_for(state, runtime)
    executor.decision = decision
    executor.goal_candidate = decision.candidate
    options = reads[0]["buildable_dishes"]
    failures = []
    for option in options:
        if runtime.stop():
            return update_partition(state, "turn", halt="stopped")
        if runtime.expired():
            return update_partition(state, "turn", halt="timed_out", error=timeout_error())
        ref = option["ref"]
        candidate = runtime.candidates.resolve(ref)
        if candidate.kind not in authorization.expected_ref_kinds(goal):
            continue
        decision.candidate.target_ref = ref
        decision.candidate.target_id = candidate.target_id
        decision.candidate.target_kind = candidate.kind
        mutation = authorization.goal_target_mutation(decision.candidate, runtime.candidates)
        mutation.excluded_ingredients = list(requirements.excluded_ingredients)
        runtime.on_phase("validate")
        try:
            staged = executor.prepare(
                state=projected, mutation=mutation, candidates=runtime.candidates,
                store=runtime.store_id, zone=runtime.delivery_zone_id,
            )
        except SemanticProtocolError as exc:
            if exc.code != "BUDGET_EXCEEDED":
                raise
            failures.append({"ref": ref, "code": exc.code, "message": exc.message})
            continue
        if (staged["status"] == "staged" and staged["plan_result"]["can_confirm"]
                and staged["plan_result"]["coverage_mode"] == "full"):
            staged["plan_result"]["target"]["selection_goal"] = goal.model_dump()
            staged["message"] = f"已按你的条件先配「{candidate.name}」。想换菜可以说换一个。"
            displayed = [row["ref"] for row in options if row["ref"] != ref]
            proposal = replace(proposal, display_refs=displayed)
            result = _stage_prepared(state, runtime, proposal, decision, [staged], [mutation])
            return {**result, **read_update}
        if staged["status"] == "failed":
            if staged["code"] not in ("SUPPLY_UNAVAILABLE", "BUDGET_EXCEEDED", "VALIDATION_FAILED", "UNCOVERED"):
                raise SemanticProtocolError(staged["code"], staged["message"])
            failures.append({"ref": ref, "code": staged["code"], "message": staged["message"]})
        elif staged["status"] == "staged":
            failures.append({"ref": ref, "code": "SUPPLY_UNAVAILABLE", "message": "候选没有完整覆盖这道菜的供货需求。"})
        else:
            raise SemanticProtocolError("SYSTEM_SELECTION_FAILED", staged["message"])
    message = "这次推荐的候选没有通过你的条件和供货校验，暂时没法帮你配出清单。可以调整条件再试。"
    if constraints.specification:
        reasons = list(dict.fromkeys(
            failure["message"] for failure in failures if failure["code"] == "VALIDATION_FAILED"
        ))
        if reasons:
            message += " " + " ".join(reasons)
    result = base(state, runtime, kind="refuse", message=message,
                  error={"code": "NO_FEASIBLE_MEAL", "message": message, "candidates": failures})
    result = _attach_plan(result, state, runtime, proposal, decision)
    return {**result, **read_update}


def _stage_prepared(
    state: GraphState, runtime: TurnRuntime, proposal: Any, decision: TurnDecision,
    prepared: list[dict[str, Any]], authorized: list[Any],
) -> dict[str, Any]:
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

    if (
        staged.get("verb") == "add"
        and staged.get("target_kind") in ("dish", "scenario")
        and decision.goal is not None
        and decision.goal.kind == "meal_plan"
        and decision.goal.fulfillment_mode == "unspecified"
        and decision.relation in ("new", "switch")
    ):
        staged["message"] = f"{staged['message']}。这份清单按食材准备；想买现成的可以告诉我。"

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
