"""Goal understanding schema: a constrained reading of what the user wants.

The understanding layer is allowed to propose *meaning* only. It cannot author
anything the server owns: no plan/state versions, no price or stock, no SKU ids,
no route or readiness, and nothing that could authorize a write. ``Goal`` is
therefore a narrow, closed structure — an unknown key is an error, not a
silently dropped field — and this module is pure: no ORM, no retrieval, no
model call, no environment variable.

Resolving a goal into ``readiness`` / ``fulfillment_mode`` / ``route`` /
``missing_slots`` lives in ``app.agent.goal_router``; this module carries the
vocabulary plus the normalization functions that turn an out-of-vocabulary value
into an honest conservative default instead of a crash or a guess.

See ``docs/plans/2026-09-19-purchase-intent-p1-implementation.md``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: What the user is trying to accomplish. ``meal_decision`` is the genuinely
#: undecided case ("不知道吃什么"); it is not a meal plan whose name is missing.
GoalKind = Literal[
    "meal_decision",
    "meal_plan",
    "product_purchase",
    "category_purchase",
    "replenishment",
    "information_only",
    "unsupported",
]

#: Whether the meal is cooked or bought ready-made. ``unspecified`` is a real
#: answer ("the user has not said") and never means "assume self-cook".
#: ``none`` means the goal is not a meal-fulfilment question at all.
FulfillmentMode = Literal["self_cook", "ready_made", "mixed", "unspecified", "none"]

#: How far the goal has got. ``information`` never prepares a plan.
Readiness = Literal["ready", "needs_clarification", "information", "unsupported"]

#: The one next step the server may take. The model never authors this.
GoalRoute = Literal[
    "clarify_goal",
    "answer_information",
    "prepare_meal_plan",
    "prepare_product_purchase",
    "prepare_category_purchase",
    "prepare_replenishment",
    "refuse_unsupported",
]

#: How strongly the shopper wants the thing they named: only look at it, or get
#: a list that can be bought. ``none`` means nothing was named.
Intent = Literal["none", "explore", "buy"]

#: What the shopper said about the whole plan on screen. It never authorizes a
#: cart write by itself: the server checks every precondition.
PlanAct = Literal["none", "confirm", "abandon"]

#: How this turn's goal stands to the goal already on screen / in discussion.
#: ``switch`` replaces the unconfirmed plan, ``append`` adds one more target,
#: ``amend`` changes the goal under discussion, ``new`` starts when there is
#: nothing to relate to. ``unspecified`` is resolved by the router: with a goal
#: or candidate in play it asks, otherwise it behaves as ``new``.
GoalRelation = Literal["new", "append", "switch", "amend", "unspecified"]

#: The one next step the *turn* may take. This is the gate's own vocabulary: it
#: is coarser than ``GoalRoute`` (which describes a single goal) because a turn
#: can legitimately have nothing to plan (chat, a read-only answer, a refusal).
TurnRoute = Literal["chat", "retrieve", "mutation", "answer", "clarify", "refuse"]

#: What ``focus_ref`` points at, resolved by the server from its own ref table.
FocusKind = Literal[
    "active_goal",
    "pending_goal",
    "pending_question",
    "plan_target",
    "none",
]

MealTime = Literal["breakfast", "lunch", "dinner", "late_night", "snack"]

#: The goal fields a constrained patch may touch. Nothing else: no paths, no
#: prices, no plan/state versions, no arbitrary nested updates.
CHANGE_FIELDS: tuple[str, ...] = (
    "people",
    "budget_yuan",
    "fulfillment_mode",
    "meal_time",
    "dietary",
    "excluded_ingredients",
    "specification",
)

GOAL_KINDS: tuple[str, ...] = (
    "meal_decision",
    "meal_plan",
    "product_purchase",
    "category_purchase",
    "replenishment",
    "information_only",
    "unsupported",
)
FULFILLMENT_MODES: tuple[str, ...] = (
    "self_cook",
    "ready_made",
    "mixed",
    "unspecified",
    "none",
)
READINESS_STATES: tuple[str, ...] = (
    "ready",
    "needs_clarification",
    "information",
    "unsupported",
)
GOAL_ROUTES: tuple[str, ...] = (
    "clarify_goal",
    "answer_information",
    "prepare_meal_plan",
    "prepare_product_purchase",
    "prepare_category_purchase",
    "prepare_replenishment",
    "refuse_unsupported",
)
MEAL_TIMES: tuple[str, ...] = ("breakfast", "lunch", "dinner", "late_night", "snack")
GOAL_RELATIONS: tuple[str, ...] = ("new", "append", "switch", "amend", "unspecified")
TURN_ROUTES: tuple[str, ...] = (
    "chat",
    "retrieve",
    "mutation",
    "answer",
    "clarify",
    "refuse",
)
FOCUS_KINDS: tuple[str, ...] = (
    "active_goal",
    "pending_goal",
    "pending_question",
    "plan_target",
    "none",
)

#: Keys a model may never author on a goal. Route/readiness/missing_slots are
#: computed by the router; the rest are server-owned facts. Their presence is a
#: protocol error rather than a silently ignored field, so a model that tries to
#: set a price or a plan version is told so instead of having the attempt dropped.
FORBIDDEN_GOAL_KEYS = frozenset(
    {
        "plan_id",
        "plan_version",
        "state_version",
        "session_version",
        "task_id",
        "user_id",
        "owner_id",
        "route",
        "readiness",
        "missing_slots",
        "confirmed",
        "can_confirm",
        "ready",
        "price",
        "price_fen",
        "unit_price_fen",
        "total_price_fen",
        "budget_fen",
        "stock",
        "available_qty",
        "sku_id",
    }
)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_goal_kind(value: Any) -> GoalKind:
    """A kind we can route on. Anything unrecognised is ``unsupported``.

    Guessing a kind would let a malformed proposal drive a purchase path, so the
    unknown case is the honest refusal, not the most common kind.
    """
    text = _text(value)
    return text if text in GOAL_KINDS else "unsupported"  # type: ignore[return-value]


def normalize_fulfillment_mode(value: Any) -> FulfillmentMode:
    """An unrecognised fulfilment mode stays ``unspecified`` (ask, never assume)."""
    text = _text(value)
    return text if text in FULFILLMENT_MODES else "unspecified"  # type: ignore[return-value]


def normalize_readiness(value: Any) -> Readiness:
    """An unrecognised readiness is conservative: the goal still needs work."""
    text = _text(value)
    return text if text in READINESS_STATES else "needs_clarification"  # type: ignore[return-value]


def normalize_route(value: Any) -> GoalRoute:
    """An unrecognised route is conservative: clarify, never prepare or write."""
    text = _text(value)
    return text if text in GOAL_ROUTES else "clarify_goal"  # type: ignore[return-value]


def normalize_meal_time(value: Any) -> MealTime | None:
    """A known meal time, or ``None``; an invented one is not kept."""
    text = _text(value)
    return text if text in MEAL_TIMES else None  # type: ignore[return-value]


class GoalConstraints(BaseModel):
    """Only constraints the user actually stated; never inferred facts.

    ``budget_yuan`` is the one money field the understanding layer may carry, and
    it is denominated in yuan like the existing protocol (``app.agent.protocol``)
    so the server converts it to fen itself. This layer does no money arithmetic.
    """

    model_config = ConfigDict(extra="forbid")

    people: int | None = Field(None, ge=1, le=99)
    budget_yuan: float | None = Field(None, ge=0)
    #: Flavour/health wording as stated ("清淡", "不辣", "低油"). Kept verbatim:
    #: it is the user's own word, not a normalized nutrition claim.
    dietary: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    meal_time: MealTime | None = None
    specification: dict[Literal["size", "brand", "item_volume_ml", "packaging", "pack_count", "pack_mode", "max_price_fen"], Any] = Field(default_factory=dict)


class Goal(BaseModel):
    """The constrained understanding result the model is allowed to propose.

    It carries no plan, no price, no stock and no route; those are server
    decisions. ``assumptions`` must stay distinguishable from user facts, so a
    default population ("按配方默认 2 人") is recorded there, never inside
    ``constraints.people``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: GoalKind
    fulfillment_mode: FulfillmentMode = "unspecified"
    #: Human-readable restatement of the goal ("两个人份可乐鸡翅").
    description: str = ""
    #: The named dish / product / category target. One field, because the same
    #: name means different things under different kinds; the kind disambiguates.
    target_name: str | None = None
    #: User-stated sell-unit count for a product purchase.
    quantity: int | None = None
    category_id: str | None = None
    category_name: str | None = None
    #: Products the user explicitly named ("买一盒牛奶" → ["牛奶"]).
    items: list[str] = Field(default_factory=list)
    constraints: GoalConstraints = Field(default_factory=GoalConstraints)
    #: Honest remarks about the reading itself ("菜名可能有歧义").
    notes: list[str] = Field(default_factory=list)
    #: System-stated assumptions that must never be read back as user facts.
    assumptions: list[str] = Field(default_factory=list)


