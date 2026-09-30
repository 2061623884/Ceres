import json

import pytest

from mercury import tools

NAMES = [
    "list_orders", "get_order_details", "get_delivery_status",
    "check_refund_eligibility", "create_refund", "get_refund_status",
    "check_return_eligibility", "create_return", "get_return_status",
    "search_after_sales_policy",
]


def run(name, arguments, user_id="test_user_001"):
    return json.loads(tools.execute_tool(name, arguments, user_id=user_id))


def test_tool_names():
    assert [t["function"]["name"] for t in tools.openai_tools()] == NAMES


def test_no_user_id_in_schemas():
    assert "user_id" not in json.dumps(tools.openai_tools())


def test_only_creates_are_write():
    writes = {t["schema"]["function"]["name"] for t in tools.TOOLS if t["write"]}
    assert writes == {"create_refund", "create_return"}


def test_injected_user_id_wins(db):
    result = run("get_order_details", '{"order_id": "O2001", "user_id": "test_user_002"}')
    assert result["ok"] is False and result["error"] == "ORDER_NOT_FOUND"


def test_injected_user_id_can_see_own_order(db):
    result = run("get_order_details", '{"order_id": "O2001"}', user_id="test_user_002")
    assert result["ok"] is True and result["data"]["order_id"] == "O2001"


@pytest.mark.parametrize("name, arguments, error", [
    ("get_order_details", "{not json", "BAD_ARGUMENTS"),
    ("get_order_details", '"O1001"', "BAD_ARGUMENTS"),
    ("no_such_tool", "{}", "UNKNOWN_TOOL"),
    ("get_order_details", "{}", "BAD_ARGUMENTS"),
    ("create_return", '{"order_id": "O1001"}', "BAD_ARGUMENTS"),
    ("search_after_sales_policy", '{"category": "refund"}', "BAD_ARGUMENTS"),
])
def test_bad_calls_do_not_raise(db, name, arguments, error):
    result = run(name, arguments)
    assert result["ok"] is False and result["error"] == error


def test_empty_arguments_for_no_param_tool(db):
    assert run("list_orders", "")["ok"] is True


def test_tool_exception_returns_tool_failed(db, monkeypatch):
    def boom(user_id, **kwargs):
        raise RuntimeError("db down")

    entry = next(t for t in tools.TOOLS if t["schema"]["function"]["name"] == "get_order_details")
    monkeypatch.setitem(entry, "func", boom)
    result = run("get_order_details", '{"order_id": "O1001"}')
    assert result["ok"] is False and result["error"] == "TOOL_FAILED"


def test_policy_tool_without_user(db):
    result = run("search_after_sales_policy", '{"query": "退款多久到账", "category": "refund"}')
    assert "P-REF-02" in [p["policy_id"] for p in result["data"]]


def test_result_is_chinese_json(db):
    raw = tools.execute_tool("get_order_details", '{"order_id": "O1001"}', user_id="test_user_001")
    assert "保温杯" in raw  # ensure_ascii=False
