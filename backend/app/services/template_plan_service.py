"""Build purchase plans from matched dish templates."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import plan_contract as contract
from app.services.catalog_service import CatalogService
from app.services.image_assets import is_raster_image_path
from app.services.ingredient_catalog import ingredient_name_zh, load_ingredient_catalog
from app.services.plan_validator import PlanValidator
from app.services.template_matcher import (
    dish_display_name,
    load_templates,
    merge_items,
    scale_items,
)
from app.services.validation_context import ValidationContext

INGREDIENT_ALIASES: dict[str, list[str]] = {
    "oil": ["oil", "olive_oil", "cooking_oil"],
    "peanut": ["peanut", "peanuts"],
    "chicken_breast": ["chicken_breast", "chicken"],
    "bell_pepper": ["bell_pepper", "green_pepper"],
}

UNIT_TO_GRAMS: dict[str, float] = {
    "g": 1.0,
    "kg": 1000.0,
    "ml": 1.0,
    "l": 1000.0,
    "pc": 1.0,
}

LIQUID_PANTRY = frozenset(
    {"oil", "vinegar", "soy_sauce", "sesame_oil", "oyster_sauce", "chili_sauce"}
)


def _load_all_dishes(db: Session | None) -> list[dict[str, Any]]:
    return load_templates(db) if db is not None else []


def expand_ingredient_terms(terms: list[str] | None) -> set[str]:
    """The ingredient ids a stated exclusion really covers.

    The shopper says an ingredient in one spelling and the catalog declares it in
    another; the synonyms the dish search already knows are applied here too, so
    the same exclusion means the same thing on every read path.
    """
    expanded: set[str] = set()
    catalog = load_ingredient_catalog()
    for term in terms or []:
        text = str(term).strip()
        if not text:
            continue
        expanded.add(text)
        expanded.update(INGREDIENT_ALIASES.get(text, []))
        for ingredient_id, ingredient in catalog["ingredients"].items():
            if text == ingredient["name_zh"] or text in ingredient["aliases"]:
                expanded.add(ingredient_id)
                expanded.update(INGREDIENT_ALIASES.get(ingredient_id, []))
    return expanded


def _declares_excluded(dish: dict[str, Any], excluded: set[str]) -> bool:
    """Whether a dish needs something the shopper ruled out.

    Required, optional and pantry items are all checked: a pantry item is still
    an ingredient the plan would buy.
    """
    if not excluded:
        return False
    declared: set[str] = set()
    for key in ("required_items", "optional_items", "pantry_items"):
        for item in dish.get(key) or []:
            if isinstance(item, str):
                declared.add(item)
            elif isinstance(item, dict) and item.get("ingredient_id"):
                declared.add(str(item["ingredient_id"]))
    return bool(declared & excluded)


class _SnapshotCatalog:
    """``CatalogService.get_candidates`` served from one prefetched snapshot.

    ``suggest_buildable_dishes`` walks the whole dish catalogue, and resolving
    each ingredient through the real catalog re-reads products and offers every
    time — the scan costs O(dishes × ingredients) queries. The snapshot is built
    once from ``CatalogService.list_sellable_products``, so it carries exactly
    the rows the per-ingredient query would return, under the same approved /
    non-quarantined / sellable rules. Only *where the candidates come from*
    changes: ``_pick_sku`` and ``_pack_qty`` still decide what is bought.

    It is scoped to that one scan and never outlives it.
    """

    def __init__(self, products: list[dict[str, Any]], service: Any):
        self._service = service
        # ``get_candidates`` orders by sku_id. Keeping the same order means an
        # equal-priced tie still resolves to the SKU it resolved to before.
        self._products = sorted(products, key=lambda p: str(p.get("sku_id") or ""))

    def __getattr__(self, name: str) -> Any:
        # Anything other than ``get_candidates`` belongs to the real service.
        return getattr(self._service, name)

    def get_candidates(
        self,
        *,
        ingredient_ids: list[str] | None = None,
        product_type: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        wanted = {str(i) for i in ingredient_ids or []}
        items: list[dict[str, Any]] = []
        for item in self._products:
            if wanted and not wanted.intersection(item.get("ingredient_ids") or []):
                continue
            if product_type and (item.get("product_type") or None) != product_type:
                continue
            if product_type == "flour" and item.get("product_type") == "leavening":
                continue
            items.append(item)
            if len(items) >= max_results:
                break
        return items


class TemplatePlanService:
    def __init__(
        self,
        db: Session,
        store_id: str = "store-demo-01",
        delivery_zone_id: str = "zone-default",
    ):
        self.db = db
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.catalog = CatalogService(db, store_id)
        self.validator = PlanValidator(db, store_id, delivery_zone_id)
        #: Set by ``suggest_buildable_dishes`` when it stopped early. Reported to
        #: the caller so an incomplete scan is never read as "there is nothing".
        self.last_suggest_scan_exhausted = False

    def _resolve_ids(self, ingredient_id: str) -> list[str]:
        return INGREDIENT_ALIASES.get(ingredient_id, [ingredient_id])

    def _pick_sku(
        self,
        candidates: list[dict[str, Any]],
        *,
        product_type: str | None = None,
        needed: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        pool = [c for c in candidates if c.get("sellable")]
        if product_type:
            typed = [c for c in pool if c.get("product_type") == product_type]
            if typed:
                pool = typed
            elif product_type == "flour":
                pool = [c for c in pool if c.get("product_type") != "leavening"]
        purchase = self._pick_packs(pool, needed)
        if purchase:
            return purchase[0][0]
        root = get_settings().root_dir
        in_stock = [c for c in pool if int(c.get("available_qty") or 0) > 0]
        if in_stock:
            # Never report the whole store as out of stock while a sellable SKU
            # with stock exists: prefer what can actually be bought.
            pool = in_stock
        if self.store_id.startswith("store-demo"):
            demo_raster = [
                c
                for c in pool
                if str(c.get("sku_id", "")).startswith("demo:")
                and is_raster_image_path(c.get("image_path"), root)
            ]
            if demo_raster:
                pool = demo_raster
            else:
                source_raster = [
                    c for c in pool if is_raster_image_path(c.get("image_path"), root)
                ]
                if source_raster:
                    pool = source_raster
        if not pool:
            return None
        return min(
            pool,
            key=lambda c: (c.get("price_fen") is None, c.get("price_fen") or 999999),
        )

    def _pick_packs(
        self, candidates: list[dict[str, Any]], needed: dict[str, Any] | None,
    ) -> list[tuple[dict[str, Any], int]]:
        """Compare one SKU and two-SKU combinations for one ingredient."""
        amount, unit = contract.amount_from_needed(needed)
        if amount is None:
            return []
        required_amount = math.ceil(amount) if unit == "pc" else amount
        packable = []
        options = []
        for sku in sorted(candidates, key=lambda item: item["sku_id"]):
            spec_unit = sku.get("spec_unit")
            if (not sku["sellable"] or sku.get("spec_quantity") is None
                    or sku.get("price_fen") is None
                    or {"kg": "g", "l": "ml"}.get(spec_unit, spec_unit) != unit):
                continue
            pack_amount = sku["spec_quantity"] * UNIT_TO_GRAMS[spec_unit]
            stock = min(99, int(sku.get("available_qty") or 0))
            quantity = math.ceil(required_amount / pack_amount)
            packable.append((sku, pack_amount, stock))
            if quantity <= stock:
                options.append((sku["price_fen"] * quantity,
                                pack_amount * quantity - required_amount, [(sku, quantity)]))
        for (first, first_amount, first_stock), (second, second_amount, second_stock) in combinations(packable, 2):
            for first_qty in range(1, min(first_stock, math.ceil(required_amount / first_amount)) + 1):
                remaining = required_amount - first_qty * first_amount
                if remaining <= 0:
                    continue
                second_qty = math.ceil(remaining / second_amount)
                if second_qty <= second_stock:
                    options.append((first["price_fen"] * first_qty + second["price_fen"] * second_qty,
                                    first_amount * first_qty + second_amount * second_qty - required_amount,
                                    [(first, first_qty), (second, second_qty)]))
        if not options:
            return []
        cheapest = min(price for price, _, _ in options)
        near = [option for option in options if option[0] * 100 <= cheapest * 105]
        return min(near, key=lambda option: (
            option[1], option[0], tuple((sku["sku_id"], qty) for sku, qty in option[2]),
        ))[2]

    def _pack_qty(self, sku: dict[str, Any], needed: dict[str, Any]) -> int | None:
        spec_qty = sku.get("spec_quantity")
        spec_unit = sku.get("spec_unit")
        if spec_qty is None or not spec_unit:
            return 1
        needed_g = needed.get("quantity_g")
        needed_pc = needed.get("quantity_pc")
        needed_ml = needed.get("quantity_ml")
        if spec_unit == "pc" and needed_pc:
            return max(1, math.ceil(float(needed_pc) / float(spec_qty)))
        if spec_unit in ("g", "kg") and needed_g:
            grams_per_unit = float(spec_qty) * UNIT_TO_GRAMS.get(spec_unit, 1.0)
            return max(1, math.ceil(float(needed_g) / grams_per_unit))
        if spec_unit in ("ml", "l") and needed_ml:
            ml_per_unit = float(spec_qty) * UNIT_TO_GRAMS.get(spec_unit, 1.0)
            return max(1, math.ceil(float(needed_ml) / ml_per_unit))
        return None

    def _pantry_needed(self, ingredient_id: str) -> dict[str, Any]:
        if ingredient_id in LIQUID_PANTRY:
            return {"ingredient_id": ingredient_id, "quantity_ml": 30}
        return {"ingredient_id": ingredient_id, "quantity_g": 50}

    def resolve_sku_for_ingredient(
        self,
        ingredient_id: str,
        *,
        needed: dict[str, Any] | None = None,
        product_type: str | None = None,
    ) -> dict[str, Any] | None:
        candidates = self.catalog.get_candidates(
            ingredient_ids=self._resolve_ids(ingredient_id), product_type=product_type, max_results=50,
        )
        return self._pick_sku(candidates, product_type=product_type, needed=needed)

    def _append_item(
        self,
        plan_items: list[dict[str, Any]],
        candidate_ids: list[str],
        seen_skus: set[str],
        ingredient_id: str,
        needed: dict[str, Any],
        *,
        role: str,
        target_kind: str,
        target_id: str,
        source_kind: str = "local_recipe",
        ctx: ValidationContext | None = None,
    ) -> str:
        """Append one requirement's SKU; report why it could not be appended.

        Returns ``added`` / ``missing`` / ``unknown``:

        * ``missing``  — no sellable SKU was found for the ingredient;
        * ``unknown``  — a SKU exists but its pack size cannot be read against the
          stated amount, so no honest pack count exists.

        The row carries the requirement it covers and whether the pack count came
        from a real catalog spec or from the one-pack fallback, so a partial plan
        stays explainable.
        """
        ptype = "flour" if ingredient_id == "flour" else None
        candidates = self.catalog.get_candidates(
            ingredient_ids=self._resolve_ids(ingredient_id), product_type=ptype, max_results=50,
        )
        allowed = candidates if ctx is None else [c for c in candidates if ctx.product_allowed(c)]
        purchase = self._pick_packs(allowed, needed)
        if not purchase:
            # If none satisfy the condition, existing validation explains the refusal.
            sku = self._pick_sku(allowed or candidates, product_type=ptype)
            if not sku:
                return "missing"
            qty = self._pack_qty(sku, needed)
            if qty is None:
                return "unknown"
            # Keep the existing honest partial/unknown supply path.
            purchase = [(sku, qty)]
        amount, unit = contract.amount_from_needed(needed)
        remaining = amount
        for sku, qty in purchase:
            if sku["sku_id"] in seen_skus:
                continue
            source = {"kind": source_kind, "ref": target_id}
            allocation = amount
            if len(purchase) > 1:
                allocation = min(remaining, qty * sku["spec_quantity"] * UNIT_TO_GRAMS[sku["spec_unit"]])
                remaining -= allocation
                source.update(original_quantity=amount, original_unit=unit)
            requirement = contract.make_requirement(
                target_kind=target_kind, target_id=target_id, key=ingredient_id,
                role=role, name=ingredient_name_zh(ingredient_id), ingredient_id=ingredient_id,
                quantity=allocation, unit=unit, source=source,
            )
            seen_skus.add(sku["sku_id"])
            candidate_ids.append(sku["sku_id"])
            plan_items.append({
                "sku_id": sku["sku_id"],
                "quantity": qty,
                "role": role,
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "catalog_spec"
                if sku.get("spec_quantity") is not None and sku.get("spec_unit")
                else "assumed_one",
            })
        return "added"

    def build_plan(
        self, dish: dict[str, Any], people: int, ctx: ValidationContext | None = None,
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        """Build the resolvable rows plus the requirements this store could not serve.

        The third element is no longer a bare list of ingredient ids: every entry
        carries the requirement evidence (name, stated amount/unit, source) so the
        caller can produce a structured gap instead of losing it.
        """
        dish_id = str(dish.get("dish_id") or dish.get("template_id") or "")
        base_people = dish.get("base_people") or 2
        scaled_required = merge_items(
            scale_items(dish.get("required_items", []), base_people, people)
        )
        scaled_optional = merge_items(
            scale_items(dish.get("optional_items", []), base_people, people)
        )
        plan_items: list[dict[str, Any]] = []
        candidate_ids: list[str] = []
        missing: list[dict[str, Any]] = []
        seen_skus: set[str] = set()

        def note_missing(needed: dict[str, Any], status: str) -> None:
            ingredient_id = str(needed.get("ingredient_id") or "")
            if not ingredient_id:
                return
            amount, unit = contract.amount_from_needed(needed)
            unresolved = status == "unknown"
            missing.append(
                {
                    "kind": "unknown" if unresolved else "not_found",
                    "unknown_of": "quantity" if unresolved else None,
                    "group_id": f"dish:{dish_id}",
                    "target_kind": "dish",
                    "target_id": dish_id,
                    "requiredness": contract.CORE,
                    "required_item_id": contract.requirement_id(
                        "dish", dish_id, ingredient_id
                    ),
                    "ingredient_id": ingredient_id,
                    "name": ingredient_name_zh(ingredient_id),
                    "required_quantity": amount,
                    "unit": unit,
                    "quantity_known": amount is not None,
                    "source": {"kind": "local_recipe", "ref": dish_id},
                }
            )

        for item in scaled_required:
            ing = item["ingredient_id"]
            status = self._append_item(
                plan_items,
                candidate_ids,
                seen_skus,
                ing,
                item,
                role="required",
                target_kind="dish",
                target_id=dish_id,
                ctx=ctx,
            )
            if status != "added":
                note_missing(item, status)

        for item in scaled_optional:
            ing = item["ingredient_id"]
            self._append_item(
                plan_items,
                candidate_ids,
                seen_skus,
                ing,
                item,
                role="pantry",
                target_kind="dish",
                target_id=dish_id,
                ctx=ctx,
            )

        for raw in dish.get("pantry_items") or []:
            ing = raw if isinstance(raw, str) else raw.get("ingredient_id")
            if not ing:
                continue
            needed = raw if isinstance(raw, dict) else self._pantry_needed(ing)
            self._append_item(
                plan_items,
                candidate_ids,
                seen_skus,
                ing,
                needed,
                role="pantry",
                target_kind="dish",
                target_id=dish_id,
                ctx=ctx,
            )

        return plan_items, candidate_ids, missing

    def suggest_buildable_dishes(
        self,
        *,
        limit: int = 3,
        scan: int | None = None,
        people: int = 2,
        deadline_expired: Any = None,
        excluded_ingredients: list[str] | None = None,
        excluded_dish_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Dishes this store can resolve into a plan right now.

        Used for the single clarifying question when the user has no idea what to
        eat, and for the open recommendation. The list is built against the live
        catalog — it is never a hard-coded menu, and a dish whose ingredients
        cannot be resolved to sellable SKUs is never offered.

        What this does **not** claim: the plan builder tolerates inferred
        mappings and default pack sizes, so "a plan could be generated" is a
        weaker statement than "this is fulfillable at this price". Stock, pack
        size and the turn's budget are not verified here, and callers must say so
        rather than report the result as配齐.

        ``scan`` bounds the work. It defaults to ``None`` — walk everything —
        because the previous default of 20 silently looked at only the first 20
        dishes of the fixture: a blind spot, not a budget. The catalog is read
        **once** for the whole scan and reused, so a full walk does not cost a
        query per ingredient. When the caller's deadline runs out, or ``scan``
        cuts the walk short, ``last_suggest_scan_exhausted`` is set so the result
        is reported as incomplete instead of as "nothing exists".
        """
        suggestions: list[dict[str, Any]] = []
        self.last_suggest_scan_exhausted = False
        excluded = expand_ingredient_terms(excluded_ingredients)
        catalog = self.catalog
        self.catalog = _SnapshotCatalog(catalog.list_sellable_products(), catalog)
        try:
            for dish in _load_all_dishes(self.db):
                if str(dish.get("dish_id") or dish.get("template_id")) in (excluded_dish_ids or set()):
                    continue
                if len(suggestions) >= limit:
                    break
                if deadline_expired is not None and deadline_expired():
                    self.last_suggest_scan_exhausted = True
                    break
                if scan is not None:
                    if scan <= 0:
                        self.last_suggest_scan_exhausted = True
                        break
                    scan -= 1
                if _declares_excluded(dish, excluded):
                    # Exploring is not a reason to offer a dish the shopper
                    # already ruled out.
                    continue
                items, _candidate_ids, missing = self.build_plan(dish, people)
                if missing or not any(i.get("role") == "required" for i in items):
                    continue
                suggestions.append(
                    {
                        "dish_id": dish.get("dish_id") or dish.get("template_id"),
                        "name": dish_display_name(dish),
                        "main_ingredients": [
                            item.get("ingredient_id")
                            for item in dish.get("required_items") or []
                            if item.get("ingredient_id")
                        ][:4],
                    }
                )
        finally:
            # The adapter never outlives the scan: every later caller gets the
            # real catalog back, whether the walk finished or raised.
            self.catalog = catalog
        return suggestions

    def validate_template_plan(
        self,
        dish: dict[str, Any],
        people: int,
        budget_fen: int | None = None,
        ctx: ValidationContext | None = None,
    ) -> dict[str, Any]:
        dish_id = str(dish.get("dish_id") or dish.get("template_id") or "")
        if ctx is None:
            from app.agent.state import Requirements

            ctx = ValidationContext.from_requirements(
                Requirements(people=people, budget_fen=budget_fen),
                store_id=self.store_id,
                delivery_zone_id=self.delivery_zone_id,
                active_template_id=dish.get("dish_id"),
            )
        plan_items, candidate_ids, missing_required = self.build_plan(dish, people, ctx)
        # A missing ingredient is a *gap*, not a reason to throw the whole dish
        # away: D2/D3 keep the resolvable rows and report what cannot be served.
        return self.validator.validate_plan(
            plan_items,
            candidate_ids,
            budget_fen=budget_fen,
            mode="bundle",
            people=people,
            ctx=ctx,
            coverage_intent=contract.GENERATION_INTENT,
            missing_required_items=missing_required,
            target_context={
                "group_id": f"dish:{dish_id}",
                "target_kind": "dish",
                "target_id": dish_id,
            },
        )
