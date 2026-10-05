# 绿阶段 002：墨墨无选单时咨询政策

- 测试：`tests/test_v3_policy_consultation.py::test_momo_can_consult_policy_without_selecting_an_order`
- 执行命令、解释器/pytest 版本、隔离环境及执行前关联文件 SHA-256：`command.txt`、`environment-and-source.json`。
- 退出码：0；stdout：`stdout.txt`（1 passed，1.82 秒）；stderr：`stderr.txt`（空）。
- 执行后 SHA-256：`source-check-after.json`，14 个关联文件均未变化。相较 red-002 的执行前基线，`backend/app/api/mercury.py` 已是新实现版本；本次执行期间该版本保持不变。
- 本例使用本地临时 SQLite 与测试内受控 OpenAI 客户端；TEMP/TMP、pytest basetemp 均位于本 run 子目录，无真实 API 调用。
- 仅执行该单例；未修改源码、测试源、TASK 或 Git 状态。本通过结果只覆盖此单例，不代表 TASK 02 整体验收。
