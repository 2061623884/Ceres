"""Low-cardinality semantic proposal protocol — the single implementation.

The model never sees the internal business operations. It sees a small, bounded
list of *server-owned candidates* (real dishes, real sellable SKUs, real open
scenarios, plus the groups and rows of the plan already on screen) and may
answer with:

* ``reply``       — user-visible text when there is no business result,
* ``target``      — what the shopper named; look or buy; add or replace,
* ``constraints`` — the conditions they stated (one place for each fact),
* ``focus`` / ``edit`` — which row on screen, and what to do with it,
* ``plan_act``    — "add to cart" / "drop the whole plan", said out loud,
* ``lookups`` / ``reads`` — read-only retrieval and answer requests,
* ``questions``   — one question whose options are real candidates.

``parse_proposal`` turns these independent dimensions into the internal
``Understanding`` + ``Mutation`` shape; the gate alone decides the route.

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

from pydantic import ValidationError

from app.schemas.goal import Goal, GoalChanges, GoalChangeSet, GoalConstraints, Understanding

PROPOSAL_VERSION = 1

LOOKUP_KINDS = ("dish", "product")
QUERY_KINDS = ("recommend", "recipe", "cart", "catalog", "compare", "history", "policy")

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
        "target",
        "constraints",
        "focus",
        "edit",
        "plan_act",
        "lookups",
        "reads",
        "questions",
        "display_refs",
        "resolved_questions",
        "memory",
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
        targets = {target["group_id"]: target for target in plan.get("targets") or []}
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
                    **({"meal_name": targets[c.group_id]["meal_name"]}
                       if targets[c.group_id].get("meal_name") else {}),
                    **({"fulfillment_mode": targets[c.group_id]["fulfillment_mode"]}
                       if targets[c.group_id].get("fulfillment_mode") else {}),
                    **({"selection_goal": targets[c.group_id]["selection_goal"]}
                       if "selection_goal" in targets[c.group_id] else {}),
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
    specification: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Lookup:
    kind: str
    query: str
    #: The turn's stated exclusions/budget when the turn only reads. A structured
    #: filter — never something the vector route is asked to understand — merged
    #: with the saved requirements by union, so a read can add an exclusion but
    #: can never silently drop one.
    excluded_ingredients: list[str] = dc_field(default_factory=list)
    budget_fen: int | None = None
    specification: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Query:
    kind: str
    query: str | None = None
    #: The same read-only filter a lookup carries (``recommend`` / ``recipe`` only).
    excluded_ingredients: list[str] = dc_field(default_factory=list)
    budget_fen: int | None = None
    specification: dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class Uncertainty:
    slot: str
    question: str
    option_refs: list[str] = dc_field(default_factory=list)


@dataclass(frozen=True)
class MemoryAction:
    verb: str
    category: str | None = None
    content: str | None = None
    ref: str | None = None


@dataclass
class SemanticProposal:
    reply: str = ""
    #: The server's reading of the model's dimensions. The gate derives route,
    #: readiness and write permission from it plus its own facts.
    understanding: Understanding = dc_field(default_factory=Understanding)
    mutations: list[Mutation] = dc_field(default_factory=list)
    lookups: list[Lookup] = dc_field(default_factory=list)
    queries: list[Query] = dc_field(default_factory=list)
    uncertainties: list[Uncertainty] = dc_field(default_factory=list)
    display_refs: list[str] = dc_field(default_factory=list)
    resolved_questions: list[str] = dc_field(default_factory=list)
    memory: MemoryAction | None = None

    @property
    def is_empty(self) -> bool:
        return not (
            self.reply.strip()
            or self.understanding != Understanding()
            or self.mutations
            or self.lookups
            or self.queries
            or self.uncertainties
            or self.display_refs
            or self.memory
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


#: The model-facing vocabulary. The first value of each tuple is the "nothing
#: said" sentinel, so an omitted key and an explicit sentinel mean the same.
TARGET_KINDS = ("none", "meal", "product", "category", "unsupported")
INTENTS = ("none", "explore", "buy")
RELATIONS = ("unstated", "add", "replace")
FULFILLMENT = ("unstated", "self_cook", "ready_made", "mixed")
EDIT_OPS = ("none", "remove", "set_quantity", "adjust_quantity")
PLAN_ACTS = ("none", "confirm", "abandon")
#: Conditions a shopper may revoke; the same names as ``GoalChangeSet``.
CLEARABLE = (
    "people", "budget_yuan", "fulfillment_mode", "excluded_ingredients",
    "specification",
)

TARGET_KEYS = frozenset({"kind", "name", "ref", "items", "intent", "relation", "quantity"})
CONSTRAINT_KEYS = frozenset(
    {"people", "budget_yuan", "fulfillment_mode", "excluded_ingredients",
     "specification", "clear", "unsupported"}
)
FOCUS_KEYS = frozenset({"ref", "name"})
EDIT_KEYS = frozenset({"op", "quantity"})
LOOKUP_KEYS = frozenset({"kind", "query"})
READ_KEYS = frozenset({"kind", "topic"})
QUESTION_KEYS = frozenset({"slot", "question", "options"})

#: A stated relation in the internal vocabulary; ``unstated`` is left to the gate.
_RELATION = {"unstated": "unspecified", "add": "append", "replace": "switch"}
_GOAL_KIND = {"product": "product_purchase", "category": "category_purchase"}


def parse_proposal(raw: Any) -> SemanticProposal:
    """Strictly parse the model's proposal into the server's internal shape.

    Every key is optional and an omitted one means "not said". An unknown key, a
    server-owned field or a wrongly typed value is a protocol error, never a
    silently dropped field. Nothing here reads server state: what a constraint
    attaches to, and what the turn may do, is decided by the gate.
    """
    top = _wire(raw, PROPOSAL_TOP_KEYS, "proposal", allow_none=False)
    try:
        proposal = SemanticProposal(
            reply=_text(top.get("reply"), "reply") or "",
            lookups=[_parse_lookup(e) for e in _as_list(top.get("lookups"), "lookups")],
            queries=[_parse_read(e) for e in _as_list(top.get("reads"), "reads")],
            uncertainties=[
                _parse_question(e) for e in _as_list(top.get("questions"), "questions")
            ],
            display_refs=_refs(top.get("display_refs"), "display_refs"),
            resolved_questions=_refs(top.get("resolved_questions"), "resolved_questions"),
            memory=_parse_memory(top.get("memory")),
        )
        if len(proposal.lookups) + len(proposal.queries) > 4:
            raise SemanticProtocolError("PROPOSAL_LIMIT_EXCEEDED", "单轮最多 4 个只读请求")
        if len(proposal.uncertainties) > 3:
            raise SemanticProtocolError("PROPOSAL_LIMIT_EXCEEDED", "单轮最多 3 个待澄清问题")
        _attach_understanding(proposal, top)
        if proposal.memory and any(top.get(key) for key in (
            "target", "constraints", "focus", "edit", "plan_act", "lookups", "reads", "questions",
        )):
            raise SemanticProtocolError("UNSUPPORTED_OPERATION", "记忆管理请单独提出，本轮没有修改记忆或清单。")
    except ValidationError as exc:
        detail = "; ".join(str(e.get("msg") or "") for e in exc.errors()[:3])
        raise SemanticProtocolError("MALFORMED_PROPOSAL", detail or "proposal 结构不合法") from exc
    return proposal


def _parse_memory(raw: Any) -> MemoryAction | None:
    if raw is None:
        return None
    data = _wire(raw, frozenset({"verb", "category", "content", "ref"}), "memory", allow_none=False)
    verb = _text(data.get("verb"), "memory.verb")
    if verb not in ("save", "list", "update", "delete"):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "memory.verb 必须是 save/list/update/delete")
    category = _text(data.get("category"), "memory.category")
    if category is not None and category not in ("user", "feedback", "project", "reference"):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "记忆类别必须是 user/feedback/project/reference")
    content = _text(data.get("content"), "memory.content")
    ref = _text(data.get("ref"), "memory.ref")
    if (verb in ("save", "update") and content is None) or (verb == "save" and category is None):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "保存/更正记忆必须给出内容；保存必须给出类别")
    if verb in ("update", "delete") and ref is None:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "更正/删除必须引用服务端给出的记忆 ref")
    return MemoryAction(verb=verb, category=category, content=content, ref=ref)


def _attach_understanding(proposal: SemanticProposal, top: dict[str, Any]) -> None:
    """Derive the internal ``Understanding`` and row mutations from the dimensions."""
    target = _wire(top.get("target"), TARGET_KEYS, "target")
    focus = _wire(top.get("focus"), FOCUS_KEYS, "focus")
    edit = _wire(top.get("edit"), EDIT_KEYS, "edit")
    kind = _choice(target.get("kind"), TARGET_KINDS, "target.kind")
    intent = _choice(target.get("intent"), INTENTS, "target.intent")
    relation = _choice(target.get("relation"), RELATIONS, "target.relation")
    op = _choice(edit.get("op"), EDIT_OPS, "edit.op")
    stated, clear, unsupported = _constraints(top.get("constraints"))
    focus_ref = _text(focus.get("ref"), "focus.ref")

    goal = _goal(kind, intent, target, stated)
    if "specification" in clear and (
        kind != "none" or proposal.lookups or proposal.queries
    ):
        raise SemanticProtocolError(
            "UNSUPPORTED_OPERATION",
            "撤销小包装条件请单独提出，本轮没有修改条件或清单。",
        )
    if goal is not None and _text(target.get("ref"), "target.ref"):
        proposal.mutations.append(_add(target, goal, stated))
    row_edit = _edit(op, edit.get("quantity"), focus_ref, _text(focus.get("name"), "focus.name"))
    if row_edit is not None:
        proposal.mutations.append(row_edit)

    changes = None
    reading = intent == "explore" or kind != "none" or proposal.lookups or proposal.queries
    if goal is None and op == "none" and reading:
        # Only reading: the stated conditions filter the reads and nothing else.
        _filter_reads(proposal, stated)
    elif goal is None and (stated or clear):
        changes = GoalChanges(set=GoalChangeSet(**stated), clear=clear)

    if goal is not None:
        goal_relation = _RELATION[relation]
    elif changes is not None or op != "none":
        goal_relation = "amend"
    else:
        goal_relation = "unspecified"
    proposal.understanding = Understanding(
        intent=intent,
        plan_act=_choice(top.get("plan_act"), PLAN_ACTS, "plan_act"),
        focus_ref=focus_ref,
        goal_relation=goal_relation,
        new_goal=goal,
        changes=changes,
        unsupported=unsupported,
    )


def _constraints(raw: Any) -> tuple[dict[str, Any], list[str], list[str]]:
    """What the shopper stated, what they revoked, and what cannot be applied.

    ``0``, ``"unstated"`` and ``[]`` all mean "not said", so a sentinel is never
    read back as a value.
    """
    spec = _wire(raw, CONSTRAINT_KEYS, "constraints")
    stated: dict[str, Any] = {}
    if people := _count(spec.get("people"), "constraints.people"):
        stated["people"] = people
    budget = spec.get("budget_yuan")
    if budget not in (None, 0):
        stated["budget_yuan"] = yuan_to_fen(budget) / 100
    mode = _choice(spec.get("fulfillment_mode"), FULFILLMENT, "constraints.fulfillment_mode")
    if mode != "unstated":
        stated["fulfillment_mode"] = mode
    excluded = _strings(spec.get("excluded_ingredients"), "constraints.excluded_ingredients")
    if excluded:
        stated["excluded_ingredients"] = excluded
    packaging = _wire(spec.get("specification"), frozenset({
        "size", "brand", "item_volume_ml", "packaging", "pack_count", "pack_mode", "max_price_yuan",
    }), "constraints.specification")
    conditions: dict[str, Any] = {}
    size = _choice(packaging.get("size"), ("none", "small"), "constraints.specification.size")
    if size == "small":
        conditions["size"] = "small"
    if brand := _text(packaging.get("brand"), "constraints.specification.brand"):
        conditions["brand"] = brand
    for key in ("item_volume_ml", "pack_count"):
        if key in packaging:
            conditions[key] = _count(packaging[key], "constraints.specification." + key) or 0
    for key, options in (("packaging", ("none", "can", "bottle", "any")),
                         ("pack_mode", ("none", "single", "multi", "any"))):
        value = _choice(packaging.get(key), options, "constraints.specification." + key)
        if value != "none":
            conditions[key] = value
    if "max_price_yuan" in packaging:
        conditions["max_price_fen"] = yuan_to_fen(packaging["max_price_yuan"])
    if conditions:
        stated["specification"] = conditions
    clear = _strings(spec.get("clear"), "constraints.clear")
    unknown = sorted(set(clear) - set(CLEARABLE))
    if unknown:
        raise SemanticProtocolError(
            "MALFORMED_PROPOSAL", f"constraints.clear 含未知字段: {', '.join(unknown)}"
        )
    return stated, clear, _strings(spec.get("unsupported"), "constraints.unsupported")


def _goal(kind: str, intent: str, target: dict[str, Any], stated: dict[str, Any]) -> Goal | None:
    """The goal a *buy* target states. Only looking at something states none."""
    if kind == "unsupported":
        return Goal(kind="unsupported")
    if kind == "none" or intent != "buy":
        return None
    name = _text(target.get("name"), "target.name")
    items = _strings(target.get("items"), "target.items")
    if kind == "meal":
        goal_kind = "meal_plan" if name or items else "meal_decision"
    else:
        goal_kind = _GOAL_KIND[kind]
    if kind == "product" and name and not items:
        items = [name]
    conditions = {key: value for key, value in stated.items() if key != "fulfillment_mode"}
    return Goal(
        kind=goal_kind,
        fulfillment_mode=stated.get("fulfillment_mode", "unspecified"),
        target_name=name,
        quantity=_count(target.get("quantity"), "target.quantity") if kind == "product" else None,
        category_name=name if kind == "category" else None,
        items=items,
        constraints=GoalConstraints(**conditions),
    )


def _add(target: dict[str, Any], goal: Goal, stated: dict[str, Any]) -> Mutation:
    """An ``add`` of the exact server candidate the shopper picked."""
    quantity = _count(target.get("quantity"), "target.quantity")
    budget = stated.get("budget_yuan")
    return Mutation(
        verb="add",
        candidate_ref=_text(target.get("ref"), "target.ref"),
        name=goal.target_name or "",
        quantity_mode="set" if quantity else None,
        quantity_value=quantity,
        people=stated.get("people"),
        excluded_ingredients=list(stated.get("excluded_ingredients") or []),
        budget_fen=None if budget is None else yuan_to_fen(budget),
        specification=dict(stated.get("specification", {})),
    )


def _edit(op: str, quantity: Any, ref: str | None, name: str | None) -> Mutation | None:
    """A row edit on the focused plan entry.

    Without a focus the edit stays unlocated: the gate asks which row instead of
    guessing one.
    """
    value = 0
    if op in ("set_quantity", "adjust_quantity"):
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "edit.quantity 必须是整数")
        value = quantity
        if op == "set_quantity" and value < 1:
            raise SemanticProtocolError(
                "MALFORMED_PROPOSAL", "set_quantity 需要正整数；要减少件数请用 adjust_quantity 和负值"
            )
        if op == "adjust_quantity" and value == 0:
            raise SemanticProtocolError("MALFORMED_PROPOSAL", "adjust_quantity 不能为 0")
    if op == "none" or not ref:
        return None
    if op == "remove":
        return Mutation(verb="remove", target_ref=ref, name=name or "")
    return Mutation(
        verb="change",
        target_ref=ref,
        name=name or "",
        field="quantity",
        quantity_mode="set" if op == "set_quantity" else "delta",
        quantity_value=value,
    )


def _filter_reads(proposal: SemanticProposal, stated: dict[str, Any]) -> None:
    """A read-only turn's stated exclusions/budget filter the reads that can use them."""
    excluded = list(stated.get("excluded_ingredients") or [])
    budget = stated.get("budget_yuan")
    budget_fen = None if budget is None else yuan_to_fen(budget)
    reads = [*proposal.lookups, *(q for q in proposal.queries if q.kind in ("recipe", "recommend", "compare"))]
    for read in reads:
        read.excluded_ingredients = list(excluded)
        read.budget_fen = budget_fen
        read.specification = dict(stated.get("specification", {}))


