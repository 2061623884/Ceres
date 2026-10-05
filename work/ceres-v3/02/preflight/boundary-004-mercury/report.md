# Mercury policy boundary regression

- 范围：运行 `Mercury/tests/test_policy.py` 与 `Mercury/tests/test_agent_flows.py::test_policy_flow`；该节点存在。未运行 live 标记用例。
- 命令、解释器/pytest 版本、TEMP/TMP/basetemp、临时 DB 说明和 10 个相关文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：1；stdout：`stdout.txt`（7 passed、1 failed，0.85 秒）；stderr：`stderr.txt`（空）。执行后 10 个相关文件 SHA-256 全一致，见 `source-check-after.json`。
- 失败：`tests/test_agent_flows.py::test_policy_flow` 在第 80 行预期 `run_mercury(...) == "1–3 个工作日到账。"`，实际返回“抱歉，服务暂时不可用，请稍后再试。”；捕获日志为 `LLM 调用失败：TypeError`（`Mercury/mercury/agent.py:67`）。
- DB 由 Mercury fixture 为每例创建于 pytest `tmp_path/mercury.db`；政策 flow 使用 `FakeLLM`，未运行真实 API 或 live 测试。
- 未修改源码、测试源、TASK 或 Git 状态。
