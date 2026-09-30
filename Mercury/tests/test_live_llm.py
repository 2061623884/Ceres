"""真实 LLM 用例：只有 MERCURY_LIVE=1 且 .env 已配置时运行，否则 skip。"""

import os

import pytest

from mercury.agent import run_mercury
from mercury.config import llm_settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("MERCURY_LIVE") != "1" or not all(llm_settings().values()),
        reason="需要 MERCURY_LIVE=1，且 .env 配置了 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL",
    ),
]

U1 = "test_user_001"


def ask(message, tool_spy):
    reply = run_mercury(U1, message)
    print(f"\n[用户] {message}\n[工具] {[(n, a) for n, a, _ in tool_spy]}\n[墨墨] {reply}")
    return reply


def called(tool_spy, name, **expected):
    return any(
        n == name and isinstance(a, dict) and all(str(a.get(k)) == str(v) for k, v in expected.items())
        for n, a, _ in tool_spy
    )


def contains_any(reply, words):
    return [w for w in words if w in reply]


def test_list_orders(db, tool_spy):
    ask("我有哪些订单？", tool_spy)
    assert called(tool_spy, "list_orders")


def test_delivery(db, tool_spy):
    ask("O1002 现在到哪了？", tool_spy)
    assert called(tool_spy, "get_delivery_status", order_id="O1002")


def test_not_shipped_is_not_fabricated(db, tool_spy):
    reply = ask("O1003 发货了吗？", tool_spy)
    assert called(tool_spy, "get_order_details") or called(tool_spy, "get_delivery_status")
    assert contains_any(reply, ["已发货", "配送中"]) == []


def test_unknown_order_is_not_fabricated(db, tool_spy):
    reply = ask("O9999 到哪了？", tool_spy)
    assert tool_spy
    assert contains_any(reply, ["配送中", "已签收", "已发货"]) == []


def test_create_refund(db, tool_spy):
    reply = ask("O1003 不想要了，帮我退款", tool_spy)
    assert called(tool_spy, "create_refund", order_id="O1003")
    assert [r["status"] for r in db("SELECT status FROM refunds WHERE order_id = 'O1003'")] == ["pending"]
    assert contains_any(reply, ["退款成功", "已退款", "已到账"]) == []


def test_refund_shipped_order(db, tool_spy):
    reply = ask("O1002 帮我退款", tool_spy)
    assert db("SELECT * FROM refunds WHERE order_id = 'O1002'") == []
    assert contains_any(reply, ["退款成功", "已退款"]) == []


def test_create_return(db, tool_spy):
    reply = ask("O1001 的保温杯我要退货", tool_spy)
    assert called(tool_spy, "create_return", order_id="O1001", item_id=2)
    assert [r["status"] for r in db("SELECT status FROM returns WHERE order_id = 'O1001'")] == ["requested"]
    assert contains_any(reply, ["退货成功", "已退款"]) == []


def test_policy(db, tool_spy):
    ask("退款一般多久到账？", tool_spy)
    assert called(tool_spy, "search_after_sales_policy")
