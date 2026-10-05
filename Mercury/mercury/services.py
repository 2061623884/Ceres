"""售后业务函数。签名统一为 fn(user_id, **args) -> dict。

成功：{"ok": True, "data": {...}}；业务失败：{"ok": False, "error": 原因码, "message": 中文说明}。
所有查询都带 user_id 条件；订单不存在或不属于当前用户一律返回 ORDER_NOT_FOUND。
"""

import uuid
from contextlib import closing
from datetime import datetime, timedelta

from mercury.db import connect

RETURN_WINDOW_DAYS = 7

ORDER_STATUS_TEXT = {"paid": "模拟订单，未发货", "shipped": "配送中", "delivered": "已签收", "cancelled": "已取消"}
DELIVERY_STATUS_TEXT = {"shipping": "配送中", "delivered": "已签收"}
REFUND_STATUS_TEXT = {"pending": "退款处理中", "completed": "退款已完成", "rejected": "退款被拒绝"}
RETURN_STATUS_TEXT = {"requested": "待审核", "approved": "审核通过", "completed": "退货已完成", "rejected": "已拒绝"}

# 没有物流记录时的订单状态说明
NO_DELIVERY_TEXT = {"paid": "模拟订单，未发货", "cancelled": "已取消"}


def _yuan(fen: int) -> str:
    return f"{fen / 100:.2f}"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _ok(data) -> dict:
    return {"ok": True, "data": data}


def _fail(error: str, message: str) -> dict:
    return {"ok": False, "error": error, "message": message}


def _order_not_found() -> dict:
    return _fail("ORDER_NOT_FOUND", "没有找到这个订单")


def _get_order(conn, user_id, order_id):
    return conn.execute(
        "SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (order_id, user_id)
    ).fetchone()


def _get_items(conn, order_id):
    return conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY item_id", (order_id,)
    ).fetchall()


# ---------- 订单 ----------

def list_orders(user_id) -> dict:
    with closing(connect()) as conn:
        orders = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,)
        ).fetchall()
        data = [
            {
                "order_id": o["order_id"],
                "status": o["status"],
                "status_text": ORDER_STATUS_TEXT[o["status"]],
                "created_at": o["created_at"],
                "total": _yuan(o["total_fen"]),
                "products": [i["product_name"] for i in _get_items(conn, o["order_id"])],
            }
            for o in orders
        ]
    return _ok(data)


def get_order_details(user_id, order_id) -> dict:
    with closing(connect()) as conn:
        o = _get_order(conn, user_id, order_id)
        if o is None:
            return _order_not_found()
        items = _get_items(conn, order_id)
    return _ok({
        "order_id": o["order_id"],
        "status": o["status"],
        "status_text": ORDER_STATUS_TEXT[o["status"]],
        "created_at": o["created_at"],
        "delivered_at": o["delivered_at"],
        "total": _yuan(o["total_fen"]),
        "items": [
            {
                "item_id": i["item_id"],
                "product_name": i["product_name"],
                "quantity": i["quantity"],
                "unit_price": _yuan(i["unit_price_fen"]),
                "returnable": bool(i["returnable"]),
            }
            for i in items
        ],
    })


# ---------- 物流 ----------

def get_delivery_status(user_id, order_id) -> dict:
    with closing(connect()) as conn:
        o = _get_order(conn, user_id, order_id)
        if o is None:
            return _order_not_found()
        d = conn.execute("SELECT * FROM deliveries WHERE order_id = ?", (order_id,)).fetchone()
    if d is None:
        return _ok({
            "order_id": order_id,
            "has_delivery": False,
            "order_status": o["status"],
            "order_status_text": NO_DELIVERY_TEXT.get(o["status"], ORDER_STATUS_TEXT[o["status"]]),
        })
    return _ok({
        "order_id": order_id,
        "has_delivery": True,
        "status": d["status"],
        "status_text": DELIVERY_STATUS_TEXT[d["status"]],
        "latest_description": d["latest_description"],
        "eta": d["eta"],
        "updated_at": d["updated_at"],
    })


