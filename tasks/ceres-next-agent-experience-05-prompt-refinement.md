# 05 逐模块精简与固定对照

状态：待验收（品类正文精简、必要回归及固定真实对照已交付；同版和本人表达验收留 08）。
负责人：实施 Agent；主会话维护本阶段任务，专职测试 Agent 执行全部测试命令。
规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)；所属任务：[实施总 TASK](ceres-next-agent-experience.md)。
依赖：[04 两角色 Prompt 模块化](ceres-next-agent-experience-04-prompt-modules.md)。依赖 04 已验证的模块组织方式与精简前阶段基线。
覆盖用户故事：12、25–26、33–36。

## 交付行为

用户在相同任务下得到符合验收的简短回复，Prompt 精简的正确性和实际开销变化都有可复核前后记录。

## 范围

以 04 的业务就绪版本为单变量对照，逐模块精简，不混入新活动、双 Agent 承接或数据扩充。优先可可能力规则，公共表达与墨墨规则的重叠修改由主会话协调。

## 验收标准

- [x] 每一步登记具体精简变量，并固定路由、模型、业务数据、用例和其他条件。
- [x] 分类/筛选、参数处理、事实依据、角色边界、确认与业务状态等关键行为由必要 41 项回归保护；真实采样与语义限制另记。
- [ ] 保留实际 Prompt、原始逐轮输出、错误、失败及比较依据，人工审读表达是否简短易读。
- [x] 报告 Prompt 长度、实际主模型调用与耗时；接口可得时报告 Token，缺失值不当作零。
- [x] 成功率和性能改善据实际结果报告，不预设比例；不能把路由或新增商品变化归因于精简。
- [x] 开发/回归用例用于迭代；新留出留到 08 候选冻结后执行。

## 修改归属与证据

本票只精简可可 category_exploration 能力规则及确实相关的该能力示例，不改公共表达、Mercury 或其他能力。与 06 按文本归属并行；真实对照在本票独立 before/candidate 完成，采样后再合最新集成并做受影响回归，不把 06 的变化混入对照。

沿用现有架构，只改本票必须内容；无需新建无依据校验、异常兜底或抽象。记录本票源码/数据/模型/Prompt/用例版本及命令、实际结果和证据入口。证据置于 work/ceres-next-agent-experience/对应票号目录；测试、真实采样、前端与人工验收分别记录。

## 下一步

源提交 `840bbb632b0516ad9e47e1896b6660bb41545619` 已无冲突合入 `e2259c09891f017b2aebf2349fdde817a2cb6f43`；[合并回执](../work/ceres-next-agent-experience/merges/05-receipt.md)。本票不再扩采同一开发例，最终集成及本人表达接受留 08。

## 固定变量与阶段证据

before 为 `481e7505951204d3d24c9c9a3bb61684e5edc213`；最终 category-only 源候选为 `840bbb632b0516ad9e47e1896b6660bb41545619`。只改 CATEGORY_EXPLORATION 正文及实际外发体量测试，能力示例、其他能力、公共表达、模型与参数固定；两臂均使用含 07 成品的同一冻结 fixture、独立 lexical 索引与受控 Kev，真实 Qwen 的物理模型版本及外部负载未知。采样前未混入 06。

公开聊天→实际 HTTP 外发接缝在未改源码时独立记录完整请求 15385 bytes；新增严格小于该值的断言 red 为 `15385 >= 15385`，不是功能缺陷或任意比例阈值。[before](../work/ceres-next-agent-experience/05/controlled-before/baseline-capture.txt)、[有效 red](../work/ceres-next-agent-experience/05/red/controlled-prompt-budget-red.txt)。早期 green 为 14025 bytes，随后补回必要 qid 表达；最终候选为 14034 bytes，净减 1351 bytes（8.78%），只适用于该固定请求：[最终计量](../work/ceres-next-agent-experience/05/green/controlled-final-candidate-meter.txt)。最终候选必要回归 41 项通过：[回归](../work/ceres-next-agent-experience/05/green/prompt-regression-green.txt)。

两条真实开发用例每臂各一次、串行、无重试。零食依旧类型澄清且不建清单/加购，主模型 2 次，输入 Token 6454→5876，单轮 10.849→6.739 秒。可乐保留清单、ACK 不加购及最终购物车不变的边界，主模型 5→6 次、输入 Token 29002→32408；before 将“只看 1 元以下”误解成“小包装修改”，after 才正确回答无匹配，不能将两者都记语义通过。可乐未使用被精简的模块，前两条实际请求 body 相同，后续历史及模型输出变化不归因于品类正文。固定场景仅一款符合多件装条件，不能证明多 SKU 比较。[派生摘要](../work/ceres-next-agent-experience/05/ab-summary.md) 保留这一失败与限制。

完整脱敏实际请求、响应、usage 及分阶段指标见 [指标](../work/ceres-next-agent-experience/05/canonical-capture-metrics.txt)、[before](../work/ceres-next-agent-experience/05/before/)、[after](../work/ceres-next-agent-experience/05/after-category-only/)。真实请求指标是捕获对象的规范重序列化，区别于 controlled meter 的实际 HTTP wire bytes。root 已对公开回复做 Agent 审读：零食候选去掉一处铺垫，ACK 边界清楚；可乐 before 的价格语义失败已登记。Agent 审读不替代本人表达验收，这些单样本不支持普遍 Token 或耗时下降。
