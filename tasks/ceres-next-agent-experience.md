# Ceres 下一阶段 Agent 体验实施总 TASK

- 状态：进行中（规格与八票已确认，执行准备及 01 启动）。
- 负责人：本会话主 Agent；各实施 Agent 使用独立 worktree，专职测试 Agent 执行测试，merger Agent 负责合并；最后一次 Standards/Spec 双轴集成审查。
- 规格：[实施规格](../docs/plans/ceres-next-agent-experience-spec.md)。
- 授权：用户 2026-10-06 明确要求 implement-spec 按依赖持续执行八票，允许无共享修改冲突的票并行，每票 TDD；必要时添加最少模拟商品及供给支撑测试。无需重新确认已讨论的测试接缝或票据粒度。
- 前提：V3 已完成，不核验其完成度、不改变旧任务状态。原工作区已有变动须保留。

## 票据与依赖

| 票据 | 阻塞依赖 |
| --- | --- |
| [01 零食分类到确认加购](ceres-next-agent-experience-01-snack-choice.md) | 无 |
| [02 饮品与候选筛选](ceres-next-agent-experience-02-drink-candidate-choice.md) | 01 |
| [03 内部能力路由与 workflow](ceres-next-agent-experience-03-capability-routing.md) | 01 |
| [04 两角色 Prompt 模块化](ceres-next-agent-experience-04-prompt-modules.md) | 03 |
| [05 Prompt 精简与固定对照](ceres-next-agent-experience-05-prompt-refinement.md) | 04 |
| [06 售后后继续采购与自然回复](ceres-next-agent-experience-06-after-sales-resume.md) | 04 |
| [07 主页专题与限定成品](ceres-next-agent-experience-07-themed-products.md) | 01 |
| [08 同版集成验收与证据整理](ceres-next-agent-experience-08-final-evidence.md) | 02、05、06、07 |

依赖满足表示所需技术行为及对应验证有证据，不要求用户提前完成本人验收。票据执行结束先置待验收；缺少必要技术验证时如实标明阻塞，不用历史结果代替。

## 执行安排

优先顺序 01→02→03→04→05→06→07→08；依赖满足且修改归属明确的票可并行。01 负责共用结构化选项与前端承接；03 负责内部能力判断；04 负责 Prompt 组织；05 与 06 的共用 Prompt 变动串行登记或明确分区；共享 schema、商品数据及索引由主会话协调。

使用单一 codex/ceres-next-agent-experience 集成分支；实施者各自 worktree/分支从集成分支创建，并合入最新集成 tip 后交付，由 merger 合并。不推送、不创建未请求 PR。完成后清理实施者 worktree，保留集成 checkout 与证据。

主测试接缝为现有公开聊天/确认/交接 API 的多轮旅程，气泡与活动入口补真实前端点击。每票一条有效失败行为断言→最小实现→通过与必要回归，全部测试命令交专职测试 Agent。确定性/受控接口、真实模型、前端与人工表达证据分别保留。最后固定本阶段起点及候选，进行一次 Standards/Spec 集成审查并修复有效问题。

## 当前进度与下一步

执行准备：发布规格与票据，建立包含当前有效源码的隔离集成基线，记录原工作区 dirty 清单与适用版本，随后启动 01。各票的具体进度、结果和阻塞只在对应票据维护。

证据入口：[执行准备](../work/ceres-next-agent-experience/00-preparation/)；执行中持续补入实际文件。规划与草案保留为历史讨论材料，不维护第二套实施状态。
