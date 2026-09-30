"""Constrained goal parsing: the model proposes, the server normalizes.

This module turns a bounded, structured goal proposal into a validated
``Goal`` and merges the goal under discussion with later answers. It never reads
the raw user message, never calls a model, and never touches the database, a
plan or the cart: the understanding layer is a pure function over what the
model already extracted.

Strictness is the point. An unknown top-level or constraint key, a server-owned
field (``plan_id``, ``price_fen``, ``route`` ...) or a wrongly shaped value is a
``GoalParseError`` rather than a silently ignored field, because "the model tried
to set a price" and "the model said nothing about price" must not look the same.
The per-turn ``Understanding`` is built by ``app.agent.protocol.parse_proposal``.

See ``docs/plans/2026-09-19-purchase-intent-p1-implementation.md``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.schemas.goal import (
    FORBIDDEN_GOAL_KEYS,
    Goal,
    GoalCandidate,
    GoalChanges,
    GoalConstraints,
    IntentState,
    Understanding,
    normalize_fulfillment_mode,
    normalize_goal_kind,
    normalize_meal_time,
)


class GoalParseError(Exception):
    """A goal proposal that violates the constrained understanding contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _str_list(value: Any, where: str) -> list[str]:
    """Strings in order, deduplicated. A bare string means a one-item list.

    Empty entries are dropped rather than kept as blank items, so an empty list
    is the only representation of "nothing stated".
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise GoalParseError("MALFORMED_GOAL", f"{where} 必须是字符串数组")
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise GoalParseError("MALFORMED_GOAL", f"{where} 必须是字符串数组")
        text = entry.strip()
        if text and text not in out:
            out.append(text)
    return out


def _positive_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoalParseError("MALFORMED_GOAL", f"{where} 必须是正整数")
    if value < 1 or value > 99:
        raise GoalParseError("MALFORMED_GOAL", f"{where} 必须在 1 到 99 之间")
    return int(value)


def _budget_yuan(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoalParseError("MALFORMED_GOAL", "constraints.budget_yuan 必须是数字")
    if value < 0:
        raise GoalParseError("MALFORMED_GOAL", "constraints.budget_yuan 不能为负")
    return float(value)


def _reject_unknown(
    payload: Mapping[str, Any],
    allowed: set[str],
    where: str,
    *,
    code: str = "MALFORMED_GOAL",
) -> None:
    unknown = sorted(str(key) for key in payload if str(key) not in allowed)
    if unknown:
        raise GoalParseError(code, f"{where} 含未知字段: {', '.join(unknown)}")


def _validation_message(exc: ValidationError) -> str:
    parts = [str(err.get("msg") or "") for err in exc.errors()[:3]]
    return "; ".join(part for part in parts if part) or "goal 结构不合法"


def _constraints(raw: Mapping[str, Any]) -> GoalConstraints:
    _reject_unknown(raw, set(GoalConstraints.model_fields), "goal.constraints")
    try:
        return GoalConstraints(
            people=_positive_int(raw.get("people"), "constraints.people"),
            budget_yuan=_budget_yuan(raw.get("budget_yuan")),
            dietary=_str_list(raw.get("dietary"), "constraints.dietary"),
            excluded_ingredients=_str_list(
                raw.get("excluded_ingredients"), "constraints.excluded_ingredients"
            ),
            meal_time=normalize_meal_time(raw.get("meal_time")),
        )
    except ValidationError as exc:  # pragma: no cover - guarded above
        raise GoalParseError("MALFORMED_GOAL", _validation_message(exc)) from exc


def parse_goal(raw: Goal | Any) -> Goal:
    """Normalize one constrained goal proposal into a ``Goal``.

    ``parse_goal`` is idempotent: an already-validated ``Goal`` is returned
    unchanged so a caller can normalize once at the boundary and pass the object
    on without re-parsing. Nothing here mutates its input.
    """
    if isinstance(raw, Goal):
        return raw
    if not isinstance(raw, Mapping):
        raise GoalParseError("MALFORMED_GOAL", "goal 必须是 JSON 对象")

    forbidden = sorted(key for key in (str(k) for k in raw) if key in FORBIDDEN_GOAL_KEYS)
    if forbidden:
        raise GoalParseError(
            "FORBIDDEN_FIELD",
            f"goal 不允许出现由服务端决定的字段: {', '.join(forbidden)}",
        )
    _reject_unknown(raw, set(Goal.model_fields), "goal")

    constraints_raw = raw.get("constraints")
    if constraints_raw is None:
        constraints_raw = {}
    if not isinstance(constraints_raw, Mapping):
        raise GoalParseError("MALFORMED_GOAL", "goal.constraints 必须是对象")

    try:
        return Goal(
            kind=normalize_goal_kind(raw.get("kind")),
            fulfillment_mode=normalize_fulfillment_mode(raw.get("fulfillment_mode")),
            description=_text(raw.get("description")) or "",
            target_name=_text(raw.get("target_name")),
            category_id=_text(raw.get("category_id")),
            category_name=_text(raw.get("category_name")),
            items=_str_list(raw.get("items"), "items"),
            constraints=_constraints(constraints_raw),
            notes=_str_list(raw.get("notes"), "notes"),
            assumptions=_str_list(raw.get("assumptions"), "assumptions"),
        )
    except ValidationError as exc:
        raise GoalParseError("MALFORMED_GOAL", _validation_message(exc)) from exc


def parse_intent_state(raw: Goal | Any, *, source_turn_id: str | None = None) -> IntentState:
    """Build the pure understanding-layer hand-off for one constrained proposal.

    The raw user-language adapter (normally the LLM/protocol boundary) is not
    part of this slice. It supplies a bounded Goal-shaped proposal; this
    function validates it and derives the route on the server.
    """
    goal = parse_goal(raw)
    # Import locally to keep the schema/parser import graph free of router cycles.
    from app.agent.goal_router import route_goal

    return IntentState(
        goal=goal,
        decision=route_goal(goal),
        source_turn_id=source_turn_id,
    )


# ----------------------------------------------------------------- goal merging


def apply_goal_changes(goal: Goal, changes: GoalChanges) -> Goal:
    """Merge one constrained patch into a goal: omitted = keep, clear = revoke.

    Pure and total: the result is a new ``Goal``. A field the patch does not name
    keeps its value, which is what makes "三个人" a follow-up rather than a
    restatement of the whole goal.
    """
    data = goal.model_dump()
    constraints = dict(data.get("constraints") or {})
    for name, value in changes.set.stated().items():
        if name == "fulfillment_mode":
            data["fulfillment_mode"] = value
        else:
            constraints[name] = value
    for name in changes.clear:
        if name == "fulfillment_mode":
            # Revoking the mode never becomes "assume self-cook".
            data["fulfillment_mode"] = "unspecified"
        elif name in ("dietary", "excluded_ingredients"):
            constraints[name] = []
        else:
            constraints[name] = None
    data["constraints"] = constraints
    return Goal(**data)


def candidate_ref_for(goal: Goal, target_ref: str | None, relation: str = "") -> str:
    """The server's own opaque handle for a candidate goal.

    Derived only from server values, so the same goal keeps the same handle, and
    two different goals can never share one: the relation is part of the identity,
    because a pending *switch* and a pending *append* of the same target are not
    the same commitment.
    """
    identity = "|".join(
        [
            str(relation),
            str(goal.kind),
            str(target_ref or goal.target_name or goal.category_name or ""),
            str(goal.fulfillment_mode),
        ]
    )
    return "goal-" + hashlib.sha256(identity.encode()).hexdigest()[:12]


def merge_goal_candidate(
    candidate: GoalCandidate,
    understanding: Understanding,
    *,
    missing_slots: list[str] | None = None,
) -> GoalCandidate | None:
    """Apply an amendment to a candidate goal without losing its switch intent.

    The candidate's original ``relation``, target and binding survive: answering
    "三个人" fills a slot, it does not turn a pending *switch* into an append. A
    proposal that carries no field patch does not touch the candidate at all.
    """
    changes = understanding.changes
    if changes is None or changes.is_empty():
        return None
    merged = apply_goal_changes(candidate.goal, changes)
    return candidate.model_copy(
        update={
            "goal": merged,
            "missing_slots": list(
                missing_slots if missing_slots is not None else candidate.missing_slots
            ),
        }
    )


def answer_goal_candidate(candidate: GoalCandidate, answer: Goal) -> Goal:
    """The goal under discussion, completed by a named answer to its question.

    What the answer states wins; what it leaves out keeps the candidate's value,
    so "番茄炒蛋" after "两个人，想吃什么？" still carries the two people.
    """
    stated = answer.constraints.model_dump(exclude_defaults=True)
    constraints = candidate.goal.constraints.model_copy(update=stated)
    mode = answer.fulfillment_mode
    if mode == "unspecified":
        mode = candidate.goal.fulfillment_mode
    return answer.model_copy(update={"constraints": constraints, "fulfillment_mode": mode})


__all__ = [
    "GoalParseError",
    "answer_goal_candidate",
    "apply_goal_changes",
    "candidate_ref_for",
    "merge_goal_candidate",
    "parse_goal",
    "parse_intent_state",
]
