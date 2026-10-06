# P0 coverage failures: diagnosis

结论：`test_p0_coverage_consistency.py` 的三个失败都在共享准备步骤 `_partial_dish` 中发生。它把用户首次提出“想吃三杯鸡，2 人”直接当成“只买可售部分”的明确选择，断言此时已经有清单；当前公共 API 实际返回的是供给预览和 `supply_gap_choice` 澄清。该响应与当前部分采购边界一致。三个失败没有进入 session restore、revision、refresh 或 row-add 断言，因此这次回放没有证明这些路径存在覆盖持久化缺陷，也没有证据支持改生产逻辑。

## 复现与原始信号

专职 tester 已按冻结候选执行三个指定的公共 API 用例，调用参数见 [`process-start.json`](../evidence/p0-coverage-replay-3521071ea9a8416ea57d7f18b16397fd/process-start.json)。候选 HEAD 为 `d3f426ecaf169bd01a7b86c137c61b9034d5079b`，冻结 ZIP SHA-256 为 `094eb7d28777d5c3d7025bcad4aebd9f71a300cb275fe8679c9ec5cd825d2dfb`；运行前后均是 312 个来源文件、0 个哈希差异，商品目录哈希也一致（见 [`source-before.json`](../evidence/p0-coverage-replay-3521071ea9a8416ea57d7f18b16397fd/source-before.json) 和 [`source-after.json`](../evidence/p0-coverage-replay-3521071ea9a8416ea57d7f18b16397fd/source-after.json)）。

三例均在 `backend/tests/test_p0_coverage_consistency.py:80` 的 `assert body["plan"] and body["plan"]["gaps"]` 失败；pytest 原始输出为 `3 failed in 10.47s`。三次 HTTP 响应的 `status` 均为 `understanding`，`task_id` 和 `plan` 均为 `null`。第一例临时 SQLite 的 `turn_request_records.response_json` 记录了确切原因：`pending_clarifications[0].slot` 是 `supply_gap_choice`，消息列出可售商品与罗勒缺项，并问“要只为这些商品生成一份不完整的待确认清单吗？”，同时说明该步不会加购。原始 trace 在 [`stdout.txt`](../evidence/p0-coverage-replay-3521071ea9a8416ea57d7f18b16397fd/stdout.txt)，临时响应数据库在 [`test.sqlite3`](../evidence/p0-coverage-replay-3521071ea9a8416ea57d7f18b16397fd/basetemp/test_partial_plan_is_consisten0/test.sqlite3)。

## 依据与因果

- 当前术语定义将“部分采购清单”限定为用户明确选择仅购买可售部分后形成的清单；决定之前展示的是尚未建单的“供给预览”（[`GLOSSARY.md:62`](../../../../GLOSSARY.md#L62)、[`GLOSSARY.md:66`](../../../../GLOSSARY.md#L66)）。[`PROJECT-next.md:55`](../../../../PROJECT-next.md#L55) 对供给不足流程也写明先预览、不建单；用户明确选择后才创建或修订部分清单。该文档在这里作为 V2 设计佐证，不单独当作已提升的正式验收来源。
- 实际实现会在缺料时构造 `supply_gap_choice` 问题，并询问用户是否生成不完整清单（[`mutation.py:757`](../../../../backend/app/agent/graph/nodes/mutation.py#L757)）。`coverage_intent=partial_ok` 是清单生成后的覆盖授权字段；它本身不能替代当前轮的用户选择（[`plan_contract.py:11`](../../../../backend/app/services/plan_contract.py#L11)、[`plan_contract.py:36`](../../../../backend/app/services/plan_contract.py#L36)）。
- 已有公共 API 测试 `test_p0_gap_persistence.py` 的 `_partial_dish` 正好覆盖该两阶段契约：首次响应断言无 `plan`/`task_id` 并出现 `supply_gap_choice`，随后模拟明确回答“那就先买能买到的”及对应 `resolved_questions`，再检查部分清单（[`test_p0_gap_persistence.py:50`](../../../../backend/tests/test_p0_gap_persistence.py#L50)、[`test_p0_gap_persistence.py:71`](../../../../backend/tests/test_p0_gap_persistence.py#L71)）。
- 新失败用例的 `_partial_dish` 只调用 `lookup_then_add_id(...)` 并发送一次原始目标请求，随即要求有带缺口的清单（[`test_p0_coverage_consistency.py:74`](../../../../backend/tests/test_p0_coverage_consistency.py#L74)、[`test_p0_coverage_consistency.py:80`](../../../../backend/tests/test_p0_coverage_consistency.py#L80)）。该语义 provider 提案不等于用户回答了 API 提出的选择问题。

因此最小修复方向是迁移这个测试 fixture/oracle：先断言供给预览及未建单，再对返回的 `supply_gap_choice` 明确 opt in，然后保留现有跨读取和写入路径的覆盖断言。这样既能验证后续 `partial_ok` 清单，又会继续捕捉错误地跳过用户选择的行为。没有理由放宽断言或改生产代码。当前只验证了原失败回放；迁移后的三例尚未执行。

## 范围

本报告仅归因这三个 `test_p0_coverage_consistency.py` 用例。`test_p0_gap_persistence.py` 使用了显式 opt-in 的两阶段路径，因此不能把其完整回归中的 `FF.F` 归因于本报告发现的同一 fixture 缺陷；需依据该套件的原始失败 trace 单独诊断。本次未执行测试、模型或评测，也未修改源码、TASK 或索引。
