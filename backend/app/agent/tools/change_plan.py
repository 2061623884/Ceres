"""Plan-change tool boundary: turn a validated proposal into real business calls.

The model proposes; the server compiles and executes. This module owns both ends
of that boundary for a plan mutation:

1. a reference is resolved against *this* turn's candidate list, so an invented
   or stale ref is refused instead of guessed at;
2. the redundant human-readable name is checked against the same row, so a copied
   ref carrying a different product's name cannot slip through;
3. the constraints the user actually stated are compiled into the internal call
   arguments;
4. the compiled call is staged through the shared ``prepare_purchase_plan``
   entry for the Graph commit node to persist later.

It has no workflow, no model, no turn routing and no direct persistence. What it does have is the
owner's real state: the plan on screen, the already-bought ledger, the current
version. Those are read through the services that own them, never re-implemented
here. There is deliberately no cart-confirmation capability at this boundary.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from sqlalchemy.orm import Session

from app.agent.protocol import (
    CandidateRef,
    CandidateSet,
    Mutation,
    SemanticProtocolError,
)
from app.agent.state import Requirements, TaskState
from app.agent.tools.prepare_purchase_plan import guarded_prepare_purchase_plan
from app.agent.tools.schemas import PREPARE_PURCHASE_PLAN_INPUT_SCHEMA
from app.agent.tools.validation import validate_json_object
from app.services.cart_service import CartService
from app.services.validation_context import ValidationContext
from app.services.shopping_plan_service import (
    ShoppingPlanService,
    group_id_for,
)
from app.services.task_lifecycle_service import TaskLifecycleService, TurnAnchor

#: Action receipt statuses. ``saved`` is kept alongside for older clients, but
#: ``status`` is the authority: a read-only result is ``completed`` while
#: ``saved`` is False, and that must never be read as a failure.
STATUS_COMMITTED = "committed"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
#: The gate refused the write before it was attempted. It is deliberately not a
#: failure of the turn: the answer to the shopper's question is still delivered.
STATUS_BLOCKED = "blocked"


def _row_group_ids(row: dict[str, Any]) -> set[str]:
    """Every group a stored plan row really contributes to.

    A collapsed row carries one contribution per group that needed its SKU, so
    reading the row's own ``group_id`` alone would miss the shared ones.
    """
    ids = {
        str(entry.get("group_id") or "")
        for entry in row.get("contributions") or []
        if isinstance(entry, dict)
    }
    ids.add(str(row.get("group_id") or ""))
    return {value for value in ids if value}


class PlanChangeExecutor:
    """Executes validated plan mutations. Never touches a model or a turn."""

    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id
        self.tasks = TaskLifecycleService(db, owner_id)
        #: The session/task version this turn snapshotted, set by the turn entry
        #: before any write. ``None`` means there is no turn boundary to defend
        #: (the legacy caller), and the conditional update alone guards the write.
        self.anchor: TurnAnchor | None = None
        #: Questions raised while executing (e.g. a pending slot fill). The
        #: caller persists them; nothing is written here.
        self.business_pending: list[dict[str, Any]] = []
        #: The gate's decision for this turn and the goal under discussion. They
        #: are what the executor derives the *relation* from: a pending candidate
        #: keeps its original switch/append intent when it is finally built, so
        #: the same turn that fills a slot cannot silently become an append.
        self.decision: Any = None
        self.goal_candidate: Any = None

    def cart_quantities_for(self, sku_ids: list[str] | None, *, store_id: str) -> dict[str, int]:
        """The already-bought ledger, owner- and store-scoped.

        One implementation, in ``CartService``; the workflow delegates to the
        same method.
        """
        return CartService(self.db, self.owner_id, store_id).quantities_for(sku_ids)

    # ------------------------------------------------------------- pure prepare

    def prepare(
        self,
        *,
        state: TaskState | None,
        mutation: Mutation,
        candidates: CandidateSet,
        store: str,
        zone: str,
    ) -> dict[str, Any]:
        """Compute one mutation's staged effect, reading only.

        This is the pure half of the write: it resolves the server-issued ref,
        compiles the internal args, runs the shared ``guarded_prepare_purchase_plan``
        and merges a preview. No ORM row is added, updated or committed here; the
        result is a plain JSON payload the commit node applies later.
        """
        candidate = resolve_mutation_refs(mutation, candidates)
        if mutation.verb == "add":
            return self._prepare_add(state, mutation, candidate, store, zone)
        if mutation.verb == "remove":
            return self._prepare_remove(state, candidate, store, zone)
        if mutation.field == "quantity":
            return self._prepare_quantity(state, mutation, candidate, store, zone)
        if mutation.field == "people":
            self._ensure_writable(state)
            target = candidate
            if candidate.kind == "group":
                target = self._group_as_candidate(candidate)
            if target.kind in ("dish", "scenario"):
                return self._prepare_add(
                    state,
                    Mutation(verb="add", candidate_ref=target.ref, people=mutation.people),
                    target,
                    store,
                    zone,
                )
            raise SemanticProtocolError("UNSUPPORTED_OPERATION", "people 只能作用于菜品或场景")
        raise SemanticProtocolError(
            "UNSUPPORTED_OPERATION",
            "改写已有清单的预算或忌口需要重算整份清单，当前版本还不支持；"
            "这些条件不会生效，请直接说要换成什么菜，或新建一份清单。",
        )

    def prepare_many(
        self,
        *,
        state: TaskState | None,
        mutations: list[Mutation],
        candidates: CandidateSet,
        store: str,
        zone: str,
    ) -> list[dict[str, Any]]:
        """Prepare an ordered batch of already-authorised mutations, purely.

        Signatures follow :meth:`prepare`; only ``mutation`` becomes a list. Every
        step reuses that same single-mutation prepare, but each one runs against
        a *virtual projection* of the previous steps' effect: the plan is merged
        in memory (existing ``ShoppingPlanService`` merge /``apply_row_quantity``)
        so a later operation sees what the earlier one would have written — e.g.
        a second ``change.quantity`` on the same row starts from the first one's
        projected quantity.

        This adds no batch-level refusal rule. The caller keeps the shared
        ``authorize_mutations`` gate (two adds, or two different rows, are still
        refused *there*, never here), and an authorised list keeps its order with
        one prepared step per mutation — nothing is blanketed or truncated to
        ``mutations[0]``.

        Preparation is read-only: no ORM row is added, updated or committed, and
        the caller's ``state``/session is not mutated. If any step is not
        ``staged`` the whole batch raises that step's own
        :class:`SemanticProtocolError` (with its code and a ``第 N 步`` prefix) and
        no partial result is returned, so the caller's transaction stays empty.

        Returns the ordered prepared steps, each the single-prepare payload
        extended with:

        * ``step_index`` — its position in ``mutations``;
        * ``mutation`` — ``asdict`` of the authorised mutation;
        * ``plan_after`` — the projected plan once this step's effect is applied.

        An ``add`` step carries ``plan_result``/``args``/``operation``/
        ``switching`` for ``PlanCommitService.apply_result``; a
        ``remove``/``change.quantity`` step carries ``plan_patch`` (the full
        projected plan) to assign to ``state.plan`` before ``to_db``. The caller
        applies the steps in order inside one transaction and advances its own
        anchor/version after each.
        """
        prepared: list[dict[str, Any]] = []
        projected = state
        for index, mutation in enumerate(mutations):
            try:
                result = self.prepare(
                    state=projected,
                    mutation=mutation,
                    candidates=candidates,
                    store=store,
                    zone=zone,
                )
            except SemanticProtocolError as exc:
                raise SemanticProtocolError(
                    exc.code, f"第 {index + 1} 步：{exc.message}"
                ) from exc
            if str(result.get("status")) != "staged":
                code = str(result.get("code") or "UNSUPPORTED_OPERATION")
                message = str(
                    result.get("message") or "这一步无法准备，本轮没有改动。"
                )
                raise SemanticProtocolError(code, f"第 {index + 1} 步：{message}")
            plan_after = self._project_plan(projected, result, store, zone)
            step = dict(result)
            step["step_index"] = index
            step["mutation"] = asdict(mutation)
            step["plan_after"] = plan_after
            prepared.append(step)
            projected = self._project_state(projected, mutation, plan_after)
        return prepared

    def _project_plan(
        self,
        state: TaskState | None,
        result: dict[str, Any],
        store: str,
        zone: str,
    ) -> dict[str, Any] | None:
        """The plan this step would leave behind, merged only in memory."""
        if result.get("verb") != "add":
            patch = result.get("plan_patch")
            return patch if isinstance(patch, dict) else None
        base_plan = None
        if state is not None and not self.tasks.task_is_terminal(state.task_id):
            base_plan = state.plan if isinstance(state.plan, dict) else None
        plan_result = result.get("plan_result")
        if not isinstance(plan_result, dict):
            return base_plan
        operation = str(result.get("operation") or "append")
        if base_plan is None:
            operation = "replace"
        target_kind = str(result.get("target_kind") or plan_result.get("target_kind") or "")
        target_id = str(result.get("target_id") or plan_result.get("target_id") or "")
        group_id = str(plan_result.get("group_id") or group_id_for(target_kind, target_id))
        return ShoppingPlanService(self.db, store, zone).merge_plan(
            base_plan,
            plan_result,
            group_id=group_id,
            operation=operation,
            cart_quantities=self.cart_quantities_for(None, store_id=store),
            ctx=ValidationContext.from_requirements(
                Requirements(specification=result["args"]["specification"],
                             excluded_ingredients=result["args"].get("exclude_ingredients", [])),
                store_id=store, delivery_zone_id=zone,
            ),
        )

    def _project_state(
        self,
        state: TaskState | None,
        mutation: Mutation,
        plan_after: dict[str, Any] | None,
    ) -> TaskState | None:
        """A copy of ``state`` with this step's plan/constraints projected."""
        if state is None:
            return None
        return replace(
            state,
            plan=plan_after,
            requirements=self._turn_constraints(state, [mutation]),
        )

    def _prepare_add(
        self,
        state: TaskState | None,
        mutation: Mutation,
        candidate: CandidateRef,
        store: str,
        zone: str,
    ) -> dict[str, Any]:
        if candidate.kind not in ("dish", "product", "scenario"):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", f"候选类型无法建单: {candidate.kind}"
            )
        if mutation.quantity_value is not None and (
            candidate.kind != "product" or mutation.quantity_mode != "set"
        ):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "新增商品使用明确件数；已有商品增减请用 change.quantity"
            )
        switching = self._relation_for(candidate) == "switch"
        active_plan = (
            state.plan if state and not self.tasks.task_is_terminal(state.task_id) else None
        )
        if (
            active_plan
            and not switching
            and mutation.excluded_ingredients
            and not set(mutation.excluded_ingredients) <= set(state.requirements.excluded_ingredients)
        ):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "新增忌口需要校验整份旧清单，本轮未修改原方案或条件。"
            )
        if (
            active_plan
            and not switching
            and mutation.budget_fen is not None
            and mutation.budget_fen != state.requirements.budget_fen
        ):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "修改预算需要重算整份旧清单，本轮未修改原方案或条件。"
            )
        constraints = self._turn_constraints(state, [mutation])
        operation = self._operation_for(state, candidate, mutation)
        args = compile_internal_args(
            mutation,
            candidate,
            people=constraints.people,
            budget_fen=constraints.budget_fen,
            excluded_ingredients=constraints.excluded_ingredients,
            operation=operation,
        )
        if candidate.kind == "product":
            args["quantity"] = mutation.quantity_value or 1
        schema_error = validate_json_object(
            PREPARE_PURCHASE_PLAN_INPUT_SCHEMA,
            {key: value for key, value in args.items() if key != "budget_fen"},
        )
        if schema_error:
            return {
                "status": "failed",
                "verb": "add",
                "candidate_ref": candidate.ref,
                "code": "INVALID_ARGS",
                "message": schema_error,
            }
        result = guarded_prepare_purchase_plan(
            self.db,
            store_id=store,
            delivery_zone_id=zone,
            target_kind=str(args.get("target_kind") or ""),
            target_id=str(args.get("target_id") or ""),
            target_name=candidate.name,
            people=constraints.people,
            budget_fen=constraints.budget_fen,
            exclude_ingredients=list(args.get("exclude_ingredients") or []),
            operation=operation,
            quantity=int(args.get("quantity") or 1),
        )
        if result.get("status") != "ok":
            return {
                "status": "failed",
                "verb": "add",
                "candidate_ref": candidate.ref,
                "code": result.get("code"),
                "message": result.get("message"),
            }
        preview = ShoppingPlanService(self.db, store, zone).merge_plan(
            active_plan,
            result,
            group_id=result["group_id"],
            operation=operation,
            cart_quantities=self.cart_quantities_for(
                None,
                store_id=store,
            ),
            ctx=ValidationContext.from_requirements(constraints, store_id=store, delivery_zone_id=zone),
        )
        if constraints.budget_fen is not None and preview["selected_total_fen"] > constraints.budget_fen:
            raise SemanticProtocolError(
                "BUDGET_EXCEEDED", "合并后的清单超出当前预算，原方案保持不变。"
            )
        if active_plan and ShoppingPlanService.content_signature(preview) == self._signature(state):
            return {
                "status": "noop",
                "verb": "add",
                "candidate_ref": candidate.ref,
                "message": "该目标已在清单中，未重复生成；增加件数请明确说要增加多少。",
            }
        return {
            "status": "staged",
            "verb": "add",
            "target_kind": str(args.get("target_kind") or ""),
            "target_id": str(args.get("target_id") or ""),
            "operation": operation,
            "switching": switching,
            "plan_result": result,
            "plan_after": preview,
            "args": args,
            "candidate_ref": candidate.ref,
            "message": f"采购清单已加入「{candidate.name or candidate.target_id}」"
            + (f"（{result['target']['people']} 人份）" if candidate.kind == "dish" else ""),
        }

    def _prepare_remove(
        self,
        state: TaskState | None,
        candidate: CandidateRef,
        store: str,
        zone: str,
    ) -> dict[str, Any]:
        if candidate.kind != "group" or not candidate.group_id:
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "remove 只能作用于当前方案里的一个分组"
            )
        self._ensure_writable(state)
        plan = getattr(state, "plan", None) if state is not None else None
        if not isinstance(plan, dict) or not plan.get("items"):
            raise SemanticProtocolError("NOTHING_TO_REMOVE", "当前没有可修改的方案")
        if not any(
            str(t.get("group_id") or "") == candidate.group_id
            for t in plan.get("targets") or []
        ):
            raise SemanticProtocolError(
                "GROUP_NOT_IN_PLAN", f"方案里没有这个分组: {candidate.group_id}"
            )
        merged = ShoppingPlanService(self.db, store, zone).merge_plan(
            plan,
            {"items": [], "target": {}},
            group_id=candidate.group_id,
            operation="remove",
            cart_quantities=self.cart_quantities_for(
                None, store_id=store
            ),
            ctx=ValidationContext.from_requirements(state.requirements, store_id=store, delivery_zone_id=zone),
        )
        return {
            "status": "staged",
            "verb": "remove",
            "group_id": candidate.group_id,
            "plan_patch": merged,
            "message": f"已移除「{candidate.name or candidate.group_id}」",
        }

    def _prepare_quantity(
        self,
        state: TaskState | None,
        mutation: Mutation,
        candidate: CandidateRef,
        store: str,
        zone: str,
    ) -> dict[str, Any]:
        self._ensure_writable(state)
        if candidate.kind == "group":
            candidate = self._group_as_item(state, candidate)
        if candidate.kind != "item":
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "quantity 只能作用于方案里的一行商品"
            )
        plan = getattr(state, "plan", None) if state is not None else None
        if not isinstance(plan, dict) or not plan.get("items"):
            raise SemanticProtocolError("NOTHING_TO_CHANGE", "当前没有可修改的方案")
        row = next(
            (i for i in plan["items"] if str(i.get("sku_id")) == candidate.target_id), None
        )
        if row is None:
            raise SemanticProtocolError("ITEM_NOT_IN_PLAN", "方案里没有这件商品")
        current = int(row.get("quantity") or 1)
        added = int(row.get("added_quantity") or 0)
        if mutation.quantity_mode == "delta":
            target = current + int(mutation.quantity_value or 0)
        else:
            target = int(mutation.quantity_value or current)
        floor = max(1, added)
        max_addable = row.get("max_addable_quantity")
        ceiling = added + int(max_addable) if max_addable is not None else 99
        if target < floor or target > ceiling:
            raise SemanticProtocolError(
                "QUANTITY_OUT_OF_RANGE",
                f"件数必须在 {floor} 到 {ceiling} 之间（已加购 {added} 件）。",
            )
        if target == current:
            raise SemanticProtocolError("NO_CHANGE", "件数没有变化")
        updated = ShoppingPlanService(self.db, store, zone).apply_row_quantity(
            plan,
            candidate.target_id,
            target,
            cart_quantities=self.cart_quantities_for(
                [str(i["sku_id"]) for i in plan["items"]], store_id=store
            ),
        )
        if updated is None:
            raise SemanticProtocolError("ITEM_NOT_IN_PLAN", "方案里没有这件商品")
        changed = next(i for i in updated["items"] if i["sku_id"] == candidate.target_id)
        if changed["remaining_quantity"] > changed["max_addable_quantity"]:
            raise SemanticProtocolError(
                "QUANTITY_OUT_OF_RANGE", "当前库存已变化，这个数量暂时无法满足。"
            )
        if (
            state.requirements.budget_fen is not None
            and updated["selected_total_fen"] > state.requirements.budget_fen
        ):
            raise SemanticProtocolError("BUDGET_EXCEEDED", "改量后超出当前预算，原方案保持不变。")
        return {
            "status": "staged",
            "verb": "change",
            "field": "quantity",
            "sku_id": candidate.target_id,
            "quantity": target,
            "plan_patch": updated,
            "message": f"已把「{candidate.name or candidate.target_id}」改为 {target} 件",
        }

    def _turn_constraints(
        self, state: TaskState | None, mutations: list[Mutation]
    ) -> Requirements:
        """The constraints the user stated this turn, from typed fields only."""
        people = None
        budget = None
        excluded: list[str] = []
        for mutation in mutations:
            if mutation.people:
                people = mutation.people
            if mutation.budget_fen is not None:
                budget = mutation.budget_fen
            excluded.extend(mutation.excluded_ingredients)
        requirements = getattr(state, "requirements", None)
        if state and self.tasks.task_is_terminal(state.task_id):
            requirements = None
        relation = getattr(self.goal_candidate, "relation", None) or getattr(self.decision, "relation", None)
        if requirements is not None and relation in ("new", "switch"):
            requirements = Requirements(excluded_ingredients=list(requirements.excluded_ingredients))
        return Requirements(
            people=people or (requirements.people if requirements else None),
            budget_fen=budget if budget is not None else (requirements.budget_fen if requirements else None),
            excluded_ingredients=list(
                dict.fromkeys(
                    (requirements.excluded_ingredients if requirements else []) + excluded
                )
            ),
        )

    def _operation_for(
        self,
        state: TaskState | None,
        candidate: CandidateRef,
        mutation: Mutation,
    ) -> str:
        """How this add relates to the plan on screen — decided by the server."""
        plan = getattr(state, "plan", None) if state is not None else None
        if not isinstance(plan, dict) or not plan.get("items"):
            return "replace"
        group_id = group_id_for(candidate.kind, candidate.target_id)
        if self._relation_for(candidate) == "switch":
            return "replace"
        existing = any(
            str(t.get("group_id") or "") == group_id for t in plan.get("targets") or []
        )
        if existing and mutation.people and candidate.kind in ("dish", "scenario"):
            return "resize"
        return "append"

    def _relation_for(self, candidate: CandidateRef) -> str | None:
        """How this add relates to what is on screen, from the validated decision."""
        pending = self.goal_candidate
        if (
            pending is not None
            and getattr(pending, "target_ref", None)
            and pending.target_ref == candidate.ref
        ):
            return str(getattr(pending, "relation", None) or "append")
        if self.decision is not None:
            return str(self.decision.relation)
        return None

    @staticmethod
    def _group_as_item(state: TaskState | None, candidate: CandidateRef) -> CandidateRef:
        """Map a single-SKU product group onto its one real row of this plan."""
        plan = getattr(state, "plan", None) if state is not None else None
        group_kind = candidate.target_kind or (
            candidate.group_id.split(":", 1)[0] if candidate.group_id else ""
        )
        if group_kind != "product" or not isinstance(plan, dict):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION",
                "只有单件商品的采购分组可以直接改件数；菜品或场景请改人数或换成别的。",
            )
        rows = [
            row
            for row in plan.get("items") or []
            if candidate.group_id and candidate.group_id in _row_group_ids(row)
        ]
        skus = {str(row.get("sku_id")) for row in rows if row.get("sku_id")}
        if len(skus) != 1:
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", "这个分组不是单件商品，无法直接改件数。"
            )
        sku_id = next(iter(skus))
        row = next(r for r in rows if str(r.get("sku_id")) == sku_id)
        return CandidateRef(
            ref=candidate.ref,
            kind="item",
            target_id=sku_id,
            name=str(row.get("name") or candidate.name),
            group_id=candidate.group_id,
            target_kind="product",
        )

    @staticmethod
    def _group_as_candidate(candidate: CandidateRef) -> CandidateRef:
        """Re-target a plan group for a rebuild (``change.field=people``)."""
        kind = candidate.group_id.split(":", 1)[0] if candidate.group_id else ""
        if kind not in ("dish", "scenario", "product"):
            raise SemanticProtocolError(
                "UNSUPPORTED_OPERATION", f"分组类型无法重建: {candidate.group_id}"
            )
        return CandidateRef(
            ref=candidate.ref,
            kind=kind,
            target_id=candidate.target_id,
            name=candidate.name,
            group_id=candidate.group_id,
            target_kind=candidate.target_kind or kind,
        )

    def _ensure_writable(self, state: TaskState | None) -> None:
        """A confirmed task's history is immutable."""
        self.tasks.assert_turn_anchor(self.anchor)
        if state is None:
            return
        if self.tasks.task_is_terminal(state.task_id):
            raise SemanticProtocolError(
                "TASK_COMPLETED_READ_ONLY",
                "这份清单已经确认加购，不能再改动；可以说要新增什么，我会另开一份新清单。",
            )

    def _signature(self, state: TaskState | None) -> str:
        plan = getattr(state, "plan", None) if state is not None else None
        return ShoppingPlanService.content_signature(plan)


