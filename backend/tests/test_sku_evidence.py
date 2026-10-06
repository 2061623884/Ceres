import json
from pathlib import Path

from app.services.retrieval_service import RetrievalFilters, _sku_evidence, _unknown_constraints


ROOT = Path(__file__).resolve().parents[2]


def test_peach_drink_evidence_includes_verified_category_type_and_taste_tags():
    products = json.loads((ROOT / "data/fixtures/demo-products.json").read_text(encoding="utf-8"))["products"]
    product = next(row for row in products if row["sku_id"] == "demo:cn-minute-maid-peach-450ml-bottle")
    payload = {key: product.get(key) for key in (
        "category_id", "product_type", "spec_quantity", "spec_unit", "usage_tags",
    )}

    evidence = _sku_evidence({"name": product["name_zh"]}, payload, "fused")

    assert len(evidence) <= 3
    assert all(len(item) <= 120 for item in evidence)
    assert any("beverage" in item and "juice_drink" in item for item in evidence)
    assert any("甜味" in item and "甜而不腻" in item for item in evidence)


def test_sugar_content_query_marks_nutrition_as_unknown():
    assert "nutrition" in _unknown_constraints(
        "想喝低糖的果汁，有糖含量数据吗？", RetrievalFilters(), "sku"
    )
