# V3 验收与历史 S1/RAG 输入边界

## 可核实事实

07 初始 candidate ZIP `094eb7d2…` 的全量 backend 原始输出中，21 个 `test_rag_codex_review.py` setup errors 都在 fixture 打开 `verification/data-completion/candidate_runtime.sqlite3` 时产生 `sqlite3.OperationalError: unable to open database file`；首个 stack 位于 `full-e5095afb1e2b4d19babc56f38e917212/backend/stdout.txt:145-151`。路径当前不存在。`backend/tests/test_rag_codex_review.py:13-35` 在测试体运行前，从该只读快照备份临时业务库、重建检索投影和词法索引；因此 21 项的具体检索断言没有执行。

该快照在历史交付文档中被定义为“隔离候选库（不进正式运行路径）”（`docs/2026-09-19-cursor-codex-delivery.md:96-110`）。RAG 实现说明称它是冻结投影的来源（`docs/rag/2026-09-19-implementation.md:64-74`）。这些 probes 检查继承的菜品/SKU 召回、食材字典、索引完整性、过滤及配送数据，不是 V3 一般政策数据源。

## 与 V3 路径的关系

V3 一般政策读取由 `backend/app/agent/tools/read.py:526-529` 调用 `policy_service.search_policies`，查询 `AfterSalesPolicy` SQL 行（`backend/app/services/policy_service.py:1-29`）；应用启动时独立初始化这些政策（`backend/app/main.py:69-78`）。Kev 的角色准则也明确两角色都能处理一般政策（`backend/app/llm/kev_provider.py:14-29`）。公共 API 覆盖可可无 Mercury session 问政策且不建 task/cart/order（`backend/tests/test_v3_policy_consultation.py:40-59`），以及墨墨未选订单政策咨询和拒绝未选单订单工具（同文件 `:101-162`）。这一链路不打开 S1 SQLite、不构建 RAG 投影。

`backend/app/api/chat.py:233-235` 的 `stay_current` 会继续调用原角色业务，因此 S1 错误仍是继承 RAG 测例的真实覆盖缺口；不得把 21 errors 或相关缺快照 skips 计作绿测。V3 自身的八个测试文件及真实角色/路由组另行通过，覆盖了本票新增路由与政策行为；真实购物旅程另见 `work/ceres-v3/07/validation.md:14-20`。根据调用路径，历史 S1 语料不是 V3 一般政策或服务路由验收的必要前置，也不能代表完整检索语料回归。

## 验收边界

07 的首项勾选范围限定为新增 V3 模块与固定集成行为；全仓 19 failures、21 setup errors、57 skips 单独保留。若要关闭继承 RAG 覆盖，须恢复可溯源的 Ceres 原始 S1 快照并另行执行对应测试；不能用邻项目同名库复制或重建来伪造通过。当前 07 与总 TASK 保持“待验收”，因为 Cursor 实际页面和本人体验仍未完成，不因 S1 缺失转为“已验收”。
