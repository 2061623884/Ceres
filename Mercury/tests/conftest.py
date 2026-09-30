import copy
import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from mercury import agent, tools
from mercury.db import connect, init_schema
from mercury.seed import seed


@pytest.fixture
def db(tmp_path, monkeypatch):
    """每个测试一个独立数据库，并清空会话历史；返回 query(sql, params)，用于断言或改数据（自动提交）。"""
    monkeypatch.setenv("MERCURY_DB_PATH", str(tmp_path / "mercury.db"))
    with closing(connect()) as conn:
        init_schema(conn)
        seed(conn)
        conn.commit()
    agent._HISTORY.clear()

    def query(sql, params=()):
        with closing(connect()) as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
            conn.commit()
            return rows

    yield query
    agent._HISTORY.clear()


def text(content):
    """FakeLLM 脚本：纯文本回复。"""
    return SimpleNamespace(content=content, tool_calls=None)


def call(*calls):
    """FakeLLM 脚本：一条带 tool_calls 的消息。calls 为 (name, args_dict) 元组。"""
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(id=f"call_{i}", type="function",
                            function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)))
            for i, (name, args) in enumerate(calls)
        ],
    )


class FakeLLM:
    """按脚本依次返回预设消息；脚本项为 Exception 时抛出。记录每次收到的 messages 和 tools。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def tool_spy(monkeypatch):
    """包装 mercury.tools.execute_tool，记录 (name, args, result)；args 和 result 解析为对象。"""
    records = []
    real = tools.execute_tool

    def spy(name, arguments, user_id):
        result = real(name, arguments, user_id=user_id)
        try:
            args = json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            args = arguments
        records.append((name, args, json.loads(result)))
        return result

    monkeypatch.setattr(tools, "execute_tool", spy)
    return records
