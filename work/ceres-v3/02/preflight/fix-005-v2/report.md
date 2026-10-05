# Fix-005 V2 order/Mercury boundary tests

- 范围：一次运行 `backend/tests/test_v2_order_mercury.py`（16 项）。
- 完整命令、解释器/pytest 版本、独立 TEMP/TMP/basetemp、DB fixture 说明及 30 个关联文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- `MEMORY_MODEL` 显式为空，并启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：0；stdout：`stdout.txt`（16 passed，12.81 秒）；stderr：`stderr.txt`（空）。执行后 30 个关联文件 SHA 全一致，见 `source-check-after.json`。
- Mercury 调用由本测试的 monkeypatch 控制。未做完整网络抓包，故不作进程级零外联断言；见 `network-scope-correction.json` 对先前范围的更正。
- 未修改源码、测试源、TASK 或 Git 状态。