# ---------- 退款（整单仅退款） ----------

def _refund_check(conn, user_id, order_id):
    """返回 None（订单不存在）或 (eligible, reason_code, reason, amount_fen)。"""
    o = _get_order(conn, user_id, order_id)
    if o is None:
        return None
    existing = conn.execute(
        "SELECT status FROM refunds WHERE order_id = ? AND status IN ('pending', 'completed')", (order_id,)
    ).fetchone()
    if existing is not None:
        return False, "REFUND_EXISTS", f"该订单已有退款申请（{REFUND_STATUS_TEXT[existing['status']]}）", None
    if o["status"] == "cancelled":
        return False, "ORDER_CANCELLED", "订单已取消，不能申请退款", None
    if o["status"] in ("shipped", "delivered"):
        return False, "ALREADY_SHIPPED", "订单已发货，不支持仅退款；签收后可申请退货", None
    return True, None, "可以申请整单退款（这只是资格判断，尚未提交退款申请）", o["total_fen"]


def check_refund_eligibility(user_id, order_id) -> dict:
    with closing(connect()) as conn:
        result = _refund_check(conn, user_id, order_id)
    if result is None:
        return _order_not_found()
    eligible, code, reason, amount_fen = result
    return _ok({
        "order_id": order_id,
        "eligible": eligible,
        "reason_code": code,
        "reason": reason,
        "amount": _yuan(amount_fen) if eligible else None,
    })


def create_refund(user_id, order_id, reason=None) -> dict:
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = _refund_check(conn, user_id, order_id)
        if result is None:
            conn.rollback()
            return _order_not_found()
        eligible, code, why, amount_fen = result
        if not eligible:
            conn.rollback()
            return _fail(code, why)
        refund_id = "R" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO refunds (refund_id, order_id, amount_fen, reason, status, created_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?)",
            (refund_id, order_id, amount_fen, reason or "未填写", _now()),
        )
        conn.commit()
    return _ok({
        "refund_id": refund_id,
        "order_id": order_id,
        "status": "pending",
        "status_text": REFUND_STATUS_TEXT["pending"],
        "amount": _yuan(amount_fen),
        "message": "退款申请已提交，正在处理，还没有到账",
    })


def get_refund_status(user_id, order_id=None) -> dict:
    with closing(connect()) as conn:
        if order_id is not None and _get_order(conn, user_id, order_id) is None:
            return _order_not_found()
        sql = ("SELECT r.* FROM refunds r JOIN orders o ON o.order_id = r.order_id"
               " WHERE o.user_id = ?")
        params = [user_id]
        if order_id is not None:
            sql += " AND r.order_id = ?"
            params.append(order_id)
        rows = conn.execute(sql + " ORDER BY r.created_at DESC", params).fetchall()
    return _ok([
        {
            "refund_id": r["refund_id"],
            "order_id": r["order_id"],
            "amount": _yuan(r["amount_fen"]),
            "status": r["status"],
            "status_text": REFUND_STATUS_TEXT[r["status"]],
            "reason": r["reason"],
            "created_at": r["created_at"],
        }
        for r in rows
    ])


# ---------- 退货（按商品整行退货） ----------

