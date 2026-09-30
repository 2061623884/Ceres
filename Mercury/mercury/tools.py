"""Tool schema 与 execute_tool。user_id 只由调用方注入，不出现在任何 schema 中。"""

import json
import logging

from mercury import policy, services

logger = logging.getLogger(__name__)

_ORDER_ID = {"type": "string", "description": "订单号，如 O1003"}
_REASON = {"type": "string", "description": "用户说明的原因，可不填"}


def _tool(name, description, properties, required, func, write=False):
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        },
        "func": func,
        "write": write,
    }


TOOLS = [
    _tool("list_orders",
          "列出当前用户最近 10 个订单（订单号、状态、下单时间、金额、商品名）。用户没有提供订单号时先调用它。",
          {}, [], services.list_orders),
    _tool("get_order_details",
          "查询单个订单的详情和商品（含 item_id、是否可退货）。用户问订单状态或商品时调用。",
          {"order_id": _ORDER_ID}, ["order_id"], services.get_order_details),
    _tool("get_delivery_status",
          "查询订单当前的物流进度。用户问订单到哪了、什么时候到、发货没有时调用。",
          {"order_id": _ORDER_ID}, ["order_id"], services.get_delivery_status),
    _tool("check_refund_eligibility",
          "只判断订单能否申请整单仅退款并返回可退金额，不会提交申请；eligible 为 true 也不代表已提交。"
          "仅在用户只是询问能不能退款时调用；用户已要求退款时不要调用本工具，直接调用 create_refund。",
          {"order_id": _ORDER_ID}, ["order_id"], services.check_refund_eligibility),
    _tool("create_refund",
          "用户明确要求退款时调用。只适用于未发货订单的整单退款。成功只表示申请已提交。"
          "内部会校验资格，无需先调用 check_refund_eligibility；reason 可不填。",
          {"order_id": _ORDER_ID, "reason": _REASON}, ["order_id"], services.create_refund, write=True),
    _tool("get_refund_status",
          "查询退款申请记录和状态。不传 order_id 时返回当前用户的全部退款记录。",
          {"order_id": _ORDER_ID}, [], services.get_refund_status),
    _tool("check_return_eligibility",
          "只判断订单内每件商品能否退货，返回 item_id 和可退金额，不会提交申请。用户只是询问能不能退货时调用。",
          {"order_id": _ORDER_ID}, ["order_id"], services.check_return_eligibility),
    _tool("create_return",
          "用户明确要求退货时调用，一次提交一件商品。item_id 不清楚时先调用 get_order_details 获取，"
          "拿到后立即调用本工具。内部会校验资格；reason 可不填，不要为此追问用户。"
          "成功只表示申请已提交，等待审核。",
          {"order_id": _ORDER_ID,
           "item_id": {"type": "integer",
                       "description": "要退货商品的 item_id，必须取自 get_order_details 返回的 items，不要猜测"},
           "reason": _REASON},
          ["order_id", "item_id"], services.create_return, write=True),
    _tool("get_return_status",
          "查询退货申请记录和状态。不传 order_id 时返回当前用户的全部退货记录。",
          {"order_id": _ORDER_ID}, [], services.get_return_status),
    _tool("search_after_sales_policy",
          "检索退款、退货、配送相关的售后政策原文（如退款到账时间、退货期限、配送时间）。"
          "用户问规则、时效、哪些商品能退时必须先调用，不要凭常识回答；"
          "某个具体订单能否退款或退货，用对应的 check Tool 判断。",
          {"query": {"type": "string", "description": "用户的问题或关键词"},
           "category": {"type": "string", "enum": ["refund", "return", "delivery"],
                        "description": "可选：refund 退款 / return 退货 / delivery 配送"}},
          ["query"], policy.search_policies),
]

_BY_NAME = {t["schema"]["function"]["name"]: t for t in TOOLS}


def openai_tools() -> list:
    return [t["schema"] for t in TOOLS]


def _dump(result) -> str:
    return json.dumps(result, ensure_ascii=False)


def execute_tool(name: str, arguments: str, user_id: str) -> str:
    tool = _BY_NAME.get(name)
    if tool is None:
        return _dump({"ok": False, "error": "UNKNOWN_TOOL", "message": f"没有名为 {name} 的工具"})

    try:
        raw = json.loads(arguments) if arguments and arguments.strip() else {}
    except (json.JSONDecodeError, TypeError):
        return _dump({"ok": False, "error": "BAD_ARGUMENTS", "message": "参数不是合法的 JSON"})
    if not isinstance(raw, dict):
        return _dump({"ok": False, "error": "BAD_ARGUMENTS", "message": "参数必须是 JSON 对象"})

    params = tool["schema"]["function"]["parameters"]
    # 只取 schema 声明的参数；模型传入的 user_id 等其他字段一律丢弃
    args = {k: raw[k] for k in params["properties"] if k in raw and raw[k] is not None}
    missing = [k for k in params["required"] if k not in args or args[k] == ""]
    if missing:
        return _dump({"ok": False, "error": "BAD_ARGUMENTS", "message": f"缺少必填参数：{', '.join(missing)}"})

    try:
        if name == "search_after_sales_policy":
            result = tool["func"](**args)
        else:
            result = tool["func"](user_id, **args)
    except Exception:
        logger.exception("Tool %s 执行失败", name)
        return _dump({"ok": False, "error": "TOOL_FAILED", "message": "工具执行失败，请稍后再试"})
    return _dump(result)
