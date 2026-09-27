#!/usr/bin/env python3
"""Read-only catalog audit."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = ROOT / "data" / "sale_guide.db"
    review_path = ROOT / "data" / "fixtures" / "catalog-review.json"
    images_dir = ROOT / "data" / "images"

    print("=== Sale-guide Catalog Audit ===")
    if not source.exists():
        print("ERROR: source DB missing")
        sys.exit(1)

    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    print(f"Source products: {total}")

    review = json.loads(review_path.read_text(encoding="utf-8"))
    quarantined = [i for i in review["items"] if i["status"] == "quarantined"]
    print(f"Quarantined in review map: {len(quarantined)}")
    for item in quarantined:
        row = conn.execute(
            "SELECT barcode, name_en, name_zh FROM products WHERE barcode=?",
            (item["source_barcode"],),
        ).fetchone()
        if row:
            print(f"  {row[0]}: {row[1]} / {row[2]} -> {item['reason']}")

    with_image = conn.execute(
        "SELECT COUNT(*) FROM products WHERE image_file IS NOT NULL AND image_file != ''"
    ).fetchone()[0]
    image_count = len(list(images_dir.glob("*.jpg"))) if images_dir.exists() else 0
    print(f"Products with image_file: {with_image}")
    print(f"Local images: {image_count}")

    demo_path = ROOT / "data" / "fixtures" / "demo-products.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    baking = [p for p in demo["products"] if p["category_id"] == "baking"]
    print(f"Demo baking SKUs: {len(baking)}")

    conn.close()
    print("Audit complete (read-only).")


if __name__ == "__main__":
    main()
