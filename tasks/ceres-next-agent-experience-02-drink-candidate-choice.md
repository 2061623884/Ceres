# 02 饮品与多候选分类筛选

状态：待验收（受控公开旅程和必要回归已通过；同版真实模型、页面及本人验收留到 08）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[01 零食分类气泡到确认加购](ceres-next-agent-experience-01-snack-choice.md)。复用 01 已可用的当前问题/选项回答契约及端到端分类选购路径。
覆盖用户故事：2–10、12–13、31–32、35。

## 交付行为

饮品需求和跨类型候选通过分类气泡收窄；同类多个商品直接展示，并按有依据的口味、品牌或规格选择继续。

## 范围

在 01 的完整路径上接入饮品供给和候选分组/筛选，覆盖需求阶段与候选阶段；统一保留条件、清单和确认规则。

## 验收标准

- [ ] 宽泛饮品需求可选实际供给支持的类型，选定后进入商品选购并可确认加购。
- [ ] 存在有意义且尚待选择的跨类型候选时，展示简短概览与分类气泡，选类后展示相应商品。
- [ ] 同类多个商品直接展示，并按实际属性提供筛选选项；候选数量本身不触发分类。
- [ ] 筛选与类型点选保留有效条件，不默认替用户决定具体商品或执行加购。
- [ ] 零食主路径不退步；饮品、跨类型、同类候选和文字修订都有可核对用例。
- [ ] 新增模拟商品仅补本票覆盖缺口，版本及索引沿既有流程记录。

## 修改归属与证据

复用 01 共用契约，负责饮品及候选分组/筛选行为；对共享数据先登记需求，避免与其他票重复导入。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

实施提交 `234a104487e205526adb0ba8cbcc3ef10b45bd81` 已合入 `5d9a8b7450afef618dcfd346e6706803d6a69c6b`，无冲突；[合并回执](../work/ceres-next-agent-experience/merges/02-receipt.md)。08 在同版数据及重建索引上补真实模型与页面验证。

## 实施证据

工作树 `work/.ceres-next-02`。宽泛饮品的实际类型选项公开旅程已通过（1 passed，3.56s），供给类型概览不受商品展示前五名截断；低预算两件无可买供给的行为经过有效 red 后通过（1 passed，3.40s），公开文案说明无符合条件饮品，pending/plan 为空且购物车未变。证据分别为 `work/ceres-next-agent-experience/02/pytest-green-03-output.txt`、`drink-unaffordable-red-02-output.txt`、`drink-unaffordable-green-02-output.txt` 及对应 provenance。

同类可乐按实际品牌、单件容量、包装及包装件数提供筛选选项；结构化 `product_filter` 经当前问题/选项校验后直达 workflow，跳过理解，保留 grounded answer。自然文字“换成瓶装的”保留数量、预算到选品及明确确认。未新增商品；检索投影 schema 从 1 升到 2，索引 schema 沿用 3，08 按既有流程重建索引。

有效 red→green 覆盖宽饮品类型、低预算供给、同类筛选、结构化筛选跳过理解。完整确认及自然文字瓶装旅程首跑通过，记为 characterization。最终窄回归：饮品 5 项、零食 6 项、旧零食选择 5 项、03 类型直达 1 项均通过；投影版本收敛后饮品 5 项再通过。证据：[饮品](../work/ceres-next-agent-experience/02/narrow-regression-drink.txt)、[零食](../work/ceres-next-agent-experience/02/narrow-regression-snack.txt)、[旧选购](../work/ceres-next-agent-experience/02/regression-legacy-snack-selection.txt)、[类型直达](../work/ceres-next-agent-experience/02/narrow-regression-capability-product-type.txt)、[投影版本](../work/ceres-next-agent-experience/02/drink-schema-version-regression.txt)。

早期 `constraints_summary` 断言属于未建采购任务时的测试契约错误。03 跳过理解后，三条旧零食 fake queue 未同步，导致 answer 收到无回复 proposal，公开错误为 `NO_REPLY`；仅迁移测试队列后通过，未加入推测性产品 guard。这些测试修正不计产品 red；原失败与诊断保留。