class GoalChangeSet(BaseModel):
    """The values a patch states. An omitted field means "unchanged".

    ``extra="forbid"`` is what refuses an arbitrary path operation: only these
    six goal fields exist, and each one is typed here. ``None`` means the field
    was not mentioned — it is never a way to erase a value. Erasing is spelled
    out in ``GoalChanges.clear``.
    """

    model_config = ConfigDict(extra="forbid")

    people: int | None = Field(None, ge=1, le=99)
    budget_yuan: float | None = Field(None, ge=0)
    fulfillment_mode: FulfillmentMode | None = None
    meal_time: MealTime | None = None
    dietary: list[str] | None = None
    excluded_ingredients: list[str] | None = None
    specification: dict[Literal["size", "brand", "item_volume_ml", "packaging", "pack_count", "pack_mode", "max_price_fen"], Any] | None = None

    def stated(self) -> dict[str, Any]:
        """Only the fields this patch really sets."""
        return {
            name: getattr(self, name)
            for name in CHANGE_FIELDS
            if getattr(self, name) is not None
        }


class GoalChanges(BaseModel):
    """A constrained field patch: ``set`` overrides, ``clear`` revokes.

    The two halves are deliberately explicit. A ``null`` in ``set`` is a
    *missing* value, not a revocation, so "撤销" has exactly one spelling and
    cannot be confused with "the model did not mention this field".
    """

    model_config = ConfigDict(extra="forbid")

    set: GoalChangeSet = Field(default_factory=GoalChangeSet)
    clear: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clear_field_is_known(self) -> "GoalChanges":
        unknown = sorted(set(self.clear) - set(CHANGE_FIELDS))
        if unknown:
            # A patch may only revoke the documented goal fields; anything else is
            # a path operation and is refused rather than dropped.
            raise ValueError(f"clear 含未知字段: {', '.join(unknown)}")
        return self

    @model_validator(mode="after")
    def _no_set_clear_conflict(self) -> "GoalChanges":
        conflicted = sorted(set(self.clear).intersection(self.set.stated()))
        if conflicted:
            # Overwriting and revoking the same field in one turn has no defined
            # winner, so it is refused instead of resolved by guesswork.
            raise ValueError(f"同一字段不能同时 set 与 clear: {', '.join(conflicted)}")
        return self

    def is_empty(self) -> bool:
        return not self.set.stated() and not self.clear

    def changed_fields(self) -> list[str]:
        """Every field this patch names, whether it sets or clears it."""
        return list(dict.fromkeys([*self.set.stated(), *self.clear]))


