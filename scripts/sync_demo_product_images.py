#!/usr/bin/env python3
"""Copy or keep raster demo product photos for sellable demo SKUs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image

from app.services.image_assets import CORE_DEMO_IMAGE_FILES, is_raster_image_path

FIXTURES = ROOT / "data" / "fixtures"
IMAGES = ROOT / "data" / "images"
SIZE = 400

# Explicit sku_id -> source barcode jpg in data/images (verified product match).
SOURCE_COPY: dict[str, str] = {
    "demo:pork-500g": "00025744.jpg",
    "demo:salt-500g": "0000420200000.jpg",
    "demo:soy-sauce-500ml": "00012447.jpg",
    "demo:cooking-oil-500ml": "00000356.jpg",
    "demo:bell-pepper-300g": "00004688.jpg",
    "demo:tomato-fresh-500g": "00004087.jpg",
    "demo:chicken-breast-500g": "00000881.jpg",
    "demo:scallion-200g": "00001373.jpg",
    "demo:peanut-200g": "00000231.jpg",
}

# Curated carton photo used only to derive a distinct 6-pack file (not shared path).
EGG_6PACK_SOURCE = "demo-eggs-10pack.jpg"

# These SKUs have no matching source-barcode photo; keep curated rasters on disk.
# Do not regenerate text-block packaging cards over them.
CURATED_RASTER_SKUS: tuple[str, ...] = (
    "demo:milk-1l",
    "demo:tofu-firm-400g",
    "demo:noodles-500g",
    "demo:soy-milk-1l",
    "demo:rice-2kg",
    "demo:sparkling-water-500ml",
    "demo:green-tea-500ml",
)


def _resize_copy(src: Path, dest: Path) -> None:
    with Image.open(src) as im:
        im = im.convert("RGB")
        im = ImageOps_contain(im, (SIZE, SIZE))
        canvas = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        x = (SIZE - im.width) // 2
        y = (SIZE - im.height) // 2
        canvas.paste(im, (x, y))
        dest.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dest, format="JPEG", quality=88)


def ImageOps_contain(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    im.thumbnail(size, Image.Resampling.LANCZOS)
    return im


def demo_filename(sku_id: str) -> str:
    return f"demo-{sku_id.removeprefix('demo:')}.jpg"


def _sync_egg_6pack() -> tuple[str, str]:
    dest = IMAGES / demo_filename("demo:eggs-fresh-6pack")
    src = IMAGES / EGG_6PACK_SOURCE
    if not src.is_file():
        raise FileNotFoundError(f"Missing 6-pack egg source image: {src}")
    _resize_copy(src, dest)
    return ("demo:eggs-fresh-6pack", f"data/images/{dest.name}")


def sync_images() -> list[tuple[str, str]]:
    updated: list[tuple[str, str]] = []
    for sku_id, source_name in SOURCE_COPY.items():
        dest = IMAGES / demo_filename(sku_id)
        src = IMAGES / source_name
        if not src.is_file():
            raise FileNotFoundError(f"Missing source image for {sku_id}: {src}")
        _resize_copy(src, dest)
        updated.append((sku_id, f"data/images/{dest.name}"))

    updated.append(_sync_egg_6pack())

    for sku_id in CURATED_RASTER_SKUS:
        dest = IMAGES / demo_filename(sku_id)
        rel = f"data/images/{dest.name}"
        if not is_raster_image_path(rel, ROOT):
            raise FileNotFoundError(f"Missing curated raster for {sku_id}: {dest}")
        if dest.stat().st_size < 20000:
            raise ValueError(f"Curated raster for {sku_id} looks like a placeholder: {dest}")
        updated.append((sku_id, rel))

    return updated


def validate_demo_fixtures() -> list[str]:
    demo = json.loads((FIXTURES / "demo-products.json").read_text(encoding="utf-8"))
    offers = {
        o["sku_id"]
        for o in json.loads((FIXTURES / "store-offers.json").read_text(encoding="utf-8"))["offers"]
    }
    errors: list[str] = []
    for product in demo["products"]:
        sku = product["sku_id"]
        if sku not in offers:
            continue
        path = product.get("image_path") or ""
        if not is_raster_image_path(path, ROOT):
            errors.append(f"{sku}: missing raster image_path ({path or 'empty'})")
        base = Path(path).name.lower() if path else ""
        if base in CORE_DEMO_IMAGE_FILES and sku in CURATED_RASTER_SKUS:
            errors.append(f"{sku}: core SKU must not use generated packaging image")
        if sku in CURATED_RASTER_SKUS:
            dest = ROOT / path
            if dest.is_file() and dest.stat().st_size < 20000:
                errors.append(f"{sku}: curated raster looks like a placeholder ({path})")
    return errors


def update_fixture_paths() -> None:
    demo_path = FIXTURES / "demo-products.json"
    data = json.loads(demo_path.read_text(encoding="utf-8"))
    offers = {
        o["sku_id"]
        for o in json.loads((FIXTURES / "store-offers.json").read_text(encoding="utf-8"))["offers"]
    }
    for product in data["products"]:
        sku = product["sku_id"]
        if sku not in offers:
            continue
        product["image_path"] = f"data/images/{demo_filename(sku)}"
    demo_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    sync_images()
    update_fixture_paths()
    errors = validate_demo_fixtures()
    if errors:
        raise SystemExit("demo fixture validation failed:\n" + "\n".join(errors))
    print(f"Synced {len(SOURCE_COPY) + len(CURATED_RASTER_SKUS) + 1} demo product images")


if __name__ == "__main__":
    main()
