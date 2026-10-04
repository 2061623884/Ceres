from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SKU = "v1-seed-cli-source-only"


@pytest.mark.parametrize("fixture_only", [False, True])
def test_seed_runtime_fixture_only_skips_source_products(tmp_path, fixture_only):
    source_db = tmp_path / "source.sqlite3"
    with sqlite3.connect(source_db) as conn:
        conn.execute(
            """
            CREATE TABLE products (
                barcode TEXT PRIMARY KEY,
                name_en TEXT,
                name_zh TEXT,
                kind TEXT,
                brands TEXT,
                image_file TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
            (SOURCE_SKU, "Source Test Fruit", "来源测试水果", "fruit", "Test", None),
        )

    runtime_db = tmp_path / "runtime.sqlite3"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{runtime_db.as_posix()}"
    env["SOURCE_DATABASE_PATH"] = str(source_db)
    command = [sys.executable, str(ROOT / "scripts" / "seed_runtime.py")]
    if fixture_only:
        command.append("--fixture-only")

    subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)

    with sqlite3.connect(runtime_db) as conn:
        seeded_skus = {
            row[0] for row in conn.execute("SELECT sku_id FROM catalog_products")
        }

    fixture_skus = {
        product["sku_id"]
        for product in json.loads(
            (ROOT / "data" / "fixtures" / "demo-products.json").read_text(encoding="utf-8")
        )["products"]
    }
    assert fixture_skus <= seeded_skus
    assert (SOURCE_SKU in seeded_skus) is (not fixture_only)
