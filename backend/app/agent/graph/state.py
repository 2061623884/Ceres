"""The request-level production graph's state contract.

One HTTP request runs exactly one graph: ``START → load_context → understand →
parse_validate → decide_turn → {retrieve | mutation | answer} → answer → respond
→ END``. There is no
checkpoint and no resume cursor, so this state is a *plain in-process record for
one turn* — nothing here is ever persisted as orchestration state.

The partitions keep the same "who may write what" split the graph always had:

``session``
    The request identity and the derived turn mode. Re-read by ``load_context``
    from the real business session on every request.
``authoritative``
    Real stored references only: task/plan ids and versions, the live pending
    questions, the real target the session is working on, and the shopper's
    explicit requirements. Every field is re-read from the business database by
    ``load_context``; there is no cached copy anywhere.
``candidate``
    The refs the model may name (``focus_refs``), the goal under discussion and
    what the shopper was really shown. The candidate *set* itself is a
    process-local object and lives on :class:`TurnRuntime`.
``turn``
    This request's reasoning: input, the one parsed proposal, the gate decision,
    the read results and the Decision route.
``staged``
    A proposed but unwritten change (plan result / plan patch / pending question
    / clarification text). Staged is never an execution credential.
``result``
    What the single commit transaction wrote and published.
"""

from __future__ import annotations

from typing import Any, TypedDict


class SessionState(TypedDict, total=False):
    """Request identity plus the dispatch mode derived from the stored task."""

    session_id: str
    owner_id: str
    turn_id: str
    #: ``active`` / ``completed`` (terminal task) / ``taskless``. Derived by
    #: ``load_context`` from the database, never supplied by the caller.
    turn_mode: str


class AuthoritativeState(TypedDict, total=False):
    """Real stored references re-read from the business database every request."""

    task_id: str | None
    plan_id: str | None
    plan_version: int | None
    state_version: int
    session_version: int
    pending: list[dict[str, Any]]
    #: The real target the session is currently built on (dish / product), with
    #: its server-side id and type so a follow-up never has to re-resolve it.
    target_kind: str | None
    target_id: str | None
    target_name: str | None
    #: The shopper's explicit requirements (people, budget, exclusions, goal).
    requirements: dict[str, Any]


class CandidateState(TypedDict, total=False):
    """The refs the model may name and the goal under discussion."""

    focus_refs: list[dict[str, Any]]
    goal_candidate: object | None
    #: What the shopper was really shown before (restored from stored context).
    displayed_candidates: list[dict[str, Any]]


class TurnState(TypedDict, total=False):
    """This request's reasoning, from the message to the route decision."""

    user_input: str
    #: The raw model payload of this request, exactly as the provider returned it.
    proposal: dict[str, Any] | None
    answer_reply: str | None
    #: Parsed Proposal produced by ``parse_validate``; consumed by the sole
    #: decision node and never used as a second routing authority.
    parsed_proposal: object | None
    understanding: dict[str, Any] | None
    decision: dict[str, Any] | None
    read_results: list[dict[str, Any]]
    model_calls: int
    #: Terminal marker: ``stopped`` / ``timed_out`` / ``failed`` / None.
    halt: str | None
    error: dict[str, Any] | None


class StagedState(TypedDict, total=False):
    """A proposed but unwritten change. Never an execution credential."""

    kind: str  # "mutation" | "clarify" | "answer" | "refuse"
    verb: str | None
    target_kind: str | None
    target_id: str | None
    operation: str | None
    switching: bool
    plan_result: dict[str, Any] | None
    args: dict[str, Any] | None
    plan_patch: dict[str, Any] | None
    group_id: str | None
    sku_id: str | None
    quantity: int | None
    pending: list[dict[str, Any]]
    mutations: list[dict[str, Any]]
    batch: list[dict[str, Any]]
    #: The durable conversation-context plan (pending/displayed/goal candidate)
    #: the commit transaction applies.
    context_plan: dict[str, Any] | None
    #: Immutable turn facts: {"session_id", "task_id", "state_version", "session_version"}.
    preconditions: dict[str, Any] | None
    message: str | None
    error: dict[str, Any] | None


class ResultState(TypedDict, total=False):
    """What the single commit transaction wrote and published."""

    plan_effect: str  # "keep" | "replace"
    action_results: list[dict[str, Any]]
    committed: bool
    #: The fixed receipt identity written in the same transaction as the effect.
    receipt: dict[str, Any] | None
    #: The published response body (kept on the runtime, never here).
    response: dict[str, Any] | None


class GraphState(TypedDict):
    """The state schema handed to :class:`langgraph.graph.StateGraph`."""

    session: SessionState
    authoritative: AuthoritativeState
    candidate: CandidateState
    turn: TurnState
    staged: StagedState
    result: ResultState


def update_partition(state: GraphState, name: str, **changes: Any) -> dict[str, Any]:
    """Return a whole-partition replacement for ``name``.

    Partitions have no reducer, so a node echoes the fields it did not touch;
    this helper is the one place that carries them forward.
    """
    return {name: {**state.get(name, {}), **changes}}


def merge_state(state: GraphState, update: dict[str, Any]) -> GraphState:
    """Apply a partition update to a *local* copy (nodes that reason further)."""
    merged: dict[str, Any] = dict(state)
    for name, value in update.items():
        merged[name] = {**state.get(name, {}), **value}
    return merged  # type: ignore[return-value]


def initial_state(
    *,
    session_id: str,
    owner_id: str,
    turn_id: str,
    user_input: str,
) -> dict[str, Any]:
    """A fresh request: identifiers and the shopper's message, nothing else.

    ``authoritative``/``candidate`` are empty on purpose — only ``load_context``
    may fill them, from the business database, on every request.
    """
    return {
        "session": {
            "session_id": session_id,
            "owner_id": owner_id,
            "turn_id": turn_id,
        },
        "authoritative": {},
        "candidate": {"focus_refs": [], "goal_candidate": None, "displayed_candidates": []},
        "turn": {
            "user_input": user_input,
            "proposal": None,
            "answer_reply": None,
            "parsed_proposal": None,
            "understanding": None,
            "decision": None,
            "read_results": [],
            "model_calls": 0,
            "halt": None,
            "error": None,
        },
        "staged": {
            "kind": "answer",
            "verb": None,
            "target_kind": None,
            "target_id": None,
            "operation": None,
            "switching": False,
            "plan_result": None,
            "args": None,
            "plan_patch": None,
            "group_id": None,
            "sku_id": None,
            "quantity": None,
            "pending": [],
            "mutations": [],
            "batch": [],
            "context_plan": None,
            "preconditions": None,
            "message": None,
            "error": None,
        },
        "result": {
            "plan_effect": "keep",
            "action_results": [],
            "committed": False,
            "receipt": None,
            "response": None,
        },
    }


__all__ = [
    "AuthoritativeState",
    "CandidateState",
    "GraphState",
    "ResultState",
    "SessionState",
    "StagedState",
    "TurnState",
    "initial_state",
    "merge_state",
    "update_partition",
]
