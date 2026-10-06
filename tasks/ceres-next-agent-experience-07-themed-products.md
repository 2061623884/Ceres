# 07 主页专题到限定成品选购

状态：待验收（公开上下文与商品接口、受控页面完整旅程和 TypeScript 已通过；同版真实模型/页面及本人验收留 08）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[01 零食分类气泡到确认加购](ceres-next-agent-experience-01-snack-choice.md)。复用 01 已可用的前端结构化选择与选购确认承接，避免活动建立第二条点选加购路径。
覆盖用户故事：27–32、35。

## 交付行为

主页现有卡片直接打开可可，展示简短专题介绍与对应限定成品；选择活动商品后沿现有清单/确认加购完成选购。

## 范围

贯通最小专题内容与商品关联、入口上下文、活动商品展示及既有选购。具体主题与商品在参考及供给内选定；需要时补最少模拟成品与供给。

## 验收标准

- [ ] 主页入口进入正确专题并展示对应简介和限定商品，活动与本轮选购上下文可关联。
- [ ] 沙拉、拼盘等以成品 SKU 展示，不展开食材采购；展示商品来自该专题清单。
- [ ] 用户点选活动商品后复用现有选购及明确确认加购流程，不把浏览当作采购授权。
- [ ] 活动数据与供给一致；如展示期限或优惠，能定位对应数据依据。
- [ ] 新增商品/供给和索引版本可定位；不扩展评论、投票、晒单或运营后台。
- [ ] 保留主页点击到确认加购的实际前端路径、业务结果及专题/用例版本。

## 修改归属与证据

本票负责专题关联与入口上下文，复用共用点选契约；商品补充沿既有流程并由主会话协调共享数据。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

实施 `677065ef88403f1f3b8b0b26335ffee5ab6023bb` 已无冲突合入 `090ed10c6bad048ff4d7cb5af24a8cd956c539f2`；[合并回执](../work/ceres-next-agent-experience/merges/07-receipt.md)。08 用重建后的同版供给、索引和真实页面完成其余验证。

## 实施证据

主页现有卡片进入 GREEN RESET｜今天轻一点，在可可内展示简短介绍及限定成品。仅补 `demo:green-reset-avocado-salad`、`demo:green-reset-fruit-platter` 两个成品和对应模拟 Offer，复用既有桃汁；价格读取商品接口，无虚构期限或折扣。没有食材展开、评论或运营功能。

现有 EntryContext/ViewContext 最小增加 `activity_id` 与 activity page；选商品沿 product page 加真实 `product_id` 并保留活动身份，后续回合和路由可读取。选择只介绍商品，后续明确选品与清单确认沿已有流程，加购前购物车不变。

有效 red 为公开请求的 activity page 被 422 拒绝、新增成品商品接口 404，以及主页点击后无专题介绍。最终公开接口 2 项通过；实际浏览器在受控 API 下完成主页→专题→真实 SKU→清单→明确确认→购物车；严格 TypeScript 检查通过。证据：[后端](../work/ceres-next-agent-experience/07/backend-activity-offers-green-01.txt)、[页面](../work/ceres-next-agent-experience/07/activity-ui-context-green-02.txt)、[类型检查](../work/ceres-next-agent-experience/07/frontend-tsc-pnpm10.txt)。测试 fixture 不存在及全局 pnpm 版本保护中止均单独保留，不计产品 red；本票页面证据不替代真实主模型或真实后端页面验收。
