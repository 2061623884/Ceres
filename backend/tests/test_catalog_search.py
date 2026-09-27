"""Catalog search tests."""

def test_list_products(client):
    resp = client.get("/api/v1/products")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    assert len(data["items"]) > 0


def test_baking_category(client):
    resp = client.get("/api/v1/products", params={"category_id": "baking"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 9


def test_refresh_demo_product_images_overwrites_svg(client, test_db_url):
    from sqlalchemy import create_engine, text

    from app.core.database import refresh_demo_product_images

    engine = create_engine(test_db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE catalog_products SET image_path = 'demo/ingredients/tomato.svg' "
                "WHERE sku_id = 'demo:tomato-fresh-500g'"
            )
        )
    refresh_demo_product_images(engine)
    resp = client.get("/api/v1/products/demo:tomato-fresh-500g")
    assert resp.status_code == 200
    assert str(resp.json().get("image_path") or "").endswith("demo-tomato-fresh-500g.jpg")


def test_baking_products_use_raster_catalog_images(client):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    raster = {".jpg", ".jpeg", ".png", ".webp"}
    resp = client.get("/api/v1/products", params={"category_id": "baking", "page_size": 24})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 9
    missing = []
    for product in items:
        image_path = product.get("image_path") or ""
        suffix = Path(image_path).suffix.lower()
        file_path = root / image_path
        if suffix not in raster or not file_path.is_file():
            missing.append((product["sku_id"], image_path))
    assert missing == [], f"baking SKUs missing raster images: {missing}"


def test_quarantined_not_listed(client):
    resp = client.get("/api/v1/products/00000231")
    assert resp.status_code == 404
    resp2 = client.get("/api/v1/products/00000622")
    assert resp2.status_code == 404


def test_quarantined_skus_excluded_from_search(client):
    resp = client.get("/api/v1/products", params={"q": "butter"})
    assert resp.status_code == 200
    ids = {item["sku_id"] for item in resp.json()["items"]}
    assert "00000231" not in ids
    resp2 = client.get("/api/v1/products", params={"q": "banana"})
    ids2 = {item["sku_id"] for item in resp2.json()["items"]}
    assert "00000622" not in ids2


def test_product_detail_includes_metadata_http(client):
    resp = client.get("/api/v1/products/demo:tomato-fresh-500g")
    assert resp.status_code == 200
    body = resp.json()
    assert "metadata" in body
    assert isinstance(body["metadata"], dict)
    assert "image_status" in body["metadata"]
    assert "provenance" in body["metadata"]


def test_product_list_includes_metadata_http(client):
    resp = client.get("/api/v1/products", params={"q": "新鲜番茄", "page_size": 10})
    assert resp.status_code == 200
    items = resp.json()["items"]
    tomato = next((i for i in items if i["sku_id"] == "demo:tomato-fresh-500g"), None)
    assert tomato is not None
    assert "metadata" in tomato
    assert isinstance(tomato["metadata"], dict)
