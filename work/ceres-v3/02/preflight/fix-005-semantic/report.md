# Fix-005 semantic transport tests

- 范围：一次运行 `backend/tests/test_semantic_transport.py`（15 项）。
- 完整命令、解释器/pytest 版本、环境与 30 个关联文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- `MEMORY_MODEL` 显式为空；启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：0；stdout：`stdout.txt`（15 passed，0.20 秒）；stderr：`stderr.txt`（空）。执行后关联文件 SHA 全一致，见 `source-check-after.json`。
- 测试使用 `httpx.MockTransport` 控制所测语义请求。未做完整进程网络抓包，不据此声明进程级零外联；旧运行范围修正见 `network-scope-correction.json`。
- 未修改源码、测试源、TASK 或 Git 状态。
