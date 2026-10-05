"""Deterministic shopping plan building for product / scenario targets.

Three target kinds share one plan shape:

* ``dish``     — a real recipe from ``chinese-dishes-v1`` (see TemplatePlanService)
* ``product``  — a direct product request resolved against the store catalog
* ``scenario`` — an open shopping situation (e.g. 火锅) defined in reviewable data

This module owns the parts the model must never invent: which SKUs exist, how
many packs are needed, which group a row belongs to, and how an incremental
request merges into the plan the user is already editing.

Money stays integer fen throughout. Yuan conversion happens only at the model
and UI boundaries.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services import plan_contract as contract
from app.services.catalog_service import CatalogService, product_to_dict
from app.services.image_assets import is_raster_image_path
from app.services.offer_service import OfferService
from app.services.plan_validator import PlanValidator
from app.services.validation_context import ValidationContext

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_PATH = ROOT / "data" / "fixtures" / "shopping-scenarios.json"

UNIT_TO_GRAMS: dict[str, float] = {"g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0, "pc": 1.0}

#: Rows that exist because a scenario lists them but that the shopper did not ask
#: to add by default. They are freely selectable and never block confirmation.
ROLE_OPTIONAL = "optional"
ROLE_REQUIRED = "required"


def _row_group_ids_for_rows(rows: list[dict[str, Any]]) -> set[str]:
    """Return every target group represented by preserved bought rows."""
    groups: set[str] = set()
    for row in rows:
        group_id = str(row.get("group_id") or "")
        if group_id:
            groups.add(group_id)
        for contribution in row.get("contributions") or []:
            if isinstance(contribution, dict) and contribution.get("group_id"):
                groups.add(str(contribution["group_id"]))
    return groups


@lru_cache(maxsize=1)
def load_scenarios() -> list[dict[str, Any]]:
    data = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    return list(data.get("scenarios", []))


def get_scenario(scenario_id: str | None) -> dict[str, Any] | None:
    if not scenario_id:
        return None
    for scenario in load_scenarios():
        if scenario.get("scenario_id") == scenario_id:
            return scenario
    return None


def group_id_for(target_kind: str, target_id: str) -> str:
    """Stable group key: the same target always upserts the same group."""
    return f"{target_kind}:{target_id}"


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower().replace(" ", "")


def match_scenario(text: str | None) -> dict[str, Any] | None:
    """Longest scenario name/alias contained in the user text."""
    normalized = _normalize(text)
    if not normalized:
        return None
    best: dict[str, Any] | None = None
    best_len = 0
    for scenario in load_scenarios():
        for label in [scenario.get("name") or "", *(scenario.get("aliases") or [])]:
            label_norm = _normalize(label)
            if label_norm and label_norm in normalized and len(label_norm) > best_len:
                best = scenario
                best_len = len(label_norm)
    return best


def _packs_for(sku: dict[str, Any], needed: dict[str, float]) -> int | None:
    spec_qty = sku.get("spec_quantity")
    spec_unit = sku.get("spec_unit")
    if spec_qty is None or not spec_unit:
        return 1
    per_unit = float(spec_qty) * UNIT_TO_GRAMS.get(str(spec_unit), 1.0)
    if per_unit <= 0:
        return 1
    for key, unit_family in (
        ("quantity_pc", "pc"),
        ("quantity_ml", "ml"),
        ("quantity_g", "g"),
    ):
        wanted = needed.get(key)
        if not wanted:
            continue
        if unit_family == "pc" and str(spec_unit) != "pc":
            continue
        if unit_family == "ml" and str(spec_unit) not in ("ml", "l"):
            continue
        if unit_family == "g" and str(spec_unit) not in ("g", "kg"):
            continue
        return max(1, math.ceil(float(wanted) / per_unit))
    return 1


class ShoppingPlanService:
    """Builds and merges product/scenario plans. Pure business logic, no model."""

    def __init__(self, db: Session, store_id: str = "store-demo-01", delivery_zone_id: str = "zone-default"):
        self.db = db
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.catalog = CatalogService(db, store_id)
        self.offers = OfferService(db, store_id)
        self.validator = PlanValidator(db, store_id, delivery_zone_id)

    # ----------------------------------------------------------- product targets

    def find_product_candidates(self, term: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        """Sellable products matching ``term``.

        ``usage_tags`` is matched as a *set*: exact tag membership only, never a
        substring, so a tag can never be matched by accident. Chinese/English
        product names are matched by containment, which is a different (and
        explicit) signal: the shopper's term appears in the product's own name.
        """
        normalized = _normalize(term)
        if not normalized:
            return []
        results: list[dict[str, Any]] = []
        for item in self._sellable_products():
            tags = {_normalize(t) for t in item.get("usage_tags") or []}
            names = [_normalize(item.get("name_zh")), _normalize(item.get("name"))]
            tag_hit = normalized in tags
            name_hit = any(name and normalized in name for name in names)
            if not tag_hit and not name_hit:
                continue
            score = 2 if tag_hit else 0
            if any(name and normalized == name for name in names):
                score += 1
            results.append({**item, "_match_score": score})
        results.sort(
            key=lambda item: (
                -int(item.get("_match_score") or 0),
                item.get("price_fen") is None,
                item.get("price_fen") or 999999,
            )
        )
        return results[:max_results]

    def _sellable_products(self) -> list[dict[str, Any]]:
        return self.catalog.list_sellable_products(store_id=self.store_id)

    def build_product_plan(
        self,
        target_name: str,
        *,
        target_id: str | None = None,
        quantity: int = 1,
        budget_fen: int | None = None,
        excluded_ingredients: list[str] | None = None,
    ) -> dict[str, Any]:
        if target_id:
            sku = self.catalog.get_product(target_id)
            candidates = [sku] if sku and sku.get("sellable") else []
        else:
            candidates = self.find_product_candidates(target_name)
        if not candidates:
            return {
                "status": "error",
                "code": "NO_MATCH",
                "message": f"本店没有找到与「{target_name}」匹配的在售商品。",
                "missing": [target_name],
            }
        best_score = candidates[0].get("_match_score")
        tied = [c for c in candidates if c.get("_match_score") == best_score]
        if not target_id and len(tied) > 1:
            # Real, sellable candidates only — never an invented list.
            return {
                "status": "error",
                "code": "AMBIGUOUS_PRODUCT",
                "message": "本店有多个相似商品，请确认要哪一个。",
                "candidates": [
                    {"sku_id": c["sku_id"], "name": c.get("name_zh") or c.get("name")}
                    for c in tied[:5]
                ],
            }
        sku = candidates[0]
        target_id = str(sku["sku_id"])
        target_name = str(sku.get("name_zh") or sku.get("name") or target_name)
        wanted = max(1, int(quantity))
        # A direct product is counted by the shopper, not by pack math: the
        # requirement is "N packs", so it is never an assumed pack size.
        requirement = contract.make_requirement(
            target_kind="product",
            target_id=target_id,
            key=target_id,
            role=ROLE_REQUIRED,
            name=target_name,
            quantity=wanted,
            unit="件",
            source={"kind": "user", "ref": target_name},
        )
        plan_items = [
            {
                "sku_id": target_id,
                "quantity": wanted,
                "role": ROLE_REQUIRED,
                "required_item_id": requirement["required_item_id"],
                "requirement": requirement,
                "pack_source": "catalog_spec",
            }
        ]
        return self._validate_target(
            target_kind="product",
            target_id=target_id,
            target_name=target_name,
            plan_items=plan_items,
            candidate_ids=[target_id],
            budget_fen=budget_fen,
            excluded_ingredients=excluded_ingredients,
            # A direct product has no headcount at all: it is never reported as
            # "what the user said about people".
            people=None,
            people_source="default",
        )

    # ---------------------------------------------------------- scenario targets

    def build_scenario_plan(
        self,
        scenario_id: str,
        *,
        people: int | None = None,
        budget_fen: int | None = None,
        excluded_ingredients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build an open-scenario basket.

        A scenario is *freely shopped*, never forced: every row is ``optional``, so
        the shopper may drop the base, the staple or anything else without
        blocking the rest of the basket. A component this store cannot supply is
        reported as a suggestion instead of failing the whole plan.

        Every row is recalled through the scenario's own ``components`` and
        ``common_tags``. There is no variant/style dimension: the same generic
        basket is what the shopper asked for, and a specific hotpot style is a
        dish of its own (see ``chinese-dishes-v1``).
        """
        scenario = get_scenario(scenario_id)
        if scenario is None:
            return {
                "status": "error",
                "code": "UNKNOWN_SCENARIO",
                "message": f"未收录的采购场景: {scenario_id}",
            }
        people_source = "user" if people is not None else "default"
        people = int(people or scenario.get("base_people") or 4)
        common_tags = {_normalize(t) for t in scenario.get("common_tags") or []}

        plan_items: list[dict[str, Any]] = []
        candidate_ids: list[str] = []
        missing_required: list[dict[str, Any]] = []
        seen: set[str] = set()
        pool = self._sellable_products()

        for component in scenario.get("components") or []:
            component_tags = {_normalize(t) for t in component.get("any_tags") or []}
            component_ingredients = set(component.get("ingredient_ids") or [])
            matched = [
                item
                for item in pool
                if self._component_matches(item, component_tags, component_ingredients, common_tags)
            ]
            if not matched:
                # Open shopping: never fail the basket for one missing component;
                # report it as a real gap instead.
                component_key = str(
                    component.get("component_id") or component.get("name") or "component"
                )
                missing_required.append(
                    {
                        "kind": "not_found",
                        "group_id": f"scenario:{scenario_id}",
                        "target_kind": "scenario",
                        "target_id": scenario_id,
                        "requiredness": contract.OPTIONAL,
                        "required_item_id": contract.requirement_id(
                            "scenario", scenario_id, component_key
                        ),
                        "component_id": component.get("component_id"),
                        "name": component.get("name"),
                        "source": {"kind": "scenario", "ref": scenario_id},
                    }
                )
                continue
            matched.sort(
                key=lambda item: (
                    # prefer a real photo over a declared placeholder, then price
                    not is_raster_image_path(item.get("image_path"), get_settings().root_dir),
                    item.get("price_fen") is None,
                    item.get("price_fen") or 999999,
                )
            )
            sku = matched[0]
            sku_id = str(sku["sku_id"])
            if sku_id in seen:
                continue
            quantity = self._component_quantity(component, sku, people)
            if quantity is None:
                continue
            seen.add(sku_id)
            amount, unit = self._component_need(component, people)
            requirement = contract.make_requirement(
                target_kind="scenario",
                target_id=scenario_id,
                key=str(component.get("component_id") or sku_id),
                role=ROLE_OPTIONAL,
                name=str(
                    component.get("name") or sku.get("name_zh") or sku.get("name") or ""
                ),
                component_id=component.get("component_id"),
                quantity=amount,
                unit=unit,
                source={"kind": "scenario", "ref": scenario_id},
            )
            spec_known = sku.get("spec_quantity") is not None and bool(sku.get("spec_unit"))
            plan_items.append(
                {
                    "sku_id": sku_id,
                    "quantity": quantity,
                    "role": ROLE_OPTIONAL,
                    "selected": bool(component.get("default_selected")),
                    "component_id": component.get("component_id"),
                    "component_name": component.get("name"),
                    "required_item_id": requirement["required_item_id"],
                    "requirement": requirement,
                    "pack_source": "catalog_spec" if spec_known else "assumed_one",
                }
            )
            candidate_ids.append(sku_id)

        if not plan_items:
            # Nothing at all is buyable: keep the reason (and every gap) instead
            # of returning a silent empty failure.
            return {
                "status": "error",
                "code": "SUPPLY_UNAVAILABLE",
                "message": "本店暂时没有可用于该场景的在售商品。",
                "missing": [str(scenario.get("name"))],
                "gaps": [
                    gap
                    for gap in (
                        contract.normalize_carried_gap(entry) for entry in missing_required
                    )
                    if gap is not None
                ],
            }
        label = scenario.get("name") or scenario_id
        result = self._validate_target(
            target_kind="scenario",
            target_id=scenario_id,
            target_name=str(label),
            plan_items=plan_items,
            candidate_ids=candidate_ids,
            budget_fen=budget_fen,
            excluded_ingredients=excluded_ingredients,
            people=people,
            people_source=people_source,
            missing_required_items=missing_required,
        )
        if result.get("status") == "ok":
            # ``missing_components`` / ``unavailable_items`` stay as compatibility
            # projections of the one gap list: they are derived here, never
            # computed a second time.
            result_gaps = [gap for gap in result.get("gaps") or [] if isinstance(gap, dict)]
            result["missing_components"] = [
                {"component_id": gap.get("component_id"), "name": gap.get("name")}
                for gap in result_gaps
                if gap.get("kind") == "not_found" and gap.get("component_id")
            ]
            result["unavailable_items"] = [
                {"sku_id": gap.get("sku_id"), "name": gap.get("name")}
                for gap in result_gaps
                if gap.get("kind") in ("out_of_stock", "insufficient_stock")
                and gap.get("sku_id")
            ]
        return result

    @staticmethod
    def _component_matches(
        item: dict[str, Any],
        component_tags: set[str],
        component_ingredients: set[str],
        common_tags: set[str],
    ) -> bool:
        tags = {_normalize(t) for t in item.get("usage_tags") or []}
        if not tags & common_tags:
            return False
        if component_tags and tags & component_tags:
            return True
        if component_ingredients and set(item.get("ingredient_ids") or []) & component_ingredients:
            return True
        return False

    @staticmethod
    def _component_need(
        component: dict[str, Any],
        people: int,
    ) -> tuple[float | None, str | None]:
        """The stated component amount in its own unit (``None`` when unstated)."""
        if component.get("per_people_g"):
            return float(component["per_people_g"]) * people, "g"
        if component.get("per_people_ml"):
            return float(component["per_people_ml"]) * people, "ml"
        if component.get("per_people_pc"):
            return float(component["per_people_pc"]) * people, "pc"
        if component.get("package_quantity"):
            return float(component["package_quantity"]), "件"
        return None, None

    @staticmethod
    def _component_quantity(
        component: dict[str, Any],
        sku: dict[str, Any],
        people: int,
    ) -> int | None:
        if component.get("package_quantity"):
            return max(1, int(component["package_quantity"]))
        needed: dict[str, float] = {}
        if component.get("per_people_g"):
            needed["quantity_g"] = float(component["per_people_g"]) * people
        if component.get("per_people_ml"):
            needed["quantity_ml"] = float(component["per_people_ml"]) * people
        if component.get("per_people_pc"):
            needed["quantity_pc"] = float(component["per_people_pc"]) * people
        if not needed:
            return 1
        return _packs_for(sku, needed)

    # ------------------------------------------------------------------ validate

    def _validate_target(
        self,
        *,
        target_kind: str,
        target_id: str,
        target_name: str,
        plan_items: list[dict[str, Any]],
        candidate_ids: list[str],
        budget_fen: int | None,
        excluded_ingredients: list[str] | None,
        people: int | None = None,
        people_source: str = "default",
        missing_required_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from app.agent.state import Requirements

        requirements = Requirements(
            people=people,
            budget_fen=budget_fen,
            excluded_ingredients=list(excluded_ingredients or []),
            goal=target_name,
        )
        ctx = ValidationContext.from_requirements(
            requirements,
            store_id=self.store_id,
            delivery_zone_id=self.delivery_zone_id,
            active_template_id=None,
        )
        validated = self.validator.validate_plan(
            plan_items,
            candidate_ids,
            budget_fen=budget_fen,
            mode="bundle",
            people=people,
            excluded_ingredients=list(excluded_ingredients or []),
            ctx=ctx,
            # P0: build a partial draft by default and never lose the gap.
            coverage_intent=contract.GENERATION_INTENT,
            missing_required_items=missing_required_items,
            target_context={
                "group_id": group_id_for(target_kind, target_id),
                "target_kind": target_kind,
                "target_id": target_id,
            },
        )
        if validated.get("validation_status") != "passed":
            errors = validated.get("errors") or ["validation failed"]
            code = "VALIDATION_FAILED"
            if budget_fen is not None and any(
                "budget" in err.lower() or "预算" in err for err in errors
            ):
                code = "BUDGET_EXCEEDED"
            return {
                "status": "error",
                "code": code,
                "message": "; ".join(errors),
                "validation_status": validated.get("validation_status"),
                "missing": [],
                "gaps": validated.get("gaps", []),
            }

        group_id = group_id_for(target_kind, target_id)
        items = []
        for item in validated.get("items", []):
            row = dict(item)
            row["group_id"] = group_id
            row["target_kind"] = target_kind
            row["target_id"] = target_id
            if not row.get("selected", item.get("role") != "pantry"):
                row["selected"] = bool(item.get("selected", item.get("role") != "pantry"))
            items.append(row)
        return {
            "status": "ok",
            "plan_id": validated["plan_id"],
            "plan_version": validated["plan_version"],
            "items": items,
            "total_price_fen": validated["total_price_fen"],
            "selected_total_fen": validated.get("selected_total_fen"),
            "missing": [],
            "validation_status": validated.get("validation_status"),
            "can_confirm": validated.get("can_confirm", True),
            "mode": validated.get("mode"),
            "coverage_mode": validated.get("coverage_mode"),
            "coverage_intent": validated.get("coverage_intent"),
            "uncovered_items": validated.get("uncovered_items", []),
            "gaps": validated.get("gaps", []),
            "expires_at": validated.get("expires_at"),
            "target_kind": target_kind,
            "target_id": target_id,
            "group_id": group_id,
            "target": {
                "group_id": group_id,
                "kind": target_kind,
                "target_id": target_id,
                "name": target_name,
                "people": people,
                "people_source": people_source,
            },
        }

    # --------------------------------------------------------------------- merge

    def merge_plan(
        self,
        base_plan: dict[str, Any] | None,
        new_plan: dict[str, Any],
        *,
        group_id: str,
        operation: str,
        cart_quantities: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Merge ``new_plan`` into ``base_plan`` without losing the user's edits.

        * ``replace`` — the previous plan is dropped entirely.
        * ``append``  — the target group is upserted, every other group keeps its
          own contribution, so previously ticked rows and hand-edited quantities
          survive.
        * ``resize``  — same group upsert; the *builder* recomputed the target
          group's quantities from the new headcount, and unrelated groups (a
          drink, another dish) are deliberately not rescaled.

        Rows are collapsed by SKU through the *per-target contribution* map, not
        through the already-collapsed total: re-appending a target replaces that
        target's own contribution instead of adding the whole plan again.

        A quantity the shopper typed themselves is an explicit decision. It is
        kept as-is when another target is appended, while the data-backed
        recommendation keeps accumulating in ``recommended_quantity`` so the
        original suggestion stays explainable.

        Compatible recipe amounts are combined before rounding to whole packs;
        direct product quantities remain additional, explicit pack counts.
        """
        new_rows = [dict(item) for item in new_plan.get("items") or []]
        for row in new_rows:
            row["group_id"] = group_id
        target = dict(new_plan.get("target") or {})
        target["group_id"] = group_id
        if new_plan.get("target_notes"):
            target["notes"] = [str(note) for note in new_plan["target_notes"]]

        base = base_plan or {}
        # A switch builds the new goal on its own: the previous goal's gaps and
        # its coverage intent belong to a plan that no longer describes what the
        # shopper asked for, so they are not carried into the new one. The new
        # plan's *own* gaps are a different thing: they were computed against the
        # rows that are about to be stored, so they are always carried — a fresh
        # or replaced plan that drops them would read "full" while its own rows
        # prove the opposite.
        replacing = operation == "replace" or not base
        if not replacing:
            previous_selection = {row["sku_id"]: row["selected"] for row in base["items"]}
            for row in new_rows:
                if row["sku_id"] in previous_selection:
                    row["selected"] = previous_selection[row["sku_id"]]
        carried_gaps = (
            [] if replacing else self._strip_group_gaps(base.get("gaps"), group_id)
        )
        if operation != "remove":
            gap_context = {
                "group_id": group_id,
                "target_kind": str(target.get("kind") or new_plan.get("target_kind") or ""),
                "target_id": str(target.get("target_id") or new_plan.get("target_id") or ""),
            }
            for gap in new_plan.get("gaps") or []:
                normalized = contract.normalize_carried_gap(gap, target_context=gap_context)
                if normalized is not None:
                    carried_gaps.append(normalized)
        coverage_intent = contract.normalize_intent(
            new_plan.get("coverage_intent")
            if (new_plan.get("coverage_intent") or replacing)
            else base.get("coverage_intent")
        )
        preserved_overrides: dict[str, int] = {}
        if operation == "remove":
            # Drop exactly one target group. Every other group keeps its own
            # contribution, its hand-edited quantity and its added ledger; no new
            # target is appended, and a group that is not in the plan is a no-op
            # (the content signature below then keeps the version).
            kept_rows = []
            for row in base.get("items") or []:
                stripped = self._strip_group(row, group_id)
                if stripped is None:
                    continue
                kept_rows.append(stripped)
            targets = [
                t for t in (base.get("targets") or []) if str(t.get("group_id") or "") != group_id
            ]
            plan_id = base.get("plan_id") or new_plan.get("plan_id")
            version = int(base.get("plan_version") or 1) + 1
        elif operation == "replace" or not base:
            # A replace is a new goal, built from its own rows alone. No old row,
            # no bought-quantity ledger, no contribution and no gap is migrated:
            # the previous goal's unconfirmed plan is dropped whole. The cart and
            # the confirmation history are separate ledgers and are untouched by
            # this — a switch never edits what was already bought.
            kept_rows = []
            targets = [target]
            plan_id = new_plan.get("plan_id")
            version = int(base.get("plan_version") or 0) + 1 if base else 1
        else:
            kept_rows = []
            for row in base.get("items") or []:
                stripped = self._strip_group(row, group_id)
                if stripped is None:
                    continue
                kept_rows.append(stripped)
            # A hand-typed quantity survives even when its whole group is rebuilt.
            preserved_overrides = {
                str(row.get("sku_id")): int(row.get("quantity") or 0)
                for row in base.get("items") or []
                if row.get("quantity_source") == "user"
                and str(row.get("group_id") or "") == group_id
                and int(row.get("quantity") or 0) > 0
            }
            targets = [
                t for t in (base.get("targets") or []) if str(t.get("group_id") or "") != group_id
            ]
            targets.append(target)
            plan_id = base.get("plan_id") or new_plan.get("plan_id")
            version = int(base.get("plan_version") or 1) + 1

        items = self._collapse(
            kept_rows + new_rows,
            cart_quantities=cart_quantities,
            preserved_overrides=preserved_overrides,
            preserved_added_quantities={
                row["sku_id"]: int(row.get("added_quantity") or 0)
                for row in base.get("items") or []
            } if not replacing else {},
        )
        totals = self._totals(
            items,
            carried_gaps=carried_gaps,
            coverage_intent=coverage_intent,
        )
        selected_total = totals["selected_total_fen"]
        outstanding_total = totals["outstanding_total_fen"]
        uncovered = totals["uncovered_items"]
        coverage_mode = totals["coverage_mode"]
        can_confirm = totals["can_confirm"]

        merged = {
            "plan_id": plan_id,
            "plan_version": version,
            "mode": "bundle",
            "items": items,
            "total_price_fen": selected_total,
            "selected_total_fen": selected_total,
            # What is still outstanding for the *next* confirmation: rows already
            # bought one by one are counted out of it.
            "outstanding_total_fen": outstanding_total,
            "expires_at": new_plan.get("expires_at") or base.get("expires_at"),
            "validation_status": "passed",
            "coverage_mode": coverage_mode,
            "coverage_intent": coverage_intent,
            "uncovered_items": uncovered,
            "gaps": totals["gaps"],
            "can_confirm": can_confirm,
            "targets": targets,
            "merged_sku_contributions": [
                {"sku_id": i["sku_id"], "contributions": i.get("contributions") or []}
                for i in items
                if len(i.get("contributions") or []) > 1
            ],
        }
        if operation != "replace" and self._same_content(base, merged):
            # Re-preparing the target the plan already describes is not a new
            # plan: keeping the version lets the announced plan.ready stay the
            # authoritative one the client is already holding.
            merged["plan_version"] = int(base.get("plan_version") or version)
        return merged

    @staticmethod
    def _strip_group_gaps(
        gaps: list[dict[str, Any]] | None, group_id: str
    ) -> list[dict[str, Any]]:
        """Drop one target's gaps; the rebuilt target brings its own back."""
        return [
            gap
            for gap in gaps or []
            if isinstance(gap, dict) and str(gap.get("group_id") or "") != group_id
        ]

    @staticmethod
    def _same_content(base: dict[str, Any], merged: dict[str, Any]) -> bool:
        return ShoppingPlanService._content_signature(base) == ShoppingPlanService._content_signature(
            merged
        )

    @staticmethod
    def _content_signature(plan: dict[str, Any]) -> str:
        return json.dumps(
            {
                "items": [
                    [
                        str(item.get("sku_id")),
                        int(item.get("quantity") or 0),
                        bool(item.get("selected", True)),
                        str(item.get("role") or ""),
                        int(item.get("added_quantity") or 0),
                        str(item.get("quantity_source") or ""),
                        # Executable facts: a price or supply change must advance the
                        # version, or a confirmation could be validated against a
                        # snapshot that no longer describes the row. Volatile
                        # provenance (``evidence.quoted_at``) stays out on purpose.
                        int(item.get("unit_price_fen") or 0),
                        int(item.get("max_addable_quantity") or 0),
                        str(item.get("availability") or ""),
                        int(item.get("shortfall_quantity") or 0),
                    ]
                    for item in plan.get("items") or []
                ],
                "targets": [
                    [
                        str(target.get("group_id") or ""),
                        str(target.get("kind") or ""),
                        str(target.get("target_id") or ""),
                        str(target.get("name") or ""),
                        target.get("people"),
                        str(target.get("people_source") or ""),
                    ]
                    for target in plan.get("targets") or []
                ],
                # Coverage belongs to the content: a gap that silently appears or
                # clears must advance the version and re-announce the plan.
                "coverage_mode": str(plan.get("coverage_mode") or "full"),
                "coverage_intent": str(plan.get("coverage_intent") or ""),
                "gaps": contract.gaps_signature(plan.get("gaps")),
            },
            sort_keys=True,
        )

    @staticmethod
    def _totals(
        items: list[dict[str, Any]],
        *,
        carried_gaps: list[dict[str, Any]] | None = None,
        coverage_intent: str = contract.LEGACY_INTENT,
    ) -> dict[str, Any]:
        """The money/coverage block every plan shape shares.

        Factored out so an explicit row-quantity edit produces exactly the same
        totals as a rebuild — the two must never drift apart. Gaps are collected
        and coverage decided by the one shared rule (``plan_contract``), so a plan
        can never read ``full`` while its own rows prove a gap.
        """
        selected_total = sum(
            int(i.get("line_total_fen") or 0) for i in items if i.get("selected", True)
        )
        outstanding_total = sum(
            int(i.get("unit_price_fen") or 0)
            * max(0, int(i.get("quantity") or 1) - int(i.get("added_quantity") or 0))
            for i in items
            if i.get("selected", True)
        )
        gaps = contract.collect_gaps(carried_gaps, items)
        coverage = contract.coverage(items, gaps, coverage_intent)
        return {
            "selected_total_fen": selected_total,
            "outstanding_total_fen": outstanding_total,
            "uncovered_items": coverage["uncovered_items"],
            "over_stock": coverage["over_stock"],
            "coverage_mode": coverage["coverage_mode"],
            "coverage_intent": coverage["coverage_intent"],
            "gaps": gaps,
            "can_confirm": coverage["can_confirm"],
        }

    def apply_row_quantity(
        self,
        plan: dict[str, Any],
        sku_id: str,
        quantity: int,
        *,
        cart_quantities: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        """Set one row's pack count from an explicit, already-validated instruction.

        The row is marked ``quantity_source="user"`` so a later append keeps the
        hand-typed number, and the added ledger is left untouched: what is already
        in the cart stays accounted for in ``outstanding_total_fen``. Returns
        ``None`` when the SKU is not in this plan.
        """
        rows: list[dict[str, Any]] = []
        found = False
        for row in plan.get("items") or []:
            entry = dict(row)
            if str(entry.get("sku_id")) == str(sku_id):
                found = True
                entry["quantity"] = int(quantity)
                entry["quantity_source"] = "user"
            rows.append(entry)
        if not found:
            return None
        items = self._collapse(rows, cart_quantities=cart_quantities or {})
        totals = self._totals(
            items,
            carried_gaps=plan.get("gaps"),
            coverage_intent=plan.get("coverage_intent"),
        )
        updated = dict(plan)
        updated.update(
            {
                "items": items,
                "plan_version": int(plan.get("plan_version") or 1) + 1,
                "total_price_fen": totals["selected_total_fen"],
                "selected_total_fen": totals["selected_total_fen"],
                "outstanding_total_fen": totals["outstanding_total_fen"],
                "coverage_mode": totals["coverage_mode"],
                "coverage_intent": totals["coverage_intent"],
                "uncovered_items": totals["uncovered_items"],
                "gaps": totals["gaps"],
                "can_confirm": totals["can_confirm"],
                "merged_sku_contributions": [
                    {"sku_id": i["sku_id"], "contributions": i.get("contributions") or []}
                    for i in items
                    if len(i.get("contributions") or []) > 1
                ],
            }
        )
        return updated

    @staticmethod
    def content_signature(plan: dict[str, Any] | None) -> str:
        """Public alias: has the plan's *content* actually changed?"""
        return ShoppingPlanService._content_signature(plan or {})

    def _strip_group(self, row: dict[str, Any], group_id: str) -> dict[str, Any] | None:
        """Remove one target's contribution from a stored row.

        The rebuilt target contributes a *fresh* set of rows, so its old
        contribution must not linger. Returns ``None`` when nothing else needed
        this SKU.
        """
        contributions = self._row_contributions(row)
        if not contributions:
            return None
        if group_id not in contributions:
            return row
        remaining = [c for c in contributions.values() if c.get("group_id") != group_id]
        if not remaining:
            return None
        stripped = {k: v for k, v in row.items() if k != "contributions"}
        stripped["contributions"] = remaining
        if stripped.get("quantity_source") != "user":
            stripped["quantity"] = sum(int(c.get("quantity") or 0) for c in remaining)
        # Removing a recipe source does not undo purchases of the remaining SKU.
        return stripped

    @staticmethod
    def _data_backed_quantity(row: dict[str, Any]) -> int:
        """The pack count the catalog wanted, ignoring a hand edit.

        ``recommended_quantity`` is the requirement's own pack count *before*
        any stock/cart clamp, so it is the honest contribution even when the
        prepared quantity had to be smaller.
        """
        recommended = row.get("recommended_quantity")
        if recommended:
            return max(1, int(recommended))
        return max(1, int(row.get("quantity") or 1))

    def _row_contributions(self, row: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Per-target contributions of one *stored* row.

        A stored row records every group that needed its SKU; a row that predates
        that record (or was built by one target only) falls back to its own
        data-backed quantity, never to a hand-edited total. Each contribution also
        carries its requirement evidence, so two targets that share one SKU keep
        both identities instead of only the last one written.
        """
        recorded = row.get("contributions")
        row_level_evidence = {
            "required_item_id": row.get("required_item_id"),
            "requirement": row.get("requirement")
            if isinstance(row.get("requirement"), dict)
            else None,
        }
        if isinstance(recorded, list):
            if not recorded:
                return {}
            result: dict[str, dict[str, Any]] = {}
            sole = len(recorded) == 1
            for entry in recorded:
                key = str(entry.get("group_id") or "")
                if not key:
                    continue
                requirement = (
                    entry.get("requirement")
                    if isinstance(entry.get("requirement"), dict)
                    else None
                )
                required_item_id = entry.get("required_item_id") or (
                    requirement or {}
                ).get("required_item_id")
                if sole:
                    # A single contribution owns the row's own evidence.
                    requirement = requirement or row_level_evidence["requirement"]
                    required_item_id = (
                        required_item_id or row_level_evidence["required_item_id"]
                    )
                result[key] = {
                    "group_id": key,
                    "quantity": max(0, int(entry.get("quantity") or 0)),
                    # Selection is edited per SKU row, not per recipe source.
                    "selected": bool(row.get("selected", True)),
                    "added_quantity": int(entry.get("added_quantity") or 0),
                    "required_item_id": required_item_id,
                    "requirement": requirement,
                }
            if result:
                return result
        key = str(row.get("group_id") or "")
        return {
            key: {
                "group_id": key,
                "quantity": self._data_backed_quantity(row),
                "selected": bool(row.get("selected", True)),
                "added_quantity": int(row.get("added_quantity") or 0),
                "required_item_id": row_level_evidence["required_item_id"],
                "requirement": row_level_evidence["requirement"],
            }
        }

    def _collapse(
        self,
        rows: list[dict[str, Any]],
        *,
        cart_quantities: dict[str, int] | None = None,
        preserved_overrides: dict[str, int] | None = None,
        preserved_added_quantities: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Collapse rows by SKU while keeping every target's contribution.

        Later rows win for the same (SKU, group) pair: an upserted target
        *replaces* its own contribution instead of piling onto it.
        """
        preserved_overrides = preserved_overrides or {}
        preserved_added_quantities = preserved_added_quantities or {}
        order: list[str] = []
        per_sku: dict[str, dict[str, Any]] = {}
        for row in rows:
            sku_id = str(row.get("sku_id") or "")
            if not sku_id:
                continue
            bucket = per_sku.setdefault(
                sku_id, {"base": dict(row), "contributions": {}, "user_quantity": None}
            )
            bucket["base"].update({k: v for k, v in row.items() if k != "contributions"})
            for key, contribution in self._row_contributions(row).items():
                bucket["contributions"][key] = contribution
            if row.get("quantity_source") == "user" and row.get("quantity"):
                bucket["user_quantity"] = int(row["quantity"])
            if sku_id not in order:
                order.append(sku_id)

        cart_quantities = cart_quantities or {}
        collapsed: list[dict[str, Any]] = []
        for sku_id in order:
            bucket = per_sku[sku_id]
            base = bucket["base"]
            contributions = list(bucket["contributions"].values())
            spec_unit = base.get("spec_unit")
            unit = {"kg": "g", "l": "ml"}.get(spec_unit, spec_unit)
            package_amount = float(base.get("spec_quantity") or 0) * UNIT_TO_GRAMS.get(spec_unit, 1)
            ingredient_amounts: dict[str, float] = {}
            pack_count = 0
            for contribution in contributions:
                requirement = contribution.get("requirement") or {}
                if (requirement.get("ingredient_id") and requirement.get("quantity") is not None
                        and requirement.get("unit") == unit and package_amount > 0):
                    ingredient_id = requirement["ingredient_id"]
                    ingredient_amounts[ingredient_id] = ingredient_amounts.get(ingredient_id, 0) + requirement["quantity"]
                else:
                    # Direct products and unknown/incompatible amounts retain
                    # their existing pack count, without claiming shared coverage.
                    pack_count += int(contribution.get("quantity") or 0)
            recommended_total = pack_count + sum(
                math.ceil((math.ceil(amount) if unit == "pc" else amount) / package_amount)
                for amount in ingredient_amounts.values()
            ) or 1
            added_total = max(
                int(base.get("added_quantity") or 0),
                sum(int(c.get("added_quantity") or 0) for c in contributions),
                preserved_added_quantities.get(sku_id, 0),
            )
            selected = any(bool(c.get("selected", True)) for c in contributions)

            offer = self.offers.get_offer(sku_id)
            # The live offer is re-read here, so a supply fact that changed since the
            # plan was built cannot keep an executable-looking row alive. A missing
            # or unreadable attribute is *unknown*, never "available".
            sellable = getattr(offer, "sellable", None) if offer is not None else None
            raw_available = getattr(offer, "available_qty", None) if offer is not None else None
            raw_price = getattr(offer, "price_fen", None) if offer is not None else None
            unverified_reason: str | None = None
            unverified_state = "unknown"
            if offer is None:
                unverified_reason = "no offer for this store"
            elif sellable is None:
                unverified_reason = "offer sellable flag missing"
            elif not sellable:
                unverified_reason = "offer is no longer sellable"
                unverified_state = "not_found"
            elif raw_available is None:
                unverified_reason = "offer stock quantity missing"
            elif raw_price is None:
                unverified_reason = "offer price missing"
            elif int(raw_available) <= 0:
                unverified_reason = "offer is out of stock"
                unverified_state = "out_of_stock"
            unit_price = (
                int(raw_price) if raw_price is not None else int(base.get("unit_price_fen") or 0)
            )
            available = int(raw_available) if raw_available is not None else 0
            in_cart = int(cart_quantities.get(sku_id) or 0)
            max_addable = max(0, min(99, available - in_cart))

            user_quantity = bucket["user_quantity"] or preserved_overrides.get(sku_id)
            if unverified_reason is not None:
                # Keep the row (a previously ticked line is never silently deleted)
                # but make it non-executable and let the derived gap explain it.
                quantity = max(
                    1, int(base.get("quantity") or 1), added_total
                )
                quantity_source = base.get("quantity_source") or "recommended"
                shortfall = 0
                availability = unverified_state
                max_addable = 0
                evidence = dict(base.get("evidence") or {})
                unknown_constraints = list(evidence.get("unknown_constraints") or [])
                if unverified_reason not in unknown_constraints:
                    unknown_constraints.append(unverified_reason)
                evidence.update(
                    {
                        "sku_source": "store_offer",
                        "stock_verified": False,
                        "unknown_constraints": unknown_constraints,
                    }
                )
            elif user_quantity:
                # A quantity the shopper typed is theirs; only the ledger floor is
                # enforced (nothing may sit below what is already in the cart).
                quantity = max(int(user_quantity), added_total)
                quantity_source = "user"
                shortfall = max(0, recommended_total - quantity)
                availability = (
                    "insufficient_stock"
                    if (shortfall > 0 or max_addable < max(0, quantity - added_total))
                    else "available"
                )
            else:
                quantity_source = base.get("quantity_source") or "recommended"
                wanted = max(1, recommended_total)
                # ``max_addable_quantity`` is the headroom *left* after this owner's
                # cart (which already holds what this plan added). It caps how much
                # can still be added; it must never pull the total below the added
                # ledger, or ``quantity - added`` would go negative and the plan
                # would claim to have bought less than it did.
                capacity = added_total + max_addable
                quantity = max(added_total, min(wanted, capacity))
                if quantity < 1:
                    quantity = 1
                shortfall = max(0, wanted - quantity)
                availability = "insufficient_stock" if shortfall > 0 else "available"

            entry = dict(base)
            entry["sku_id"] = sku_id
            entry["quantity"] = quantity
            entry["quantity_source"] = quantity_source
            entry["recommended_quantity"] = recommended_total
            entry["user_quantity"] = user_quantity
            entry["selected"] = selected
            entry["unit_price_fen"] = unit_price
            entry["line_total_fen"] = unit_price * quantity if selected else 0
            entry["max_addable_quantity"] = max_addable
            entry["added_quantity"] = added_total
            entry["remaining_quantity"] = max(0, quantity - added_total)
            entry["availability"] = availability
            entry["shortfall_quantity"] = shortfall
            if unverified_reason is not None:
                entry["evidence"] = evidence
            entry["contributions"] = contributions
            entry["group_id"] = (
                str(base.get("group_id") or "")
                or (contributions[0]["group_id"] if contributions else "")
            )
            collapsed.append(entry)
        return collapsed
