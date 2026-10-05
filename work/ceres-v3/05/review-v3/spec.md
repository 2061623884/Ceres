# Spec review v3 — source findings; execution evidence pending

审查基线：HEAD `5462e999d583a9bab6147d0b4141d98321f3cc92`；原始本票前工作源码 ZIP `e91bbd5f0e02469d4cce9942d42763d75c4c64d6219c40b040fb7faa29c1382c`；候选 v3 ZIP `057c8503f97e49da9425e07294bfdaf5af3d8cb46c20fb1814eac0f202131b69`。按 `review-v3/source.patch` 的 13 项范围审查，13/13 文件摘要匹配；继承 V2 dirty 排除。**Source finding: 1。**

### 缺失或部分满足

1. **完整回复 Q20 可被不完整样本组误判通过。**规格要求“报告正常输入逐轮时长和样本量”及“超时和失败单列，不能靠排除失败宣称达标”（`docs/plans/ceres-v3-spec.md:96`），TASK 05 也要求记录完整回复样本量（`tasks/ceres-v3-05-baseline-evaluation.md:18`）。采样协议固定 5 个角色样本且 H01 另计一次交接回复（`work/ceres-v3/05/evaluation-protocol.md:10-12`），但分析器仅对发现的 receipt 检查 `max(reply_times) <= 15000` 与 `all(row["passed"] ...)`（`work/ceres-v3/05/analyze-evidence.py:20-51`），未验证五个预期案例均有回执，也未要求 H01 交接计时存在。若缺回执的样本未写出，少量剩余通过项仍可能得到 `reply_q20_pass=true`。需先要求完整 5 个案例回执及 H01 双段回复计时，再评 Q20；不完整时明确失败/缺失。

### 未授权范围

未发现。产品件数传递、Kev 仅以 v3.2 准则区分服务归属与业务内澄清、采样异常持久化均对应本票已记录的失败与验收需求（`work/ceres-v3/05/fixes.md`）；未见改动固定用例标签、模型或业务数据。

### 已实现但行为错误

除上述分析器 completeness gate 外，未发现额外源码规格错误。真实执行证据尚不完整：v3 实时路由原始记录为 22/22 通过、exit 0；角色采样为 1 failed / 4 passed、exit 1，R01 实际响应 `stay_current` 但终态 `plan=null`。原始材料位于 `work/ceres-v3/05/evidence/20261006T063034368-f2b8c785af8745e7b39535c735aa930f/`。这是真实业务失败，不能与 v2 已纠正的 `user_quantity` 假断言混同，也不能称本票通过；当前 core/probe 与完整 Q20 分析待补证。本审查未运行测试或模型。
