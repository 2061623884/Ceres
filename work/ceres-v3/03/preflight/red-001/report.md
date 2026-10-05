# V3 Routing Handoff red-001

- 测试：`backend/tests/test_v3_routing_handoff.py::test_shopping_continues_existing_guide_with_observable_route`
- 完整命令、解释器/pytest 版本、TEMP/TMP/basetemp、隔离 DB 说明及 29 个相关文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- 环境：`MEMORY_MODEL` 显式为空；启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：1；stdout：`stdout.txt`（1 failed，2.60 秒）；stderr：`stderr.txt`（空）。失败为预期红：`opening()` 对 `POST /api/v1/chat/openings` 收到 404 `{"detail":"Not Found"}`，触发 `test_v3_routing_handoff.py:40` 的 200 断言。执行后 29 个关联文件 SHA-256 全一致，见 `source-check-after.json`。
- KEV fixture 仅在受控主机 `kev-controlled.invalid` 上模拟响应；本例在打开入口 404 时尚未调用该边界。未做完整网络抓包，不作进程级零外联声明。
- 仅执行该单例；未运行 03 其他测试、修改源码、测试源、TASK 或 Git 状态。
