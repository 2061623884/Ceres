"""Demo store SKU picking prefers raster demo photos."""

from __future__ import annotations

from app.services.template_plan_service import TemplatePlanService


def test_pick_sku_prefers_raster_demo_over_source(db_session):
    service = TemplatePlanService(db_session)
    candidates = [
        {
            "sku_id": "demo:pork-500g",
            "sellable": True,
            "price_fen": 1980,
            "image_path": "data/images/demo-pork-500g.jpg",
        },
        {
            "sku_id": "00000680",
            "sellable": True,
            "price_fen": 1500,
            "image_path": "data/images/00000680.jpg",
        },
    ]
    picked = service._pick_sku(candidates)
    assert picked["sku_id"] == "demo:pork-500g"


def test_pick_sku_falls_back_to_source_when_demo_missing_raster(db_session):
    service = TemplatePlanService(db_session)
    candidates = [
        {
            "sku_id": "demo:pork-500g",
            "sellable": True,
            "price_fen": 1980,
            "image_path": None,
        },
        {
            "sku_id": "00000680",
            "sellable": True,
            "price_fen": 1500,
            "image_path": "data/images/00000680.jpg",
        },
    ]
    picked = service._pick_sku(candidates)
    assert picked["sku_id"] == "00000680"
