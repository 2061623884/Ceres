"""M2 entity matching with RapidFuzz."""

from __future__ import annotations

from app.services.entity_matcher import NOT_FOUND_MESSAGE, match_dish_entity


def test_exact_match_tomato_egg():
    result = match_dish_entity("番茄炒蛋")
    assert result.status == "matched"
    assert result.dish is not None
    assert result.dish["dish_id"] == "dish-fanqie-chao-dan"


def test_alias_match_tomato_egg():
    result = match_dish_entity("西红柿炒鸡蛋")
    assert result.status == "matched"
    assert result.dish["dish_id"] == "dish-fanqie-chao-dan"


def test_fuzzy_typo_matches_tomato_egg():
    result = match_dish_entity("蕃茄炒蛋")
    assert result.status == "matched"
    assert result.dish is not None
    assert result.dish["dish_id"] == "dish-fanqie-chao-dan"


def test_fuzzy_typo_matches_gongbao():
    result = match_dish_entity("宫爆鸡丁")
    assert result.status == "matched"
    assert result.dish["dish_id"] == "dish-gongbao-jiding"


def test_unknown_dish_not_found():
    result = match_dish_entity("xyzqwerty未知菜")
    assert result.status == "not_found"
    assert result.message == NOT_FOUND_MESSAGE
    assert result.failure_type in ("not_in_catalog", "spelling")


def test_xiaochaorou_not_qingjiao_rousi():
    result = match_dish_entity("小炒肉")
    assert result.dish is None or result.dish["dish_id"] != "dish-qingjiao-rousi"
    assert result.status == "not_found"
    assert result.message == NOT_FOUND_MESSAGE
    assert result.failure_type == "not_in_catalog"


def test_ambiguous_short_dish_name_returns_candidates():
    result = match_dish_entity("炒蛋")
    assert result.status == "ambiguous"
    assert len(result.candidates) >= 2
    assert result.failure_type == "multi_dish"
