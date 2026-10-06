# Standards 轴复审（v5）

以固定点 `d3f426ecaf169bd01a7b86c137c61b9034d5079b` 和候选 ZIP `a85bfc70c017999c01833c0969abf7217a4373c49673ca2ed750ef662a3a7dae` 复审。review-scope 列出的 12 个当前文件 SHA-256 均与工作区匹配；相对 v4 的变更仅在 deadline 测试。未运行测试或检查工具。

**Hard violations：0。** `backend/tests/test_agent_deadline.py:233-237` 修正了 SSE 事件与终态响应的结构比较：明确对齐 `plan_effect`、task/state/session 版本四个 envelope 字段，其余计划字段整体与 `body["plan"]` 比较。这与 `plan_ready_payload` 将权威版本字段放在计划 payload 上的现行结构一致，也保留了完整计划内容比较，没有弱化业务断言或增加生产代码。

**Possible smells：0。** 新比较是局部且直接的结构断言，没有引入抽象或重复逻辑。完整新文档和独立路由测试仍与 v4 reviewed scope 的 SHA-256 一致，沿用 v4 全文件复审结论。v5 deadline 用例仍待 QA 复验，本报告不推断其通过。
