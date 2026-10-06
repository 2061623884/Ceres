# 03 内部能力路由与 workflow 直达

状态：待验收（四类公开聊天与门控回归、复杂修订、真实 Kev 各类单样本已完成；同版真实角色主模型/UI 在 08，用户本人待验收）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[01 零食分类气泡到确认加购](ceres-next-agent-experience-01-snack-choice.md)。复用 01 的有效结构化回答与 workflow 入口；02 是首轮覆盖范围的推荐先行票，不伪造为运行该路由的技术前置。
覆盖用户故事：12–18、32、34–35。

## 交付行为

可可把品类探索、采购与修改、事实问答、闲聊交给对应能力；有效结构化输入和齐全参数直接由 workflow 完成，复杂表达仍被主模型正确理解。

## 范围

贯通内部 Kev 闭合判断、能力分支、相关工具/上下文选择、实际业务结果与记录。外层服务路由和用户选择切换沿用 V3。

## 验收标准

- [ ] 四类诉求通过实际聊天入口产生对应能力处理与可核对结果，普通闲聊不创建采购任务。
- [ ] 内部 Kev 只选择能力，不生成自由业务参数、业务对象或授权，也不改变角色。
- [ ] 本轮有效结构化操作参数齐全时跳过主模型理解阶段，由 workflow 得到正确结果；记录实际调用阶段与次数。
- [ ] 复杂、多目标和自由文字修订保留主模型理解，不因 workflow 直达遗漏需求。
- [ ] 商品与政策回答有对应事实依据，清单/加购沿用原确认规则。
- [ ] 固定能力判断准则与输入版本，记录原始结果、分支、调用及耗时；真实判断和受控业务用例分别报告。

## 修改归属与证据

本票负责内部能力判断及直达入口，不修改既有外层三类服务判断语义，不另建通用路由平台。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

实施提交 `be1177e38f39c749bcd97b7031820c00c6e5d6cb`。可可内部四类闭合判断及实际准则/原始响应/阶段/耗时 Trace 已接入；结构化商品类型回答只由已校验问题和选项确定含义，即使 Kev 判断为采购修改也省去 understanding，保留 grounded answer。复杂文字追加仍调用理解，公开结果保留可乐×2、鸡蛋×1和 ¥20 预算，不写购物车。外层服务归属未改。

技术结果：门控/直达/stop 回归 6 项通过；四类公开 V3 与旧交接回归 11 项通过；复杂双轮 1 项通过（文件名含 red，实际为首跑通过的 characterization，未算红测）。证据：[门控回归](../work/ceres-next-agent-experience/03/final-regression-01-output.txt)、[四类公开聊天与旧交接](../work/ceres-next-agent-experience/03/controlled-v3-regression-01-output.txt)、[复杂修订](../work/ceres-next-agent-experience/03/multi-target-public-red-01-output.txt)。

真实 Kev 每类各 1 次均返回预期类别，只证明这四个实例。alias 为 `kev-latest`，物理权重 revision 未能确认；类型样本 token 计数因记录误脱敏丢失，保留 null，其他三类 input/output 为 304/81、289/81、289/80。原始记录：[类型选择](../work/ceres-next-agent-experience/03/kev-live-capability-snack-choice-n1.json)、[其余三类](../work/ceres-next-agent-experience/03/kev-live-capability-samples-n3.json)。不据此外推准确率或主模型整体性能。

集成合并 `2304b3253ce8de942a5dbc356139f6d49e1355ee`，无冲突；[合并回执](../work/ceres-next-agent-experience/merges/03-receipt.md)。后续 04 复用 semantic request 的 capability 接缝。02 的 product_filter 契约冻结后补直达适配，并登记该阶段来源；同版真实主模型/页面与最终双轴 review 留 08。
