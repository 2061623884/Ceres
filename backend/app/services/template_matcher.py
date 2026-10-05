"""Match user text to purchase dish templates."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.catalog import PurchaseTemplate

ROOT = Path(__file__).resolve().parents[3]
DISHES_PATH = ROOT / "data" / "fixtures" / "chinese-dishes-v1.json"

_FILLER_PATTERN = re.compile(
    r"(我想吃|我要吃|我想做|我要做|来一份|来一个|做个|做一道|做顿|做|吃|点|份|的|吧|啊|呢|了|请|帮我|给我|想要|想)"
)
_PUNCT_PATTERN = re.compile(r"[\s\u3000，。！？、；：""''（）()\[\]【】\-—·…]+")
_QUANTITY_KEYS = ("quantity_g", "quantity_pc", "quantity_ml")


def normalize_text(text: str) -> str:
    """Normalize user or dish text for substring matching."""
    cleaned = text.strip().lower()
    cleaned = _PUNCT_PATTERN.sub("", cleaned)
    cleaned = _FILLER_PATTERN.sub("", cleaned)
    return cleaned


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _parse_json_items(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


@lru_cache(maxsize=1)
def _load_fixture_dishes() -> list[dict[str, Any]]:
    data = json.loads(DISHES_PATH.read_text(encoding="utf-8"))
    return list(data.get("dishes", []))


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _dish_metadata_wrapper(dish: dict[str, Any]) -> dict[str, Any]:
    if dish.get("metadata"):
        return dish["metadata"]
    return {
        "meta": dish.get("meta", {}),
        "meta_provenance": dish.get("meta_provenance", {}),
        "review": dish.get("review", {}),
    }


def template_record_to_dict(row: PurchaseTemplate) -> dict[str, Any]:
    return {
        "template_id": row.template_id,
        "scenario": row.scenario,
        "name": row.scenario,
        "dish_id": row.template_id,
        "aliases": _parse_json_list(row.aliases_json),
        "base_people": row.base_people,
        "required_items": _parse_json_items(row.required_items),
        "optional_items": _parse_json_items(row.optional_items),
        "pantry_items": _parse_json_list(row.pantry_items),
        "source": row.source,
        "metadata": _parse_metadata(row.metadata_json),
    }


def dish_fixture_to_dict(dish: dict[str, Any]) -> dict[str, Any]:
    """Convert fixture dish row to template matcher shape."""
    name = dish.get("name_zh") or dish.get("name") or ""
    return {
        "template_id": dish["dish_id"],
        "dish_id": dish["dish_id"],
        "scenario": name,
        "name": name,
        "aliases": dish.get("aliases", []),
        "base_people": dish.get("base_people", 2),
        "required_items": dish.get("required_items", []),
        "optional_items": dish.get("optional_items", []),
        "pantry_items": dish.get("pantry_items", []),
        "metadata": _dish_metadata_wrapper(dish),
    }


def load_fixture_templates() -> list[dict[str, Any]]:
    return [dish_fixture_to_dict(d) for d in _load_fixture_dishes()]


def load_templates(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(PurchaseTemplate)
        .filter(PurchaseTemplate.source == "chinese-dishes-v1")
        .all()
    )
    if rows:
        return [template_record_to_dict(row) for row in rows]
    return load_fixture_templates()


def _match_labels(record: dict[str, Any]) -> list[str]:
    labels = [record.get("scenario") or record.get("name") or ""]
    labels.extend(record.get("aliases") or [])
    return [label for label in labels if label]


def _best_match(normalized: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1
    for record in records:
        for label in _match_labels(record):
            label_norm = normalize_text(label)
            if not label_norm:
                continue
            if label_norm in normalized or normalized in label_norm:
                score = len(label_norm)
                if score > best_score:
                    best = record
                    best_score = score
    return best


def match_dish(
    text: str,
    templates: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return the best matching dish/template for user text, or None."""
    if not text or not text.strip():
        return None
    normalized = normalize_text(text)
    if not normalized:
        return None

    if templates is not None:
        return _best_match(normalized, templates)

    fixture_records = [dish_fixture_to_dict(d) for d in _load_fixture_dishes()]
    hit = _best_match(normalized, fixture_records)
    if hit is None:
        return None
    # Workflow expects raw fixture keys such as `name`.
    for dish in _load_fixture_dishes():
        if dish["dish_id"] == hit["dish_id"]:
            return dish
    return hit


def scale_quantity(value: float, base_people: int, target_people: int) -> float | int:
    if base_people <= 0:
        return value
    return value * target_people / base_people


def scale_items(
    items: list[dict[str, Any]],
    base_people: int,
    target_people: int,
) -> list[dict[str, Any]]:
    scaled: list[dict[str, Any]] = []
    for item in items:
        out: dict[str, Any] = {"ingredient_id": item["ingredient_id"]}
        for key in _QUANTITY_KEYS:
            if key in item:
                out[key] = scale_quantity(float(item[key]), base_people, target_people)
        scaled.append(out)
    return scaled


def merge_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        ingredient_id = item["ingredient_id"]
        bucket = merged.setdefault(ingredient_id, {"ingredient_id": ingredient_id})
        for key in _QUANTITY_KEYS:
            if key in item:
                bucket[key] = bucket.get(key, 0) + item[key]
    return list(merged.values())


def scale_template(
    template: dict[str, Any],
    target_people: int | None = None,
) -> dict[str, Any]:
    """Scale template quantities to target people (defaults to base_people)."""
    base_people = template.get("base_people") or 2
    people = target_people or base_people
    return {
        **template,
        "target_people": people,
        "required_items": scale_items(template.get("required_items", []), base_people, people),
        "optional_items": scale_items(template.get("optional_items", []), base_people, people),
        "pantry_items": list(template.get("pantry_items") or []),
    }


def scale_dish_items(template: dict[str, Any], people: int) -> list[dict[str, Any]]:
    """Scale and merge required, optional, and pantry items for a headcount."""
    scaled = scale_template(template, people)
    pantry_items = [
        {"ingredient_id": ing, "quantity_g": 10}
        for ing in scaled.get("pantry_items", [])
        if isinstance(ing, str)
    ]
    return merge_items(
        scaled.get("required_items", [])
        + scaled.get("optional_items", [])
        + pantry_items
    )


def dish_display_name(template: dict[str, Any]) -> str:
    return template.get("scenario") or template.get("name") or "这道菜"


def get_template_by_id(db: Session, template_id: str | None) -> dict[str, Any] | None:
    if not template_id:
        return None
    for template in load_templates(db):
        if template.get("dish_id") == template_id or template.get("template_id") == template_id:
            if "required_items" in template and isinstance(template["required_items"], list):
                for dish in _load_fixture_dishes():
                    if dish["dish_id"] == template_id:
                        return dish
                return template
    for dish in _load_fixture_dishes():
        if dish["dish_id"] == template_id:
            return dish
    return None


def match_dish_for_db(db: Session, text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    matched = match_dish(text, load_templates(db))
    if matched is None:
        return None
    if "required_items" in matched and isinstance(matched["required_items"], list):
        return matched
    for dish in _load_fixture_dishes():
        if dish["dish_id"] == matched.get("dish_id") or dish["dish_id"] == matched.get("template_id"):
            return dish
    return matched


def match_dish_from_fixture(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    return match_dish(text)
