"""run_mercury + Tool Calling Loop（同步）。"""

import logging
from contextlib import closing

from mercury import tools
from mercury.db import connect, use_database
from mercury.llm import OpenAIChatClient
from mercury.prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
HISTORY_TURNS = 6

# user_id -> [{"role": "user", ...}, {"role": "assistant", ...}, ...]，只存最终文本
_HISTORY: dict[str | tuple[str, str, str | None], list[dict]] = {}


def _user_exists(user_id) -> bool:
    with closing(connect()) as conn:
        return conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None


def run_mercury(user_id: str, message: str, llm=None, *, database_path: str | None = None,
                session_id: str | None = None, selected_order_id: str | None = None) -> str:
    with use_database(database_path):
        if session_id is None and not _user_exists(user_id):
            return "未找到该用户"
        if llm is None:
            llm = OpenAIChatClient()

        history_key = user_id if session_id is None else (user_id, session_id, selected_order_id)
        history = _HISTORY.get(history_key, [])[-HISTORY_TURNS * 2:]
        prompt = SYSTEM_PROMPT
        if selected_order_id is not None:
            prompt += f"\n本会话只咨询已选订单 {selected_order_id}。选单与查询不会申请售后；用户明确要求时才执行对应写工具。"
        messages = [{"role": "system", "content": prompt}, *history, {"role": "user", "content": message}]

        try:
            answer = None
            for _ in range(MAX_TOOL_ROUNDS):
                msg = llm.chat(messages, tools=tools.openai_tools(selected_order_id))
                if not msg.tool_calls:
                    answer = msg.content
                    break
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    result = tools.execute_tool(tc.function.name, tc.function.arguments, user_id=user_id, selected_order_id=selected_order_id)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                # 5 轮 Tool 都执行完仍没有最终回答：不带 tools 再调用一次
                messages.append({"role": "user", "content": "已达到工具调用上限，请只根据已有 Tool 结果回答"})
                answer = llm.chat(messages).content
        except Exception as exc:
            logger.warning("LLM 调用失败：%s %s", type(exc).__name__, getattr(exc, "status_code", ""))
            return "抱歉，服务暂时不可用，请稍后再试。"

        answer = (answer or "").strip() or "抱歉，我暂时无法回答这个问题。"
        turns = _HISTORY.setdefault(history_key, [])
        turns += [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
        del turns[:-HISTORY_TURNS * 2]
        return answer
