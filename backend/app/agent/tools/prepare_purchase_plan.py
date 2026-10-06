"""prepare_purchase_plan business tool implementation.

One tool, three verifiable target kinds. The model may *name* a target, but the
server decides which SKUs exist, how many packs are needed and what they cost.
``people`` is optional: a recipe falls back to its template ``base_people`` and a
direct product never scales with headcount.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agent.state import Requirements
from app.services.shopping_plan_service import (
    ShoppingPlanService,
    get_scenario,
    group_id_for,
)
from app.services.template_matcher import get_template_by_id
from app.services.template_plan_service import TemplatePlanService
from app.services.catalog_service import CatalogService
from app.services.ingredient_catalog import ingredient_name_zh
from app.services.validation_context import ValidationContext

TARGET_KINDS = ("dish", "product", "scenario")
OPERATIONS = ("append", "replace", "resize")


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message, **extra}


def _missing_keys(gaps: list[dict[str, Any]] | None) -> list[str]:
    """Compatibility view of a plan's gaps: the ingredient/SKU keys, in order."""
    keys: list[str] = []
    for gap in gaps or []:
        if not isinstance(gap, dict):
            continue
        key = gap.get("ingredient_id") or gap.get("sku_id") or gap.get("component_id")
        if key and str(key) not in keys:
            keys.append(str(key))
    return keys


def _friendly_failure(
    dish_label: str,
    errors: list[str],
    *,
    ctx: ValidationContext,
    db: Session,
    store_id: str,
) -> tuple[str, str]:
    """Map validator wording onto something a shopper can act on."""
    joined = "; ".join(errors)
    lowered = joined.lower()
    if ctx.specification.get("size") == "small":
        for error in errors:
            if "violates constraints" not in error.lower():
                continue
            sku_id = error.split(" ", 2)[1]
            product = CatalogService(db, store_id).get_product(sku_id)
            if not ctx.matches_spec(product):
                size = (
                    f"{product['spec_quantity']}{product['spec_unit']}"
                    if product.get("spec_quantity") is not None and product.get("spec_unit")
                    else "规格信息不完整"
                )
                name = product.get("name_zh") or product.get("name") or sku_id
                return (
                    "VALIDATION_FAILED",
                    f"商品「{name}」当前规格为 {size}，不符合小包装要求；「{dish_label}」清单没有生成。",
                )
    if "insufficient stock" in lowered or "not sellable" in lowered or "not approved" in lowered:
        return (
            "SUPPLY_UNAVAILABLE",
            f"「{dish_label}」里有商品库存不足或已下架，暂时无法配齐，原来的清单保持不变。",
        )
    if "budget" in lowered or "预算" in joined:
        return "BUDGET_EXCEEDED", f"按现在的价格，这份「{dish_label}」超出了你说的预算。"
    if "uncovered" in lowered or "覆盖" in joined:
        return "UNCOVERED", f"「{dish_label}」还有主料没有勾选，勾选后才能确认。"
    if "not in candidate set" in lowered or "violates constraints" in lowered:
        message = f"「{dish_label}」里有商品不满足当前条件，暂时无法配齐。"
        if ctx.excluded_ingredients:
            names = dict.fromkeys(ingredient_name_zh(term) or term for term in ctx.excluded_ingredients)
            message += f"本次排除条件：{'、'.join(names)}。"
        return "VALIDATION_FAILED", message
    return "VALIDATION_FAILED", f"暂时无法配齐「{dish_label}」：{joined}"


def resolve_target_kind(args: dict[str, Any]) -> str | None:
    explicit = args.get("target_kind")
    if explicit in TARGET_KINDS:
        return str(explicit)
    if explicit:
        return None
    if args.get("dish_id") or args.get("target_id", "").startswith("dish-"):
        return "dish"
    if args.get("target_id") and get_scenario(str(args["target_id"])):
        return "scenario"
    if args.get("target_id"):
        return "product"
    return None


def resolve_target_id(args: dict[str, Any], kind: str) -> str:
    if kind == "dish":
        return str(args.get("dish_id") or args.get("target_id") or "")
    return str(args.get("target_id") or args.get("dish_id") or "")


