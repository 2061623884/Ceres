# 04 两角色 Prompt 模块化

状态：待验收（模块化、真实阶段对照及合 02/07 后选项接缝通过；同版最终验收留 08）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[03 内部能力路由与 workflow 直达](ceres-next-agent-experience-03-capability-routing.md)。依赖 03 已确定并可运行的能力分支、工具和上下文选择，避免先写无实际调用方的 Prompt 模块。
覆盖用户故事：14–17、25–26、33–35。

## 交付行为

同样的选购、咨询、闲聊与售后输入继续得到正确结果，各角色及能力只使用必要的表达、规则与事实，并能复核实际发送的 Prompt。

## 范围

按公共表达、角色规则、当前能力规则与本轮必要事实组织可可和墨墨 Prompt；本票保留行为语义，精简由 05 分步开展。

## 验收标准

- [x] 通过实际两角色聊天链路核对模块化前后行为，协议、事实来源、角色边界和确认规则无退步（必要受控回归及四条真实开发样本，最终同版覆盖归 08）。
- [x] 可可四类能力使用对应规则与必要事实；墨墨既有一般咨询和明确订单业务继续成立。
- [x] 模块均有现有实际调用方，不新增 Prompt 插件系统、配置切换平台或重复规则源。
- [x] 保留模块化前阶段基线及实际发送的 Prompt、模型/数据/用例版本、输出与失败。
- [x] 固定业务、路由和模型作阶段对照；模块组织、示例、表达及规则对齐作为组合变量，不声称后续精简或路由的单独收益。

## 修改归属与证据

本票确定 Prompt 组织方式与共用表达规则的修改入口；后续 05 与 06 明确各自文本范围，由主会话协调重叠修改。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

本票已技术交付，合入 `814dcdde2de1587d7ff83f2c45a503c215d4e793`；[合并回执](../work/ceres-next-agent-experience/merges/04-receipt.md)。05/06 可沿明确修改归属推进，同版集成验收与本人接受留 08。

最终源提交 `a5a00a6827bf345c6134fadcd9f4f205aca55931`，已包含 02/07 的集成 tip。直达类型和筛选在回答阶段按实际 category/explore 查询选择品类规则，保留 Trace 的原始 Kev 能力判断。有效外发契约 red：[记录](../work/ceres-next-agent-experience/04/red-direct-category-prompt-03.txt)；green 1 项、集成接缝回归 3 项：[green](../work/ceres-next-agent-experience/04/green-direct-category-prompt.txt)、[回归](../work/ceres-next-agent-experience/04/integration-prompt-seam-regression.txt)。前两次 fixture/调用索引错误不是有效 red，均保留。无需重复真实采样。

模块化候选回归：[后端 60 项](../work/ceres-next-agent-experience/04/prompt-regression-backend-facts-rerun-02.txt)、[Mercury 独立 13 项](../work/ceres-next-agent-experience/04/mercury-standalone-prompt-regression.txt)。05/06 以最终合入版本为运行前提。

## 阶段基线

实施树 `work/.ceres-next-04` 的未修改起点为 `91ca0b80161dada5c83fa5955b8a27043172299d`。同一提交的独立只读基线树为 `work/.ceres-next-04-before`；测试 Agent 在该树记录模块化前实际调用。模型、业务供给、索引与用例在两臂执行时保持一致并登记；结果与限制见以下阶段证据。

阶段候选冻结为 `04f5efde0c66d50213de72df266b7e692d2ca019`，tracked clean，尚未合入 02/07；后端必要回归 60 项、Mercury 独立回归 13 项通过。四条同条件真实主模型 after 已在该候选完成；合最新 integration 后验证共用选项接缝。完整实际请求仍含公共 JSON schema；能力隔离断言仅覆盖自然语言指引，长度按完整发送请求记录。

四例真实 Qwen 前后采样均已完成，每例每臂一次、各批串行、Kev 受控、独立 lexical 索引，外部模型负载未知。[对照摘要](../work/ceres-next-agent-experience/04/live-after-04-alone/ab-summary.md) 链接完整脱敏实际请求及响应。零食基线 EMPTY_PROPOSAL，候选问类型且不建任务；可乐、政策和选中未签收订单拒绝退货的行为保持。逐轮均不超过 15 秒；零食 4.57 秒失败→14.16 秒成功，不能称整体加速。政策输入 Token 降低，Momo 5382→5400（增加 18）；不预设所有模块均减少，不据 4 个实例声称总体成功率。

该阶段包括模块组织、能力示例筛选、公共表达及与已交付分类规则对齐，不能分离归因于单独压缩或路由。合 02/07 后的有效类型/筛选直达能力适配另行记录，不混入 `04f5efde` 的对照。
