# V3 三条 tracer 小回归 003

- 范围：一次运行当前 `backend/tests/test_v3_policy_consultation.py` 中的 3 项测试；无筛选项。
- 解释器、pytest 版本、完整命令、隔离环境和执行前关联文件 SHA-256：`environment-and-source.json`、`command.txt`。
- 退出码：0；stdout：`stdout.txt`（3 passed，25.41 秒）；stderr：`stderr.txt`（空）。
- 执行后关联文件 SHA-256：`source-check-after.json`，21 个文件均未变化。测试使用本地临时 SQLite、语义提供器测试替身或受控 MockTransport；无真实 API 调用。
- 仅运行该测试文件一次；未修改源码、测试源、TASK 或 Git 状态。这是三个 tracer 的小范围回归，不代表 TASK 02 整体验收。
