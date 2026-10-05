"""Guide API schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Intent = Literal["purchase_task", "category_selection"]
Step = Literal[
    "understanding",
    "clarifying",
    "searching",
    "planning",
    "validating",
    "awaiting_confirmation",
    "adding_to_cart",
    "completed",
    "degraded",
    "cancelled",
]


class EntryContext(BaseModel):
    page: Literal["home", "category", "search", "product", "cart"] = "home"
    category_id: str | None = None
    store_id: str = "store-demo-01"
    delivery_zone_id: str = "zone-default"


class ViewContext(BaseModel):
    page: Literal["home", "category", "search", "product", "cart"] = "home"
    category_id: str | None = None
    product_id: str | None = None


class TurnRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    expected_task_id: str | None = None
    expected_state_version: int = Field(..., ge=0)
    expected_session_version: int | None = Field(None, ge=0)
    view_context: ViewContext | None = None

    @field_validator("expected_state_version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v < 0:
            raise ValueError("expected_state_version must be non-negative")
        return v


class PlanItem(BaseModel):
    sku_id: str
    name: str | None = None
    quantity: int = Field(..., ge=1, le=99)
    unit_price_fen: int = Field(..., ge=0)
    line_total_fen: int = Field(..., ge=0)
    image_path: str | None = None
    image_kind: Literal[
        "photo", "packaging_illustration", "placeholder", "unverified", "demo_photo", "missing"
    ] | None = None
    image_kind_legacy: Literal["demo_photo", "placeholder", "missing"] | None = None
    #: ``optional`` is a freely selectable scenario row: it never blocks
    #: confirmation when it stays unticked.
    role: Literal["required", "pantry", "optional"] = "required"
    selected: bool = True
    recommended_quantity: int | None = None
    max_addable_quantity: int | None = None
    spec_quantity: int | None = None
    spec_unit: str | None = None
    sell_unit: str | None = None
    quantity_source: Literal["recommended", "user"] | None = None
    #: Which target contributed this row, and how many packs that contribution
    #: needs. The same SKU shared by two targets is one row with two entries.
    group_id: str | None = None
    target_kind: Literal["dish", "product", "scenario"] | None = None
    target_id: str | None = None
    component_name: str | None = None
    contributions: list[dict[str, Any]] | None = None
    #: Packs already written to the cart by an explicit per-row add. A later batch
    #: confirm only covers ``remaining_quantity``.
    added_quantity: int | None = None
    remaining_quantity: int | None = None
    #: P0 requirement/fulfilment evidence. Every row carries the requirement it
    #: covers and the supply facts behind it, so a partial plan stays explainable
    #: after a reload. See ``app.services.plan_contract``.
    required_item_id: str | None = None
    requirement: dict[str, Any] | None = None
    #: ``available`` / ``insufficient_stock`` rows are selectable; the other
    #: states are reported as gaps and never kept as a purchasable line.
    availability: Literal[
        "available", "insufficient_stock", "out_of_stock", "not_found", "unknown"
    ] | None = None
    evidence: dict[str, Any] | None = None
    #: ``assumed_one`` means the catalog spec was missing and one pack was
    #: suggested: honest, but never proof the requirement is covered.
    pack_source: Literal["catalog_spec", "assumed_one"] | None = None
    #: Packs the requirement wanted but this store could not supply.
    shortfall_quantity: int | None = None


class PlanGap(BaseModel):
    """One structured gap: supply shortfall or an unresolved requirement.

    ``gaps`` is the plan's single gap authority; ``uncovered_items`` remains the
    compatibility projection of the required rows the user did not tick. Money is
    never part of a gap.
    """

    gap_id: str
    group_id: str | None = None
    target_kind: Literal["dish", "product", "scenario"] | None = None
    target_id: str | None = None
    kind: Literal["not_found", "out_of_stock", "insufficient_stock", "unknown"]
    unknown_of: Literal["availability", "quantity"] | None = None
    requiredness: Literal["core", "optional"] = "core"
    required_item_id: str | None = None
    #: Every requirement the affected row covers (two targets can share one SKU).
    required_item_ids: list[str] | None = None
    ingredient_id: str | None = None
    component_id: str | None = None
    name: str | None = None
    sku_id: str | None = None
    required_quantity: float | None = None
    unit: str | None = None
    quantity_known: bool | None = None
    #: Packs the pack math wanted for this requirement (never an amount in
    #: ``unit``): ``required_quantity``/``unit`` are the requirement's own amount.
    requested_pack_count: int | None = None
    available_quantity: int | None = None
    shortfall_quantity: int | None = None
    source: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    message: str = ""


class PlanTarget(BaseModel):
    group_id: str | None = None
    kind: Literal["dish", "product", "scenario"] | None = None
    target_id: str | None = None
    name: str | None = None
    people: int | None = None
    people_source: Literal["user", "default"] | None = None
    #: Honest remarks about this target (e.g. missing components).
    notes: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    plan_id: str
    plan_version: int
    mode: Literal["bundle", "alternatives"]
    items: list[PlanItem]
    total_price_fen: int
    selected_total_fen: int | None = None
    expires_at: str
    validation_status: str
    coverage_mode: str | None = None
    #: The intent this version was built/revised under. Omitted on legacy plans.
    coverage_intent: Literal["full", "partial_ok", "user_supplied"] | None = None
    uncovered_items: list[dict[str, Any]] = Field(default_factory=list)
    #: P0 gap authority (supply shortfalls / unresolved requirements).
    gaps: list[PlanGap] = Field(default_factory=list)
    can_confirm: bool | None = None
    gap_fill: bool | None = None
    #: Provenance of every group in this plan, in the order the user asked for it.
    targets: list[PlanTarget] = Field(default_factory=list)
    merged_sku_contributions: list[dict[str, Any]] = Field(default_factory=list)
    outstanding_total_fen: int | None = None


PlanEffect = Literal["keep", "replace", "clear"]
AnswerStatus = Literal[
    "accepted",
    "explained",
    "clarifying",
    "failed",
    "cancelled",
    "awaiting_confirmation",
    "understanding",
    "degraded",
]


class TurnResponse(BaseModel):
    request_id: str
    session_id: str
    #: ``stopped`` is the server's cancellation of *this generation*. It is not a
    #: purchase step and not a task status: the task keeps its own step, and the
    #: plan it already holds is still delivered. It mirrors what the SSE contract
    #: already sends as ``turn.stopped``, so both transports say the same thing.
    answer_status: AnswerStatus | Literal["stopped"] = "accepted"
    purchase_step: Step | Literal["none"] = "none"
    current_editable_task_id: str | None = None
    explained_task_id: str | None = None
    explained_plan_id: str | None = None
    explained_plan_version: int | None = None
    task_id: str | None = None
    state_version: int
    session_version: int = 0
    status: Step | Literal["stopped"]
    message: str
    product_cards: list[dict[str, Any]] = Field(default_factory=list)
    clarification: str | None = None
    plan: PlanResponse | None = None
    plan_effect: PlanEffect = "keep"
    pending_clarification: dict[str, Any] | None = None
    #: Every question this turn left open. ``pending_clarification`` remains the
    #: first entry so existing clients keep working.
    pending_clarifications: list[dict[str, Any]] = Field(default_factory=list)
    #: One receipt per action the server actually attempted. ``saved`` says
    #: whether anything was written; ``reply_ok`` says whether the wording step
    #: succeeded. They are independent: a saved plan with a failed reply is still
    #: a saved plan, never a whole-turn error.
    action_results: list[dict[str, Any]] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    message_sequence: int | None = None
    trace_id: str
    model_mode: str
    business_data_mode: str
    missing_constraints: list[str] = Field(default_factory=list)
    #: Read-only echo of the server's decision for this turn (see
    #: ``app.agent.goal_router.decide_turn``). ``None`` means the turn carried no
    #: semantic statement at all (a legacy proposal). It is informational: it
    #: grants nothing, and the plan plus the receipts remain authoritative.
    route: str | None = None
    readiness: str | None = None
    missing_slots: list[str] = Field(default_factory=list)


class ConfirmItem(BaseModel):
    sku_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., ge=1, le=99)


class AddPlanItemRequest(BaseModel):
    """Explicit single-row add from an editable plan."""

    request_id: str = Field(..., min_length=1, max_length=128)
    quantity: int = Field(1, ge=1, le=99)
    expected_state_version: int = Field(..., ge=1)
    expected_session_version: int | None = Field(None, ge=0)


class AddPlanItemResponse(BaseModel):
    operation_id: str
    task_id: str
    added_sku_id: str
    plan_id: str
    plan_version: int
    state_version: int
    session_version: int
    cart_version: int
    items_added: list[dict[str, Any]] = Field(default_factory=list)
    items: list[PlanItem] = Field(default_factory=list)
    can_confirm: bool = False
    outstanding_total_fen: int = 0
    #: The gaps and intent of the plan this row write left behind, so the client
    #: never has to guess coverage from the rows alone.
    coverage_mode: str | None = None
    coverage_intent: Literal["full", "partial_ok", "user_supplied"] | None = None
    uncovered_items: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[PlanGap] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    plan_id: str
    plan_version: int = Field(..., ge=1)
    expected_state_version: int = Field(..., ge=1)
    expected_session_version: int | None = Field(None, ge=0)
    selected_items: list[ConfirmItem] = Field(..., min_length=1, max_length=99)


class SessionCreateRequest(BaseModel):
    entry_context: EntryContext


class ConfirmResponse(BaseModel):
    operation_id: str
    status: str
    cart_version: int
    items_added: list[dict[str, Any]]
    errors: list[str] = Field(default_factory=list)
    task_id: str
    state_version: int
    session_version: int = 0
    confirmation_id: str


class CancelRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    expected_session_version: int = Field(..., ge=0)
    expected_state_version: int = Field(..., ge=0)


class CancelResponse(BaseModel):
    task_id: str
    status: str
    state_version: int
    session_version: int = 0


class StopTurnRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)


class StopTurnResponse(BaseModel):
    """Outcome of a cooperative stop request for one logical turn."""

    session_id: str
    request_id: str
    #: stopping | accepted | completed | stopped | failed | retryable_failed | not_found
    status: str
    run_id: str | None = None
    cancelled: bool = False


class CreateTaskRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    expected_session_version: int = Field(..., ge=0)
    action: Literal["start_new", "resume_last_goal"] = "start_new"
    view_context: ViewContext | None = None
    constraints: dict[str, Any] | None = None


class RevisionItem(BaseModel):
    sku_id: str
    quantity: int = Field(..., ge=1, le=99)
    selected: bool = True


class PlanRevisionRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    expected_session_version: int = Field(..., ge=0)
    expected_state_version: int = Field(..., ge=1)
    base_plan_id: str
    base_plan_version: int = Field(..., ge=1)
    client_edit_sequence: int = Field(1, ge=1)
    coverage_intent: Literal["full", "partial_ok", "user_supplied"] = "full"
    user_supplied_ingredients: list[str] = Field(default_factory=list)
    items: list[RevisionItem] = Field(..., min_length=1)


class PlanRevisionResponse(BaseModel):
    plan_id: str
    plan_version: int
    state_version: int
    session_version: int
    items: list[PlanItem]
    selected_total_fen: int
    total_price_fen: int
    outstanding_total_fen: int | None = None
    uncovered_items: list[dict[str, Any]] = Field(default_factory=list)
    coverage_intent: Literal["full", "partial_ok", "user_supplied"] | None = None
    gaps: list[PlanGap] = Field(default_factory=list)
    coverage_mode: str
    can_confirm: bool
    validation_errors: list[str] = Field(default_factory=list)


class GuideMessageResponse(BaseModel):
    message_id: str
    session_id: str
    task_id: str | None = None
    sequence: int
    role: str
    kind: str
    content: str
    plan_id: str | None = None
    plan_version: int | None = None
    request_id: str | None = None
    status: str
    created_at: str | None = None


class MessagesPageResponse(BaseModel):
    messages: list[GuideMessageResponse]
    has_more: bool
    next_cursor: int | None = None
    history_status: str | None = None


class PlanRefreshRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    expected_session_version: int = Field(..., ge=0)
    expected_state_version: int = Field(..., ge=1)
    base_plan_id: str
    base_plan_version: int = Field(..., ge=1)
    items: list[RevisionItem] | None = None


class PlanRefreshResponse(BaseModel):
    plan_id: str
    plan_version: int
    state_version: int
    session_version: int
    items: list[PlanItem]
    selected_total_fen: int
    total_price_fen: int
    can_confirm: bool
    stale_items: list[dict[str, Any]] = Field(default_factory=list)
    coverage_mode: str = "full"
    coverage_intent: Literal["full", "partial_ok", "user_supplied"] | None = None
    uncovered_items: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[PlanGap] = Field(default_factory=list)


class SupplyContextRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=128)
    expected_session_version: int = Field(..., ge=0)
    store_id: str
    delivery_zone_id: str


class SessionResponse(BaseModel):
    session_id: str
    product_cards: list[dict[str, Any]] = Field(default_factory=list)
    task_id: str | None = None
    state_version: int = 0
    session_version: int = 0
    current_step: Step | None = None
    task_status: str | None = None
    entry_context: EntryContext
    plan: PlanResponse | None = None
    #: True when the returned plan is a finished/historical deliverable: the
    #: client may dock it read-only. It never re-enables buying on its own.
    plan_read_only: bool = False
    pending_clarifications: list[dict[str, Any]] = Field(default_factory=list)
    confirmation_result: dict[str, Any] | None = None
    message: str | None = None
    available_actions: list[str] = Field(default_factory=list)
    constraints_summary: dict[str, Any] = Field(default_factory=dict)
    cart_version: int | None = None
    confirmation_id: str | None = None
    history_status: str | None = None
    messages: list[GuideMessageResponse] | None = None
