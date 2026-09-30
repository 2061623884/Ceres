"""``answer``: the request's final reasoning, then the single staged effect.

Three shapes reach this node:

* ``route == "mutation"`` — the ``mutation`` node already staged the plan change;
  there is nothing left to decide, so the node passes through.
* ``route == "retrieve"`` — one read-only model call supplies answer text from
  the facts ``retrieve`` actually fetched, without changing the Decision.
* otherwise — the proposal already carries the answer / question, so the node
  stages the reply, the clarification or the honest refusal.

It reuses the existing wording and context-plan helpers; it adds no business
action and never fabricates a price, a stock level or a success.
"""

from __future__ import annotations

from typing import Any

from app.agent.goal_router import PLAN_ACT_REPLIES
from app.agent.graph.nodes.staging import base, plan_context
from app.agent.graph.nodes.understand import (
    Halt,
    halt_update,
    propose_round,
    understanding_error,
)
from app.agent.graph.response_contract import prepare_graph_message
from app.agent.graph.runtime import TurnRuntime, context_of
from app.agent.graph.state import GraphState, merge_state, update_partition
from app.agent.graph.turn_commit import (
    committed_step_row,
    understanding_wrapper,
)
from app.agent.protocol import SemanticProtocolError
from app.schemas.goal import TurnDecision

