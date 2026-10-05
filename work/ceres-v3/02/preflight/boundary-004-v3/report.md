# V3 policy consultation boundary regression

- 范围：一次运行 `backend/tests/test_v3_policy_consultation.py`，覆盖无选单订单工具越权（三参数用例）、闲聊不建任务、政策初始化保留既有事实及未命中时诚实回答。
- 命令、解释器/pytest 版本、隔离 TEMP/TMP/basetemp、DB fixture 说明与 25 个相关文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- pytest 原始结果：stdout `stdout.txt` 显示 8 passed、51.27 秒，stderr `stderr.txt` 为空；进程退出码为 0。执行后 25 个相关文件 SHA-256 全一致，见 `source-check-after.json`。
- 验收状态：未通过。stdout 含 `PytestUnhandledThreadExceptionWarning`；最后的 `test_policy_reinitialization_keeps_existing_facts_and_unknown_query_is_honest` 之后，后台 `_run_turn_worker` 在 `AutomaticMemoryService.process_turn → TraceService.record` 写 `trace_events` 时收到 SQLite `database is locked`。按本轮验证规则将该警告视为失败；保留原始运行证据，不重跑覆盖。
- 测试用语义替身或 MockTransport；无真实模型/API。未改源码、测试源、TASK 或 Git 状态。
