"""直接调用业务函数，不经过 LLM。"""

import pytest

from mercury import services as s

U1, U2 = "test_user_001", "test_user_002"


# ---------- 订单 ----------

def test_list_orders_only_own(db):
    ids = [o["order_id"] for o in s.list_orders(U1)["data"]]
    assert sorted(ids) == ["O1001", "O1002", "O1003", "O1004", "O1005"]
    assert "O2001" not in ids
    assert ids[0] == "O1003"  # created_at 倒序：20 分钟前下单的最新


def test_other_users_order_not_found(db):
    assert s.get_order_details(U1, order_id="O2001")["error"] == "ORDER_NOT_FOUND"


def test_order_details(db):
    data = s.get_order_details(U1, order_id="O1001")["data"]
    assert len(data["items"]) == 2
    apple = next(i for i in data["items"] if i["item_id"] == 1)
    assert apple["returnable"] is False
    assert data["total"] == "118.90"


# ---------- 物流 ----------

def test_delivery_shipping(db):
    data = s.get_delivery_status(U1, order_id="O1002")["data"]
    assert data["has_delivery"] is True
    assert data["status"] == "shipping"
    assert data["latest_description"] == "骑手已取货，正在配送中"


def test_delivery_none(db):
    data = s.get_delivery_status(U1, order_id="O1003")["data"]
    assert data["has_delivery"] is False
    assert data["order_status_text"] == "已支付，未发货"


# ---------- 退款 ----------

def test_refund_flow(db):
    check = s.check_refund_eligibility(U1, order_id="O1003")["data"]
    assert check["eligible"] is True and check["amount"] == "79.80"

    created = s.create_refund(U1, order_id="O1003")
    assert created["ok"] is True and created["data"]["status"] == "pending"
    rows = db("SELECT * FROM refunds WHERE order_id = 'O1003'")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending" and rows[0]["amount_fen"] == 7980
    assert rows[0]["reason"] == "未填写"
    assert rows[0]["refund_id"] == created["data"]["refund_id"]

    status = s.get_refund_status(U1, order_id="O1003")["data"]
    assert [r["status"] for r in status] == ["pending"]

    again = s.create_refund(U1, order_id="O1003")
    assert again["ok"] is False and again["error"] == "REFUND_EXISTS"
    assert len(db("SELECT * FROM refunds WHERE order_id = 'O1003'")) == 1


def test_refund_not_available(db):
    assert s.check_refund_eligibility(U1, order_id="O1002")["data"]["reason_code"] == "ALREADY_SHIPPED"
    assert s.check_refund_eligibility(U1, order_id="O1005")["data"]["reason_code"] == "REFUND_EXISTS"
    assert s.get_refund_status(U1, order_id="O1005")["data"][0]["status"] == "completed"

    created = s.create_refund(U1, order_id="O1002")
    assert created["ok"] is False and created["error"] == "ALREADY_SHIPPED"
    assert db("SELECT * FROM refunds WHERE order_id = 'O1002'") == []


def test_refund_delivered_is_already_shipped(db):
    assert s.check_refund_eligibility(U1, order_id="O1001")["data"]["reason_code"] == "ALREADY_SHIPPED"


def test_refund_order_cancelled(db):
    # O1005 已有 completed 退款会先命中 REFUND_EXISTS；去掉该记录后才轮到 ORDER_CANCELLED
    db("DELETE FROM refunds WHERE order_id = 'O1005'")
    data = s.check_refund_eligibility(U1, order_id="O1005")["data"]
    assert data["eligible"] is False and data["reason_code"] == "ORDER_CANCELLED"


def test_refund_status_all(db):
    data = s.get_refund_status(U1)["data"]
    assert [r["refund_id"] for r in data] == ["R0001"]
    assert s.get_refund_status(U2)["data"] == []


@pytest.mark.parametrize("fn", [s.check_refund_eligibility, s.create_refund, s.get_refund_status])
@pytest.mark.parametrize("order_id", ["O2001", "O9999"])
def test_refund_order_not_found(db, fn, order_id):
    assert fn(U1, order_id=order_id)["error"] == "ORDER_NOT_FOUND"