def answer(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Stage the reply / question / refusal for this request."""
    runtime = context_of(runtime)
    state = dict(state)  # type: ignore[assignment]
    route = (state["turn"].get("decision") or {}).get("route")

    if route == "mutation" and not state["turn"].get("halt"):
        # The mutation node already staged the prepared change; the answer is
        # organized from that real staged business result below.
        staged = dict(state["staged"])
    else:
        if route == "retrieve" and not state["turn"].get("halt"):
            state = _grounded_answer(state, runtime)
        update = _dispatch(state, runtime)
        staged = dict(update.get("staged") or state["staged"])

    _compose_message(state, runtime, staged)
    return {"staged": staged}


def _compose_message(
    state: GraphState, runtime: TurnRuntime, staged: dict[str, Any]
) -> str:
    """Organize this request's user-facing text from the real staged result.

    Uses the shared wording helpers (no extra model, no polish call). The plan's
    own summary is a post-merge fact and is appended by the commit transaction,
    which owns the really persisted plan.
    """
    kind = str(staged.get("kind") or "answer")
    decision = state["turn"].get("decision") or {}
    proposal = state["turn"].get("proposal") or {}
    context_plan = staged.get("context_plan") or {}
    displayed = list(context_plan.get("displayed") or [])
    pending = list(context_plan.get("new_pending") or staged.get("pending") or [])
    rows = [committed_step_row(step) for step in staged.get("batch") or []]
    error = staged.get("error") or {}
    refusal = None
    if error:
        refusal = (
            understanding_wrapper(error)
            if error.get("understanding")
            else str(error.get("message") or "")
        )
    message = prepare_graph_message(
        kind=kind,
        # A plan act chat cannot carry out is answered in the server's words.
        model_reply=(
            PLAN_ACT_REPLIES.get(str(decision.get("reason_code") or ""))
            or str(state["turn"].get("answer_reply") or proposal.get("reply") or "")
            if kind == "answer" else ""
        ),
        plan=None,
        plan_effect="keep",
        action_results=rows,
        pending=pending,
        displayed=displayed,
        refusal_message=refusal,
    )
    note = _unsupported_note(state)
    if note:
        message = f"{message}\n{note}" if message else note
    staged["message"] = message
    return message


def _unsupported_note(state: GraphState) -> str:
    """Name the stated conditions nothing could apply, instead of dropping them."""
    proposal = state["turn"].get("parsed_proposal")
    unsupported = getattr(getattr(proposal, "understanding", None), "unsupported", None) or []
    if not unsupported:
        return ""
    return f"说明：「{'、'.join(unsupported)}」暂时没法按条件筛选，这次没有用上。"


def _grounded_answer(state: GraphState, runtime: TurnRuntime) -> GraphState:
    """One read-only model call that supplies answer text only.

    The original Decision remains authoritative.  In particular, mutations in
    a malformed/over-eager read-only response never become a new route.
    """
    query_results = list(state["turn"].get("read_results") or [])
    try:
        raw, calls = propose_round(
            state, runtime, query_results=query_results, read_only=True
        )
    except Halt as halt:
        return merge_state(state, halt_update(state, halt.reason, halt.error))

    state = merge_state(state, update_partition(state, "turn", model_calls=calls))
    reply = raw.get("reply") if raw else None
    if not isinstance(reply, str) or not reply.strip():
        return merge_state(
            state,
            halt_update(
                state,
                "failed",
                understanding_error(
                    SemanticProtocolError("NO_REPLY", "模型没有给出回答", retryable=True)
                ),
            ),
        )
    return merge_state(state, update_partition(state, "turn", answer_reply=reply))


def _dispatch(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Pick the staged kind, with the same precedence the decision always had."""
    turn = state["turn"]
    decision = turn.get("decision") or {}
    if (
        turn.get("halt")
        or turn.get("error")
        or decision.get("route") == "refuse"
    ):
        return refuse_prepare(state, runtime)
    if decision.get("route") == "clarify":
        return clarify_prepare(state, runtime)
    return answer_prepare(state, runtime)


def answer_prepare(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    turn = state["turn"]
    result = base(
        state,
        runtime,
        kind="answer",
        message=str(turn.get("answer_reply") or (turn.get("proposal") or {}).get("reply") or ""),
    )
    proposal = turn["parsed_proposal"]
    decision = TurnDecision.model_validate(turn["decision"]) if turn.get("decision") else None
    result = _attach_plan(result, state, runtime, proposal, decision)
    return result


def clarify_prepare(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    from app.agent import context as turn_context

    raw = state["turn"].get("proposal") or {}
    proposal = state["turn"]["parsed_proposal"]
    pending: list[dict[str, Any]] = []
    try:
        for uncertainty in proposal.uncertainties:
            pending.append(turn_context.build_pending(uncertainty, runtime.candidates))
    except SemanticProtocolError as exc:
        # A question whose option references a candidate the server never issued
        # is refused whole: publishing it would show fewer choices than intended.
        return base(
            state,
            runtime,
            kind="refuse",
            message=exc.message,
            error={
                "code": exc.code,
                "message": exc.message,
                "retryable": bool(exc.retryable),
                "understanding": True,
            },
        )
    result = base(
        state,
        runtime,
        kind="clarify",
        pending=pending,
        message="",
    )
    decision_raw = state["turn"].get("decision")
    decision = TurnDecision.model_validate(decision_raw) if decision_raw else None
    return _attach_plan(result, state, runtime, proposal, decision)


def refuse_prepare(state: GraphState, runtime: TurnRuntime) -> dict[str, Any]:
    """Stage the already-decided refusal or a real execution failure."""
    turn = state["turn"]
    decision = turn.get("decision") or {}
    halt = turn.get("halt")
    if halt:
        error = turn.get("error") or {}
        code = str(
            error.get("code")
            or {"stopped": "STOPPED", "timed_out": "TURN_DEADLINE_EXCEEDED"}.get(
                halt, "TURN_FAILED"
            )
        )
        message = str(error.get("message") or "本轮没有执行修改。")
        if halt == "stopped":
            message = "已停止，原清单保持不变。"
        return base(
            state,
            runtime,
            kind="refuse",
            message=message,
            error={
                "code": code,
                "message": message,
                "retryable": bool(error.get("retryable")),
                "understanding": bool(error.get("understanding")),
            },
        )
    if turn.get("error"):
        error = turn["error"]
        return base(
            state,
            runtime,
            kind="refuse",
            message=str(error.get("message") or "本轮没有执行修改。"),
            error={
                "code": error.get("code"),
                "message": error.get("message"),
                "retryable": bool(error.get("retryable")),
                "understanding": bool(error.get("understanding")),
            },
        )
    message = "本轮没有执行修改。"
    return base(
        state, runtime, kind="refuse", message=message,
        error={"code": decision.get("reason_code") or "TURN_REFUSED", "message": message},
    )


def _attach_plan(
    result: dict[str, Any],
    state: GraphState,
    runtime: TurnRuntime,
    proposal: Any,
    decision: TurnDecision | None,
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


__all__ = ["answer", "answer_prepare", "clarify_prepare", "refuse_prepare"]
