"""Fake LLM 离线链路测试。"""

from conftest import FakeLLM, call, text

from mercury import agent
from mercury.agent import run_mercury

U1, U2 = "test_user_001", "test_user_002"


def tool_messages(llm_call):
    return "\n".join(m["content"] for m in llm_call["messages"] if m["role"] == "tool")


def spied(tool_spy):
    return [(name, args) for name, args, _ in tool_spy]


# ---------- 五条链路 ----------

def test_list_orders_flow(db, tool_spy):
    llm = FakeLLM([call(("list_orders", {})), text("您有 5 个订单。")])
    assert run_mercury(U1, "我有哪些订单？", llm=llm) == "您有 5 个订单。"
    assert spied(tool_spy) == [("list_orders", {})]
    seen = tool_messages(llm.calls[1])
    for oid in ["O1001", "O1002", "O1003", "O1004", "O1005"]:
        assert oid in seen
    assert "O2001" not in seen


def test_delivery_flow(db, tool_spy):
    llm = FakeLLM([call(("get_delivery_status", {"order_id": "O1002"})), text("骑手正在配送。")])
    assert run_mercury(U1, "O1002 到哪了？", llm=llm) == "骑手正在配送。"
    assert spied(tool_spy) == [("get_delivery_status", {"order_id": "O1002"})]
    assert "骑手已取货，正在配送中" in tool_messages(llm.calls[1])


def test_refund_flow(db, tool_spy):
    llm = FakeLLM([
        call(("check_refund_eligibility", {"order_id": "O1003"})),
        call(("create_refund", {"order_id": "O1003", "reason": "不想要了"})),
        call(("get_refund_status", {"order_id": "O1003"})),
        text("退款申请已提交，正在处理。"),
    ])
    assert run_mercury(U1, "O1003 不想要了，帮我退款", llm=llm) == "退款申请已提交，正在处理。"
    assert spied(tool_spy) == [
        ("check_refund_eligibility", {"order_id": "O1003"}),
        ("create_refund", {"order_id": "O1003", "reason": "不想要了"}),
        ("get_refund_status", {"order_id": "O1003"}),
    ]
    assert '"amount": "79.80"' in tool_messages(llm.calls[1])
    assert "退款申请已提交，正在处理，还没有到账" in tool_messages(llm.calls[2])
    assert "退款处理中" in tool_messages(llm.calls[3])
    rows = db("SELECT * FROM refunds WHERE order_id = 'O1003'")
    assert len(rows) == 1 and rows[0]["status"] == "pending" and rows[0]["reason"] == "不想要了"


def test_return_flow(db, tool_spy):
    llm = FakeLLM([
        call(("check_return_eligibility", {"order_id": "O1001"})),
        call(("create_return", {"order_id": "O1001", "item_id": 2})),
        call(("get_return_status", {"order_id": "O1001"})),
        text("保温杯退货申请已提交，等待审核。"),
    ])
    assert run_mercury(U1, "O1001 的保温杯我要退货", llm=llm) == "保温杯退货申请已提交，等待审核。"
    assert spied(tool_spy) == [
        ("check_return_eligibility", {"order_id": "O1001"}),
        ("create_return", {"order_id": "O1001", "item_id": 2}),
        ("get_return_status", {"order_id": "O1001"}),
    ]
    assert "NOT_RETURNABLE" in tool_messages(llm.calls[1])
    assert '"refund_amount": "89.00"' in tool_messages(llm.calls[2])
    assert "待审核" in tool_messages(llm.calls[3])
    rows = db("SELECT * FROM returns")
    assert len(rows) == 1 and rows[0]["item_id"] == 2 and rows[0]["status"] == "requested"


def test_policy_flow(db, tool_spy):
    llm = FakeLLM([call(("search_after_sales_policy", {"query": "退款多久到账"})), text("1–3 个工作日到账。")])
    assert run_mercury(U1, "退款一般多久到账？", llm=llm) == "1–3 个工作日到账。"
    assert spied(tool_spy) == [("search_after_sales_policy", {"query": "退款多久到账"})]
    assert "退款审核通过后原路退回，1–3 个工作日到账。" in tool_messages(llm.calls[1])


