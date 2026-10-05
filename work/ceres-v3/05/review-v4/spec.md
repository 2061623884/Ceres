# V4 Spec review — initial source review

审查基线：原始本票前工作源码 ZIP `e91bbd5f0e02469d4cce9942d42763d75c4c64d6219c40b040fb7faa29c1382c`；HEAD `5462e999d583a9bab6147d0b4141d98321f3cc92`；候选 v4 ZIP `496e3417b4176ed3e4fcf35fda963037e193f6c357c9921c04bc47fde07b55f6`。按 `review-v4/source.patch` 的 14 项范围审查，14/14 SHA 与 scope 匹配，历史 V2 dirty 排除；无提交。

### 缺失或部分满足

未发现静态源码缺项。`reply_q20_pass` 现要求 5 个预定 case ID、5 份 receipt、H01 独立交接时长（总计 6 个计时）且全部样本断言通过（`work/ceres-v3/05/analyze-evidence.py`）；目标数量经 Goal/Mutation 保存（`backend/app/schemas/goal.py`、`backend/app/agent/protocol.py`、`backend/app/agent/authorization.py`），R06 v3.2 先判服务再留业务澄清（`backend/app/llm/kev_provider.py`），均符合已确认要求。

### 超出范围

未发现。v4 仅把已有 `LLM_MAX_OUTPUT_TOKENS` 从 1536 调到 3072，并在 `runtime-config.json` 记录非凭据变更；模型、主 Prompt、业务用例、数据和调用流程保持固定，符合针对实际截断的定向探查。

### 已实现但行为错误

未发现静态源码错误。运行验收尚不能下结论：v3 的 22/22 路由通过与 R01 `finish_reason=length` 失败仍保留；v4 五条真实角色样本正在执行，待读取原始命令、回执、退出码、实际 outgoing `max_tokens`、业务结果和逐轮耗时后再给最终证据判断。TASK 要求 18 个核心场景全部通过、失败保留，并记录样本量和 Q20（`tasks/ceres-v3-05-baseline-evaluation.md:14,17-19`）；完整回复 ≤15 秒及失败不排除的准则见 `docs/plans/ceres-v3-spec.md:96,98`。本审查未运行测试或模型。
