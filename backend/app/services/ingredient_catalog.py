"""Canonical ingredient catalog loader and validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "data" / "fixtures" / "ingredient-catalog.json"


@lru_cache(maxsize=1)
def load_ingredient_catalog() -> dict[str, Any]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    by_id: dict[str, dict[str, Any]] = {}
    alias_to_id: dict[str, str] = {}
    for item in data.get("ingredients", []):
        iid = item["ingredient_id"]
        by_id[iid] = item
        for alias in item.get("aliases") or []:
            alias_to_id[alias] = iid
    return {
        "version": data.get("version", "v1"),
        "ingredients": by_id,
        "alias_to_id": alias_to_id,
    }


def canonical_ingredient_id(ingredient_id: str) -> str | None:
    catalog = load_ingredient_catalog()
    if ingredient_id in catalog["ingredients"]:
        return ingredient_id
    return catalog["alias_to_id"].get(ingredient_id)


def is_valid_ingredient_id(ingredient_id: str) -> bool:
    return canonical_ingredient_id(ingredient_id) is not None


def validate_ingredient_ids(ingredient_ids: list[str]) -> list[str]:
    """Return ingredient_ids that are not in the canonical catalog."""
    invalid: list[str] = []
    for iid in ingredient_ids:
        if not is_valid_ingredient_id(iid):
            invalid.append(iid)
    return invalid


def ingredient_name_zh(ingredient_id: str) -> str | None:
    catalog = load_ingredient_catalog()
    canonical = canonical_ingredient_id(ingredient_id)
    if not canonical:
        return None
    item = catalog["ingredients"].get(canonical)
    return item.get("name_zh") if item else None


def all_ingredient_ids() -> set[str]:
    catalog = load_ingredient_catalog()
    return set(catalog["ingredients"].keys())
