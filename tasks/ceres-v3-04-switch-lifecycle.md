# 04 双向切换与打开周期

状态：待验收（技术实现、相关回归及双轴复审完成；正式页面与本人验收另列）
负责人：主 Agent；正式 UI 由用户后续交 Cursor。
规格：[V3 实施规格](../docs/plans/ceres-v3-spec.md)
依赖：[03 可可上下文路由到确认交接](ceres-v3-03-context-routing-handoff.md)。

## 交付行为

墨墨的新选购诉求能经确认返回可可；两角色共享本次打开的自动提示额度，拒绝或来回切换不反复提示，主动切换可续接未处理诉求或恢复目标会话。

## 验收标准

- [x] R08 的墨墨→可可路径先询问，接受后携原话继续既有导购；不变更两角色主业务职责。
- [x] H02/H05 本次打开最多实际展示一次自动提示，接受／拒绝／双向切换均不重置；结束本次打开再进入才开始新周期，与 demo／Cursor 的进入退出事件一致。
- [x] 用完额度仍逐条路由，必要时说明能力边界、固定入口可用；不以聊天追问反复提出同一切换询问。
- [x] H03 有明确未处理诉求时主动入口续接，H04 单纯切换只恢复目标会话，不重发旧消息、不跳过业务确认。
- [x] 本轮明确新诉求及已处理结果使旧待交接失效，原有选单 B 不覆盖明确交接 A；不建设全量聊天同步。
- [x] 公共接口状态、最小交互 demo 的周期状态、双轴审查与 Cursor 接入约定一致；静态模拟、真实 API 与正式页面证据分开。

## 测试边界

同一 owner 的两角色公共聊天与切换路径、源消息处理状态、最小 demo 生命周期；正式 React 页由 Cursor 接入，本票不修改生产 frontend 源码。

## 阻塞与下一步

03 技术依赖已交付；04 基线 fbd9d01875eaeab5ec01e9849f4ce2bc562d1837 及未提交工作源码冻结在 baseline/source.zip，继承 V2 不作为本票差异。R08 同意后原话到可可并生成真实鸡蛋清单；首复验的供给/索引未配对失败保留 DB/trace，改用现有 indexed_client 后通过，未改业务检索。red-003 的三个缺口逐切片修复：green-004 保留旧可乐清单并添加鸡蛋，来源墨墨用户/助手消息进入目标受控 provider；green-005 验证共享展示额度和 DELETE 重开；green-006 验证一般澄清不臆测取消。red-008 两参数证实已回答问句仍进入下轮路由，green-009 接受/拒绝两例均通过（2 passed，exit 0）。目标模型均受控，不宣称真实网络验证。demo-red-007 未复现 SSE 解析假设：原脚本 Node CRLF 消费通过，浏览器尝试未取得有效结果，未因此修改解析器。demo/契约与相关回归、双轴复审已完成；不增加永久拒绝偏好或跨设备系统。

## 证据

相关回归原始运行及修复记录：最终组 1 路由/周期 17 项、组 2 政策/订单/传输 39 项及 Mercury 政策 8 项通过；原组 4 是 14 passed / 16 failed。14 个确认实例在 `_new_plan` 前置失败：测试库 105/322 与本机配置索引 105/321 不匹配。原 trace 只保留 `GOAL_TARGET_UNRESOLVED`，不能伪造未保存的 lookup payload。代表确认节点在显式空索引配置下 1 passed，原话、模式及业务源码均未改；完整原节点隔离复验结果见下文，不声称 hybrid/vector。两个集成旅程的旧禁 SDK fixture 与 02 政策入口冲突，现仅改受控 SDK 为 policy-only 的选单答复，保留 owner、显式选单及零退款退货断言。Phase2b 继承未提交文件保持原样。冻结 app/Mercury overlay 因根目录缺少静态数据未进入可比断言，不能作为旧版行为对照。见 [原失败](../work/ceres-v3/04/preflight/final-regression-012/group-04-guide-confirmation-journey/report.md)、[只读诊断](../work/ceres-v3/04/diagnosis-013.md)、[代表运行及不可比限制](../work/ceres-v3/04/preflight/diagnostic-013/report.md)。

[流程图](../work/ceres-v3-discussion/service-routing-proposal.mmd)、[案例依据](../work/ceres-v3-discussion/evaluation-plan.md)；执行证据放在 `work/ceres-v3/04/`。

原组 4 的最终隔离复验为 [run-002](../work/ceres-v3/04/preflight/group4-empty-index-016/run-002/result.json)：30 passed / exit 0，stderr 空，原 30 个节点及业务断言均执行，记录范围内源码 before/after 相同。run-001 因重复启动共用 basetemp 保留但不作最终证据。与前三组共 94 项通过；普通 client 是无部署索引的直读路径，indexed_client 为配对 lexical，不声称 hybrid/vector 或真实模型通过。Standards 首审的重复内部检查与命名建议已修复；两轴最终有效 Finding 均为 0。修复后关闭/重开公共接口单例 1 passed，demo Node VM/mock API 的 34 个行为断言及 Node 语法检查通过。首次 demo 驱动未等待异步点击的失败保留，重试仅增加等待，不修改断言。见 [最终双轴审查](../work/ceres-v3/04/review.md)、[API 复验](../work/ceres-v3/04/preflight/standards-recheck-013/api-lifecycle/result.json)、[demo 复验](../work/ceres-v3/04/preflight/standards-recheck-013/demo-retry-002/result.json)。这些是受控公共接口与模拟 DOM 证据，正式浏览器页面和真实模型质量在后续票单列。

执行记录：[R08 红](../work/ceres-v3/04/preflight/red-001/result.json)、[首复验失败](../work/ceres-v3/04/preflight/green-001/report.md)、[保留 DB 诊断与纠正](../work/ceres-v3/04/preflight/green-001/forensics.json)、[R08 绿](../work/ceres-v3/04/preflight/green-002/report.md)、[三个缺口红](../work/ceres-v3/04/preflight/red-003/report.md)、[上下文绿](../work/ceres-v3/04/preflight/green-004/report.md)、[周期绿](../work/ceres-v3/04/preflight/green-005/report.md)、[澄清绿](../work/ceres-v3/04/preflight/green-006/lifecycle-clarify/result.json)、[SSE 假设未复现](../work/ceres-v3/04/preflight/demo-red-007/report.md)、[问句红](../work/ceres-v3/04/preflight/red-008/report.md)、[问句绿](../work/ceres-v3/04/preflight/green-009/report.md)、[本票基线](../work/ceres-v3/04/baseline/baseline.json)。根主会话已读取各定向运行原始命令、环境、stdout、退出码及记录范围内源码摘要；相关回归、修复后定向复验及双轴复审已完成。