# ---------- 退货 ----------

def test_return_flow(db):
    check = s.check_return_eligibility(U1, order_id="O1001")["data"]
    assert check["order_eligible"] is True
    items = {i["item_id"]: i for i in check["items"]}
    assert items[2]["eligible"] is True and items[2]["refund_amount"] == "89.00"
    assert items[1]["eligible"] is False and items[1]["reason_code"] == "NOT_RETURNABLE"

    created = s.create_return(U1, order_id="O1001", item_id=2)
    assert created["ok"] is True and created["data"]["status"] == "requested"
    rows = db("SELECT * FROM returns WHERE order_id = 'O1001'")
    assert len(rows) == 1
    assert rows[0]["item_id"] == 2
    assert rows[0]["status"] == "requested" and rows[0]["refund_amount_fen"] == 8900

    status = s.get_return_status(U1, order_id="O1001")["data"]
    assert [r["status"] for r in status] == ["requested"]

    again = s.create_return(U1, order_id="O1001", item_id=2)
    assert again["ok"] is False and again["error"] == "RETURN_EXISTS"
    assert len(db("SELECT * FROM returns")) == 1

    check_after = s.check_return_eligibility(U1, order_id="O1001")["data"]
    assert next(i for i in check_after["items"] if i["item_id"] == 2)["reason_code"] == "RETURN_EXISTS"


def test_return_not_available(db):
    assert s.check_return_eligibility(U1, order_id="O1002")["data"]["reason_code"] == "NOT_DELIVERED"
    assert s.check_return_eligibility(U1, order_id="O1004")["data"]["reason_code"] == "RETURN_WINDOW_EXPIRED"

    not_returnable = s.create_return(U1, order_id="O1001", item_id=1)
    assert not_returnable["ok"] is False and not_returnable["error"] == "NOT_RETURNABLE"
    assert db("SELECT * FROM returns") == []

    wrong_item = s.create_return(U1, order_id="O1001", item_id=5)
    assert wrong_item["ok"] is False and wrong_item["error"] == "ITEM_NOT_FOUND"
    assert db("SELECT * FROM returns") == []


def test_create_return_order_level_rejections(db):
    assert s.create_return(U1, order_id="O1002", item_id=3)["error"] == "NOT_DELIVERED"
    assert s.create_return(U1, order_id="O1004", item_id=5)["error"] == "RETURN_WINDOW_EXPIRED"
    assert db("SELECT * FROM returns") == []


def test_return_status_all(db):
    assert s.get_return_status(U1)["data"] == []
    s.create_return(U1, order_id="O1001", item_id=2)
    assert [r["order_id"] for r in s.get_return_status(U1)["data"]] == ["O1001"]
    assert s.get_return_status(U2)["data"] == []


@pytest.mark.parametrize("fn", [s.check_return_eligibility, s.get_return_status])
@pytest.mark.parametrize("order_id", ["O2001", "O9999"])
def test_return_order_not_found(db, fn, order_id):
    assert fn(U1, order_id=order_id)["error"] == "ORDER_NOT_FOUND"


def test_create_return_order_not_found(db):
    assert s.create_return(U1, order_id="O2001", item_id=7)["error"] == "ORDER_NOT_FOUND"
    assert db("SELECT * FROM returns") == []


# ---------- 不写完成态 ----------

def test_creates_only_write_pending_or_requested(db):
    before_refunds = {r["refund_id"] for r in db("SELECT refund_id FROM refunds")}
    for oid in ["O1001", "O1002", "O1003", "O1004", "O1005", "O2001", "O9999"]:
        s.create_refund(U1, order_id=oid)
    for oid, item in [("O1001", 1), ("O1001", 2), ("O1002", 3), ("O1004", 5), ("O1001", 2)]:
        s.create_return(U1, order_id=oid, item_id=item)

    new_refunds = [r for r in db("SELECT * FROM refunds") if r["refund_id"] not in before_refunds]
    new_returns = db("SELECT * FROM returns")
    assert new_refunds and {r["status"] for r in new_refunds} == {"pending"}
    assert new_returns and {r["status"] for r in new_returns} == {"requested"}
