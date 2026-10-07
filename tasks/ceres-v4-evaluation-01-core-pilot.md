# 01：冻结候选并跑通核心场景评分

- 状态：已验收（2026-10-07 评分有效性与最终补断言离线复验通过；仅本票技术条件，不代表产品通过）。
- 负责人：主 Agent 实现，专职测试 Agent 执行。
- Git 基线：`ee7ce104885f731bc48bc8c6338c00d802ba0619`；评测分支 `codex/ceres-v4-evaluation`，产品候选独立固定为 `ac895fd`。
- 所属：[总 TASK](ceres-v4-evaluation.md)。
- 依据：[规格](../docs/plans/ceres-v4-evaluation-spec.md)。
- 阻塞：无。

## 交付行为

验收负责人可以针对 ac895fd，在独立状态下执行 20 个核心任务首轮，并从实际轨迹核对评分是否有效。完成一次从冻结候选、准备初始业务条件、真实模型/API 调用、确定性判分到失败记录的完整路径；产品失败保留，不阻塞其他独立任务。

## 范围与验收

- [x] 固定产品候选、源码及未提交输入、种子数据、lexical 索引、实际模型/Prompt、样本和评分规则，继续执行会拒绝版本漂移。
- [x] 完整套件满足 60 场景、40 回归/20 新验收、20 核心三次的结构，旧已用留出不重命名为新验收。
- [x] 评分器离线负例证明缺失金额/预算、错误价格、未经同意的角色切换与未授权写入不能通过，失败保留分母。
- [x] 20 个核心首轮各独立执行，保留准备、输入、SSE、前后状态、检查、错误和实际最终回复时间。
- [x] 代码评分逐项与当前接口契约核对；脚本失败与产品失败分开，评测器问题修复后保留原记录并重新冻结。
- [x] 自动执行停在首批边界，不直接放行剩余 80 次；主会话记录评分规则复核结论。

## 排除与后续

不修产品，不做人工评测，不把首批达标解释为整体通过。现有 runner、样本和准备产物作为草稿输入，不能提前勾选已验收；最终执行须使用本票复核后的冻结版本。

原始执行保留在 [run-01](../work/ceres-v4-evaluation/run-01/report.md)。复核修正 R14 漏读 Mercury 政策依据、R17 helper 覆盖完整前态两项评测器错误，并加强默认食材角色断言；用已有状态/调用重评分，没有新增产品模型执行。中间修订 run-02 留作历史；[run-03](../work/ceres-v4-evaluation/run-03/manifest.json) 是全量真实执行与当时评分条件的入口，保存原始执行路径/摘要和评分器版本。最终补断言离线评分另见 run-04。

首批业务 16/20，业务与性能均达标 12/20；35 个计时回合 P50 5752ms、P95 23671.1ms、最大 28239.4ms。业务失败 R01/R07/R11/R19，性能失败 R03/R06/R12/R17，保留产品失败。离线评分器修订后复验 10 项通过，见 [修订后测试输出](../work/ceres-v4-evaluation/corrected-pilot-evidence/scorer-tests.stderr.txt) 与 [评分复核记录](../work/ceres-v4-evaluation/corrected-pilot-evidence/corrected-pilot-verification.json)。裁判原始输出多数缺失 JSON，作为未知诊断保留，不进入本票评分有效性硬门槛。

主会话确认评分规则有效，解除 02、03 依赖，授权仅剩余 80 次任务执行及两条 UI 旅程；本票不授权扩批。

最终审查补足 R17/H03/H12 的指定商品、数量、选中状态与金额规则，样本 v2 仅改变这三步断言。用已捕获记录离线派生 [run-04](../work/ceres-v4-evaluation/run-04/manifest.json)，100 条来源/调用/时间均核对，未重跑产品。当前评分器 10 项单测与三场景 18 项负例通过，见 [补断言复验](../work/ceres-v4-evaluation/evidence/rescore-run04/negative-cases.stdout.json) 与 [单测](../work/ceres-v4-evaluation/evidence/rescore-run04/unittest.stderr.txt)。原评分与冻版保留。
