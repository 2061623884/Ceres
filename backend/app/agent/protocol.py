"""Low-cardinality semantic proposal protocol — the single implementation.

The model never sees the internal business operations. It sees a small, bounded
list of *server-owned candidates* (real dishes, real sellable SKUs, real open
scenarios, plus the groups and rows of the plan already on screen) and may
answer with:

* ``reply``         — user-visible text,
* ``mutations``     — typed ``add`` / ``change`` / ``remove`` intents,
* ``lookups``       — read-only retrieval requests,
* ``queries``       — read-only answer requests,
* ``uncertainties`` — one question whose options are real candidates.

Nothing in this module reads the raw user message for meaning. Every string the
model is allowed to reference is an opaque ref allocated here, and every ref is
resolved against server data before anything is executed.

This module is deliberately dependency-free: no ORM, no services, no FastAPI, no
``app.agent.state``. It carries the wire protocol and the reference vocabulary
only. Business compilation (turning a validated mutation into real service
arguments) lives at the tool boundary in ``agent/tools/change_plan.py``, and the
ORM-backed snapshot assembly lives in ``agent/context.py``.
"""

from __future__ import annotations

import hashlib
#: ``field`` is aliased because ``Mutation`` legitimately has a *field* called
#: ``field``; an unaliased import would be shadowed inside that class body and
#: the next ``field(default_factory=...)`` would call ``None``.
from dataclasses import dataclass, field as dc_field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.agent.goal import GoalParseError, parse_understanding
from app.schemas.goal import Understanding

PROPOSAL_VERSION = 1

MUTATION_VERBS = ("add", "change", "remove")
CHANGE_FIELDS = ("quantity", "people", "constraints")
QUANTITY_MODES = ("set", "delta")
LOOKUP_KINDS = ("dish", "product")
QUERY_KINDS = ("recommend", "recipe", "cart", "catalog")

CANDIDATE_KINDS = ("dish", "product", "scenario", "group", "item")

#: Caps for the parts of the candidate set that come from a bounded source: the
#: scenario fixture, the plan on screen. Dishes and products have no cap here —
#: they are only ever present because a real retrieval returned them.
MAX_SCENARIOS = 3
MAX_GROUPS = 64
MAX_ITEMS = 128

#: Keys the model may never author. Their presence is a protocol error, not a
#: silently ignored field: a model that tries to set a price or a version must be
#: told so instead of having its attempt dropped.
FORBIDDEN_KEYS = frozenset(
    {
        "plan_id",
        "plan_version",
        #: Money is authored in yuan only; a fen amount from the model is refused
        #: outright rather than silently rescaled.
        "budget_fen",
        "price",
        "price_fen",
        "unit_price_fen",
        "total_price_fen",
        "stock",
        "available_qty",
        "ready",
        "state_version",
        "session_version",
        "task_id",
        "operation",
        "target_kind",
        "target_id",
        "dish_id",
    }
)

PROPOSAL_TOP_KEYS = frozenset(
    {
        "reply",
        "understanding",
        "mutations",
        "lookups",
        "queries",
        "uncertainties",
        "display_refs",
        "resolved_questions",
        "purchase_requested",
    }
)


