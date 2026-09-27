#!/usr/bin/env python3
"""Import a sample of fresh products and recipes into Sale-guide SQLite."""

from __future__ import annotations

import ast
import csv
import gzip
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sale_guide.db"
OFF_PATH = ROOT.parent / "reference/openfoodfacts/en.openfoodfacts.org.products.csv.gz"
RECIPE_PATH = ROOT.parent / "reference/recipenlg-data/RecipeNLG_dataset.csv"

MAX_PRODUCTS_PER_INGREDIENT = 5
MAX_RECIPES = 2000
MIN_RECIPE_INGREDIENT_HITS = 2
MIN_RECIPE_NER_COUNT = 4
MAX_RECIPE_NER_COUNT = 12

EXCLUDE_TAG_RE = re.compile(
    r"en:potato-crisps|en:chips|en:snacks|en:sausages|en:hams|en:canned-|"
    r"en:prepared-meats|en:cured-meats|en:instant-noodles|en:smoked-|"
    r"en:fruit-jellies|en:marshmallows",
    re.I,
)


@dataclass
class IngredientDef:
    name_norm: str
    name_zh: str
    kind: str
    ner_terms: list[str] = field(default_factory=list)
    off_tags: list[str] = field(default_factory=list)
    off_main_categories: list[str] = field(default_factory=list)


def _load_ingredient_catalog() -> list[IngredientDef]:
    """Load canonical ingredients from fixture JSON (single source of truth)."""
    catalog_path = DATA_DIR / "fixtures" / "ingredient-catalog.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog: list[IngredientDef] = []
    for item in data.get("ingredients", []):
        catalog.append(
            IngredientDef(
                name_norm=item["ingredient_id"],
                name_zh=item["name_zh"],
                kind=item["kind"],
                ner_terms=list(item.get("ner_terms") or []),
                off_tags=list(item.get("off_tags") or []),
                off_main_categories=list(item.get("off_main_categories") or []),
            )
        )
    return catalog


INGREDIENT_CATALOG: list[IngredientDef] = _load_ingredient_catalog()

NER_TO_NORM: dict[str, str] = {}
for item in INGREDIENT_CATALOG:
    for term in item.ner_terms:
        NER_TO_NORM[term.lower()] = item.name_norm


def normalize_ner(text: str) -> str | None:
    text = text.strip().lower()
    if text in NER_TO_NORM:
        return NER_TO_NORM[text]
    for term, norm in sorted(NER_TO_NORM.items(), key=lambda x: -len(x[0])):
        if term in text or text in term:
            return norm
    return None


def match_product_to_ingredient(tags: str, main_category: str) -> str | None:
    tags_lower = tags.lower()
    main_lower = (main_category or "").lower()

    def matches(item: IngredientDef) -> bool:
        if any(tag in tags_lower for tag in item.off_tags):
            return True
        return any(
            mc.lower() == main_lower or mc.lower() in main_lower
            for mc in item.off_main_categories
        )

    for item in INGREDIENT_CATALOG:
        if item.kind == "condiment" and matches(item):
            return item.name_norm

    if EXCLUDE_TAG_RE.search(tags_lower):
        return None

    for item in INGREDIENT_CATALOG:
        if item.kind != "condiment" and matches(item):
            return item.name_norm
    return None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        DROP TABLE IF EXISTS product_ingredient;
        DROP TABLE IF EXISTS recipe_ingredients;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS recipes;
        DROP TABLE IF EXISTS ingredient_catalog;

        CREATE TABLE ingredient_catalog (
            name_norm TEXT PRIMARY KEY,
            name_zh TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('vegetable', 'meat', 'seafood', 'fruit', 'condiment'))
        );

        CREATE TABLE products (
            barcode TEXT PRIMARY KEY,
            name_en TEXT,
            name_zh TEXT NOT NULL,
            kind TEXT NOT NULL,
            category_en TEXT,
            category_zh TEXT,
            brands TEXT,
            image_url TEXT,
            image_file TEXT
        );

        CREATE TABLE recipes (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT,
            link TEXT,
            ingredients_raw TEXT,
            directions_raw TEXT
        );

        CREATE TABLE recipe_ingredients (
            recipe_id INTEGER NOT NULL,
            name_en TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id),
            FOREIGN KEY (name_norm) REFERENCES ingredient_catalog(name_norm)
        );

        CREATE TABLE product_ingredient (
            barcode TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            PRIMARY KEY (barcode, name_norm),
            FOREIGN KEY (barcode) REFERENCES products(barcode),
            FOREIGN KEY (name_norm) REFERENCES ingredient_catalog(name_norm)
        );

        CREATE INDEX idx_products_kind ON products(kind);
        CREATE INDEX idx_recipe_ingredients_norm ON recipe_ingredients(name_norm);
        CREATE INDEX idx_product_ingredient_norm ON product_ingredient(name_norm);
        """
    )


def seed_catalog(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO ingredient_catalog (name_norm, name_zh, kind) VALUES (?, ?, ?)",
        [(i.name_norm, i.name_zh, i.kind) for i in INGREDIENT_CATALOG],
    )


def import_products(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {i.name_norm: 0 for i in INGREDIENT_CATALOG}
    if not OFF_PATH.exists():
        raise FileNotFoundError(f"OFF CSV not found: {OFF_PATH}")

    catalog_by_norm = {i.name_norm: i for i in INGREDIENT_CATALOG}
    csv.field_size_limit(sys.maxsize)

    with gzip.open(OFF_PATH, "rt", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if all(counts[n] >= MAX_PRODUCTS_PER_INGREDIENT for n in counts):
                break
            image_url = (row.get("image_url") or "").strip()
            if not image_url:
                continue
            tags = row.get("categories_tags") or ""
            main_cat = row.get("main_category_en") or row.get("main_category") or ""
            norm = match_product_to_ingredient(tags, main_cat)
            if not norm or counts[norm] >= MAX_PRODUCTS_PER_INGREDIENT:
                continue

            item = catalog_by_norm[norm]
            barcode = (row.get("code") or "").strip()
            if not barcode:
                continue
            name_en = (row.get("product_name") or "").strip()
            brands = (row.get("brands") or "").strip()
            name_zh = item.name_zh
            if brands and brands.lower() not in name_en.lower():
                name_zh = f"{brands} {item.name_zh}"

            conn.execute(
                """
                INSERT OR IGNORE INTO products
                (barcode, name_en, name_zh, kind, category_en, category_zh, brands, image_url, image_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    barcode,
                    name_en,
                    name_zh,
                    item.kind,
                    main_cat,
                    item.name_zh,
                    brands,
                    image_url,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO product_ingredient (barcode, name_norm) VALUES (?, ?)",
                (barcode, norm),
            )
            counts[norm] += 1

    return counts


