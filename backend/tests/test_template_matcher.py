"""Dish template matching tests."""

from app.services.template_matcher import (
    load_templates,
    match_dish,
    match_dish_from_fixture,
    normalize_text,
    scale_dish_items,
    scale_template,
)


def test_match_tomato_egg_aliases():
    hit = match_dish_from_fixture("我想吃番茄炒蛋")
    assert hit is not None
    assert hit["name"] == "番茄炒蛋"

    hit2 = match_dish_from_fixture("西红柿炒鸡蛋")
    assert hit2 is not None
    assert hit2["dish_id"] == hit["dish_id"]


def test_scale_dish_items_defaults_pantry():
    dish = match_dish_from_fixture("番茄炒蛋")
    assert dish is not None
    items = scale_dish_items(dish, 2)
    ids = {item["ingredient_id"] for item in items}
    assert "tomato" in ids
    assert "egg" in ids
    assert "oil" in ids
    assert "salt" in ids


def test_scale_dish_items_doubles_for_four_people():
    dish = match_dish_from_fixture("番茄炒蛋")
    assert dish is not None
    two = scale_dish_items(dish, 2)
    four = scale_dish_items(dish, 4)
    tomato_two = next(i for i in two if i["ingredient_id"] == "tomato")
    tomato_four = next(i for i in four if i["ingredient_id"] == "tomato")
    assert tomato_four["quantity_g"] == tomato_two["quantity_g"] * 2


def test_no_match_for_unrelated_text():
    assert match_dish("我想买洗衣液") is None


def test_normalize_text_strips_filler():
    assert normalize_text("我想吃番茄炒蛋") == "番茄炒蛋"


def test_scale_template_doubles_for_four_people():
    dish = match_dish_from_fixture("番茄炒蛋")
    assert dish is not None
    scaled = scale_template(dish, target_people=4)
    required = {item["ingredient_id"]: item for item in scaled["required_items"]}
    assert required["tomato"]["quantity_g"] == 600
    assert required["egg"]["quantity_pc"] == 6


def test_load_templates_from_db_seeds_all_105_dishes(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        templates = load_templates(db)
    finally:
        db.close()

    chinese = [t for t in templates if t.get("source") == "chinese-dishes-v1" or t["template_id"].startswith("dish-")]
    assert len(chinese) == 105
    assert "dish-fanqie-chao-dan" in {t["template_id"] for t in templates}
