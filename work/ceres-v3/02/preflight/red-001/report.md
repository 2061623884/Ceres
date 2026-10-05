# 红阶段 001：可可在未创建墨墨会话前读取退货政策

- 测试：`tests/test_v3_policy_consultation.py::test_keke_reads_return_policy_before_any_mercury_session`
- 执行环境、精确命令及执行前源码/测试 SHA-256：`environment-and-source.json`、`command.txt`。
- 退出码：1；stdout：`stdout.txt`；stderr：`stderr.txt`（空）。
- 结果：1 failed，3.12 秒。测试请求成功返回 200，但最终响应 JSON 不含 `P-RET-01`，失败在 `backend/tests/test_v3_policy_consultation.py:28` 的响应来源断言。失败发生在预期业务红用例处，未见解释器、pytest、TEMP/TMP、数据库或外部 API 错误。
- 解释边界：当前可确认输出未包含来源编号；仅凭该断言不进一步推断内部根因。测试源码中使用 `semantic_provider` 注入受控语义提供器，没有调用真实模型 API。
- 执行后源码和测试 SHA-256 对比：`source-check-after.json`，未发现执行导致的内容变化。pytest 临时数据库及 TEMP/TMP 均位于本 run 子目录；没有运行其他测试。
