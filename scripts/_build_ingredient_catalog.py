#!/usr/bin/env python3
"""One-off helper to emit data/fixtures/ingredient-catalog.json (run manually if needed)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fixtures" / "ingredient-catalog.json"

# OFF import catalog (52) — ingredient_id was name_norm in import_db.py
OFF_ENTRIES: list[dict] = [
    {"ingredient_id": "tomato", "name_zh": "番茄", "kind": "vegetable", "ner_terms": ["tomato", "tomatoes"], "off_tags": ["en:fresh-tomatoes"], "off_main_categories": ["Fresh tomatoes"]},
    {"ingredient_id": "lettuce", "name_zh": "生菜", "kind": "vegetable", "ner_terms": ["lettuce", "romaine", "iceberg lettuce"], "off_tags": ["en:lettuces", "en:leaf-salads"], "off_main_categories": ["Lettuces", "Leaf salads"]},
    {"ingredient_id": "spinach", "name_zh": "菠菜", "kind": "vegetable", "ner_terms": ["spinach"], "off_tags": ["en:spinachs"], "off_main_categories": ["Spinachs", "Frozen spinachs"]},
    {"ingredient_id": "carrot", "name_zh": "胡萝卜", "kind": "vegetable", "ner_terms": ["carrot", "carrots"], "off_tags": ["en:fresh-carrots"], "off_main_categories": ["Fresh carrots"]},
    {"ingredient_id": "onion", "name_zh": "洋葱", "kind": "vegetable", "ner_terms": ["onion", "onions"], "off_tags": ["en:fresh-onions", "en:onions"], "off_main_categories": ["Fresh onions", "Onions"]},
    {"ingredient_id": "potato", "name_zh": "土豆", "kind": "vegetable", "ner_terms": ["potato", "potatoes"], "off_tags": ["en:fresh-potatoes", "en:potatoes"], "off_main_categories": ["Fresh potatoes", "Potatoes"]},
    {"ingredient_id": "cabbage", "name_zh": "卷心菜", "kind": "vegetable", "ner_terms": ["cabbage", "red cabbage"], "off_tags": ["en:cabbages", "en:red-cabbages"], "off_main_categories": ["Red cabbage", "Cabbages"]},
    {"ingredient_id": "broccoli", "name_zh": "西兰花", "kind": "vegetable", "ner_terms": ["broccoli"], "off_tags": ["en:broccolis"], "off_main_categories": ["Broccolis"]},
    {"ingredient_id": "cucumber", "name_zh": "黄瓜", "kind": "vegetable", "ner_terms": ["cucumber", "cucumbers"], "off_tags": ["en:cucumbers"], "off_main_categories": ["Cucumbers"]},
    {"ingredient_id": "mushroom", "name_zh": "蘑菇", "kind": "vegetable", "ner_terms": ["mushroom", "mushrooms"], "off_tags": ["en:fresh-mushrooms", "en:mushrooms"], "off_main_categories": ["Fresh mushrooms"]},
    {"ingredient_id": "garlic", "name_zh": "大蒜", "kind": "vegetable", "ner_terms": ["garlic"], "off_tags": ["en:fresh-garlic", "en:garlics"], "off_main_categories": ["Garlics", "Fresh garlic"]},
    {"ingredient_id": "bell_pepper", "name_zh": "青椒", "kind": "vegetable", "ner_terms": ["bell pepper", "green pepper", "peppers", "sweet pepper"], "off_tags": ["en:fresh-peppers", "en:bell-peppers", "en:sweet-peppers"], "off_main_categories": ["Fresh peppers", "Bell peppers", "Sweet peppers"]},
    {"ingredient_id": "celery", "name_zh": "芹菜", "kind": "vegetable", "ner_terms": ["celery"], "off_tags": ["en:celeries", "en:celery", "en:fresh-celery"], "off_main_categories": ["Celeries", "Celery"]},
    {"ingredient_id": "zucchini", "name_zh": "西葫芦", "kind": "vegetable", "ner_terms": ["zucchini", "courgette"], "off_tags": ["en:zucchinis"], "off_main_categories": ["Zucchinis"]},
    {"ingredient_id": "eggplant", "name_zh": "茄子", "kind": "vegetable", "ner_terms": ["eggplant", "aubergine"], "off_tags": ["en:eggplants"], "off_main_categories": ["Eggplants"]},
    {"ingredient_id": "chicken_breast", "name_zh": "鸡胸肉", "kind": "meat", "ner_terms": ["chicken breast", "chicken breasts", "boneless chicken breast"], "off_tags": ["en:chicken-breasts", "en:fresh-chicken-breasts"], "off_main_categories": ["Chicken breasts"]},
    {"ingredient_id": "chicken_thigh", "name_zh": "鸡腿", "kind": "meat", "ner_terms": ["chicken thigh", "chicken thighs", "chicken leg"], "off_tags": ["en:chicken-thighs"], "off_main_categories": ["Chicken thighs"]},
    {"ingredient_id": "ground_beef", "name_zh": "牛肉馅", "kind": "meat", "ner_terms": ["ground beef", "minced beef", "beef mince"], "off_tags": ["en:ground-beef", "en:ground-beef-steaks", "en:ground-beef-meats"], "off_main_categories": ["Ground beef steaks", "Ground beef meats", "Fresh ground beef steaks"]},
    {"ingredient_id": "beef_steak", "name_zh": "牛排", "kind": "meat", "ner_terms": ["beef steak", "steak", "sirloin", "ribeye"], "off_tags": ["en:beef-steaks", "en:steaks"], "off_main_categories": ["Beef steaks", "Steaks"]},
    {"ingredient_id": "pork", "name_zh": "猪肉", "kind": "meat", "ner_terms": ["pork", "pork chop", "pork loin", "pork shoulder"], "off_tags": ["en:fresh-pork", "en:pork"], "off_main_categories": ["Pork", "Fresh pork"]},
    {"ingredient_id": "lamb", "name_zh": "羊肉", "kind": "meat", "ner_terms": ["lamb", "lamb chop", "lamb leg"], "off_tags": ["en:fresh-lamb", "en:lamb"], "off_main_categories": ["Lamb", "Fresh lamb"]},
    {"ingredient_id": "salmon", "name_zh": "三文鱼", "kind": "seafood", "ner_terms": ["salmon"], "off_tags": ["en:salmon-fillets", "en:salmons", "en:fresh-salmon"], "off_main_categories": ["Salmon fillets", "Salmons"]},
    {"ingredient_id": "shrimp", "name_zh": "虾", "kind": "seafood", "ner_terms": ["shrimp", "shrimps", "prawn", "prawns"], "off_tags": ["en:shrimps", "en:fresh-shrimps", "en:prawns"], "off_main_categories": ["Shrimps", "Prawns"]},
    {"ingredient_id": "cod", "name_zh": "鳕鱼", "kind": "seafood", "ner_terms": ["cod", "cod fillet"], "off_tags": ["en:cods", "en:cod-fillets"], "off_main_categories": ["Cod fillets", "Cods"]},
    {"ingredient_id": "green_bean", "name_zh": "四季豆", "kind": "vegetable", "ner_terms": ["green bean", "green beans", "string bean"], "off_tags": ["en:green-beans", "en:fresh-green-beans"], "off_main_categories": ["Green beans"]},
    {"ingredient_id": "peas", "name_zh": "豌豆", "kind": "vegetable", "ner_terms": ["peas", "green peas"], "off_tags": ["en:peas", "en:fresh-peas"], "off_main_categories": ["Peas", "Fresh peas"], "aliases": ["green_pea"]},
    {"ingredient_id": "corn", "name_zh": "玉米", "kind": "vegetable", "ner_terms": ["corn", "sweet corn"], "off_tags": ["en:corn-on-the-cob", "en:sweet-corn"], "off_main_categories": ["Corn on the cob", "Sweet corn"]},
    {"ingredient_id": "ginger", "name_zh": "姜", "kind": "vegetable", "ner_terms": ["ginger", "fresh ginger"], "off_tags": ["en:ginger", "en:fresh-ginger"], "off_main_categories": ["Ginger"]},
    {"ingredient_id": "turkey", "name_zh": "火鸡", "kind": "meat", "ner_terms": ["turkey", "turkey breast"], "off_tags": ["en:turkey", "en:turkey-breasts"], "off_main_categories": ["Turkey", "Turkey breasts"]},
    {"ingredient_id": "duck", "name_zh": "鸭", "kind": "meat", "ner_terms": ["duck", "duck breast"], "off_tags": ["en:duck", "en:duck-breasts"], "off_main_categories": ["Duck", "Duck breasts"]},
    {"ingredient_id": "tuna", "name_zh": "金枪鱼", "kind": "seafood", "ner_terms": ["tuna", "tuna steak"], "off_tags": ["en:tuna", "en:tuna-steaks", "en:fresh-tuna"], "off_main_categories": ["Tuna", "Tuna steaks"]},
    {"ingredient_id": "scallop", "name_zh": "扇贝", "kind": "seafood", "ner_terms": ["scallop", "scallops"], "off_tags": ["en:scallops", "en:fresh-scallops"], "off_main_categories": ["Scallops"]},
    {"ingredient_id": "salt", "name_zh": "盐", "kind": "condiment", "ner_terms": ["salt"], "off_tags": ["en:salts", "en:sea-salt", "en:table-salt"], "off_main_categories": ["Salts", "Sea salt", "Table salt"]},
    {"ingredient_id": "black_pepper", "name_zh": "黑胡椒", "kind": "condiment", "ner_terms": ["black pepper", "pepper", "ground pepper"], "off_tags": ["en:black-peppers", "en:ground-peppers", "en:peppercorns"], "off_main_categories": ["Black peppers", "Ground peppers", "Peppercorns"]},
    {"ingredient_id": "soy_sauce", "name_zh": "酱油", "kind": "condiment", "ner_terms": ["soy sauce"], "off_tags": ["en:soy-sauces"], "off_main_categories": ["Soy sauces"]},
    {"ingredient_id": "vinegar", "name_zh": "醋", "kind": "condiment", "ner_terms": ["vinegar"], "off_tags": ["en:vinegars"], "off_main_categories": ["Vinegars"]},
    {"ingredient_id": "olive_oil", "name_zh": "橄榄油", "kind": "condiment", "ner_terms": ["olive oil"], "off_tags": ["en:olive-oils"], "off_main_categories": ["Olive oils"]},
    {"ingredient_id": "sesame_oil", "name_zh": "芝麻油", "kind": "condiment", "ner_terms": ["sesame oil"], "off_tags": ["en:sesame-oils"], "off_main_categories": ["Sesame oils"]},
    {"ingredient_id": "chili_sauce", "name_zh": "辣椒酱", "kind": "condiment", "ner_terms": ["chili sauce", "hot sauce", "chilli sauce"], "off_tags": ["en:hot-sauces", "en:chili-sauces", "en:chilli-sauces"], "off_main_categories": ["Hot sauces", "Chili sauces"]},
    {"ingredient_id": "oyster_sauce", "name_zh": "蚝油", "kind": "condiment", "ner_terms": ["oyster sauce"], "off_tags": ["en:oyster-sauces"], "off_main_categories": ["Oyster sauces"]},
    {"ingredient_id": "sugar", "name_zh": "糖", "kind": "condiment", "ner_terms": ["sugar", "white sugar", "brown sugar"], "off_tags": ["en:sugars", "en:granulated-sugars"], "off_main_categories": ["Sugars", "Granulated sugars"]},
    {"ingredient_id": "butter", "name_zh": "黄油", "kind": "condiment", "ner_terms": ["butter"], "off_tags": ["en:butters"], "off_main_categories": ["Butters"]},
    {"ingredient_id": "apple", "name_zh": "苹果", "kind": "fruit", "ner_terms": ["apple", "apples"], "off_tags": ["en:apples", "en:fresh-apples"], "off_main_categories": ["Apples", "Fresh apples"]},
    {"ingredient_id": "banana", "name_zh": "香蕉", "kind": "fruit", "ner_terms": ["banana", "bananas"], "off_tags": ["en:bananas"], "off_main_categories": ["Bananas"]},
    {"ingredient_id": "orange", "name_zh": "橙子", "kind": "fruit", "ner_terms": ["orange", "oranges"], "off_tags": ["en:oranges", "en:fresh-oranges"], "off_main_categories": ["Oranges"]},
    {"ingredient_id": "lemon", "name_zh": "柠檬", "kind": "fruit", "ner_terms": ["lemon", "lemons"], "off_tags": ["en:lemons", "en:fresh-lemons"], "off_main_categories": ["Lemons"]},
    {"ingredient_id": "strawberry", "name_zh": "草莓", "kind": "fruit", "ner_terms": ["strawberry", "strawberries"], "off_tags": ["en:strawberries"], "off_main_categories": ["Strawberries"]},
    {"ingredient_id": "grape", "name_zh": "葡萄", "kind": "fruit", "ner_terms": ["grape", "grapes"], "off_tags": ["en:grapes"], "off_main_categories": ["Grapes"]},
    {"ingredient_id": "blueberry", "name_zh": "蓝莓", "kind": "fruit", "ner_terms": ["blueberry", "blueberries"], "off_tags": ["en:blueberries"], "off_main_categories": ["Blueberries"]},
    {"ingredient_id": "mango", "name_zh": "芒果", "kind": "fruit", "ner_terms": ["mango", "mangoes", "mangos"], "off_tags": ["en:mangoes", "en:mangos"], "off_main_categories": ["Mangoes"]},
    {"ingredient_id": "pear", "name_zh": "梨", "kind": "fruit", "ner_terms": ["pear", "pears"], "off_tags": ["en:pears"], "off_main_categories": ["Pears"]},
    {"ingredient_id": "watermelon", "name_zh": "西瓜", "kind": "fruit", "ner_terms": ["watermelon", "watermelons"], "off_tags": ["en:watermelons"], "off_main_categories": ["Watermelons"]},
]

# Dish-namespace ingredients not in OFF 52 (or need distinct identity from parent class)
DISH_ENTRIES: list[dict] = [
    {"ingredient_id": "green_pea", "name_zh": "豌豆", "kind": "vegetable", "aliases": ["peas"], "ner_terms": ["green pea", "green peas", "peas"]},
    {"ingredient_id": "egg", "name_zh": "鸡蛋", "kind": "dairy", "ner_terms": ["egg", "eggs"]},
    {"ingredient_id": "rice", "name_zh": "大米", "kind": "staple", "ner_terms": ["rice"]},
    {"ingredient_id": "noodle", "name_zh": "面条", "kind": "staple", "ner_terms": ["noodle", "noodles", "pasta"]},
    {"ingredient_id": "flour", "name_zh": "面粉", "kind": "staple", "ner_terms": ["flour"]},
    {"ingredient_id": "tofu", "name_zh": "豆腐", "kind": "staple", "ner_terms": ["tofu"]},
    {"ingredient_id": "oil", "name_zh": "食用油", "kind": "condiment", "aliases": ["cooking_oil", "olive_oil"], "ner_terms": ["cooking oil", "vegetable oil", "oil"]},
    {"ingredient_id": "scallion", "name_zh": "葱", "kind": "vegetable", "ner_terms": ["scallion", "green onion", "spring onion"]},
    {"ingredient_id": "pork_ribs", "name_zh": "排骨", "kind": "meat", "ner_terms": ["pork ribs", "pork rib", "spare ribs"]},
    {"ingredient_id": "chicken_wing", "name_zh": "鸡翅", "kind": "meat", "ner_terms": ["chicken wing", "chicken wings"]},
    {"ingredient_id": "beef_slice", "name_zh": "牛肉片", "kind": "meat", "ner_terms": ["beef slice", "beef slices", "sliced beef"]},
    {"ingredient_id": "beef_brisket", "name_zh": "牛腩", "kind": "meat", "ner_terms": ["beef brisket", "brisket"]},
    {"ingredient_id": "wood_ear", "name_zh": "木耳", "kind": "vegetable", "ner_terms": ["wood ear", "black fungus"]},
    {"ingredient_id": "shiitake", "name_zh": "香菇", "kind": "vegetable", "ner_terms": ["shiitake", "shiitake mushroom"]},
    {"ingredient_id": "enoki_mushroom", "name_zh": "金针菇", "kind": "vegetable", "ner_terms": ["enoki", "enoki mushroom"]},
    {"ingredient_id": "baby_cabbage", "name_zh": "娃娃菜", "kind": "vegetable", "ner_terms": ["baby cabbage", "bok choy baby"]},
    {"ingredient_id": "bok_choy", "name_zh": "油菜", "kind": "vegetable", "ner_terms": ["bok choy", "pak choi"]},
    {"ingredient_id": "bean_sprout", "name_zh": "豆芽", "kind": "vegetable", "ner_terms": ["bean sprout", "bean sprouts"]},
    {"ingredient_id": "basil", "name_zh": "罗勒", "kind": "vegetable", "ner_terms": ["basil"]},
    {"ingredient_id": "cauliflower", "name_zh": "花椰菜", "kind": "vegetable", "ner_terms": ["cauliflower"]},
    {"ingredient_id": "chive", "name_zh": "韭菜", "kind": "vegetable", "ner_terms": ["chive", "chives", "garlic chive"]},
    {"ingredient_id": "dried_chili", "name_zh": "干辣椒", "kind": "condiment", "ner_terms": ["dried chili", "dried chilli", "dried pepper"]},
    {"ingredient_id": "fish_fillet", "name_zh": "鱼片", "kind": "seafood", "ner_terms": ["fish fillet", "fish fillets"]},
    {"ingredient_id": "hairtail", "name_zh": "带鱼", "kind": "seafood", "ner_terms": ["hairtail", "beltfish"]},
    {"ingredient_id": "ham", "name_zh": "火腿", "kind": "meat", "ner_terms": ["ham"]},
    {"ingredient_id": "peanut", "name_zh": "花生", "kind": "staple", "ner_terms": ["peanut", "peanuts"]},
    {"ingredient_id": "pickled_cabbage", "name_zh": "酸菜", "kind": "vegetable", "ner_terms": ["pickled cabbage", "sauerkraut"]},
    {"ingredient_id": "preserved_egg", "name_zh": "皮蛋", "kind": "dairy", "ner_terms": ["preserved egg", "century egg"]},
    {"ingredient_id": "radish", "name_zh": "白萝卜", "kind": "vegetable", "ner_terms": ["radish", "white radish", "daikon"]},
    {"ingredient_id": "sea_bass", "name_zh": "鲈鱼", "kind": "seafood", "ner_terms": ["sea bass", "bass"]},
    {"ingredient_id": "soy_milk", "name_zh": "豆浆", "kind": "beverage", "ner_terms": ["soy milk"]},
    {"ingredient_id": "tofu_skin", "name_zh": "豆腐皮", "kind": "staple", "ner_terms": ["tofu skin", "bean curd sheet"]},
    {"ingredient_id": "vermicelli", "name_zh": "粉丝", "kind": "staple", "ner_terms": ["vermicelli", "glass noodle"]},
    {"ingredient_id": "water_spinach", "name_zh": "空心菜", "kind": "vegetable", "ner_terms": ["water spinach", "morning glory"]},
    {"ingredient_id": "winter_melon", "name_zh": "冬瓜", "kind": "vegetable", "ner_terms": ["winter melon"]},
    {"ingredient_id": "youtiao", "name_zh": "油条", "kind": "staple", "ner_terms": ["youtiao", "fried dough stick"]},
    {"ingredient_id": "cola", "name_zh": "可乐", "kind": "beverage", "ner_terms": ["cola", "coke"]},
    {"ingredient_id": "shrimp_paste", "name_zh": "虾滑", "kind": "seafood", "ner_terms": ["shrimp paste"]},
    {"ingredient_id": "sour_soup_base", "name_zh": "酸汤底料", "kind": "condiment", "ner_terms": ["sour soup base"]},
    {"ingredient_id": "tripe", "name_zh": "毛肚", "kind": "meat", "ner_terms": ["tripe", "beef tripe"]},
    {"ingredient_id": "vanilla", "name_zh": "香草", "kind": "condiment", "ner_terms": ["vanilla", "vanilla extract"]},
    {"ingredient_id": "milk", "name_zh": "牛奶", "kind": "dairy", "ner_terms": ["milk"]},
    {"ingredient_id": "yeast", "name_zh": "酵母", "kind": "condiment", "ner_terms": ["yeast", "dry yeast"]},
    {"ingredient_id": "baking_powder", "name_zh": "泡打粉", "kind": "condiment", "ner_terms": ["baking powder"]},
    {"ingredient_id": "cream_cheese", "name_zh": "奶油奶酪", "kind": "dairy", "ner_terms": ["cream cheese"]},
    {"ingredient_id": "hotpot_base", "name_zh": "火锅底料", "kind": "condiment", "ner_terms": ["hot pot base", "hotpot base"]},
    {"ingredient_id": "hotpot_beef_roll", "name_zh": "肥牛卷", "kind": "meat", "ner_terms": ["beef roll", "sliced beef roll"]},
    {"ingredient_id": "lamb_slice", "name_zh": "羊肉卷", "kind": "meat", "ner_terms": ["lamb slice", "lamb roll"]},
    {"ingredient_id": "beef_neck", "name_zh": "吊龙牛肉", "kind": "meat", "ner_terms": ["beef neck", "diaolong"]},
]


def main() -> None:
    by_id: dict[str, dict] = {}
    for entry in OFF_ENTRIES + DISH_ENTRIES:
        iid = entry["ingredient_id"]
        if iid in by_id:
            raise SystemExit(f"duplicate ingredient_id: {iid}")
        by_id[iid] = {**entry, "aliases": entry.get("aliases", [])}
    payload = {
        "version": "v1",
        "description": "Canonical ingredient catalog (OFF 52 + dish namespace)",
        "ingredients": sorted(by_id.values(), key=lambda x: x["ingredient_id"]),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(payload['ingredients'])} ingredients to {OUT}")


if __name__ == "__main__":
    main()
