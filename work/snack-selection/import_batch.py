"""Import only the two approved simulated snack sales packages."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.catalog import CatalogProduct
from app.models.store import Offer
from scripts.seed_runtime import build_product_metadata

SKU_IDS = (
    "demo:snack-original-potato-chips-70g-bag",
    "demo:snack-soda-crackers-100g-box",
)
fixtures = ROOT / "data/fixtures"
products = {p["sku_id"]: p for p in json.loads((fixtures / "demo-products.json").read_text(encoding="utf-8"))["products"]}
offer_fixture = json.loads((fixtures / "store-offers.json").read_text(encoding="utf-8"))
offers = {row["sku_id"]: row for row in offer_fixture["offers"]}
store_id = offer_fixture["store"]["store_id"]
counts = {"catalog_added": 0, "offers_added": 0}

with SessionLocal() as db, db.begin():
    for sku_id in SKU_IDS:
        p = products[sku_id]
        if db.get(CatalogProduct, sku_id) is None:
            db.add(CatalogProduct(
                sku_id=sku_id,
                name=p["name"], name_zh=p["name_zh"], category_id=p["category_id"],
                ingredient_ids=json.dumps(p["ingredient_ids"], ensure_ascii=False),
                brand=p["brand"], image_path=p["image_path"], source=p["source"],
                review_status=p["review_status"], spec_quantity=p["spec_quantity"],
                spec_unit=p["spec_unit"], product_type=p["product_type"],
                usage_tags=json.dumps(p["usage_tags"], ensure_ascii=False),
                metadata_json=json.dumps(build_product_metadata(p), ensure_ascii=False),
            ))
            counts["catalog_added"] += 1
        if db.query(Offer).filter_by(store_id=store_id, sku_id=sku_id).one_or_none() is None:
            offer = offers[sku_id]
            db.add(Offer(store_id=store_id, sku_id=sku_id, price_fen=offer["price_fen"],
                         available_qty=offer["available_qty"], sellable=True,
                         offer_version=1, is_demo=offer["is_demo"]))
            counts["offers_added"] += 1

print(json.dumps({"database": str(get_settings().runtime_db_path.resolve()),
                  "store_id": store_id, "batch_size": len(SKU_IDS), **counts}, ensure_ascii=False))
