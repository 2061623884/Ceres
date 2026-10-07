# 04：归档验收结论与产品修复入口

- 状态：待验收（2026-10-07 code-review修复、15项离线复验与最终派生报告归档完成；用户本人未确认交付，产品严格验收未通过）。
- 负责人：主 Agent 汇总；Standards/Spec 只读审查，专职测试 Agent 执行必要复验。
- Git 基线：`ee7ce104885f731bc48bc8c6338c00d802ba0619`；评测分支 `codex/ceres-v4-evaluation`，产品候选独立固定为 `ac895fd`。
- 所属：[总 TASK](ceres-v4-evaluation.md)。
- 依据：[规格](../docs/plans/ceres-v4-evaluation-spec.md)。
- 依赖：[02：完成 100 次任务评测与组件诊断](ceres-v4-evaluation-02-full-task-evaluation.md)、[03：验证真实专题入口和聊天气泡旅程](ceres-v4-evaluation-03-browser-journeys.md)，评测证据条件已满足。

## 交付行为

用户可以从唯一任务入口审查本次候选的自动验收结论、全部证据、可复跑命令和待修问题，知道哪些已经验证、哪些失败或未知，并可按最小复现启动后续产品修复。

## 范围与验收

- [x] 汇总 JSON/Markdown 与逐执行证据、实际命令、版本/数据/索引/模型冻结信息一致，可定位原始记录。
- [x] 固定必验场景/硬约束全通过、零关键违规、每轮 ≤15 秒才写自动验收通过；任一未满足保留未通过。
- [x] API、记忆组件、浏览器、模型裁判与人工未评测分别写结论，lexical 条件和未知成本/时延不被隐藏。
- [x] 产品失败按实际根因归档；未确认的根因写未知，不把评测器错误归咎产品。
- [x] 产品修复另列本地 TASK，包含冻结失败版本、最小复现、观察结果及预期结果；本轮不实施修复。
- [x] 双轴审查覆盖本轮全部修改，有效问题修复并完成必要复验，不额外扩批或修产品。
- [x] 检查最终差异，仅保留本次必要文件，候选产品源码和已有dirty工作保留；交付当前待用户验收。

## 边界与证据

不修改历史任务状态，不把交付完成写成用户已验收，不推送或部署。总 TASK 维护唯一最新状态，日志只记录关键取舍及原因。

最新证据：[报告](../work/ceres-v4-evaluation/review-20261007/acceptance-final-v3/acceptance.md)、[机器汇总](../work/ceres-v4-evaluation/review-20261007/acceptance-final-v3/acceptance.json)、[本轮code-review及修复](../work/ceres-v4-evaluation/review-20261007/code-review.md)。原[正式报告](../work/ceres-v4-evaluation/acceptance/acceptance.md)、[原机器汇总](../work/ceres-v4-evaluation/acceptance/acceptance.json)、[原失败阶段](../work/ceres-v4-evaluation/acceptance/failures.json)、[前轮审查](../work/ceres-v4-evaluation/final-review.md)保留。中断/准备失败/缺结果与诊断、陈旧汇总、来源指针和无依据模板已补离线负例；15项单测通过。H20性能N/A单列，有计时证据的54/99与业务及适用性能55/100分别报告；产品结论不变。

本轮修复Git基线为abd61394437f21c1b474d39c56559a245dc21e97；修复源代码摘要不同于历史冻结，不混用旧resume。新证据统一在review-20261007。历史辅助校验器失败及退出码保留于evidence/rescore-run04；不把测试适配器或旧CLI参数拒绝当作新的产品失败。