class Understanding(BaseModel):
    """The server's reading of one proposal: meaning only, never authority.

    Built by ``app.agent.protocol.parse_proposal`` from the model's independent
    dimensions. It carries no route, readiness, version, price or stock — the
    gate computes those from this object plus the server's own snapshot. A new
    goal and a set-patch are mutually exclusive; a clear list may travel with
    the new goal so a revoked field is not filled back in.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent = "none"
    plan_act: PlanAct = "none"
    #: A ref the server itself issued (active goal / pending goal / pending
    #: question / plan target). The model chooses one, never invents one.
    focus_ref: str | None = None
    #: Derived by the parser: ``append`` / ``switch`` only when the shopper said
    #: "add" / "replace"; ``amend`` for a patch or a row edit; otherwise
    #: ``unspecified``, which the gate resolves against the server's state.
    goal_relation: GoalRelation = "unspecified"
    new_goal: Goal | None = None
    changes: GoalChanges | None = None
    #: Conditions the shopper stated that nothing can apply yet, verbatim. They
    #: never filter anything; the reply says they were not applied.
    unsupported: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _new_goal_xor_patch(self) -> "Understanding":
        # A new goal can carry a clear list for fields it refuses to inherit.
        # A set-patch still cannot accompany a new goal.
        if (
            self.new_goal is not None
            and self.changes is not None
            and (self.changes.set.stated() or self.goal_relation == "amend")
        ):
            raise ValueError("new_goal 与 changes 只能二选一")
        if self.goal_relation in ("new", "append", "switch") and self.new_goal is None:
            raise ValueError(f"goal_relation={self.goal_relation} 必须给出 new_goal")
        if self.goal_relation == "amend" and self.new_goal is not None:
            raise ValueError("amend 只能更新已有目标，不能给出 new_goal")
        return self


class GoalCandidate(BaseModel):
    """A goal under discussion that is not (yet) the plan on screen.

    It is persisted in the existing session context, never mixed into
    ``task.plan_json``: understanding half a goal must not pollute the
    authoritative plan. Its original ``relation`` (a pending ``switch`` or
    ``append``) is kept, so a later amendment that fills a missing slot cannot
    silently turn the candidate into something else.
    """

    model_config = ConfigDict(extra="forbid")

    ref: str
    goal: Goal
    relation: GoalRelation
    #: The server candidate this goal will be built from, recorded when the
    #: candidate was created so a later turn can replay it instead of guessing.
    target_ref: str | None = None
    target_id: str = ""
    target_name: str = ""
    target_kind: str = ""
    missing_slots: list[str] = Field(default_factory=list)
    #: The task and plan version the candidate was agreed against. A candidate
    #: whose binding has moved on is stale: it may not fill slots or activate.
    task_id: str | None = None
    plan_version: int | None = None

    def is_stale(self, *, task_id: str | None, plan_version: int | None) -> bool:
        if self.task_id != task_id:
            return True
        if self.plan_version is None or plan_version is None:
            return False
        return self.plan_version != plan_version


class TurnDecision(BaseModel):
    """The gate's answer for one turn: what may happen next, and why.

    ``reason_code`` is an internal diagnostic. ``write_blocked`` is consumed
    only by the mutation execution chain; non-mutation routes do not turn it
    into a refusal.
    """

    model_config = ConfigDict(extra="forbid")

    route: TurnRoute
    #: Minimal internal action for the unified ``mutation`` route.  The route
    #: remains the sole graph decision; this field only preserves the existing
    #: prepare-vs-amend executor behavior.
    mutation_action: Literal[
        "prepare", "apply_mutation", "patch_meal_mode", "cancel_task", "confirm_plan"
    ] | None = None
    readiness: Readiness
    missing_slots: list[str] = Field(default_factory=list)
    write_blocked: bool
    reason_code: str
    relation: GoalRelation = "unspecified"
    focus_ref: str | None = None
    focus_kind: FocusKind = "none"
    #: The goal the decision is about (the merged candidate for an amendment).
    goal: Goal | None = None
    #: The goal fields this turn names (set or clear).
    changed_fields: list[str] = Field(default_factory=list)
    #: The candidate to persist for later turns, when the goal is not ready yet.
    candidate: GoalCandidate | None = None


class RouteDecision(BaseModel):
    """The pure routing result: what the next step is, and what is still unknown.

    ``missing_slots`` names the slots that block preparation. An empty list with
    ``readiness="ready"`` is the only combination that may prepare a plan.
    """

    model_config = ConfigDict(extra="forbid")

    kind: GoalKind
    readiness: Readiness
    fulfillment_mode: FulfillmentMode
    route: GoalRoute
    missing_slots: list[str] = Field(default_factory=list)
    #: Server-composed diagnostic wording; never a fact source and never shown
    #: as a promise. Empty when the route needs no explanation.
    reason: str = ""


class IntentState(BaseModel):
    """The understanding-layer snapshot consumed by a later workflow.

    ``goal`` is the constrained meaning proposal; ``decision`` is the
    server-derived next step. Keeping both together gives the runtime one
    immutable hand-off without putting route/readiness back under model
    control. This is not a purchase plan and carries no authorization.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    goal: Goal
    decision: RouteDecision
    source_turn_id: str | None = None


__all__ = [
    "CHANGE_FIELDS",
    "FOCUS_KINDS",
    "FORBIDDEN_GOAL_KEYS",
    "FULFILLMENT_MODES",
    "GOAL_KINDS",
    "GOAL_RELATIONS",
    "GOAL_ROUTES",
    "MEAL_TIMES",
    "READINESS_STATES",
    "TURN_ROUTES",
    "FocusKind",
    "FulfillmentMode",
    "Goal",
    "GoalCandidate",
    "GoalChangeSet",
    "GoalChanges",
    "GoalConstraints",
    "GoalKind",
    "GoalRelation",
    "GoalRoute",
    "Intent",
    "IntentState",
    "MealTime",
    "PlanAct",
    "Readiness",
    "RouteDecision",
    "TurnDecision",
    "TurnRoute",
    "Understanding",
    "normalize_fulfillment_mode",
    "normalize_goal_kind",
    "normalize_meal_time",
    "normalize_readiness",
    "normalize_route",
]
