"""测试数据与政策数据。所有时间相对执行 seed 的时刻计算。

python -m mercury.seed：删除并重建数据库，再执行 init_schema 和 seed。
"""

import sqlite3
from datetime import datetime, timedelta

from mercury import config
from mercury.db import connect, init_schema

POLICIES = [
    ("P-REF-01", "refund", "未发货订单退款",
     "未发货订单可申请整单退款；已发货或已签收的订单不支持仅退款，签收后可申请退货。",
     "退款,取消,不想要,未发货,仅退款"),
    ("P-REF-02", "refund", "退款到账时间",
     "退款审核通过后原路退回，1–3 个工作日到账。",
     "到账,退回,原路,几天"),
    ("P-RET-01", "return", "签收后退货",
     "签收后 7 天内，可退货商品可按件申请退货退款。",
     "退货,七天,7天,签收"),
    ("P-RET-02", "return", "不支持退货的商品",
     "生鲜等标注“不可退货”的商品不支持退货。",
     "生鲜,水果,不能退,不支持退货,不可退"),
    ("P-DEL-01", "delivery", "配送时间",
     "下单当天配送，预计送达时间以物流信息为准。",
     "配送,送达,多久送到,几点到"),
    ("P-DEL-02", "delivery", "配送延迟",
     "超过预计时间仍未送达的，以最新物流进度为准；订单发货前可申请整单退款。",
     "延迟,超时,还没到,没送到"),
]


def seed(conn: sqlite3.Connection) -> None:
    now = datetime.now().replace(microsecond=0)

    def ago(**kw) -> str:
        return (now - timedelta(**kw)).isoformat()

    def later(**kw) -> str:
        return (now + timedelta(**kw)).isoformat()

    conn.executemany(
        "INSERT INTO users (user_id, name) VALUES (?, ?)",
        [("test_user_001", "测试用户一"), ("test_user_002", "测试用户二")],
    )
    conn.executemany(
        "INSERT INTO orders (order_id, user_id, status, total_fen, created_at, delivered_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("O1001", "test_user_001", "delivered", 11890, ago(days=3), ago(days=2)),
            ("O1002", "test_user_001", "shipped", 5990, ago(hours=1), None),
            ("O1003", "test_user_001", "paid", 7980, ago(minutes=20), None),
            ("O1004", "test_user_001", "delivered", 4500, ago(days=11), ago(days=10)),
            ("O1005", "test_user_001", "cancelled", 12800, ago(days=3), None),
            ("O2001", "test_user_002", "shipped", 1990, ago(hours=1), None),
        ],
    )
    conn.executemany(
        "INSERT INTO order_items (item_id, order_id, product_name, quantity, unit_price_fen, returnable)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "O1001", "红富士苹果 2kg", 1, 2990, 0),
            (2, "O1001", "不锈钢保温杯", 1, 8900, 1),
            (3, "O1002", "纯牛奶 250ml×12", 1, 5990, 1),
            (4, "O1003", "洗衣液 2kg", 2, 3990, 1),
            (5, "O1004", "玻璃密封罐", 3, 1500, 1),
            (6, "O1005", "坚果礼盒", 1, 12800, 1),
            (7, "O2001", "厨房纸", 1, 1990, 1),
        ],
    )
    conn.executemany(
        "INSERT INTO deliveries (order_id, status, latest_description, eta, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            ("O1001", "delivered", "已签收", None, ago(days=2)),
            ("O1002", "shipping", "骑手已取货，正在配送中", later(minutes=30), ago(minutes=30)),
            ("O1004", "delivered", "已签收", None, ago(days=10)),
            ("O2001", "shipping", "骑手已取货，正在配送中", None, ago(minutes=30)),
        ],
    )
    conn.execute(
        "INSERT INTO refunds (refund_id, order_id, amount_fen, reason, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("R0001", "O1005", 12800, "不想要了", "completed", ago(days=3)),
    )
    conn.executemany(
        "INSERT INTO policies (policy_id, category, title, content, keywords) VALUES (?, ?, ?, ?, ?)",
        POLICIES,
    )


def main() -> None:
    path = config.db_path()
    path.unlink(missing_ok=True)
    conn = connect()
    try:
        init_schema(conn)
        seed(conn)
        conn.commit()
    finally:
        conn.close()
    print(f"seed 完成：{path}")


if __name__ == "__main__":
    main()