class SemanticProtocolError(Exception):
    """A proposal that violates the protocol. Never silently repaired."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# --------------------------------------------------------------------- candidates


@dataclass(frozen=True)
class CandidateRef:
    ref: str
    kind: str
    target_id: str
    name: str = ""
    group_id: str | None = None
    scope: str = ""
    #: The real business target type (``dish`` / ``product`` / ``scenario``).
    #: For a group ref ``kind`` is ``group``, so the true type must be carried
    #: separately or the model loses it the moment a plan exists.
    target_kind: str = ""


@dataclass
class CandidateSet:
    """Server-owned, bounded candidate list for exactly one turn."""

    refs: dict[str, CandidateRef] = dc_field(default_factory=dict)
    order: list[str] = dc_field(default_factory=list)
    _counters: dict[str, int] = dc_field(default_factory=dict)

    # ---------------------------------------------------------------- allocation

    def allocate(
        self,
        kind: str,
        target_id: str,
        name: str = "",
        *,
        group_id: str | None = None,
        scope: str = "",
        target_kind: str = "",
    ) -> CandidateRef:
        if kind not in CANDIDATE_KINDS:
            # A ref is the model's only handle on server data. Minting one under
            # an unknown kind would let a reference resolve against a type that
            # no downstream check knows about, so it is refused outright.
            raise SemanticProtocolError(
                "UNKNOWN_CANDIDATE_KIND",
                f"候选引用类型必须是 {', '.join(CANDIDATE_KINDS)} 之一: {kind}",
            )
        if not str(target_id or "").strip():
            raise SemanticProtocolError("MALFORMED_CANDIDATE", "候选引用必须有 target_id")
        identity = f"{kind}:{target_id}:{group_id or ''}:{scope}"
        ref = kind[0] + hashlib.sha256(identity.encode()).hexdigest()[:16]
        if ref in self.refs:
            return self.refs[ref]
        candidate = CandidateRef(
            ref=ref,
            kind=kind,
            target_id=str(target_id),
            name=name,
            group_id=group_id,
            scope=scope,
            target_kind=target_kind or (kind if kind in ("dish", "product", "scenario") else ""),
        )
        self.refs[ref] = candidate
        self.order.append(ref)
        return candidate

    def resolve(self, ref: Any) -> CandidateRef | None:
        if not isinstance(ref, str):
            return None
        return self.refs.get(ref)

    def by_kind(self, *kinds: str) -> list[CandidateRef]:
        return [self.refs[r] for r in self.order if self.refs[r].kind in kinds]

    # -------------------------------------------------------------------- view

    def model_view(self, state: Any = None) -> dict[str, Any]:
        """Exactly what the model is allowed to see and reference.

        ``state`` is only read through ``getattr(state, "plan", None)`` so this
        module never depends on the ORM-backed task state.

        ``candidates_note`` matters: this list is a *bounded starting point*, not
        the whole store. Without it the model reads a short list as the complete
        catalogue and tells the shopper an item does not exist.
        """
        view: dict[str, Any] = {
            "candidates_note": (
                "以下只是本轮的有限候选起点，不代表全店商品；"
                "没有你要的东西时用 lookups 做只读检索，不要据此断言没有。"
            ),
            "dishes": [{"ref": c.ref, "name": c.name} for c in self.by_kind("dish")],
            "products": [{"ref": c.ref, "name": c.name} for c in self.by_kind("product")],
            "scenarios": [
                {"ref": c.ref, "name": c.name}
                for c in self.by_kind("scenario")
            ],
            "current_plan": self._plan_view(state),
        }
        return view

    def _plan_view(self, state: Any) -> dict[str, Any] | None:
        """What is actually on screen, in enough detail that the model is not
        blind after delivery: quantities, ticks, what is already bought, and the
        real type of every target."""
        plan = getattr(state, "plan", None) if state is not None else None
        if not isinstance(plan, dict) or not plan.get("items"):
            return None
        rows = {
            str(item.get("sku_id")): item for item in plan.get("items") or []
        }
        return {
            "plan_id": plan.get("plan_id"),
            "plan_version": plan.get("plan_version"),
            "can_confirm": plan.get("can_confirm"),
            "coverage_mode": plan.get("coverage_mode"),
            "groups": [
                {
                    "ref": c.ref,
                    "group_id": c.group_id,
                    "target_kind": c.target_kind,
                    "name": c.name,
                }
                for c in self.by_kind("group")
            ],
            "items": [
                {
                    "ref": c.ref,
                    "sku_id": c.target_id,
                    "name": c.name,
                    "quantity": (rows.get(c.target_id) or {}).get("quantity"),
                    "selected": (rows.get(c.target_id) or {}).get("selected"),
                    "added_quantity": (rows.get(c.target_id) or {}).get("added_quantity"),
                    "remaining_quantity": (rows.get(c.target_id) or {}).get("remaining_quantity"),
                    "role": (rows.get(c.target_id) or {}).get("role"),
                }
                for c in self.by_kind("item")
            ],
        }


def add_lookup_candidates(
    candidates: CandidateSet,
    *,
    kind: str,
    rows: list[dict[str, Any]],
    limit: int,
) -> list[CandidateRef]:
    """Append read-only retrieval results to the same bounded list."""
    added: list[CandidateRef] = []
    for row in rows[:limit]:
        if kind == "dish":
            target_id = row.get("dish_id") or row.get("template_id")
            name = str(row.get("name") or row.get("scenario") or target_id or "")
        else:
            target_id = row.get("sku_id")
            name = str(row.get("name_zh") or row.get("name") or target_id or "")
        if not target_id:
            continue
        existing = next(
            (c for c in candidates.by_kind(kind) if c.target_id == str(target_id)), None
        )
        added.append(
            existing
            if existing is not None
            else candidates.allocate(kind, str(target_id), name)
        )
    return added


# --------------------------------------------------------------------- proposal


@dataclass
class Mutation:
    verb: str
    name: str = ""
    candidate_ref: str | None = None
    target_ref: str | None = None
    field: str | None = None
    quantity_mode: str | None = None
    quantity_value: int | None = None
    people: int | None = None
    excluded_ingredients: list[str] = dc_field(default_factory=list)
    budget_fen: int | None = None
    #: Deprecated: a whole-plan replacement used to be granted by this boolean
    #: alone. It is still accepted so an older proposal parses, but it no longer
    #: authorizes anything by itself: the turn's validated ``goal_relation``
    #: decides, and a switch without that relation is refused.
    switch_goal: bool = False


@dataclass
class Lookup:
    kind: str
    query: str
    #: Constraints stated in *this* turn, for *this* read only. They are parsed
    #: by the same ``_parse_constraints`` the mutation path uses, so an exclusion
    #: is a structured filter here too — never something the vector route is
    #: asked to understand. They are merged with the saved requirements by union,
    #: so a read can add an exclusion but can never silently drop one.
    excluded_ingredients: list[str] = dc_field(default_factory=list)
    budget_fen: int | None = None


@dataclass
class Query:
    kind: str
    query: str | None = None
    #: The same read-only constraints a lookup may carry, parsed by the same
    #: ``_parse_constraints``. Without them a first-turn "不要花生" could only be
    #: expressed on a lookup, so a recommendation or a recipe would have to be
    #: retrieved with no exclusion at all. They are merged with the saved
    #: requirements by union, so a query can add an exclusion and can never
    #: silently lift one that is already saved.
    excluded_ingredients: list[str] = dc_field(default_factory=list)
    budget_fen: int | None = None


@dataclass
class Uncertainty:
    slot: str
    question: str
    option_refs: list[str] = dc_field(default_factory=list)


@dataclass
class SemanticProposal:
    reply: str = ""
    #: What the sentence meant, in the constrained understanding vocabulary. The
    #: model proposes it and may not turn it into authority: route, readiness and
    #: write permission are derived from it by the server gate.
    understanding: Understanding | None = None
    #: The shopper's purchase intent for this turn, recognised by the model
    #: *before* any retrieval. It is the only thing that lets a proposal which
    #: starts with lookups/queries still compile a mutation afterwards; it is
    #: never a server-side reading of the raw sentence, and it can never be
    #: acquired after the read-only phase has begun.
    purchase_requested: bool = False
    mutations: list[Mutation] = dc_field(default_factory=list)
    lookups: list[Lookup] = dc_field(default_factory=list)
    queries: list[Query] = dc_field(default_factory=list)
    uncertainties: list[Uncertainty] = dc_field(default_factory=list)
    display_refs: list[str] = dc_field(default_factory=list)
    resolved_questions: list[str] = dc_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.reply.strip()
            or self.understanding
            or self.mutations
            or self.lookups
            or self.queries
            or self.uncertainties
            or self.display_refs
        )


def _reject_forbidden(payload: Any, where: str) -> None:
    if not isinstance(payload, dict):
        return
    hit = sorted(FORBIDDEN_KEYS.intersection(payload))
    if hit:
        raise SemanticProtocolError(
            "FORBIDDEN_FIELD",
            f"{where} 不允许出现由模型决定的字段: {', '.join(hit)}",
        )


def _as_list(value: Any, where: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是数组")
    return value


def parse_proposal(raw: Any) -> SemanticProposal:
    """Strictly parse the model's proposal. Anything unexpected is an error."""
    if not isinstance(raw, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "proposal 必须是 JSON 对象")
    _reject_forbidden(raw, "proposal")
    unknown = sorted(set(raw) - PROPOSAL_TOP_KEYS)
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"proposal 含未知字段: {', '.join(unknown)}"
        )

    reply = raw.get("reply")
    if reply is not None and not isinstance(reply, str):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "reply 必须是字符串")

    purchase_requested = raw.get("purchase_requested", False)
    if not isinstance(purchase_requested, bool):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "purchase_requested 必须是 true/false")

    proposal = SemanticProposal(
        reply=(reply or "").strip(),
        purchase_requested=bool(purchase_requested),
    )
    if raw.get("understanding") is not None:
        try:
            # The semantic contract is parsed by its own module; the protocol
            # only carries it. A contract violation is a protocol violation.
            proposal.understanding = parse_understanding(raw["understanding"])
        except GoalParseError as exc:
            raise SemanticProtocolError(exc.code, exc.message) from exc
    for entry in _as_list(raw.get("mutations"), "mutations"):
        proposal.mutations.append(_parse_mutation(entry))
    for entry in _as_list(raw.get("lookups"), "lookups"):
        proposal.lookups.append(_parse_lookup(entry))
    for entry in _as_list(raw.get("queries"), "queries"):
        proposal.queries.append(_parse_query(entry))
    for entry in _as_list(raw.get("uncertainties"), "uncertainties"):
        proposal.uncertainties.append(_parse_uncertainty(entry))
    if len(proposal.mutations) > 8 or len(proposal.uncertainties) > 3:
        raise SemanticProtocolError("PROPOSAL_LIMIT_EXCEEDED", "单轮最多 8 个修改与 3 个待澄清问题")
    if len(proposal.lookups) + len(proposal.queries) > 4:
        raise SemanticProtocolError("PROPOSAL_LIMIT_EXCEEDED", "单轮最多 4 个只读请求")
    for key in ("display_refs", "resolved_questions"):
        values = _as_list(raw.get(key), key)
        if len(values) > 12 or any(not isinstance(v, str) or not v for v in values):
            raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{key} 必须是至多 12 个非空引用")
        setattr(proposal, key, list(dict.fromkeys(values)))
    return proposal


