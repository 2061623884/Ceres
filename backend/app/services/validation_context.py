"""Unified validation context for plan building and confirmation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.state import Requirements

SMALL_PACK_GRAMS = 500


@dataclass
class ValidationContext:
    store_id: str
    delivery_zone_id: str
    requirements: Requirements
    people: int | None = None
    budget_fen: int | None = None
    excluded_ingredients: list[str] = field(default_factory=list)
    delivery_deadline_minutes: int | None = None
    specification: dict[str, Any] = field(default_factory=dict)
    pantry_confirmed: list[str] = field(default_factory=list)
    active_template_id: str | None = None

    @classmethod
    def from_requirements(
        cls,
        requirements: Requirements,
        *,
        store_id: str,
        delivery_zone_id: str,
        active_template_id: str | None = None,
    ) -> ValidationContext:
        deadline_minutes = _parse_deadline_minutes(requirements.delivery_deadline)
        return cls(
            store_id=store_id,
            delivery_zone_id=delivery_zone_id,
            requirements=requirements,
            people=requirements.people,
            budget_fen=requirements.budget_fen,
            excluded_ingredients=list(requirements.excluded_ingredients or []),
            delivery_deadline_minutes=deadline_minutes,
            specification=dict(requirements.specification or {}),
            pantry_confirmed=list(requirements.pantry_confirmed or []),
            active_template_id=active_template_id,
        )

    def matches_spec(self, product: dict[str, Any]) -> bool:
        size = self.specification.get("size")
        if size != "small":
            return True
        spec_qty = product.get("spec_quantity")
        spec_unit = product.get("spec_unit")
        if spec_qty is None or not spec_unit:
            return False
        if spec_unit in ("g", "kg"):
            grams = float(spec_qty) * (1000.0 if spec_unit == "kg" else 1.0)
            return grams <= SMALL_PACK_GRAMS
        if spec_unit in ("ml", "l"):
            ml = float(spec_qty) * (1000.0 if spec_unit == "l" else 1.0)
            return ml <= SMALL_PACK_GRAMS
        return False

    def product_allowed(self, product: dict[str, Any]) -> bool:
        ing_ids = set(product.get("ingredient_ids") or [])
        if self.excluded_ingredients and ing_ids.intersection(self.excluded_ingredients):
            return False
        if not self.matches_spec(product):
            return False
        return True


def _parse_deadline_minutes(deadline: str | None) -> int | None:
    if not deadline:
        return None
    text = deadline.strip()
    match = re.search(r"(\d+)\s*分钟", text)
    if match:
        return int(match.group(1))
    if re.search(r"尽快|马上|立刻", text):
        return 10
    return None
