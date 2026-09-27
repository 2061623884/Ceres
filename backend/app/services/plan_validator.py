"""Plan validation against business constraints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.catalog import CatalogProduct
from app.services import plan_contract as contract
from app.services.catalog_service import CatalogService
from app.services.delivery_service import DeliveryService
from app.services.image_assets import image_kind_for_path, image_kind_legacy
from app.services.offer_service import OfferService
from app.services.validation_context import ValidationContext

PLAN_TTL_MINUTES = 5


class PlanValidator:
    def __init__(
        self,
        db: Session,
        store_id: str = "store-demo-01",
        delivery_zone_id: str = "zone-default",
    ):
        self.db = db
        self.store_id = store_id
        self.delivery_zone_id = delivery_zone_id
        self.offers = OfferService(db, store_id)
        self.delivery = DeliveryService(db)
        self.catalog = CatalogService(db, store_id)

    def check_constraints(
        self,
        items: list[dict[str, Any]],
        candidate_sku_ids: list[str],
        budget_fen: int | None = None,
        mode: str = "bundle",
        *,
        people: int | None = None,
        excluded_ingredients: list[str] | None = None,
        delivery_deadline_minutes: int | None = None,
        ctx: ValidationContext | None = None,
        coverage_intent: str = "full",
        user_supplied_ingredients: list[str] | None = None,
        missing_required_items: list[dict[str, Any]] | None = None,
        target_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate items against business rules without publishing a snapshot.

        Two kinds of failure are deliberately kept apart:

        * **hard constraints** (candidate set, approval, exclusions, budget,
          delivery) remain fatal ``errors``;
        * **supply problems** (no offer, not sold, out of stock, not enough
          stock) become structured ``gaps`` instead of killing the whole plan.

        A row this store cannot supply is *never* kept as a selectable line:
        unknown supply is reported as ``unknown`` (never dressed up as a stock
        out), and a row that is short is prepared at the verified addable count
        while the shortfall stays on the plan as a gap (D2/D3/D7).
        """
        if ctx is not None:
            budget_fen = ctx.budget_fen if budget_fen is None else budget_fen
            people = ctx.people if people is None else people
            excluded_ingredients = (
                ctx.excluded_ingredients if excluded_ingredients is None else excluded_ingredients
            )
            delivery_deadline_minutes = (
                ctx.delivery_deadline_minutes
                if delivery_deadline_minutes is None
                else delivery_deadline_minutes
            )

        target_context = target_context or {}
        effective_intent = contract.normalize_intent(coverage_intent)
        errors: list[str] = []
        validated_items: list[dict[str, Any]] = []
        selected_total = 0
        sku_set = set(candidate_sku_ids)
        excluded = set(excluded_ingredients or [])
        user_supplied = set(user_supplied_ingredients or [])
        gaps: list[dict[str, Any]] = []
        quoted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

        for item in items:
            sku_id = str(item["sku_id"])
            qty = item.get("quantity", 1)
            group_id = str(item.get("group_id") or target_context.get("group_id") or "")
            target_kind = str(
                item.get("target_kind") or target_context.get("target_kind") or ""
            )
            target_id = str(item.get("target_id") or target_context.get("target_id") or "")
            requirement = (
                item.get("requirement") if isinstance(item.get("requirement"), dict) else {}
            )
            required_item_id = item.get("required_item_id") or requirement.get(
                "required_item_id"
            )
            role = item.get("role", "required")
            requiredness = contract.requiredness_for_role(role)
            row_name = item.get("name") or requirement.get("name")
            pack_source = str(item.get("pack_source") or "")
            unknown_constraints = [
                str(entry) for entry in item.get("unknown_constraints") or []
            ]
            if pack_source == "assumed_one":
                unknown_constraints.append("catalog pack spec missing; one pack suggested")

            def _evidence(
                *, stock_verified: bool, extra: list[str] | None = None
            ) -> dict[str, Any]:
                """Where this fact came from: this store's offer snapshot.

                It is deliberately explicit that this is demo/store data and not
                a live external stock feed.
                """
                return {
                    "sku_source": "store_offer",
                    "quoted_at": quoted_at,
                    "stock_verified": stock_verified,
                    "data_mode": get_settings().business_data_mode,
                    "source_note": (
                        f"本店 offer 快照（business_data_mode="
                        f"{get_settings().business_data_mode}）；不是外部实时库存源"
                    ),
                    "unknown_constraints": [*unknown_constraints, *(extra or [])],
                }

            def _gap(kind: str, **extra: Any) -> dict[str, Any]:
                return contract.make_gap(
                    group_id=group_id,
                    target_kind=target_kind,
                    target_id=target_id,
                    kind=kind,
                    requiredness=requiredness,
                    key=sku_id,
                    required_item_id=required_item_id,
                    ingredient_id=requirement.get("ingredient_id"),
                    component_id=requirement.get("component_id"),
                    name=row_name,
                    sku_id=sku_id,
                    required_quantity=requirement.get("quantity"),
                    unit=requirement.get("unit"),
                    quantity_known=requirement.get("quantity_known"),
                    source=requirement.get("source"),
                    **extra,
                )

            if qty <= 0:
                errors.append(f"SKU {sku_id} invalid quantity")
                continue
            if sku_id not in sku_set:
                errors.append(f"SKU {sku_id} not in candidate set")
                continue
            product = self.db.get(CatalogProduct, sku_id)
            if not product or product.review_status != "approved":
                errors.append(f"SKU {sku_id} not approved")
                continue
            product_dict = {
                "sku_id": sku_id,
                "ingredient_ids": [],
                "spec_quantity": product.spec_quantity,
                "spec_unit": product.spec_unit,
            }
            try:
                import json

                product_dict["ingredient_ids"] = json.loads(product.ingredient_ids or "[]")
            except json.JSONDecodeError:
                pass
            if ctx and not ctx.product_allowed(product_dict):
                errors.append(f"SKU {sku_id} violates constraints")
                continue
            ing_ids = set(product_dict["ingredient_ids"])
            if excluded and ing_ids.intersection(excluded):
                errors.append(f"SKU {sku_id} contains excluded ingredient")
                continue
            offer = self.offers.get_offer(sku_id)
            if offer is None:
                # No offer row at all is *missing information*, not a stock-out.
                gaps.append(
                    _gap(
                        "unknown",
                        unknown_of="availability",
                        evidence=_evidence(
                            stock_verified=False, extra=["no offer for this store"]
                        ),
                    )
                )
                continue
            sellable = getattr(offer, "sellable", None)
            if sellable is None:
                # A missing hard attribute is unverified, never accepted.
                gaps.append(
                    _gap(
                        "unknown",
                        unknown_of="availability",
                        evidence=_evidence(
                            stock_verified=False,
                            extra=["offer sellable flag missing"],
                        ),
                    )
                )
                continue
            if not sellable:
                gaps.append(
                    _gap("not_found", evidence=_evidence(stock_verified=True))
                )
                continue
            raw_available = getattr(offer, "available_qty", None)
            if raw_available is None:
                gaps.append(
                    _gap(
                        "unknown",
                        unknown_of="availability",
                        evidence=_evidence(
                            stock_verified=False,
                            extra=["offer stock quantity missing"],
                        ),
                    )
                )
                continue
            if getattr(offer, "price_fen", None) is None:
                # A row with no verified price cannot be confirmed against a
                # snapshot, so it is an unverified supply fact, not a free item.
                gaps.append(
                    _gap(
                        "unknown",
                        unknown_of="availability",
                        evidence=_evidence(stock_verified=False, extra=["offer price missing"]),
                    )
                )
                continue
            available_qty = int(raw_available)
            if available_qty <= 0:
                gaps.append(
                    _gap(
                        "out_of_stock",
                        available_quantity=0,
                        evidence=_evidence(stock_verified=True),
                    )
                )
                continue

            user_set = str(item.get("quantity_source") or "") == "user"
            effective_qty = int(qty)
            shortfall = 0
            availability = "available"
            if available_qty < qty:
                if user_set:
                    # A quantity the shopper typed is theirs: stock is enforced by
                    # ``max_addable_quantity``/over_stock, never by a silent edit.
                    pass
                else:
                    effective_qty = max(1, available_qty)
                    shortfall = int(qty) - effective_qty
                    availability = "insufficient_stock"
                    # The gap itself is derived from the row below: one rule, one
                    # place, so a merged/re-checked row can never leave a stale
                    # shortfall behind.

            unit_price = offer.price_fen
            line_total = unit_price * effective_qty
            selected = item.get("selected", role != "pantry")
            if selected:
                selected_total += line_total
            evidence = _evidence(stock_verified=True)
            image_path = product.image_path
            image_kind = image_kind_for_path(image_path, get_settings().root_dir)
            validated_items.append(
                {
                    "sku_id": sku_id,
                    "name": product.name_zh or product.name,
                    "quantity": effective_qty,
                    "recommended_quantity": int(qty),
                    "quantity_source": item.get("quantity_source") or "recommended",
                    "unit_price_fen": unit_price,
                    "line_total_fen": line_total if selected else 0,
                    "image_path": image_path,
                    "image_kind": image_kind,
                    "image_kind_legacy": image_kind_legacy(image_kind),
                    "role": role,
                    "selected": selected,
                    "ingredient_ids": list(ing_ids),
                    "spec_quantity": product.spec_quantity,
                    "spec_unit": product.spec_unit,
                    "sell_unit": "件",
                    "max_addable_quantity": max(0, min(99, available_qty)),
                    # Which target this row belongs to: a row-derived gap needs it
                    # so a remove/replace can retire exactly this group's gaps.
                    "group_id": group_id or None,
                    "target_kind": target_kind or None,
                    "target_id": target_id or None,
                    # P0 requirement/fulfilment evidence (see plan_contract).
                    "required_item_id": required_item_id,
                    "requirement": requirement or None,
                    "availability": availability,
                    "evidence": evidence,
                    "pack_source": pack_source or None,
                    "shortfall_quantity": shortfall,
                }
            )

        for entry in missing_required_items or []:
            carried = contract.normalize_carried_gap(entry, target_context=target_context)
            if carried is not None:
                gaps.append(carried)
        # Row-derived gaps (stock shortfall, unknown pack size) take precedence
        # over the explicit ones, so a row and its gap can never disagree.
        gaps = contract.collect_gaps(gaps, validated_items)

        if effective_intent == "user_supplied" and not user_supplied:
            errors.append("user_supplied requires ingredient list")
        coverage = contract.coverage(
            validated_items,
            gaps,
            effective_intent,
            user_supplied_ingredients=user_supplied,
            ignore_unselected_required=mode == "alternatives",
        )

        if budget_fen is not None:
            if mode == "alternatives":
                selected_items = [i for i in validated_items if i.get("selected", True)]
                if selected_items and not any(i["line_total_fen"] <= budget_fen for i in selected_items):
                    errors.append(f"No alternative within budget {budget_fen}")
                cheapest = min(
                    (i["line_total_fen"] for i in validated_items if i.get("selected", True)),
                    default=0,
                )
                if selected_total > budget_fen and cheapest <= budget_fen:
                    errors.append(f"Selected total {selected_total} exceeds budget {budget_fen}")
            elif selected_total > budget_fen:
                errors.append(f"Total {selected_total} exceeds budget {budget_fen}")

        if not self.delivery.check_delivery(self.store_id, self.delivery_zone_id):
            errors.append("Delivery not reachable")

        if delivery_deadline_minutes is not None:
            quote = self.delivery.get_quote(self.store_id, self.delivery_zone_id)
            eta = quote.get("eta_minutes")
            if eta is None or eta > delivery_deadline_minutes:
                errors.append("Delivery ETA exceeds deadline")

        can_confirm = not errors and coverage["can_confirm"]
        # A plan whose only content is a gap is still a real, clearly
        # non-confirmable answer — never an empty ``failed`` that loses the gap.
        status = "passed" if not errors and (validated_items or gaps) else "failed"
        return {
            "items": validated_items,
            "selected_total_fen": selected_total,
            "total_price_fen": selected_total,
            "validation_status": status,
            "errors": errors,
            "coverage_mode": coverage["coverage_mode"],
            "coverage_intent": coverage["coverage_intent"],
            "uncovered_items": coverage["uncovered_items"],
            "gaps": gaps,
            "can_confirm": can_confirm,
            "mode": mode,
        }

    def publish_snapshot(
        self,
        check_result: dict[str, Any],
        *,
        plan_id: str | None = None,
        plan_version: int = 1,
        mode: str = "bundle",
        supply_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish an immutable plan snapshot after constraints pass."""
        if check_result.get("validation_status") != "passed":
            raise ValueError("Cannot publish snapshot for failed validation")
        now = datetime.now(timezone.utc)
        snapshot = {
            "plan_id": plan_id or f"plan-{uuid4().hex[:12]}",
            "plan_version": plan_version,
            "mode": mode,
            "items": check_result["items"],
            "total_price_fen": check_result["total_price_fen"],
            "selected_total_fen": check_result["selected_total_fen"],
            "expires_at": (now + timedelta(minutes=PLAN_TTL_MINUTES)).isoformat(),
            "validation_status": "passed",
            "errors": [],
            "coverage_mode": check_result.get("coverage_mode", "full"),
            "coverage_intent": check_result.get("coverage_intent", contract.LEGACY_INTENT),
            "uncovered_items": check_result.get("uncovered_items", []),
            "gaps": check_result.get("gaps", []),
            "can_confirm": check_result.get("can_confirm", True),
        }
        if supply_context:
            snapshot["supply_store_id"] = supply_context.get("store_id")
            snapshot["supply_zone_id"] = supply_context.get("delivery_zone_id")
            snapshot["supply_version"] = supply_context.get("supply_version", 1)
        return snapshot

    def validate_plan(
        self,
        items: list[dict[str, Any]],
        candidate_sku_ids: list[str],
        budget_fen: int | None = None,
        mode: str = "bundle",
        *,
        people: int | None = None,
        excluded_ingredients: list[str] | None = None,
        delivery_deadline_minutes: int | None = None,
        ctx: ValidationContext | None = None,
        coverage_intent: str = "full",
        user_supplied_ingredients: list[str] | None = None,
        missing_required_items: list[dict[str, Any]] | None = None,
        target_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checked = self.check_constraints(
            items,
            candidate_sku_ids,
            budget_fen=budget_fen,
            mode=mode,
            people=people,
            excluded_ingredients=excluded_ingredients,
            delivery_deadline_minutes=delivery_deadline_minutes,
            ctx=ctx,
            coverage_intent=coverage_intent,
            user_supplied_ingredients=user_supplied_ingredients,
            missing_required_items=missing_required_items,
            target_context=target_context,
        )
        if checked.get("validation_status") != "passed":
            return {
                **checked,
                "plan_id": f"plan-{uuid4().hex[:12]}",
                "plan_version": 1,
                "expires_at": datetime.now(timezone.utc).isoformat(),
            }
        if mode == "alternatives" and checked["items"]:
            checked["total_price_fen"] = min(
                i["line_total_fen"] for i in checked["items"] if i.get("selected", True)
            ) if any(i.get("selected", True) for i in checked["items"]) else min(
                i["line_total_fen"] for i in checked["items"]
            )
        return self.publish_snapshot(checked, mode=mode)