def _parse_lookup(entry: Any) -> Lookup:
    spec = _wire(entry, LOOKUP_KEYS, "lookup", allow_none=False)
    query = _text(spec.get("query"), "lookup.query")
    if not query:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "lookup.query 不能为空")
    return Lookup(kind=_choice(spec.get("kind"), LOOKUP_KINDS, "lookup.kind"), query=query)


def _parse_read(entry: Any) -> Query:
    spec = _wire(entry, READ_KEYS, "read", allow_none=False)
    kind = _choice(spec.get("kind"), QUERY_KINDS, "read.kind")
    topic = _text(spec.get("topic"), "read.topic")
    if topic and len(topic) > 200:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "read.topic 最多 200 字")
    if kind == "compare" and not topic:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "compare 需要商品品类 topic")
    if topic and kind not in ("recipe", "recommend", "compare", "history", "policy"):
        # cart / catalog describe the session itself; a product name is a lookup.
        raise SemanticProtocolError(
            "UNSUPPORTED_OPERATION", "只有 recipe、recommend、compare、history 与 policy 支持主题；商品名使用 lookups"
        )
    return Query(kind=kind, query=topic)


def _parse_question(entry: Any) -> Uncertainty:
    spec = _wire(entry, QUESTION_KEYS, "question", allow_none=False)
    slot = _text(spec.get("slot"), "question.slot")
    question = _text(spec.get("question"), "question.question")
    if not slot or not question:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", "question 需要 slot 和 question")
    return Uncertainty(
        slot=slot, question=question, option_refs=_refs(spec.get("options"), "question.options")
    )