def _parse_mutation(entry: Any) -> Mutation:
    if not isinstance(entry, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "mutation 必须是对象")
    _reject_forbidden(entry, "mutation")
    verb = entry.get("verb")
    if verb not in MUTATION_VERBS:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"verb 必须是 {', '.join(MUTATION_VERBS)} 之一"
        )
    allowed = {
        "verb",
        "name",
        "candidate_ref",
        "target_ref",
        "field",
        "quantity",
        "people",
        "constraints",
        "switch_goal",
    }
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"mutation 含未知字段: {', '.join(unknown)}"
        )

    candidate_ref = entry.get("candidate_ref")
    target_ref = entry.get("target_ref")
    name = entry.get("name", "")
    if not isinstance(name, str) or ("name" in entry and not name.strip()):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "name 必须是目标清单中的完整名称")
    if candidate_ref is not None and target_ref is not None:
        raise SemanticProtocolError(
            "REF_KIND_CONFLICT", "candidate_ref 与 target_ref 不能同时出现"
        )

    if verb == "add":
        if not isinstance(candidate_ref, str) or not candidate_ref:
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "add 必须给出 candidate_ref")
        if entry.get("field") is not None:
            raise SemanticProtocolError("UNSUPPORTED_OPERATION", "add 不接受 field")
        mutation = Mutation(verb="add", candidate_ref=candidate_ref, name=name.strip())
        switch_goal = entry.get("switch_goal", False)
        if not isinstance(switch_goal, bool):
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "switch_goal 必须是 true/false")
        mutation.switch_goal = switch_goal
        # A shopper-stated pack count / headcount / constraint travels with the
        # add: it is something the user said, so it must be expressible.
        _apply_stated_modifiers(entry, mutation)
        return mutation

    if verb == "remove":
        if not isinstance(target_ref, str) or not target_ref:
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "remove 必须给出 target_ref")
        if any(
            entry.get(k) is not None
            for k in ("field", "quantity", "people", "constraints")
        ):
            raise SemanticProtocolError("UNSUPPORTED_OPERATION", "remove 不接受字段修饰")
        return Mutation(verb="remove", target_ref=target_ref, name=name.strip())

    # change
    if entry.get("field") == "constraints":
        excluded, budget = _parse_constraints(entry.get("constraints"))
        return Mutation(verb="change", field="constraints", target_ref=target_ref, name=name.strip(),
                        excluded_ingredients=excluded, budget_fen=budget)
    if not isinstance(target_ref, str) or not target_ref:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "change 必须给出 target_ref")
    field_name = entry.get("field")
    if field_name not in CHANGE_FIELDS:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"field 必须是 {', '.join(CHANGE_FIELDS)} 之一"
        )
    mutation = Mutation(verb="change", target_ref=target_ref, field=field_name, name=name.strip())
    extra_modifiers = {"quantity", "people", "constraints"} - {field_name}
    if any(k in entry for k in extra_modifiers):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "change 只能携带所选 field 的值")

    if field_name == "quantity":
        mode, value = _parse_quantity(entry.get("quantity"), require_mode=True)
        mutation.quantity_mode = mode
        mutation.quantity_value = value
    elif field_name == "people":
        mutation.people = _parse_people(entry.get("people"))
    else:
        excluded, budget = _parse_constraints(entry.get("constraints"))
        mutation.excluded_ingredients = excluded
        mutation.budget_fen = budget
    return mutation


