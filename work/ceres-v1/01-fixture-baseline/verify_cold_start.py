"""Reconstruct the declared source and verify two independent empty databases."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
manifest = json.loads((OUT / "frozen-inputs.json").read_text(encoding="utf-8"))
archive = OUT / "source-base.zip"
subprocess.run([
    "git", "-c", "filter.lfs.process=", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false",
    "archive", manifest["base_commit"], "--format=zip", f"--output={archive}",
    "backend/app", "backend/pyproject.toml", "scripts", "Mercury/mercury", "frontend", "data/fixtures",
], cwd=ROOT, check=True)
products = json.loads((OUT / "frozen-fixtures/demo-products.json").read_text(encoding="utf-8"))["products"]
explicit_offers = json.loads((OUT / "frozen-fixtures/store-offers.json").read_text(encoding="utf-8"))["offers"]
fixture_skus = sorted(product["sku_id"] for product in products)
receipts = []
for repetition in (1, 2):
    checkout = OUT / f"cold-start-{repetition}" / "Ceres"
    checkout.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(checkout)
    subprocess.run(["git", "apply", f"--directory={checkout.relative_to(ROOT).as_posix()}",
                    str(OUT / "runtime-baseline.patch")], cwd=ROOT, check=True)
    for relative in ("scripts/seed_runtime.py", "backend/app/api/mercury.py"):
        shutil.copyfile(ROOT / relative, checkout / relative)
    for fixture in (OUT / "frozen-fixtures").glob("*.json"):
        shutil.copyfile(fixture, checkout / "data/fixtures" / fixture.name)
    for product in products:
        if product["image_path"]:
            destination = checkout / product["image_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / product["image_path"], destination)
    for relative, expected_hash in manifest["runtime_source_hashes"].items():
        actual_hash = hashlib.sha256((checkout / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        assert actual_hash == expected_hash, relative
    runtime = checkout / "data/runtime-v1-fixture/sale_guide.sqlite3"
    env = dict(os.environ)
    env.update(DATABASE_URL=f"sqlite:///{runtime.as_posix()}", SOURCE_DATABASE_PATH=str(ROOT / "data/sale_guide.db"),
               PYTHONPATH=str(checkout / "backend"), RETRIEVAL_INDEX_DIR="", RETRIEVAL_MODE="hybrid")
    seeded = subprocess.run([sys.executable, "-X", "utf8", str(checkout / "scripts/seed_runtime.py"), "--fixture-only"],
                            cwd=checkout, env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    assert "source=0" in seeded.stdout
    smoke = subprocess.run([sys.executable, "-X", "utf8", "-c", """
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
import mercury
assert Path(mercury.__file__).resolve().is_relative_to(Path.cwd())
with TestClient(app) as client:
    health = client.get('/health')
    bootstrap = client.get('/api/v1/bootstrap')
    product = client.get('/api/v1/products/demo:cn-minute-maid-peach-450ml-bottle')
    cart = client.get('/api/v1/cart')
    assert health.status_code == bootstrap.status_code == product.status_code == cart.status_code == 200
    assert health.json()['database'] == 'connected'
    assert health.json()['retrieval']['reason'] == 'RETRIEVAL_NOT_CONFIGURED'
    assert bootstrap.json()['store_id'] == 'store-demo-01'
    item = product.json()
    assert item['category_id'] == 'beverage' and item['spec_quantity'] == 450 and item['spec_unit'] == 'ml'
    assert item['price_fen'] == 450 and item['available_qty'] == 30 and item['sellable']
    assert item['ingredient_ids'] == [] and item['metadata']['allergens']['status'] == 'unknown'
    assert cart.json()['items'] == []
    print(json.dumps({'health': health.json(), 'bootstrap_notice': bootstrap.json()['demo_notice'], 'product': item, 'cart': cart.json()}, ensure_ascii=False))
"""], cwd=checkout, env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    with sqlite3.connect(f"file:{runtime.as_posix()}?mode=ro", uri=True) as connection:
        actual_skus = [row[0] for row in connection.execute("SELECT sku_id FROM catalog_products ORDER BY sku_id")]
        assert actual_skus == fixture_skus
        offers = connection.execute("SELECT sku_id, store_id, price_fen, available_qty, sellable, is_demo FROM offers ORDER BY sku_id").fetchall()
        assert len(offers) == len(products)
        assert all(row[-1] for row in offers)
        template_counts = dict(connection.execute("SELECT source, count(*) FROM purchase_templates GROUP BY source"))
        assert template_counts['chinese-dishes-v1'] == 105
        template_total = connection.execute("SELECT count(*) FROM purchase_templates").fetchone()[0]
        assert template_total == 111
        static_products = connection.execute("SELECT sku_id, name, name_zh, category_id, ingredient_ids, usage_tags, brand, spec_quantity, spec_unit, product_type, metadata_json FROM catalog_products ORDER BY sku_id").fetchall()
    projected = subprocess.run([sys.executable, "-X", "utf8", "-c", """
import json
from app.services.retrieval_projection import build_projection
from app.core.config import get_settings
projection, dictionary = build_projection(get_settings().runtime_db_path)
juice = next(doc for doc in projection.docs if doc.target_id == 'demo:cn-minute-maid-peach-450ml-bottle')
assert '果汁' in juice.text and '甜而不腻' in juice.text
print(json.dumps({'documents': len(projection.docs), 'snapshot': projection.snapshot, 'hashes': projection.doc_hashes, 'juice_text': juice.text}, ensure_ascii=False))
"""], cwd=checkout, env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    projection = json.loads(projected.stdout)
    assert projection['documents'] == 170
    fingerprint = hashlib.sha256(json.dumps([static_products, offers, projection['hashes']], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = {'repetition': repetition, 'seed_stdout': seeded.stdout.strip(), 'products': len(actual_skus),
               'offers': len(offers), 'explicit_offers': len(explicit_offers), 'generated_offers': len(offers)-len(explicit_offers),
               'templates': template_total, 'projection': projection, 'logical_fingerprint': fingerprint,
               'startup': json.loads(smoke.stdout), 'checkout': str(checkout), 'runtime_db': str(runtime)}
    (OUT / f"cold-start-{repetition}.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipts.append(receipt)
    print(json.dumps({key: receipt[key] for key in ('repetition', 'seed_stdout', 'products', 'offers', 'templates', 'logical_fingerprint')}, ensure_ascii=False))
assert receipts[0]['logical_fingerprint'] == receipts[1]['logical_fingerprint']
print('Two independent cold starts match; vector and live-model validation are pending subsequent tasks.')
