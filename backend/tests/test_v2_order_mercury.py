"""The independent cart checkout persists this owner's simulated order."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core import database as db_module
from app.core.config import get_settings

from support.v2_fixture import source_database_path


@pytest.mark.parametrize("run", [1, 2])
def test_checkout_persists_exact_cart_and_clears_it(client, run):
    added = client.post("/api/v1/cart/items", json={
        "sku_id": "demo:eggs-fresh-6pack", "quantity": 2, "expected_cart_version": 0,
    })
    assert added.status_code == 200, added.json()
    cart = added.json()
    response = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]})
    assert response.status_code == 200, response.json()
    result = response.json()
    order = result["order"]
    assert order["order_id"]
    assert order["status"] == "paid"
    assert order["total_fen"] == cart["total_price_fen"]
    assert [{k: item[k] for k in ("sku_id", "product_name", "quantity", "unit_price_fen")}
            for item in order["items"]] == [
                {"sku_id": item["sku_id"], "product_name": item["name"],
                 "quantity": item["quantity"], "unit_price_fen": item["unit_price_fen"]}
                for item in cart["items"]]
    assert result["cart"]["items"] == []
    assert result["cart"]["version"] == cart["version"] + 1
    assert client.get("/api/v1/cart").json() == result["cart"]
    assert client.get(f"/api/v1/orders/{order['order_id']}").json() == order
    assert client.get("/api/v1/orders").json()["items"] == [order]


@pytest.mark.parametrize("run", [1, 2])
def test_mercury_selects_and_queries_this_owners_real_order(client, monkeypatch, run):
    cart = client.post("/api/v1/cart/items", json={
        "sku_id": "demo:eggs-fresh-6pack", "quantity": 2, "expected_cart_version": 0,
    }).json()
    order = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"]
    session = client.post("/api/v1/mercury/sessions").json()
    sid = session["session_id"]
    assert session["selected_order_id"] is None
    selected = client.post(f"/api/v1/mercury/sessions/{sid}/order", json={"order_id": order["order_id"]})
    assert selected.status_code == 200, selected.json()
    assert selected.json() == {"session_id": sid, "order": order}
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0

    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()

    def create(**kwargs):
        assert kwargs["model"] == "controlled-mercury"
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="", tool_calls=[SimpleNamespace(id="read-order", function=SimpleNamespace(
                    name="get_order_details", arguments=json.dumps({"order_id": order["order_id"]}))) ]))])
        facts = json.loads(messages[-1]["content"])
        assert facts["ok"] is True and facts["data"]["order_id"] == order["order_id"]
        assert facts["data"]["total"] == "19.60"
        assert facts["data"]["items"][0]["quantity"] == 2
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=f"{order['order_id']} 买了两盒鸡蛋，成交总价19.60元，模拟订单未发货。", tool_calls=[]))])

    def fake_openai(**settings):
        assert settings["base_url"] == "http://controlled-mercury.invalid/v1"
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr("mercury.llm.OpenAI", fake_openai)
    streamed = client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream",
                          json={"message": "这一单买了什么？", "request_id": f"query-{run}"})
    assert streamed.status_code == 200, streamed.text
    assert order["order_id"] in streamed.text and "19.60" in streamed.text
    assert "服务暂时不可用" not in streamed.text
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0
    assert client.get("/api/v1/cart").json()["items"] == []
    another = client.post("/api/v1/mercury/sessions").json()["session_id"]
    assert client.post(f"/api/v1/mercury/sessions/{another}/order", json={"order_id": order["order_id"]}).json()["order"] == order
    client.cookies.clear()
    assert client.get("/api/v1/orders").json()["items"] == []
    assert client.get(f"/api/v1/orders/{order['order_id']}").status_code == 404
    assert client.post(f"/api/v1/mercury/sessions/{sid}/order", json={"order_id": order["order_id"]}).status_code == 404
    assert client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream", json={"message": "查询", "request_id": "foreign"}).status_code == 404


@pytest.mark.parametrize("run", [1, 2])
def test_checkout_rejects_stale_or_empty_without_partial_order(client, run):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 2}).json()
    updated = client.patch("/api/v1/cart/items/demo:eggs-fresh-6pack", json={
        "quantity": 3, "expected_cart_version": cart["version"]}).json()
    stale = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_STATE"
    assert client.get("/api/v1/cart").json() == updated
    assert client.get("/api/v1/orders").json()["items"] == []
    success = client.post("/api/v1/cart/checkout", json={"expected_cart_version": updated["version"]}).json()
    assert success["order"]["items"][0]["quantity"] == 3
    empty = client.post("/api/v1/cart/checkout", json={"expected_cart_version": success["cart"]["version"]})
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "EMPTY_CART"
    assert client.get("/api/v1/orders").json()["items"] == [success["order"]]


@pytest.mark.parametrize("run", [1, 2])
def test_checkout_failure_rolls_back_order_and_cart_together(client, run):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 2}).json()
    with db_module.SessionLocal() as db:
        db.execute(text("CREATE TRIGGER fail_order_item BEFORE INSERT ON order_items "
                        "BEGIN SELECT RAISE(ABORT, 'controlled order storage failure'); END"))
        db.commit()
    with pytest.raises(IntegrityError, match="controlled order storage failure"):
        client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]})
    assert client.get("/api/v1/cart").json() == cart
    assert client.get("/api/v1/orders").json()["items"] == []


@pytest.mark.parametrize("run", [1, 2])
def test_order_snapshot_and_existing_policy_survive_reinitialization(client, run):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 2}).json()
    order = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"]
    client.post("/api/v1/mercury/sessions")
    with db_module.SessionLocal() as db:
        db.execute(text("UPDATE catalog_products SET name_zh='商品资料已更新' WHERE sku_id='demo:eggs-fresh-6pack'"))
        db.execute(text("UPDATE offers SET price_fen=9999 WHERE sku_id='demo:eggs-fresh-6pack'"))
        db.execute(text("UPDATE policies SET content='已核本地政策' WHERE policy_id='P-REF-01'"))
        db.commit()
    db_module.init_db()
    session = client.post("/api/v1/mercury/sessions")
    assert session.status_code == 200, session.json()
    assert client.get(f"/api/v1/orders/{order['order_id']}").json() == order
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM catalog_products")).scalar_one() == 65
        assert db.execute(text("SELECT COUNT(*) FROM policies")).scalar_one() == 6
        assert db.execute(text("SELECT content FROM policies WHERE policy_id='P-REF-01'")).scalar_one() == "已核本地政策"


@pytest.mark.parametrize("run", [1, 2])
def test_no_selected_order_returns_real_id_options_without_order_tool_or_write(client, monkeypatch, run):
    cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": 2}).json()
    order = client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"]
    sid = client.post("/api/v1/mercury/sessions").json()["session_id"]

    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()

    def create(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            message = SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="unselected-order",
                function=SimpleNamespace(name="get_order_details", arguments=json.dumps({"order_id": order["order_id"]})))])
        else:
            result = json.loads(messages[-1]["content"])
            assert result["error"] == "ORDER_NOT_SELECTED"
            message = SimpleNamespace(content="请选择要咨询的订单；一般政策无需选单。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **settings:
                        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    response = client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream",
                           json={"message": "我想退款", "request_id": f"no-selection-{run}"})
    payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert next(p["items"] for p in payloads if "items" in p) == [order]
    assert any("请选择" in p.get("final_text", "") for p in payloads)
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0
    client.cookies.clear()
    stranger_sid = client.post("/api/v1/mercury/sessions").json()["session_id"]
    response = client.post(f"/api/v1/mercury/sessions/{stranger_sid}/turns/stream",
                           json={"message": "看我的订单", "request_id": "new-owner"})
    assert order["order_id"] not in response.text and "O1001" not in response.text
    payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert next(p["items"] for p in payloads if "items" in p) == []


@pytest.mark.parametrize("run", [1, 2])
@pytest.mark.parametrize("write_tool", ["create_refund", "create_return"])
def test_explicit_aftersale_uses_selected_order_and_existing_eligibility(client, monkeypatch, run, write_tool):
    orders = []
    for quantity in [2, 1]:
        cart = client.post("/api/v1/cart/items", json={"sku_id": "demo:eggs-fresh-6pack", "quantity": quantity}).json()
        orders.append(client.post("/api/v1/cart/checkout", json={"expected_cart_version": cart["version"]}).json()["order"])
    chosen, other = orders
    sid = client.post("/api/v1/mercury/sessions").json()["session_id"]
    assert client.post(f"/api/v1/mercury/sessions/{sid}/order", json={"order_id": chosen["order_id"]}).status_code == 200
    mode = "wrong-order"
    monkeypatch.setenv("OPENAI_BASE_URL", "http://controlled-mercury.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "controlled-test-key")
    monkeypatch.setenv("LLM_MODEL", "controlled-mercury")
    get_settings.cache_clear()

    def create(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            name = "get_order_details" if mode == "wrong-order" else write_tool
            args = {"order_id": other["order_id"] if mode == "wrong-order" else chosen["order_id"]}
            if name == "create_return":
                args["item_id"] = chosen["items"][0]["item_id"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[
                SimpleNamespace(id=f"tool-{mode}", function=SimpleNamespace(name=name, arguments=json.dumps(args))) ]))])
        result = json.loads(messages[-1]["content"])
        if mode == "wrong-order":
            assert result["error"] == "ORDER_NOT_SELECTED"
            answer = "只能咨询当前选定订单，请先重新选单。"
        elif write_tool == "create_refund":
            assert result["ok"] is True and result["data"]["order_id"] == chosen["order_id"]
            assert result["data"]["status"] == "pending" and result["data"]["amount"] == "19.60"
            answer = "这笔模拟订单退款申请已提交，处理中，尚未到账。"
        else:
            assert result["error"] == "NOT_DELIVERED"
            answer = "这笔模拟订单未签收，不能申请退货。"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer, tool_calls=[]))])

    monkeypatch.setattr("mercury.llm.OpenAI", lambda **settings: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    wrong = client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream",
                        json={"message": "查询当前订单", "request_id": "wrong-model-id"})
    assert "重新选单" in wrong.text
    with db_module.SessionLocal() as db:
        assert db.execute(text("SELECT COUNT(*) FROM refunds")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0
    mode = "explicit-write"
    requested = client.post(f"/api/v1/mercury/sessions/{sid}/turns/stream",
                            json={"message": "我要求这一单申请整单退款" if write_tool == "create_refund" else "我要求退这件商品",
                                  "request_id": f"write-{run}"})
    assert "服务暂时不可用" not in requested.text
    assert ("申请已提交" if write_tool == "create_refund" else "未签收") in requested.text
    with db_module.SessionLocal() as db:
        rows = db.execute(text("SELECT order_id, amount_fen, status FROM refunds")).all()
        assert rows == ([(chosen["order_id"], 1960, "pending")] if write_tool == "create_refund" else [])
        assert db.execute(text("SELECT COUNT(*) FROM returns")).scalar_one() == 0
    assert client.get(f"/api/v1/orders/{other['order_id']}").json() == other