def _parse_quantity(spec: Any, *, require_mode: bool) -> tuple[str, int]:
    """``{"mode": "set|delta", "value": n}``. A bare integer means ``set``.

    The two modes have deliberately different domains: ``set`` is an absolute
    pack count and must be a positive integer, while ``delta`` is a *change* and
    may be negative ("少一件"). Refusing a negative delta would make "减一件"
    inexpressible.
    """
    if isinstance(spec, int) and not isinstance(spec, bool):
        if require_mode:
            raise SemanticProtocolError(
                "MALFORMED_PROPOSAL", "quantity 需要 {mode, value} 对象"
            )
        spec = {"mode": "set", "value": spec}
    if not isinstance(spec, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "quantity 需要 {mode, value} 对象")
    unknown = sorted(set(spec) - {"mode", "value"})
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"quantity 含未知字段: {', '.join(unknown)}"
        )
    mode = spec.get("mode")
    value = spec.get("value")
    if mode not in QUANTITY_MODES:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"quantity.mode 必须是 {', '.join(QUANTITY_MODES)} 之一"
        )
    if not isinstance(value, int) or isinstance(value, bool):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "quantity.value 必须是整数")
    if mode == "set":
        if value < 1:
            raise SemanticProtocolError(
                "MALFORMED_PROPOSAL",
                "quantity.value 在 set 模式下必须是正整数；要减少件数请用 mode=delta 和负值",
            )
    elif value == 0:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "quantity.value 在 delta 模式下不能为 0")
    return str(mode), int(value)