def _refs(value: Any, where: str) -> list[str]:
    """At most 12 distinct, non-empty server refs."""
    values = _as_list(value, where)
    if len(values) > 12 or any(not isinstance(v, str) or not v.strip() for v in values):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是至多 12 个非空引用")
    return list(dict.fromkeys(v.strip() for v in values))


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


def _wire(
    value: Any, allowed: frozenset[str], where: str, *, allow_none: bool = True
) -> dict[str, Any]:
    """One wire object: omitted is empty; otherwise only known, model-owned keys."""
    if value is None and allow_none:
        return {}
    if not isinstance(value, dict):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是 JSON 对象")
    _reject_forbidden(value, where)
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 含未知字段: {', '.join(unknown)}")
    return value


def _choice(value: Any, allowed: tuple[str, ...], where: str) -> str:
    """An enum value; omitted means the first ("nothing said") one."""
    if value is None or value == "":
        return allowed[0]
    if value not in allowed:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是 {', '.join(allowed)} 之一")
    return str(value)


def _text(value: Any, where: str) -> str | None:
    """A trimmed string, or ``None`` when omitted or blank."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是字符串")
    return value.strip() or None


def _strings(value: Any, where: str) -> list[str]:
    """Distinct, non-empty strings in their original order."""
    values = _as_list(value, where)
    if any(not isinstance(v, str) for v in values):
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是字符串数组")
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


def _count(value: Any, where: str) -> int | None:
    """A non-negative integer; ``0`` or omitted means "not said"."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SemanticProtocolError("MALFORMED_PROPOSAL", f"{where} 必须是非负整数")
    return value or None