__all__ = [
    "PlanChangeExecutor",
    "STATUS_BLOCKED",
    "compile_internal_args",
    "resolve_mutation_refs",
]


def resolve_mutation_refs(
    mutation: Mutation,
    candidates: CandidateSet,
) -> CandidateRef:
    """Resolve a mutation's ref against this turn's candidate list."""
    ref = mutation.candidate_ref or mutation.target_ref
    resolved = candidates.resolve(ref)
    if resolved is None:
        raise SemanticProtocolError(
            "UNKNOWN_CANDIDATE_REF", f"未知的候选引用: {ref}"
        )
    allowed = ("dish", "product", "scenario") if mutation.verb == "add" else ("group", "item")
    if resolved.kind not in allowed:
        raise SemanticProtocolError("REF_KIND_CONFLICT", "候选引用与当前方案目标引用不能混用")
    if not mutation.name:
        raise SemanticProtocolError("MISSING_TARGET_NAME", "修改必须同时给出目标 ref 和完整 name；本次未执行。")
    if mutation.name != resolved.name.strip():
        raise SemanticProtocolError(
            "TARGET_NAME_MISMATCH",
            f"目标名称「{mutation.name}」与引用对应的「{resolved.name}」不一致；本次未执行。",
        )
    return resolved


def compile_internal_args(
    mutation: Mutation,
    candidate: CandidateRef,
    *,
    people: int | None,
    budget_fen: int | None,
    excluded_ingredients: list[str],
    operation: str,
) -> dict[str, Any]:
    """Compile a validated ``add``/``resize`` into the existing internal call args."""
    if candidate.kind not in ("dish", "product", "scenario"):
        raise SemanticProtocolError(
            "UNSUPPORTED_OPERATION", f"无法为该候选类型建单: {candidate.kind}"
        )
    args: dict[str, Any] = {
        "target_kind": candidate.kind,
        "target_id": candidate.target_id,
        "operation": operation,
    }
    if people:
        args["people"] = people
    if budget_fen is not None:
        args["budget_fen"] = budget_fen
    if excluded_ingredients:
        args["exclude_ingredients"] = list(excluded_ingredients)
    return args