def _parse_people(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "people 必须是正整数")
    return int(value)


#: The only money field a model may author. It is denominated in yuan, and the
#: server converts it to the internal minor unit itself — the model is never
#: asked to do money arithmetic, and can never hand over a fen amount.
CONSTRAINT_KEYS = frozenset({"excluded_ingredients", "budget_yuan"})


def yuan_to_fen(value: Any) -> int:
    """Convert a yuan amount to integer fen without binary-float drift."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "budget_yuan 必须是数字")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "budget_yuan 必须是数字") from None
    if amount.is_nan() or amount.is_infinite() or amount < 0:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "budget_yuan 不能为负")
    fen = (amount * 100).to_integral_value(rounding=ROUND_HALF_UP)
    return int(fen)


def _parse_constraints(spec: Any) -> tuple[list[str], int | None]:
    if not isinstance(spec, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "constraints 需要对象")
    _reject_forbidden(spec, "constraints")
    unknown = sorted(set(spec) - CONSTRAINT_KEYS)
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"constraints 含未知字段: {', '.join(unknown)}"
        )
    excluded = spec.get("excluded_ingredients") or []
    if not isinstance(excluded, list) or any(not isinstance(x, str) for x in excluded):
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", "excluded_ingredients 必须是字符串数组"
        )
    budget = spec.get("budget_yuan")
    budget_fen = None if budget is None else yuan_to_fen(budget)
    return [x for x in excluded if x.strip()], budget_fen


def _apply_stated_modifiers(entry: dict[str, Any], mutation: Mutation) -> None:
    """Carry the constraints the user actually stated on an ``add``."""
    if entry.get("quantity") is not None:
        mode, value = _parse_quantity(entry.get("quantity"), require_mode=False)
        mutation.quantity_mode = mode
        mutation.quantity_value = value
    if entry.get("people") is not None:
        mutation.people = _parse_people(entry.get("people"))
    if entry.get("constraints") is not None:
        excluded, budget = _parse_constraints(entry.get("constraints"))
        mutation.excluded_ingredients = excluded
        mutation.budget_fen = budget


def _parse_lookup(entry: Any) -> Lookup:
    if not isinstance(entry, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "lookup 必须是对象")
    unknown = sorted(set(entry) - {"kind", "query", "constraints"})
    if unknown:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"lookup 含未知字段: {', '.join(unknown)}")
    kind = entry.get("kind")
    query = entry.get("query")
    if kind not in LOOKUP_KINDS:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"lookup.kind 必须是 {', '.join(LOOKUP_KINDS)} 之一")
    if not isinstance(query, str) or not query.strip():
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "lookup.query 不能为空")
    excluded: list[str] = []
    budget_fen: int | None = None
    if entry.get("constraints") is not None:
        excluded, budget_fen = _parse_constraints(entry.get("constraints"))
    return Lookup(
        kind=kind,
        query=query.strip(),
        excluded_ingredients=excluded,
        budget_fen=budget_fen,
    )


def _parse_query(entry: Any) -> Query:
    if not isinstance(entry, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "query 必须是对象")
    unknown = sorted(set(entry) - {"kind", "query", "constraints"})
    if unknown:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"query 含未知字段: {', '.join(unknown)}")
    kind = entry.get("kind")
    if kind not in QUERY_KINDS:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"query.kind 必须是 {', '.join(QUERY_KINDS)} 之一")
    text = entry.get("query")
    if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 200):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "query.query 必须是 1 到 200 字的查询主题")
    #: ``recommend`` may carry the topic the shopper actually asked about, so the
    #: retrieval answers *that* instead of returning whatever happens to be first.
    #: ``cart``/``catalog`` describe the session itself and take no topic.
    if text is not None and kind not in ("recipe", "recommend"):
        raise SemanticProtocolError(
            "UNSUPPORTED_OPERATION", "只有 recipe 与 recommend 查询支持指定主题；商品名使用 lookups"
        )
    excluded: list[str] = []
    budget_fen: int | None = None
    if entry.get("constraints") is not None:
        # Same rule as the topic: only the two retrieving kinds can apply a
        # constraint, because only they run a retrieval that could honour one.
        if kind not in ("recipe", "recommend"):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "只有 recipe 与 recommend 查询支持忌口/预算约束"
            )
        excluded, budget_fen = _parse_constraints(entry.get("constraints"))
    return Query(
        kind=kind,
        query=text.strip() if text else None,
        excluded_ingredients=excluded,
        budget_fen=budget_fen,
    )


def _parse_uncertainty(entry: Any) -> Uncertainty:
    if not isinstance(entry, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "uncertainty 必须是对象")
    unknown = sorted(set(entry) - {"slot", "question", "options"})
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"uncertainty 含未知字段: {', '.join(unknown)}"
        )
    slot = entry.get("slot")
    question = entry.get("question")
    if not isinstance(slot, str) or not slot.strip():
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "uncertainty.slot 不能为空")
    if not isinstance(question, str) or not question.strip():
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "uncertainty.question 不能为空")
    option_refs: list[str] = []
    for option in _as_list(entry.get("options"), "uncertainty.options"):
        if not isinstance(option, dict):
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "uncertainty option 必须是对象")
        unknown = sorted(set(option) - {"candidate_ref"})
        if unknown:
            raise SemanticProtocolError(
                "MALFORMED_PROPOSAL", f"uncertainty option 含未知字段: {', '.join(unknown)}"
            )
        ref = option.get("candidate_ref")
        if not isinstance(ref, str) or not ref:
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "uncertainty option 缺少 candidate_ref")
        option_refs.append(ref)
    return Uncertainty(slot=slot.strip(), question=question.strip(), option_refs=option_refs)


def proposal_schema() -> dict[str, Any]:
    """Output JSON Schema, not a pseudo-proposal with illegal example keys.

    The server parser and reference/business checks remain authoritative.
    """
    def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "object", "properties": properties,
                "required": required or [], "additionalProperties": False}

    def array(items: dict[str, Any], maximum: int) -> dict[str, Any]:
        return {"type": "array", "items": items, "maxItems": maximum}

    text = {"type": "string", "minLength": 1}
    positive = {"type": "integer", "minimum": 1}
    ref_name = {"name": {**text, "description": "与引用同一行的完整名称，必须一致"}}
    quantity = {"oneOf": [
        obj({"mode": {"const": "set"}, "value": positive}, ["mode", "value"]),
        obj({"mode": {"const": "delta"}, "value": {"type": "integer", "not": {"const": 0}}}, ["mode", "value"]),
    ]}
    constraints = obj({"excluded_ingredients": array(text, 20),
                       "budget_yuan": {"type": "number", "minimum": 0}})
    #: The semantic statement. It is the only thing that authorizes a plan write,
    #: so the schema describes exactly the two mutually exclusive shapes: a new
    #: goal, or a patch of the goal under discussion.
    goal = obj({
        "kind": {"enum": ["meal_decision", "meal_plan", "product_purchase",
                          "category_purchase", "replenishment", "information_only",
                          "unsupported"]},
        "fulfillment_mode": {"enum": ["self_cook", "ready_made", "mixed",
                                      "unspecified", "none"],
                             "description": "用户没说就不要猜；未说明用 unspecified"},
        "description": {"type": "string"},
        "target_name": {**text},
        "category_id": {**text},
        "category_name": {**text},
        "items": array(text, 20),
        "constraints": obj({"people": positive, "budget_yuan": {"type": "number", "minimum": 0},
                            "dietary": array(text, 20), "excluded_ingredients": array(text, 20),
                            "meal_time": {"enum": ["breakfast", "lunch", "dinner",
                                                    "late_night", "snack"]}}),
        "notes": array(text, 5),
        "assumptions": array(text, 5),
    }, ["kind"])
    change_set = obj({"people": positive,
                      "budget_yuan": {"type": "number", "minimum": 0},
                      "fulfillment_mode": {"enum": ["self_cook", "ready_made", "mixed",
                                                     "unspecified", "none"]},
                      "meal_time": {"enum": ["breakfast", "lunch", "dinner",
                                              "late_night", "snack"]},
                      "dietary": array(text, 20),
                      "excluded_ingredients": array(text, 20)})
    understanding = obj({
        "speech_act": {"enum": ["ask_fact", "request_action", "correct",
                                 "answer_clarification", "chat", "unspecified"],
                       "description": "这句话在做什么，不是要你执行的动作"},
        "focus_ref": {**text, "description": "focus_refs 里的一个引用；不确定就不要填"},
        "goal_relation": {"enum": ["new", "append", "switch", "amend", "unspecified"],
                          "description": ("与快照中已有目标的关系：new=新建，append=再加一个，"
                                          "switch=换掉现在这份未确认清单，amend=修正同一目标")},
        "new_goal": {**goal, "description": "new/append/switch 时给出；不是对服务端状态的复述"},
        "changes": {**obj({
            "set": change_set,
            "clear": array({"enum": ["people", "budget_yuan", "fulfillment_mode",
                                      "meal_time", "dietary", "excluded_ingredients"]}, 6),
        }), "description": "amend 时给出；省略的字段保持不变，null 不代表撤销"},
        "notes": array(text, 5),
    })

    mutation = {"oneOf": [
        obj({"verb": {"const": "add"}, "candidate_ref": text, **ref_name,
             "quantity": positive, "people": positive, "constraints": constraints},
            ["verb", "candidate_ref", "name"]),
        obj({"verb": {"const": "change"},
             "target_ref": {**text, "description": (
                 "current_plan 的一行商品；只有单件商品的 groups 行（该分组仅含这一个 SKU）也可以"
             )}, **ref_name,
             "field": {"const": "quantity"}, "quantity": quantity},
            ["verb", "target_ref", "name", "field", "quantity"]),
        obj({"verb": {"const": "change"}, "target_ref": text, **ref_name,
             "field": {"const": "people"}, "people": positive},
            ["verb", "target_ref", "name", "field", "people"]),
        obj({"verb": {"const": "remove"}, "target_ref": text, **ref_name},
            ["verb", "target_ref", "name"]),
    ]}
    return obj({
        "reply": {"type": "string", "description": "自然语言回答，不提前宣称执行成功"},
        "understanding": {**understanding, "description": (
            "这一句的语义：做什么（speech_act）、和已有目标什么关系（goal_relation）、"
            "新目标或要改的字段。一次给出即可；服务端据此执行，不需要等检索结果后再补一轮提案。"
            "只聊天或只提问时不要编造目标。"
        )},
        "purchase_requested": {"type": "boolean", "description": (
            "仅兼容旧格式，不授予写入权限；是否允许准备清单由 understanding 与服务端决定。"
        )},
        "mutations": array(mutation, 8),
        "lookups": array(obj({
            "kind": {"enum": ["dish", "product"]},
            "query": {**text, "description": (
                "只填要检索的名称/主题，不要带否定词。“不要花生”里的花生要放进 constraints，"
                "query 只留菜名或主题。"
            )},
            "constraints": {**constraints, "description": (
                "本轮用户说出的忌口/预算，只作用于这次检索；" +
                "它只会与已保存的忌口合并，不会解除已保存的忌口。"
            )},
        }, ["kind", "query"]), 2),
        "queries": array({"oneOf": [
            obj({"kind": {"const": "recommend"},
                 "query": {**text, "maxLength": 200, "description": (
                     "用户想找的东西（如“番茄炒蛋”“不辣的家常菜”）。"
                     "给了主题就必须按它检索；没有主题才是开放式探索。"
                 )},
                 "constraints": {**constraints, "description": (
                     "本轮用户说出的忌口/预算，只作用于这次检索；"
                     "它只会与已保存的忌口合并，不会解除已保存的忌口。"
                 )}}, ["kind"]),
            obj({"kind": {"enum": ["cart", "catalog"]}}, ["kind"]),
            obj({"kind": {"const": "recipe"}, "query": {**text, "maxLength": 200},
                 "constraints": {**constraints, "description": (
                     "本轮用户说出的忌口/预算，只作用于这次检索；"
                     "它只会与已保存的忌口合并，不会解除已保存的忌口。"
                 )}}, ["kind"]),
        ]}, 4),
        "display_refs": array(text, 12),
        "resolved_questions": array(text, 12),
        "uncertainties": array(obj({"slot": text, "question": text,
            "options": array(obj({"candidate_ref": text}, ["candidate_ref"]), 12)}, ["slot", "question"]), 3),
    })


__all__ = [
    "CandidateRef",
    "CandidateSet",
    "Lookup",
    "Mutation",
    "PROPOSAL_VERSION",
    "Query",
    "SemanticProposal",
    "SemanticProtocolError",
    "Uncertainty",
    "add_lookup_candidates",
    "parse_proposal",
    "proposal_schema",
    "yuan_to_fen",
]