def proposal_schema() -> dict[str, Any]:
    """Guidance schema for the understanding stage.

    Every key is optional and the parser stays authoritative: an omitted key
    means "not said", so the model writes only what the shopper actually said.
    """
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "additionalProperties": False}

    def enum(values: tuple[str, ...], description: str = "") -> dict[str, Any]:
        return {"enum": list(values), **({"description": description} if description else {})}

    text = {"type": "string"}
    texts = {"type": "array", "items": text, "maxItems": 12}
    count = {"type": "integer", "minimum": 0}
    return obj({
        "reply": {**text, "description": "只在没有业务结果时说的话；不要声称已加购、改单或检索成功"},
        "target": obj({
            "kind": enum(TARGET_KINDS, "用户提到的东西：一餐 / 商品 / 品类；做不到的写 unsupported"),
            "name": {**text, "description": "用户说的名字；「今晚这顿」这类没有名字就不填"},
            "ref": {**text, "description": "用户选了服务端给出的某个候选时填它的 ref"},
            "items": texts,
            "intent": enum(INTENTS, "explore=只是看看/问问；buy=要一份能买的清单（「帮我选」也是 buy）"),
            "relation": enum(RELATIONS, "只有用户明说「再加」=add、「换成 / 不是X是Y」=replace 才填"),
            "quantity": {**count, "description": "用户说的件数，没说不填"},
        }),
        "constraints": obj({
            "people": count,
            "budget_yuan": {"type": "number", "minimum": 0},
            "fulfillment_mode": enum(FULFILLMENT, "只有用户说了自己做 / 买现成才填"),
            "excluded_ingredients": texts,
            "specification": obj({
                "size": enum(("none", "small"), "用户要求小包装时填small"),
                "brand": {**text, "description": "明确品牌名；any撤销品牌限制"},
                "item_volume_ml": {**count, "description": "每罐/瓶容量（ml），0撤销"},
                "packaging": enum(("none", "can", "bottle", "any"), "罐/瓶；any撤销"),
                "pack_count": {**count, "description": "一销售包装内件数，0撤销"},
                "pack_mode": enum(("none", "single", "multi", "any"), "单件/多件；any撤销"),
                "max_price_yuan": {"type": "number", "minimum": 0,
                                   "description": "一销售包装的最高售价（元），0撤销；不是整份清单预算"},
            }),
            "clear": {"type": "array", "items": enum(CLEARABLE)},
            "unsupported": {**texts, "description": "用户说了、上面没有字段的条件原话，如「清淡」「10分钟送到」「大包装」「精确100克」"},
        }),
        "focus": obj({"ref": {**text, "description": "focus_refs 里的一个引用；指代不清就不填"},
                      "name": text}),
        "edit": obj({"op": enum(EDIT_OPS, "对 focus 那一项做什么"), "quantity": {"type": "integer"}}),
        "plan_act": enum(PLAN_ACTS, "只有明说「加入购物车 / 下单」=confirm、「不买了」=abandon；「好的」不算"),
        "lookups": {"type": "array", "maxItems": 2, "items": obj({
            "kind": enum(LOOKUP_KINDS), "query": {**text, "description": "只填名称，不带否定词"}})},
        "reads": {"type": "array", "maxItems": 4, "items": obj({
            "kind": enum(QUERY_KINDS, "policy=一般门店政策，history=本用户历史方案，compare=品类商品规格价格比较，recommend=推荐菜品，recipe=做法，cart=购物车，catalog=目录；具名商品用lookups"),
            "topic": {**text, "description": "policy填写政策问题；compare必须填品类名；history可填已核实方案ID或菜/商品名，不填则最近方案；recommend / recipe可填主题；cart / catalog不填"}})},
        "questions": {"type": "array", "maxItems": 3, "items": obj({
            "slot": text, "question": text, "options": texts})},
        "display_refs": texts,
        "resolved_questions": {**texts, "description": "这句话已经回答或不再需要的 pending_clarifications 的 question_id"},
        "memory": obj({
            "verb": enum(("save", "list", "update", "delete"), "仅用户明确要求记住、查询、更正或删除；单独管理，不同时采购"),
            "category": enum(("user", "feedback", "project", "reference")),
            "content": text,
            "ref": {**text, "description": "更正/删除必须用服务端给出的记忆 ref；不清楚先查询或问清楚"},
        }),
    })


def answer_schema() -> dict[str, Any]:
    """The answer stage: grounded words and the candidates actually shown."""
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string", "description": "只根据 query_results 回答"},
            "display_refs": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 12,
                "description": "按向用户展示的顺序列出候选 ref；没有展示候选时填空数组",
            },
        },
        "required": ["reply", "display_refs"],
        "additionalProperties": False,
    }


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
    "answer_schema",
    "parse_proposal",
    "proposal_schema",
    "yuan_to_fen",
]
