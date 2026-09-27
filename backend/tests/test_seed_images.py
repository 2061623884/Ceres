import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from seed_runtime import resolve_image_path, validate_sellable_demo_rasters


def test_resolve_image_path_strips_images_prefix():
    path = resolve_image_path("images/00000162.jpg")
    assert path == "data/images/00000162.jpg"


def test_resolve_image_path_bare_filename():
    path = resolve_image_path("00000162.jpg")
    assert path == "data/images/00000162.jpg"


def test_resolve_image_path_missing_file():
    assert resolve_image_path("missing-file.jpg") is None


def test_sellable_demo_products_have_raster_images():
    errors = validate_sellable_demo_rasters()
    assert errors == [], f"sellable demo raster gaps: {errors}"


def test_demo_baking_fixture_raster_files_exist():
    raster = {".jpg", ".jpeg", ".png", ".webp"}
    demo = json.loads((ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8"))
    offers = {
        o["sku_id"]
        for o in json.loads((ROOT / "data" / "fixtures" / "store-offers.json").read_text(encoding="utf-8"))[
            "offers"
        ]
    }
    missing = []
    for product in demo["products"]:
        if product["sku_id"] not in offers:
            continue
        if product.get("image_status") == "placeholder":
            continue
        meta = product.get("metadata") or {}
        if (meta.get("image_status") or {}).get("kind") == "placeholder":
            continue
        image_path = product.get("image_path") or ""
        suffix = Path(image_path).suffix.lower()
        file_path = ROOT / image_path
        if suffix not in raster or not file_path.is_file():
            missing.append((product["sku_id"], image_path))
    assert missing == [], f"demo fixture images missing: {missing}"
