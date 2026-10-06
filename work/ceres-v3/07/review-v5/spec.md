# Spec 轴复审（v5 冻结候选）

审查基线 `d3f426ecaf169bd01a7b86c137c61b9034d5079b`，依据 ZIP `c585b1d7…`→`a85bfc70…` 的 12-path owned delta；当前 12 个文件摘要与 review-scope 一致，且仅 deadline 测试相对 v4 改动。无生产运行时代码变更，W 测试恢复基线并保留其原始失败记录。

## 结论

v4 唯一 P2 已在 v5 修正：`backend/tests/test_agent_deadline.py:233-237` 现在分别校对 `plan.ready` 的四个 envelope 字段，再剥除后比较业务 plan；符合 `plan_ready_payload` 与 SSE 包装契约（`backend/app/agent/responses.py:36-67`、`backend/app/services/turn_stream_service.py:194-198`）。事务提交后时钟过期的用例仍通过 public SSE、GET 和 receipt replay 验证保存事实，没有改生产逻辑。未发现其他 Spec 轴问题；没有执行测试，且专职 QA 仍在复验该新增节点，不能宣称通过。

## 验收边界与状态

新增/相关模块回归与全仓回归应分开报告，但不能互相抵销：07 要求固定核心通过、相关模块完整回归和有效问题复验（`tasks/ceres-v3-07-final-acceptance.md:14,23`）；计划仍要求完整运行 121 个 backend 与 5 个 Mercury 测试文件（`regression-plan.json:64-95,239`），不以过滤隐藏问题。历史 v3 全量结果是 19 failed、21 setup errors、57 skipped（`evidence/full-e5095afb1e2b4d19babc56f38e917212/backend/stdout.txt:1274`），其中包含明确排除的 P1 W 用例、缺失 RAG review 数据和未提供的 S1 snapshot；它不是 v5 结果，也不能改写成通过。RAG 相关错误与政策/检索验证有关，缺数据时不能凭独立测试绿灯宣布相关完整回归通过。

建议 TASK 保持 `进行中`，不要标 `待验收` 或 `阻塞`：v5 新增节点复验、22+5+4 最终组及候选同版相关完整回归尚无结果，尚有可执行验证；仅待 Cursor 页面与本人确认时再转入待验收。TASK 六项仍未勾选，Cursor 清单仍未执行。
