"""search_dishes business tool implementation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.entity_matcher import match_dish_entity
from app.services.template_matcher import dish_display_name
from app.services.template_plan_service import INGREDIENT_ALIASES

#: A ``matched`` result at or above this score came from an exact name/alias or
#: an unambiguous label embedded in the sentence — the user really named the
#: dish. Lower scores are fuzzy guesses and must be confirmed by the user.
NAMED_MATCH_MIN_SCORE = 95.0


def _candidate_payload(dish: dict[str, Any]) -> dict[str, Any]:
    main_ingredients = [
        item.get("ingredient_id") or item.get("name") or ""
        for item in dish.get("required_items") or []
        if item.get("ingredient_id") or item.get("name")
    ]
    return {
        "dish_id": dish.get("dish_id") or dish.get("template_id"),
        "name": dish_display_name(dish),
        "main_ingredients": main_ingredients[:6],
        "source": dish.get("source") or "chinese-dishes-v1",
        "note": None,
    }


def _ingredient_aliases(ingredient_id: str) -> set[str]:
    return set(INGREDIENT_ALIASES.get(ingredient_id, [ingredient_id])) | {ingredient_id}


def _conflicting_ingredients(dish: dict[str, Any], excluded: set[str]) -> list[str]:
    if not excluded:
        return []
    conflicts: list[str] = []
    for item in dish.get("required_items") or []:
        ingredient_id = item.get("ingredient_id")
        if not ingredient_id:
            continue
        if _ingredient_aliases(ingredient_id) & excluded:
            conflicts.append(ingredient_id)
    return conflicts


def _payloads_with_conflicts(
    dishes: list[dict[str, Any]],
    excluded: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into those that keep the hard exclusions and those that do not."""
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for dish in dishes:
        payload = _candidate_payload(dish)
        conflicts = _conflicting_ingredients(dish, excluded)
        if conflicts:
            payload["conflicts"] = conflicts
            dropped.append(payload)
        else:
            kept.append(payload)
    return kept, dropped


def search_dishes(
    db: Session,
    *,
    query: str,
    taste_preferences: list[str] | None = None,
    exclude_ingredients: list[str] | None = None,
) -> dict[str, Any]:
    # Taste preferences are ranking hints only; they are not a second semantic pass.
    del taste_preferences
    excluded = {str(i) for i in (exclude_ingredients or []) if str(i).strip()}

    result = match_dish_entity(query, db)

    if result.status == "matched" and result.dish:
        kept, dropped = _payloads_with_conflicts([result.dish], excluded)
        match_kind = "exact" if result.score >= NAMED_MATCH_MIN_SCORE else "fuzzy"
        if not kept:
            return {
                "status": "error",
                "code": "CONSTRAINT_CONFLICT",
                "message": "该菜需要被排除的食材，无法满足，请换一道菜或取消排除条件。",
                "candidates": dropped,
                "match_kind": match_kind,
            }
        return {
            "status": "ok",
            "candidates": kept,
            "match_kind": match_kind,
        }

    if result.status == "ambiguous" and result.candidates:
        kept, dropped = _payloads_with_conflicts(result.candidates[:5], excluded)
        if not kept:
            return {
                "status": "error",
                "code": "CONSTRAINT_CONFLICT",
                "message": "候选菜都包含被排除的食材，请调整排除条件。",
                "candidates": dropped,
                "match_kind": "ambiguous",
            }
        return {
            "status": "ok",
            "candidates": kept,
            "match_kind": "ambiguous",
        }

    if result.status == "not_found":
        return {
            "status": "error",
            "code": "NO_MATCH",
            "message": result.message or "未找到匹配菜谱",
            "candidates": [],
        }

    return {
        "status": "error",
        "code": "RETRIEVAL_FAILED",
        "message": result.message or "菜谱检索失败",
        "candidates": [],
    }
