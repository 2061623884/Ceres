# 06 售后后继续采购与自然回复

状态：进行中（04 已技术交付；与 05 按明确文本归属并行）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[04 两角色 Prompt 模块化](ceres-next-agent-experience-04-prompt-modules.md)。复用 04 的角色/公共表达组织方式，以及其上游 01 已确定的选项承接契约；05 是推荐先行的精简票，不是该链路的运行前置。
覆盖用户故事：18–26、32、35。

## 交付行为

用户购买并模拟结算后，在墨墨提交售后申请，再选择回可可选购替代商品；已明确诉求不用重输，状态与下一步用自然中文说明。

## 范围

贯通既有订单、售后操作、角色交接、剩余采购诉求与前端继续入口。仅实现有界代表链路，改善两角色表达并保留政策依据。

## 验收标准

- [ ] 完整演示购买确认加购、独立模拟结算、明确订单售后申请提交、用户选择继续采购和替代商品选购。
- [ ] 目标角色携剩余诉求、有效条件、明确对象及完成步骤续接，并重新读取业务事实。
- [ ] 申请提交准确表述为 Tool 返回状态，不声称退款到账或退货完成；完成步骤不重复执行。
- [ ] 售后失败先说明并暂停；用户选择继续采购时保留失败状态，未选择时不擅自续购或切换。
- [ ] 具体订单、owner 与执行授权沿既有规则；明确退货诉求不新增重复确认。
- [ ] 回复简短自然，说明结果与下一步，政策名称和适用条件易读；人工审读与事实/业务断言分别记录。
- [ ] 记录原请求、交接、已完成/剩余步骤及实际结果；受控、真实模型与前端选择验证分开。

## 修改归属与证据

本票负责有界续接数据与继续入口、墨墨及共用表达改进，不改可可 category_exploration 模块或其示例。05 在独立 before/candidate 树完成真实精简对照，再合最新集成；本票交付合最新 integration，单独登记源码与实际效果。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

完成申请提交为 pending 的购买至售后后续购旅程，以及取消、重复接受、旧交接重放和真实写入后模型失败边界；合最新集成版本后运行受影响回归。真实模型与同版页面证据由 08 补齐，本人验收另列。

## 实施证据（尚未技术交付）

- 公共接口的可可→墨墨及订单页直接墨墨两条失败售后路径，均已形成有效 red→green；实际 `create_return` 返回 `NOT_DELIVERED`，先保留结果再提供由用户选择的续购入口。见 [两路径绿测](../work/ceres-next-agent-experience/06/green/two-aftersales-paths-green.txt)。这不代表申请成功路径已通过。
- 续接 child 的显示确认、带 ID 切换、路由来源及自然 CTA 分别取得有效 red→green。确定性结果来源记录为 `aftersales_tool_result`，`raw_choice` 为空，未冒充 Kev 推断。见 [显示确认](../work/ceres-next-agent-experience/06/green/child-prompt-displayed-green.txt)、[来源](../work/ceres-next-agent-experience/06/green/continuation-route-provenance-green.txt)、[续购文案](../work/ceres-next-agent-experience/06/green/continuation-copy-green.txt)。
- 单类型商品回复的原内部标签串已沿公共导购接口 red→green 修复，见 [商品回复](../work/ceres-next-agent-experience/06/green/snack-natural-reply-green.txt)。这只是可观察回复边界，自然表达仍需实际对话审读。
- 前端锁定 pnpm 10.34.3 构建通过，见 [build](../work/ceres-next-agent-experience/06/green/frontend-build.txt)；先前全局 pnpm 11.7 的执行失败属于工具链，不计产品 red。受控页面续接点击尚在准备。
- 第一条失败售后 red 曾发生源码冻结重叠，早期记录不计有效失败；使用重新冻结的 [有效 red](../work/ceres-next-agent-experience/06/red/failed-aftersales-resume-red-frozen.txt)。递归类型声明缺少 future annotations 的早期 setup 错误也不计产品 red。
