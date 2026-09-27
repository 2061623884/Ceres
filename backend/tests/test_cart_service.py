"""Cart API tests."""

def test_add_to_cart(client):
    products = client.get("/api/v1/products", params={"category_id": "baking"}).json()["items"]
    sku = products[0]["sku_id"]
    resp = client.post("/api/v1/cart/items", json={"sku_id": sku, "quantity": 1, "expected_cart_version": 0})
    assert resp.status_code == 200
    cart = resp.json()
    assert cart["total_price_fen"] > 0
    assert any(i["sku_id"] == sku for i in cart["items"])