def _return_check(conn, user_id, order_id):
    """返回 None（订单不存在）或 (order_eligible, order_reason_code, order_reason, items)。

    items 中每项：item_id、product_name、eligible、reason_code、reason、refund_amount_fen。
    """
    o = _get_order(conn, user_id, order_id)
    if o is None:
        return None
    order_code, order_reason = None, "订单可以申请退货"
    if o["status"] != "delivered":
        order_code, order_reason = "NOT_DELIVERED", "订单还没有签收，签收后才能申请退货"
    elif datetime.now() - datetime.fromisoformat(o["delivered_at"]) > timedelta(days=RETURN_WINDOW_DAYS):
        order_code, order_reason = "RETURN_WINDOW_EXPIRED", "已超过签收后的退货期限"

    items = []
    for i in _get_items(conn, order_id):
        code, why = order_code, order_reason
        if code is None:
            if not i["returnable"]:
                code, why = "NOT_RETURNABLE", "该商品不支持退货"
            elif conn.execute(
                "SELECT 1 FROM returns WHERE item_id = ? AND status IN ('requested', 'approved', 'completed')",
                (i["item_id"],),
            ).fetchone():
                code, why = "RETURN_EXISTS", "该商品已有退货申请"
            else:
                why = "可以申请退货"
        eligible = code is None
        items.append({
            "item_id": i["item_id"],
            "product_name": i["product_name"],
            "eligible": eligible,
            "reason_code": code,
            "reason": why,
            "refund_amount_fen": i["unit_price_fen"] * i["quantity"] if eligible else None,
        })
    return order_code is None, order_code, order_reason, items


def check_return_eligibility(user_id, order_id) -> dict:
    with closing(connect()) as conn:
        result = _return_check(conn, user_id, order_id)
    if result is None:
        return _order_not_found()
    order_eligible, code, reason, items = result
    return _ok({
        "order_id": order_id,
        "order_eligible": order_eligible,
        "reason_code": code,
        "reason": reason,
        "items": [
            {
                "item_id": i["item_id"],
                "product_name": i["product_name"],
                "eligible": i["eligible"],
                "reason_code": i["reason_code"],
                "reason": i["reason"],
                "refund_amount": _yuan(i["refund_amount_fen"]) if i["eligible"] else None,
            }
            for i in items
        ],
    })


def create_return(user_id, order_id, item_id, reason=None) -> dict:
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return _fail("ITEM_NOT_FOUND", "该订单中没有这件商品")
    with closing(connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = _return_check(conn, user_id, order_id)
        if result is None:
            conn.rollback()
            return _order_not_found()
        order_eligible, code, why, items = result
        if not order_eligible:
            conn.rollback()
            return _fail(code, why)
        item = next((i for i in items if i["item_id"] == item_id), None)
        if item is None:
            conn.rollback()
            return _fail("ITEM_NOT_FOUND", "该订单中没有这件商品")
        if not item["eligible"]:
            conn.rollback()
            return _fail(item["reason_code"], item["reason"])
        return_id = "T" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO returns (return_id, order_id, item_id, refund_amount_fen, reason, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'requested', ?)",
            (return_id, order_id, item_id, item["refund_amount_fen"], reason or "未填写", _now()),
        )
        conn.commit()
    return _ok({
        "return_id": return_id,
        "order_id": order_id,
        "item_id": item_id,
        "product_name": item["product_name"],
        "status": "requested",
        "status_text": RETURN_STATUS_TEXT["requested"],
        "refund_amount": _yuan(item["refund_amount_fen"]),
        "message": "退货申请已提交，等待审核；审核通过并收到退回商品后退款",
    })


def get_return_status(user_id, order_id=None) -> dict:
    with closing(connect()) as conn:
        if order_id is not None and _get_order(conn, user_id, order_id) is None:
            return _order_not_found()
        sql = ("SELECT t.*, i.product_name FROM returns t"
               " JOIN orders o ON o.order_id = t.order_id"
               " JOIN order_items i ON i.item_id = t.item_id"
               " WHERE o.user_id = ?")
        params = [user_id]
        if order_id is not None:
            sql += " AND t.order_id = ?"
            params.append(order_id)
        rows = conn.execute(sql + " ORDER BY t.created_at DESC", params).fetchall()
    return _ok([
        {
            "return_id": t["return_id"],
            "order_id": t["order_id"],
            "item_id": t["item_id"],
            "product_name": t["product_name"],
            "refund_amount": _yuan(t["refund_amount_fen"]),
            "status": t["status"],
            "status_text": RETURN_STATUS_TEXT[t["status"]],
            "reason": t["reason"],
            "created_at": t["created_at"],
        }
        for t in rows
    ])