def import_recipes(conn: sqlite3.Connection) -> int:
    if not RECIPE_PATH.exists():
        raise FileNotFoundError(f"Recipe CSV not found: {RECIPE_PATH}")

    imported = 0
    per_ingredient: dict[str, int] = {i.name_norm: 0 for i in INGREDIENT_CATALOG}

    with open(RECIPE_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if imported >= MAX_RECIPES:
                break
            if len(row) < 7:
                continue
            recipe_id = int(row[0])
            title = row[1]
            ingredients_raw = row[2]
            directions_raw = row[3]
            link = row[4]
            source = row[5]
            try:
                ner_list = ast.literal_eval(row[6]) if row[6] else []
            except (ValueError, SyntaxError):
                continue
            if not isinstance(ner_list, list):
                continue
            if not (MIN_RECIPE_NER_COUNT <= len(ner_list) <= MAX_RECIPE_NER_COUNT):
                continue

            matched: dict[str, str] = {}
            for ner in ner_list:
                if not isinstance(ner, str):
                    continue
                norm = normalize_ner(ner)
                if norm:
                    matched[norm] = ner

            if len(matched) < MIN_RECIPE_INGREDIENT_HITS:
                continue

            conn.execute(
                """
                INSERT INTO recipes (id, title, source, link, ingredients_raw, directions_raw)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (recipe_id, title, source, link, ingredients_raw, directions_raw),
            )
            for norm, ner in matched.items():
                conn.execute(
                    "INSERT INTO recipe_ingredients (recipe_id, name_en, name_norm) VALUES (?, ?, ?)",
                    (recipe_id, ner, norm),
                )
                per_ingredient[norm] += 1
            imported += 1

    return imported


def print_summary(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    product_count = cur.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    recipe_count = cur.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    kind_counts = cur.execute(
        "SELECT kind, COUNT(*) FROM products GROUP BY kind ORDER BY kind"
    ).fetchall()
    ingredient_product_counts = cur.execute(
        """
        SELECT ic.name_zh, ic.kind, COUNT(p.barcode) AS n
        FROM ingredient_catalog ic
        LEFT JOIN product_ingredient pi ON ic.name_norm = pi.name_norm
        LEFT JOIN products p ON p.barcode = pi.barcode
        GROUP BY ic.name_norm
        ORDER BY n DESC, ic.name_zh
        """
    ).fetchall()
    sample = cur.execute(
        """
        SELECT r.title, GROUP_CONCAT(ic.name_zh, '、')
        FROM recipes r
        JOIN recipe_ingredients ri ON r.id = ri.recipe_id
        JOIN ingredient_catalog ic ON ic.name_norm = ri.name_norm
        WHERE ri.name_norm IN ('tomato', 'chicken_breast')
        GROUP BY r.id
        HAVING COUNT(DISTINCT ri.name_norm) >= 2
        LIMIT 3
        """
    ).fetchall()

    print(f"DB: {DB_PATH}")
    print(f"products: {product_count}")
    print(f"recipes: {recipe_count}")
    print("products by kind:", dict(kind_counts))
    print("ingredients with product counts (top 10):")
    for name_zh, kind, n in ingredient_product_counts[:10]:
        print(f"  {name_zh} ({kind}): {n}")
    zero_products = [row for row in ingredient_product_counts if row[2] == 0]
    if zero_products:
        print(f"ingredients with 0 products: {len(zero_products)}")
    print("sample recipes matching tomato + chicken_breast:")
    for title, ings in sample:
        print(f"  - {title[:60]} | {ings}")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)
        seed_catalog(conn)
        conn.commit()

        print("Importing products from Open Food Facts...")
        product_counts = import_products(conn)
        conn.commit()
        filled = sum(1 for c in product_counts.values() if c > 0)
        print(f"  ingredients with products: {filled}/{len(product_counts)}")
        print(f"  total product slots used: {sum(product_counts.values())}")

        print("Importing recipes from RecipeNLG...")
        recipe_count = import_recipes(conn)
        conn.commit()
        print(f"  recipes imported: {recipe_count}")

        print_summary(conn)

        meta = {
            "max_products_per_ingredient": MAX_PRODUCTS_PER_INGREDIENT,
            "max_recipes": MAX_RECIPES,
            "ingredient_count": len(INGREDIENT_CATALOG),
            "product_count": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "recipe_count": conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0],
        }
        (DATA_DIR / "import_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
