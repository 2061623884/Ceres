# Spec 轴复审（v4 冻结候选）

审查基线 `d3f426ecaf169bd01a7b86c137c61b9034d5079b`，依据 ZIP `c585b1d7…`→`352dfedd…` 的 12-path owned delta；12 个当前文件摘要与 review-scope 一致。差异限于测试、文档和回归计划，无生产运行时代码变更；W 文件已恢复基线字节。

## P2：deadline 新用例比较了不同层级的 SSE 结构

`test_a_saved_plan_is_reported_when_the_budget_expires_during_publication` 在 `backend/tests/test_agent_deadline.py:233` 将终态 `body["plan"]` 与 `plan.ready` 的 `payload.plan` 直接比较。后者来自 `plan_ready_payload`，还带 `plan_effect`、`task_id`、`state_version`、`session_version`；前者只含业务计划（`backend/app/agent/responses.py:36-67`，由 `turn_stream_service.py:194-198` 包装）。v4 专项 QA 实际为 7 passed / 1 failed，原始失败列出这四个多余字段；同一回执已显示 `committed=True`，GET 内容和计划 ID/版本一致（`evidence/deadline-candidate-v4-04c44c7c6dfd4208830ca5c16bbcdbcf/agent-deadline/stdout.txt`）。这是测试 oracle 错误，不是保存缺陷。v5 已把外层元数据分别核对、剥除后再比计划；该修订仍待定向复验，不计 v4 通过。

未发现其他 Spec 轴偏差：Kev 固定；路由保守且切换须同意；一般政策无需订单；一次打开额度按实际展示 ACK；Prompt 优化在业务基线后；正式前端交给 Cursor。P0 gap、ledger、选择与无加购断言仍在。回归计划运行全 121 个 backend/5 个 Mercury 测试文件，不用过滤隐藏失败；原 v3 全量的 W/P1 与 RAG 数据问题仍保留为失败/缺项，S1 快照未替换。

v4 尚未验收：基线标注 `measurement_status` 为 not yet measured；v4 专项 deadline 回归有 1 项失败，22+5+4 最终组未运行；07 TASK 六项均未勾选，Cursor 页面和本人体验未执行。未发现生产功能偏差不等于最终验收通过。
