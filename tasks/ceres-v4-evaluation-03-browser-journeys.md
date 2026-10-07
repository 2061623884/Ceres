# 03：验证真实专题入口和聊天气泡旅程

- 状态：待验收（2026-10-07 修正后两条固定旅程已完成，业务 1/2、性能 1/2、两者同时达标 0/2）。
- 负责人：主 Agent 实现，专职测试 Agent 执行。
- Git 基线：`ee7ce104885f731bc48bc8c6338c00d802ba0619`；评测分支 `codex/ceres-v4-evaluation`，产品候选独立固定为 `ac895fd`。
- 所属：[总 TASK](ceres-v4-evaluation.md)。
- 依据：[规格](../docs/plans/ceres-v4-evaluation-spec.md)。
- 阻塞：无；[01](ceres-v4-evaluation-01-core-pilot.md) 已满足，不依赖 02 全量执行结束。

## 交付行为

在同一候选的实际前后端和真实模型下，用户能从专题入口、产品/分类气泡完成预设选购与明确加购。浏览器操作、可见结果和业务结果共同形成证据，单独报告 UI 结论。

## 范围与验收

- [x] 前后端与本票隔离数据库固定到候选；不复用 API 批次污染的数据库。
- [x] 一条专题成品选购及一条零食分类气泡选购使用固定有界操作；脚本不临场救场或替模型选择答案。
- [x] 使用真实页面和真实 API/模型，不拦截请求、不注入假状态。
- [x] 核对入口/气泡可见性、选定商品、确认前无购物车写入、明确确认后数量与金额；缺少清单时保留失败，不代替确认。
- [x] 保留操作、可见回复、请求/回执、截图和失败阶段；可采集时记录首个有用结果及最终完成时间。
- [x] 每轮最终回复沿用 ≤15 秒，功能与性能分开；失败不由 API 通过替代。
- [x] API 的 100 次结果与本票 UI 执行不合并成一个成功率，不代替人工体验。

## 边界与证据

本票限定专题与气泡的必要旅程，不扩成全量浏览器平台。自建进程与隧道按所属关系清理，保存启动身份与实际运行条件。本票不修产品行为。

原 [UI run-01](../work/ceres-v4-evaluation/ui/run-01/result.json) 是无效取证批次：候选导购 SSE 使用 `data:{type,payload}`，旧 parser 只识别带 event 行的格式；页面实际已显示专题商品答复却被误判缺完成回执。另外可可导航按钮的 SVG aria-label 使精确名称匹配失败，脱离 action 的 response waiter 拒绝造成第二旅程未完成。原脚本、命令、exit=1、截图和取证结果保留；这两项不是产品失败，也不计为有效两条 UI 验收。

新脚本沿当前 API/helper 契约解析两种实际 SSE 格式，先保存原文再解析；修正 accessible-name selector，所有 action/waiter 均即时绑定拒绝。重跑前使用新种子库、运行 receipt、进程/源码身份和独立冻结副本；仅重新执行本票两条固定旅程，不重跑 API 100 次。UI 的最终回复时间口径是动作开始至完整收到 completed SSE，文本渲染时间未采集。

有效 [run-02](../work/ceres-v4-evaluation/ui/run-02/result.json) 的两条旅程均完成取证，脚本退出 1 表示严格验收未通过。专题沙拉完成真实入口、准备清单及明确确认，最终购物车 1 件 / 2380 分；首轮完成 SSE 为 15576.31ms，功能通过、性能未通过。零食入口与薯片气泡可见且已点击；固定需求“原味薯片70克两包”在准备清单时收到 `TARGET_NAME_MISMATCH`（显示引用名称为“原味薯片70克袋装”），无清单、购物车为空，功能未通过；3 轮均在 15 秒内。守卫阻止错名执行是实际观察，未确认根因，已归入 [选购修复票](ceres-v4-repair-shopping.md)。

运行身份见 [receipt](../work/ceres-v4-evaluation/ui/runtime-receipt-run02.json) 与 [服务身份](../work/ceres-v4-evaluation/ui/run-02-service-identity.json)：候选 backend app 的真实路径/摘要、启动 PID 与监听 PID 相符，前端独立代理至本票 18012，实际 App 模块摘要已记录。owner/数据库绑定复核通过；首轮与之后所有确认前购物车写入为零。已核对当前命令行和监听端口后关闭本票后端、Vite 与 Kev 隧道，用户 8012 仍为原 PID；见 [清理回执](../work/ceres-v4-evaluation/ui/cleanup-receipt.json)。

最终审查在当前脚本补足确认前行小计、选中总额和零食预算断言。使用 run-02 已捕获专题清单离线核对：1 件 / 单价 2380 / 小计及选中总额 2380，全部通过；零食未到清单阶段，预算断言未执行，仍保留失败。当前脚本与执行时冻版的差异仅为三项断言，静态检查通过；没有重跑浏览器，见 [离线复核](../work/ceres-v4-evaluation/evidence/rescore-run04/ui-run02-offline-audit.stdout.json)。
