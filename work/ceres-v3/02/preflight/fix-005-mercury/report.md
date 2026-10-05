# Fix-005 Mercury policy boundary tests

- 范围：运行 `Mercury/tests/test_policy.py` 与 `Mercury/tests/test_agent_flows.py::test_policy_flow`（8 项）；未运行 live 标记用例。
- 完整命令、解释器/pytest 版本、临时 DB/TEMP/TMP/basetemp、环境与 12 个相关文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- `MEMORY_MODEL` 显式为空；启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：0；stdout：`stdout.txt`（8 passed，0.60 秒）；stderr：`stderr.txt`（空）。执行后 12 个相关文件 SHA 全一致，见 `source-check-after.json`。
- 测试节点使用 FakeLLM；没有进行完整网络抓包，因此不作进程级零外联声明。
- 未修改源码、测试源、TASK 或 Git 状态。
