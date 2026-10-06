# 07 Spec 独立审查

审查基准：HEAD `d3f426ecaf169bd01a7b86c137c61b9034d5079b`，无后续提交；候选源码 ZIP SHA-256 `094eb7d28777d5c3d7025bcad4aebd9f71a300cb275fe8679c9ec5cd825d2dfb`。依据 `review-scope.json` / `source.patch.json` 静态审查；未运行测试、模型或评测。

**结论：1 项 P2 验收覆盖缺口；需求范围缺项 0；范围蔓延 0。** README 仅新增入口；后台说明、独立留出观察器、07回归计划及TASK状态更新均在本票范围。

- **[P2] 建议切换时未证明业务确实暂停。** 契约要求“路由建议的本轮以 `turn.completed` 的 `business_not_run:true` 结束，须等用户选择后才执行另一角色”（`work/ceres-v3/04/api-contract.md:89`）。观察器只取首个 SSE 事件，并按路由结果、角色未变及订单列表不变判通过（`backend/tests/test_v3_independent_routing.py:83-95`）；未断言终端事件的 `business_not_run`，也未核对相关清单/业务状态。HO03/HO04 即使建议切换后错误执行当前业务，仍可能通过。建议保留并断言完整 SSE 终态及未授权业务状态不变。

Cursor正式页面和本人体验确认仍未完成（`work/ceres-v3/07/cursor-acceptance.md:3,21-23`），不能据后台 API 交付宣称总体已验收。完整回归、22条路由、5段真实角色旅程/7个回复计时、4条独立留出仍待最终证据；主会话报告的 deadline 模块5项失败尚待 trace/独立诊断，不据此预判最终结果。Q20 目标仍为同版路由 P95≤1秒、完整回复≤15秒，冷启动单列。