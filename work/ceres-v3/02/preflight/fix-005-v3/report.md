# Fix-005 V3 policy boundary tests

- 范围：一次运行 `backend/tests/test_v3_policy_consultation.py`（8 项）。
- 完整命令、解释器/pytest 版本、环境、DB 隔离说明及 30 个关联文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- 退出码：0；stdout：`stdout.txt`（8 passed，7.44 秒）；stderr：`stderr.txt`（空）。`-W error::pytest.PytestUnhandledThreadExceptionWarning` 已启用。执行后 30 个相关文件 SHA 全一致，见 `source-check-after.json`。
- `MEMORY_MODEL` 显式设为空；V3 测试的语义 HTTP 边界使用 `httpx.MockTransport`，测试夹具隔离并等待实际 turn worker。未做完整网络抓包，因此本报告不作进程级零外联断言；见上级 `network-scope-correction.json` 对旧运行的更正。
- 未修改源码、测试源、TASK 或 Git 状态。