# ---------- 循环细节 ----------

def test_assistant_message_format(db, tool_spy):
    llm = FakeLLM([call(("get_order_details", {"order_id": "O1001"}),
                        ("get_delivery_status", {"order_id": "O1001"})),
                   text("好的。")])
    run_mercury(U1, "O1001 怎么样了", llm=llm)
    msgs = llm.calls[1]["messages"]
    assistant, tool_a, tool_b = msgs[-3:]
    assert assistant == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call_0", "type": "function",
             "function": {"name": "get_order_details", "arguments": '{"order_id": "O1001"}'}},
            {"id": "call_1", "type": "function",
             "function": {"name": "get_delivery_status", "arguments": '{"order_id": "O1001"}'}},
        ],
    }
    assert tool_a["role"] == "tool" and tool_a["tool_call_id"] == "call_0"
    assert tool_b["role"] == "tool" and tool_b["tool_call_id"] == "call_1"
    assert [name for name, _ in spied(tool_spy)] == ["get_order_details", "get_delivery_status"]


def test_tool_round_limit(db, tool_spy):
    llm = FakeLLM([call(("list_orders", {}))] * 5 + [text("根据已有结果回答。")])
    assert run_mercury(U1, "一直查", llm=llm) == "根据已有结果回答。"
    assert len(tool_spy) == 5
    assert len(llm.calls) == 6
    assert all(c["tools"] is not None for c in llm.calls[:5])
    assert llm.calls[5]["tools"] is None
    assert llm.calls[5]["messages"][-1] == {"role": "user", "content": "已达到工具调用上限，请只根据已有 Tool 结果回答"}


def test_llm_exception(db):
    llm = FakeLLM([RuntimeError("network down")])
    assert run_mercury(U1, "我有哪些订单？", llm=llm) == "抱歉，服务暂时不可用，请稍后再试。"
    assert U1 not in agent._HISTORY


def test_llm_exception_mid_loop_returns_no_partial(db, tool_spy):
    llm = FakeLLM([call(("list_orders", {})), RuntimeError("timeout")])
    assert run_mercury(U1, "我有哪些订单？", llm=llm) == "抱歉，服务暂时不可用，请稍后再试。"
    assert U1 not in agent._HISTORY


def test_empty_answer_fallback(db):
    llm = FakeLLM([text("   ")])
    assert run_mercury(U1, "你好", llm=llm) == "抱歉，我暂时无法回答这个问题。"


def test_unknown_user(db):
    llm = FakeLLM([])
    assert run_mercury("unknown", "我有哪些订单？", llm=llm) == "未找到该用户"
    assert llm.calls == []


# ---------- 会话历史 ----------

def test_history_per_user(db, tool_spy):
    llm = FakeLLM([call(("list_orders", {})), text("您有 5 个订单。"), text("第二次回复"), text("你好")])
    run_mercury(U1, "我有哪些订单？", llm=llm)
    run_mercury(U1, "最新的是哪个？", llm=llm)

    second = llm.calls[2]["messages"]
    assert second[1:] == [
        {"role": "user", "content": "我有哪些订单？"},
        {"role": "assistant", "content": "您有 5 个订单。"},
        {"role": "user", "content": "最新的是哪个？"},
    ]

    run_mercury(U2, "我有哪些订单？", llm=llm)
    other = llm.calls[3]["messages"]
    assert [m["role"] for m in other] == ["system", "user"]

    for turns in agent._HISTORY.values():
        assert {m["role"] for m in turns} <= {"user", "assistant"}
        assert all("tool_calls" not in m for m in turns)


def test_history_keeps_last_six_turns(db):
    llm = FakeLLM([text(f"回复{i}") for i in range(8)])
    for i in range(8):
        run_mercury(U1, f"消息{i}", llm=llm)
    assert len(agent._HISTORY[U1]) == 12
    assert agent._HISTORY[U1][0] == {"role": "user", "content": "消息2"}
    last_sent = [m["content"] for m in llm.calls[7]["messages"][1:]]
    assert last_sent[0] == "消息1" and last_sent[-1] == "消息7"
    assert len(last_sent) == 13  # 6 轮历史 + 本条
