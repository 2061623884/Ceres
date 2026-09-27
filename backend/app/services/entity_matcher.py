"""Dish name normalization and fuzzy matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.template_matcher import (
    _load_fixture_dishes,
    dish_fixture_to_dict,
    load_templates,
    normalize_text,
)

try:
    from rapidfuzz import fuzz, process
except ImportError:
    fuzz = None
    process = None

from sqlalchemy.orm import Session

NOT_FOUND_MESSAGE = "暂未收录"

# RapidFuzz scores are for ranking only — not treated as probabilities.
FUZZY_MIN_SCORE = 75.0
AUTO_MATCH_MIN_SCORE = 75.0
AMBIGUITY_SCORE_GAP = 5.0


@dataclass
class EntityMatchResult:
    status: str  # matched | ambiguous | not_found | not_sellable | tool_failed
    dish: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    failure_type: str | None = None
    score: float = 0.0
    message: str | None = None


def _labels_for_dish(dish: dict[str, Any]) -> list[str]:
    labels = [dish.get("name_zh") or dish.get("name") or dish.get("scenario") or ""]
    labels.extend(dish.get("aliases") or [])
    return [label for label in labels if label]


def _substring_hits(normalized: str, dishes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """User span contains a catalog label (e.g. dish name + budget in one sentence)."""
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dish in dishes:
        dish_id = dish.get("dish_id") or dish.get("template_id")
        if not dish_id or dish_id in seen:
            continue
        for label in _labels_for_dish(dish):
            label_norm = normalize_text(label)
            if label_norm and label_norm in normalized:
                hits.append(dish)
                seen.add(dish_id)
                break
    return hits


def _exact_matches(normalized: str, dishes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dish in dishes:
        dish_id = dish.get("dish_id") or dish.get("template_id")
        if not dish_id or dish_id in seen:
            continue
        for label in _labels_for_dish(dish):
            if normalize_text(label) == normalized:
                hits.append(dish)
                seen.add(dish_id)
                break
    return hits


def _is_partial_label(normalized: str, label: str) -> bool:
    label_norm = normalize_text(label)
    if not label_norm or normalized == label_norm:
        return False
    return normalized in label_norm or label_norm in normalized


def _has_partial_label_match(normalized: str, dish: dict[str, Any]) -> bool:
    return any(_is_partial_label(normalized, label) for label in _labels_for_dish(dish))


@dataclass
class _RankedDish:
    dish: dict[str, Any]
    score: float


def _rank_dishes(normalized: str, dishes: list[dict[str, Any]]) -> list[_RankedDish]:
    if not process or not fuzz:
        return []

    choices: dict[str, dict[str, Any]] = {}
    for dish in dishes:
        for label in _labels_for_dish(dish):
            label_norm = normalize_text(label)
            if label_norm:
                choices[label_norm] = dish

    if not choices:
        return []

    results = process.extract(normalized, choices.keys(), scorer=fuzz.WRatio, limit=8)
    best_by_dish: dict[str, _RankedDish] = {}
    for label, score, _ in results:
        dish = choices[label]
        dish_id = dish.get("dish_id") or dish.get("template_id")
        if not dish_id:
            continue
        current = best_by_dish.get(dish_id)
        if current is None or score > current.score:
            best_by_dish[dish_id] = _RankedDish(dish=dish, score=float(score))

    return sorted(best_by_dish.values(), key=lambda item: item.score, reverse=True)


def _not_found(failure_type: str, score: float = 0.0) -> EntityMatchResult:
    return EntityMatchResult(
        status="not_found",
        failure_type=failure_type,
        score=score,
        message=NOT_FOUND_MESSAGE,
    )


def _ambiguous(candidates: list[dict[str, Any]], score: float) -> EntityMatchResult:
    return EntityMatchResult(
        status="ambiguous",
        candidates=candidates,
        failure_type="multi_dish",
        score=score,
    )


def _matched(dish: dict[str, Any], score: float) -> EntityMatchResult:
    return EntityMatchResult(status="matched", dish=dish, score=score)


def match_dish_entity(text: str, db: Session | None = None) -> EntityMatchResult:
    """Match user dish text to catalog entries.

    RapidFuzz is used for candidate ranking only. Exact name/alias hits win;
    close fuzzy scores become ambiguous candidates; unknown dishes return
    ``message='暂未收录'``.
    """
    if not text or not text.strip():
        return _not_found("empty")

    normalized = normalize_text(text)
    if not normalized:
        return _not_found("empty")

    dishes = load_templates(db) if db else [dish_fixture_to_dict(d) for d in _load_fixture_dishes()]

    exact_hits = _exact_matches(normalized, dishes)
    if len(exact_hits) == 1:
        return _matched(exact_hits[0], score=100.0)
    if len(exact_hits) > 1:
        return _ambiguous(exact_hits, score=100.0)

    span_hits = _substring_hits(normalized, dishes)
    if len(span_hits) == 1:
        return _matched(span_hits[0], score=95.0)
    if len(span_hits) > 1:
        return _ambiguous(span_hits, score=95.0)

    ranked = _rank_dishes(normalized, dishes)
    if not ranked or ranked[0].score < FUZZY_MIN_SCORE:
        return _not_found("not_in_catalog", score=ranked[0].score if ranked else 0.0)

    top_score = ranked[0].score
    close = [item for item in ranked if item.score >= top_score - AMBIGUITY_SCORE_GAP and item.score >= FUZZY_MIN_SCORE]
    unique_close = list({(item.dish.get("dish_id") or item.dish.get("template_id")): item for item in close}.values())

    if _has_partial_label_match(normalized, unique_close[0].dish):
        partial_hits = [item.dish for item in unique_close if _has_partial_label_match(normalized, item.dish)]
        in_span = _substring_hits(normalized, partial_hits)
        if len(in_span) == 1:
            return _matched(in_span[0], score=top_score)
        if len(in_span) > 1:
            return _ambiguous(in_span, score=top_score)
        if len(partial_hits) > 1:
            return _ambiguous(partial_hits, score=top_score)
        return _not_found("not_in_catalog", score=top_score)

    if len(unique_close) == 1 and top_score >= AUTO_MATCH_MIN_SCORE:
        return _matched(unique_close[0].dish, score=top_score)

    if unique_close:
        return _ambiguous([item.dish for item in unique_close], score=top_score)

    return _not_found("not_in_catalog", score=top_score)