def guarded_prepare_purchase_plan(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    target_kind: str,
    target_id: str,
    target_name: str = "",
    people: int | None = None,
    budget_fen: int | None = None,
    exclude_ingredients: list[str] | None = None,
    operation: str = "append",
    quantity: int = 1,
    specification: dict[str, str] | None = None,
    allowed_dish_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Structure-check a target, then build the plan.

    Keep target-specific business checks at the shared plan-building boundary:

    * ``allowed_dish_ids`` optionally restricts the caller's accepted dish IDs.
      The semantic path passes ``None``: its reference was already resolved
      against server-owned candidates, which is a stronger check than a name.

    An open scenario is generic: it is built from its own ``components`` /
    ``common_tags``, never from a model-supplied variant.
    """
    if target_kind not in TARGET_KINDS:
        return _error("INVALID_ARGS", f"target_kind 必须是 {', '.join(TARGET_KINDS)} 之一")
    if operation not in OPERATIONS:
        return _error("INVALID_ARGS", f"operation 必须是 {', '.join(OPERATIONS)} 之一")

    if target_kind == "dish":
        if not target_id:
            return _error("INVALID_ARGS", "target_id（菜谱 id）不能为空")
        if allowed_dish_ids is not None and target_id not in allowed_dish_ids:
            return _error(
                "DISH_NOT_SELECTED",
                f"dish_id 尚未由用户确认: {target_id}。"
                "请先在候选里让用户选择，或使用用户明确说出的菜名。",
            )
    elif target_kind == "scenario":
        if get_scenario(target_id) is None:
            return _error("UNKNOWN_SCENARIO", f"未收录的采购场景: {target_id or '(空)'}")

    return prepare_purchase_plan(
        db,
        store_id=store_id,
        delivery_zone_id=delivery_zone_id,
        target_kind=target_kind,
        target_id=target_id,
        target_name=target_name,
        people=people,
        budget_fen=budget_fen,
        exclude_ingredients=exclude_ingredients,
        operation=operation,
        quantity=quantity,
        specification=specification,
    )


def prepare_purchase_plan(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    target_kind: str = "",
    target_id: str = "",
    target_name: str = "",
    dish_id: str = "",
    people: int | None = None,
    budget_fen: int | None = None,
    exclude_ingredients: list[str] | None = None,
    operation: str = "append",
    quantity: int = 1,
    specification: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Prepare a plan for a dish, a direct product or an open scenario.

    ``dish_id`` stays accepted as the legacy spelling of ``target_id`` so older
    callers and stored prompts keep working.
    """
    if not target_kind:
        target_kind = "dish" if dish_id else "product"
    if not target_id:
        target_id = dish_id
    if target_kind not in TARGET_KINDS:
        return _error(
            "INVALID_ARGS",
            f"target_kind 必须是 {', '.join(TARGET_KINDS)} 之一",
        )
    if people is not None and people < 1:
        return _error("INVALID_ARGS", "people must be a positive integer")
    if operation not in OPERATIONS:
        return _error("INVALID_ARGS", f"operation 必须是 {', '.join(OPERATIONS)} 之一")

    if target_kind == "dish":
        return _prepare_dish(
            db,
            store_id=store_id,
            delivery_zone_id=delivery_zone_id,
            dish_id=target_id,
            people=people,
            budget_fen=budget_fen,
            exclude_ingredients=exclude_ingredients,
            operation=operation,
            specification=specification,
        )
    if target_kind == "scenario":
        return _prepare_scenario(
            db,
            store_id=store_id,
            delivery_zone_id=delivery_zone_id,
            scenario_id=target_id,
            people=people,
            budget_fen=budget_fen,
            exclude_ingredients=exclude_ingredients,
            operation=operation,
            specification=specification,
        )
    return _prepare_product(
        db,
        store_id=store_id,
        delivery_zone_id=delivery_zone_id,
        target_id=target_id,
        target_name=target_name,
        quantity=quantity,
        budget_fen=budget_fen,
        exclude_ingredients=exclude_ingredients,
        operation=operation,
        specification=specification,
    )


def _prepare_dish(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    dish_id: str,
    people: int | None,
    budget_fen: int | None,
    exclude_ingredients: list[str] | None,
    operation: str,
    specification: dict[str, str] | None,
) -> dict[str, Any]:
    if not dish_id:
        return _error("INVALID_ARGS", "target_id (dish_id) is required for target_kind=dish")
    dish = get_template_by_id(db, dish_id)
    if not dish:
        return _error("INVALID_DISH_ID", f"unknown dish_id: {dish_id}")

    # A recipe without a stated headcount uses its own template basis. The
    # defaulted number is reported separately so it is never presented as
    # something the user said.
    people_source = "user" if people else "default"
    effective_people = int(people or dish.get("base_people") or 2)

    req = Requirements(
        people=effective_people,
        budget_fen=budget_fen,
        excluded_ingredients=list(exclude_ingredients or []),
        specification=dict(specification or {}),
        goal=dish.get("name") or dish.get("scenario"),
    )
    ctx = ValidationContext.from_requirements(
        req,
        store_id=store_id,
        delivery_zone_id=delivery_zone_id,
        active_template_id=dish_id,
    )
    planner = TemplatePlanService(db, store_id, delivery_zone_id)
    validated = planner.validate_template_plan(
        dish,
        effective_people,
        budget_fen=budget_fen,
        ctx=ctx,
    )

    if validated.get("validation_status") != "passed":
        errors = validated.get("errors") or ["validation failed"]
        label = str(dish.get("name") or dish.get("scenario") or dish_id)
        code, message = _friendly_failure(
            label,
            errors,
            ctx=ctx,
            db=db,
            store_id=store_id,
        )
        gaps = validated.get("gaps") or []
        if gaps and not (
            ctx.specification.get("size") == "small"
            and any("violates constraints" in error.lower() for error in errors)
        ):
            code = "SUPPLY_UNAVAILABLE"
        return {
            "status": "error",
            "code": code,
            "message": message,
            "validation_status": validated.get("validation_status"),
            "detail": "; ".join(errors),
            # The gap is never lost, even on a hard refusal.
            "missing": _missing_keys(gaps) or validated.get("uncovered_items") or [],
            "gaps": gaps,
        }

    group_id = group_id_for("dish", dish_id)
    # Return the validated public item fields verbatim. Rebuilding the rows by
    # hand previously dropped image/spec/stock/recommended-quantity/coverage
    # metadata that the planner had already computed and validated.
    items = []
    for item in validated.get("items", []):
        row = dict(item)
        row["group_id"] = group_id
        row["target_kind"] = "dish"
        row["target_id"] = dish_id
        items.append(row)

    gaps = validated.get("gaps") or []
    return {
        "status": "ok",
        "plan_id": validated["plan_id"],
        "plan_version": validated["plan_version"],
        "items": items,
        "total_price_fen": validated["total_price_fen"],
        "missing": _missing_keys(gaps),
        "validation_status": validated.get("validation_status"),
        "can_confirm": validated.get("can_confirm", True),
        "mode": validated.get("mode"),
        "selected_total_fen": validated.get("selected_total_fen"),
        "expires_at": validated.get("expires_at"),
        "coverage_mode": validated.get("coverage_mode"),
        "coverage_intent": validated.get("coverage_intent"),
        "uncovered_items": validated.get("uncovered_items", []),
        "gaps": gaps,
        "target_kind": "dish",
        "target_id": dish_id,
        "group_id": group_id,
        "operation": operation,
        "target": {
            "group_id": group_id,
            "kind": "dish",
            "target_id": dish_id,
            "name": dish.get("name") or dish.get("scenario"),
            "people": effective_people,
            "people_source": people_source,
        },
    }


def _prepare_scenario(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    scenario_id: str,
    people: int | None,
    budget_fen: int | None,
    exclude_ingredients: list[str] | None,
    operation: str,
    specification: dict[str, str] | None,
) -> dict[str, Any]:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        return _error("UNKNOWN_SCENARIO", f"未收录的采购场景: {scenario_id}")
    service = ShoppingPlanService(db, store_id, delivery_zone_id)
    result = service.build_scenario_plan(
        scenario_id,
        people=people,
        budget_fen=budget_fen,
        excluded_ingredients=exclude_ingredients,
        specification=specification,
    )
    if result.get("status") == "ok":
        result["operation"] = operation
    return result


def _prepare_product(
    db: Session,
    *,
    store_id: str,
    delivery_zone_id: str,
    target_id: str,
    target_name: str,
    quantity: int,
    budget_fen: int | None,
    exclude_ingredients: list[str] | None,
    operation: str,
    specification: dict[str, str] | None,
) -> dict[str, Any]:
    if not target_id and not target_name:
        return _error("INVALID_ARGS", "target_id 或 target_name 至少需要一个")
    service = ShoppingPlanService(db, store_id, delivery_zone_id)
    result = service.build_product_plan(
        target_name or target_id,
        target_id=target_id or None,
        quantity=quantity,
        budget_fen=budget_fen,
        excluded_ingredients=exclude_ingredients,
        specification=specification,
    )
    if result.get("status") == "ok":
        result["operation"] = operation
    return result
