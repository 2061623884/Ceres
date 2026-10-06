# Spec 轴复审（v3 冻结候选）

审查基线 `d3f426ecaf169bd01a7b86c137c61b9034d5079b`，比较实际 ZIP `c585b1d7…`→`0a4e45eb…` 的 13-path owned delta。候选未改生产运行时代码。写报告时共享工作树已有 v4 后续改动；以下只评 frozen `source.patch.json`，后续改动不计入 v3 结论。

## P2：迁移仍保留范围外的购物车补齐 oracle

patch 将 W03/M1b 的顶层状态期望改为 `completed`，却保留 `gap_fill_scope`、确认后追加差额及 `zero_delta` 断言（`backend/tests/test_w_dish_and_gap.py:71-87,197-237`）。M1b 明确要求购物车补齐；现行边界将它列为 P1 且不纳入导购（`PROJECT-next.md:18,30`; `PROJECT.md:56`）。v3 定向回执中三项仍因 `pending_clarification=None` 失败（`targeted-v3…/dish-gap-turns/stdout.txt:15-29`），不能以状态字段迁移称为修复，也不能因此新增 gap-fill runtime。W03 的“另做一份”可作为单独新任务能力另行定义；当前规格没有把它绑定到 post-confirm 补齐澄清。v4 已恢复 W 文件基线字节；这些旧失败仍须保留并按范围外记录。

## P2：deadline 覆盖需迁移到现行事务边界

冻结候选删去旧“部分 mutation 已提交后超时”断言，只留下提交前过期测试（`backend/tests/test_agent_deadline.py` patch hunk `@@ -138,154 +129,117 @@`）。现行 `_apply_batch` 的写入处于同一事务、异常回滚；提交发生在 `_emit_transport_events` 之前（`backend/app/agent/graph/turn_commit.py:约 578、约 529`），没有可达的 durable-prefix 路径，故旧 oracle 与当前实现不符。V3 要求以公共 API/SSE 和实际业务状态验证（`docs/plans/ceres-v3-spec.md:90,96`）；提交后发布 `plan.ready` 时预算耗尽，是可达的独立边界。v4 新增了终态、GET 与 receipt replay 断言，但该用例仍待 QA，不能计作通过或倒推 v3 已覆盖。

其余文档与迁移符合用户边界：Kev 固定、保守路由/同意、无订单政策问答、打开周期提示额度、业务完成后 Q20、Cursor 页面依赖均有明确记录；holdout 加入 `business_not_run` 与 Guide/cart 前后对照。没有新增业务运行时代码越界。07 六项验收仍未勾选；Cursor 页面未执行，22+5+4 实际验证未执行，21 个 RAG setup errors 仍未解决，故本审查不构成通过结论。
