# 绿阶段 001：可可在未创建墨墨会话前读取退货政策

- 测试：`tests/test_v3_policy_consultation.py::test_keke_reads_return_policy_before_any_mercury_session`
- 执行环境、精确命令及执行前源码/测试 SHA-256：`environment-and-source.json`、`command.txt`。
- 退出码：0；stdout：`stdout.txt`；stderr：`stderr.txt`（空）。结果为 1 passed，12.96 秒。
- 执行后 SHA-256 对比：`source-check-after.json`。当前快照中只有测试模块 hash 不同；其文件修改时间 17:27:15 UTC 晚于测试完成时间 17:26:39 UTC。协调者随后确认已在该测试模块添加 red-002，因此这是测试完成后的并发工作树更新，不能据此推断测试运行改写源码。其余文件 hash 匹配。
- 隔离：TEMP/TMP 与 pytest basetemp 均为本 run 子目录；使用 backend 虚拟环境 Python 3.12.10 x64、pytest 9.1.1，禁用 pytest cache 和 Python bytecode。fixture 使用本地临时 SQLite，语义提供器受控，无真实 API 调用。
- 范围：仅执行此单例；未运行其他测试、修改源码/测试源/TASK 或提交 Git。测试通过仅覆盖该断言，不代表 TASK 02 整体验收。
