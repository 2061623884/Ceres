# 06 售后后继续采购与自然回复

状态：待验收（技术交付；同版真实模型、完整页面恢复与本人表达接受留 08）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[04 两角色 Prompt 模块化](ceres-next-agent-experience-04-prompt-modules.md)。复用 04 的角色/公共表达组织方式，以及其上游 01 已确定的选项承接契约；05 是推荐先行的精简票，不是该链路的运行前置。
覆盖用户故事：18–26、32、35。

## 交付行为

用户购买并模拟结算后，在墨墨提交售后申请，再选择回可可选购替代商品；已明确诉求不用重输，状态与下一步用自然中文说明。

## 范围

贯通既有订单、售后操作、角色交接、剩余采购诉求与前端继续入口。仅实现有界代表链路，改善两角色表达并保留政策依据。

## 验收标准

- [x] 公共接口受控旅程覆盖购买确认加购、独立模拟结算、明确订单退款申请 pending、用户选择继续采购、替代商品待确认清单及明确确认；真实模型/页面完整演示另列。
- [x] 目标角色携原请求、有效条件、明确对象及实际 Tool 结果，按角色规则续接剩余采购并重查供给；不建立通用任务队列。
- [x] 实际申请 pending 与退货 NOT_DELIVERED 分开保留；最终模型回复出错不丢失已执行结果，重复接受不重复业务调用。
- [x] 售后失败先说明并暂停；用户选择继续时保留失败结果，取消不续购或切换。
- [x] 具体订单、owner 与执行授权沿既有规则；测试核对明确目标订单，未给角色切换额外业务授权。
- [ ] 回复简短自然，说明结果与下一步，政策名称和适用条件易读；人工审读与事实/业务断言分别记录。
- [ ] 记录原请求、交接、已完成/剩余步骤及实际结果；受控、真实模型与前端选择验证分开。

## 修改归属与证据

本票负责有界续接数据与继续入口、墨墨及共用表达改进，不改可可 category_exploration 模块或其示例。05 在独立 before/candidate 树完成真实精简对照，再合最新集成；本票交付合最新 integration，单独登记源码与实际效果。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

本票源提交 `5868f2dd60b38ad84638b28c02ed496db68f2afc`；实施分支最终 `7b86b04af3d7f4c848a51e938dcd5e9347fee348` 已继承集成 `8da6d9b46e07f4ebd23ef0fad75aa7c55915e7e2`。merger 合入后交 08 同版真实模型、页面结果恢复与表达审读；本人验收待完成，不扩采旧开发用例。

## 实施证据与适用范围

- 公共接口的可可→墨墨及订单页直接墨墨两条失败售后路径，均已形成有效 red→green；实际 `create_return` 返回 `NOT_DELIVERED`，先保留结果再提供由用户选择的续购入口。见 [两路径绿测](../work/ceres-next-agent-experience/06/green/two-aftersales-paths-green.txt)。这不代表申请成功路径已通过。
- 续接 child 的显示确认、带 ID 切换、路由来源及自然 CTA 分别取得有效 red→green。确定性结果来源记录为 `aftersales_tool_result`，`raw_choice` 为空，未冒充 Kev 推断。见 [显示确认](../work/ceres-next-agent-experience/06/green/child-prompt-displayed-green.txt)、[来源](../work/ceres-next-agent-experience/06/green/continuation-route-provenance-green.txt)、[续购文案](../work/ceres-next-agent-experience/06/green/continuation-copy-green.txt)。
- 单类型商品回复先去掉“主推/推荐理由”等内部格式；发现仍在罗列用途标签后，继续以公共可见回复修复。有效第二轮为 [tag red](../work/ceres-next-agent-experience/06/red/natural-reply-v2-red-03.txt)→[最终 green](../work/ceres-next-agent-experience/06/green/natural-reply-v2-green-02.txt)，两项通过；保留已核实商品名和底层数据，不锁定固定自然句、不增加模型调用。自然表达仍需实际对话审读。
- 前端锁定 pnpm 10.34.3 构建通过，见 [build](../work/ceres-next-agent-experience/06/green/frontend-build.txt)；先前全局 pnpm 11.7 的执行失败属于工具链，不计产品 red。受控页面续接点击尚在准备。
- 第一条失败售后 red 曾发生源码冻结重叠，早期记录不计有效失败；使用重新冻结的 [有效 red](../work/ceres-next-agent-experience/06/red/failed-aftersales-resume-red-frozen.txt)。递归类型声明缺少 future annotations 的早期 setup 错误也不计产品 red。
- 后续自然文案的一次精确句式断言口径过窄；red-02 和初次 green 实际先失败在本切片额外添加的卡片断言，未运行到 tag 断言。两轮原始输出及更正均保留，不计有效 tag 红绿。移除无关的新断言后取得上述 red-03→green。
- 完整售后生命周期模块 [12 项通过](../work/ceres-next-agent-experience/06/final/backend-lifecycle-suite.txt)，24.94 秒，覆盖退款 pending 后最终 Momo 模型异常、用户接受/取消、续接清单/确认和同 ID 重放。已实现边界首次绿测为 characterization/回归，不伪造产品 red。
- 合入 05 及最新 Prompt 后，[三模块必要回归](../work/ceres-next-agent-experience/06/final/post-merge-backend-regression-rerun.txt)为 20 passed，37.04 秒，exit 0；之后只合档案/VCS 属性，产品源码未变，未重复业务采样。
- [受控实际浏览器 probe](../work/ceres-next-agent-experience/06/ui/after-sales-continuation-ui-probe.mjs)及 [通过记录](../work/ceres-next-agent-experience/06/final/ui-controlled-probe-rerun.txt)：订单页选单后展示续接入口，自动显示确认和用户点击均使用同一 child handoff ID，目标为可可。API 全受控，无真实模型；只证明入口/ID/选择与切换，未证明切换后采购回复/方案恢复。首次等待未提供的 mock 回复超时属于 probe 口径错误，原记录保留。
- 最终关键 SHA256：Mercury agent `13FFD9E40CECAD0CF4214BD48A7A8A4516D756611DCA630A947D9E93B0BAA96B`；chat API `2AA8CC186EE45C7D3D75E2764449E2EDA500AD50D9EFF795464EF91024D360FB`；Guide answer `E8CFC8586158883D9CEECBAAD08B77196DD2207C1393E76F7755A0311DFFD018`；合并后 semantic Prompt `6D62849E82842A3CECAD491AAEB449ACF7B6D7CCCE02704C3D28D0893281ECB1`。原始记录按各自源码/测试冻结身份解释，不混合报告。
