# P1 理解-决策层交付与验收记录

- 日期：2026-09-20；本次证据修订：2026-09-22；对应设计稿：[2026-09-20-p1-planner-decision-layer-review.md](2026-09-20-p1-planner-decision-layer-review.md)
- 状态：**R1–R5 主链路已接入；离线定向验证通过；历史 L2 live 未通过，排除 INDEX_STALE 后的隔离真实 LLM 重跑仍为 1/5，不能标记全方案验收完成。** UI 未新增交互。

## 已实现（有离线测试覆盖）

- **契约（R1/R2）**：`schemas/goal.py` 增 `SpeechAct`/`GoalRelation`/`TurnRoute`/`GoalChanges`/`Understanding`/`GoalCandidate`/`TurnDecision`；
  `agent/goal.py` 增 `parse_understanding`（未知字段、`new_goal`+`changes` 并存、`set`/`clear` 冲突一律拒绝；未知枚举保守归一化）、
  `apply_goal_changes`（省略=不变、`set`=覆盖、`clear`=撤销）、`merge_goal_candidate`（候选保留原 switch/append 意图）。
  `protocol.parse_proposal` 增 `understanding` 并复用同一契约；`proposal_schema()` 同步。
- **未知与省略的区别**：`understanding.goal_relation` 只有"真正省略"才允许在无目标可关联时按 `new` 处理；
  写了但不在词表内的值一律阻断（`relation_declared` 记录是否写过）。`changes.clear` 仅接受白名单字段，越界即协议错。
  focus 指向的组与 mutation 的 ref 不一致、待答问题不属于当前候选、一轮内多个组/多个目标变更，均整批拒绝。
  候选重新建立使用新的服务端 handle；包括业务风格问题在内的 pending 绑定候选与版本，回答已知槽位自动撤销旧问题。
- **同一轮语义锁定**：loop 以本轮首次声明的 `speech_act` 为准，只读回合只能补充目标语义，不能把提问升级成采购；
  被阻断/被拒绝的 mutation 会丢弃模型原文，避免"已修改"话术。
- **Gate（R1）**：`agent/goal_router.decide_turn` 组合 `route_goal` 给出 `route/readiness/missing_slots/write_blocked/reason_code`，
  并输出候选目标；`mutation_refusal` 做结构化授权（关系×动词×字段×目标一致）。
  **无 `understanding` 一律不写**：`_legacy_decision` 对带 mutations 的旧提案返回 `write_blocked=True`（reason `MISSING_UNDERSTANDING`），
  `mutation_refusal(None, ...)` 也返回拒绝；旧协议仍可解析、只读/闲聊/澄清照常。未知 `speech_act` 一律阻断。
  真实能力槽位：自煮/混合餐食缺人数 → `missing_slots=["people"]` 并澄清（不再判 ready 让执行器猜默认）；
  成品 goal + dish/scenario 原料 add → `READY_MADE_NOT_RAW` 拒绝；`new_goal` 与 add ref 的 kind/名称不一致 → `GOAL_TARGET_MISMATCH` 拒绝。
- **执行边界（R3/R4）**：loop 内对最终提案跑一次 Gate 并在 `write_blocked` 时丢弃 mutations（回执可见）；
  同一轮的理解跨只读回合保留（后续可补真实目标引用，但不得从只读提权）。
  `_execute_proposal` 复核授权（冲突整批拒绝，不部分执行）、把候选写回既有会话 context（绑定 task/plan 版本，仅限当前绑定）、
  按需编译就绪目标（服务端 ref + 名称一致校验）与 people patch（非可 patch 字段明确拒绝而非静默丢弃）；
  执行器用已校验关系决定 replace/append/resize（switch 才 replace），switch 走 `create_purchase_task`（旧任务 superseded，
  不清车、不改确认历史）。新计划 merge 完成并通过停止/超时/anchor 复核后才创建新任务；不提前取代旧任务。
- 当前 proposal schema 顶层 required 为空，SemanticProposal.understanding 也可为 None，因此“每轮必须输出 understanding”仍只是 Prompt 级要求，不是 Parser/Structured Output 级硬约束；这是 P1 尚未收口的兼容协议缺口。
- **切换独立构建（R4）**：`merge_plan` 的 replace 分支不再迁移旧行/旧 gaps，也不再继承旧 coverage_intent。
- **只读回显（R5）**：`TurnResponse` 增 `route/readiness/missing_slots`（`responses.build_response` → `api/guide._turn_response` 透传），
  前端 `guide-client.ts` 仅补类型，未做 UI。
- **提示词**：`prompts/semantic.py` 增加 `understanding` 契约与 goal_relation 指引，删去"不支持替换目标"，取消默认自做（未说明用 `unspecified`），
  新增 switch/amend few-shot。当前 Prompt 仍需清理 reply-only 聊天指令与缺少 understanding 的 few-shot，避免与“每次回答都给 understanding”冲突。

## 离线验证

工作目录：`C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend`。

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_goal_understanding.py tests/test_goal_decision_gate.py tests/test_p1_planner_decision_layer.py tests/test_p1_planner_independent.py tests/test_semantic_pipeline.py tests/test_agent_loop.py tests/test_semantic_acceptance_edges.py tests/test_agent_service.py tests/test_agent_concurrency.py tests/test_agent_deadline.py tests/test_revision_confirmation.py tests/test_trace_eval.py tests/test_semantic_transport.py -q --tb=short
```

- **260 passed，exit 0，115.70 秒**（其中 Codex 独立测试 24 条）。原始输出：`C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/work/p1-planner-decision-layer/final-targeted-tests.txt`。
- Codex 独立测试已归档为 `backend/tests/test_p1_planner_independent.py`，涵盖无理解/未知枚举阻断、只读后高层提权、非法 clear、引用错位、模型假成功、混合 patch 整体拒绝、人数不默认、纯高层候选切换、旧确认拒绝、构建失败不激活、旧问题隔离、eval 状态断言和 prompt 解析。
- 旧 inline fixtures 已按新契约迁移；检索前先声明 speech_act。ScriptedSemanticProvider 不自动补理解，故恶意/非法提案仍能被真实 Gate 测到。保留真实并发、停止、超时、确认边界断言。
- 前端：在 `frontend` 执行 `node node_modules/typescript/bin/tsc --noEmit --incremental false`，exit 0。
- `git diff --check`（相关已跟踪文件）通过；`workflow.py` 与任务开始时的保存基线逐字节一致。
- 未重跑无关全量测试。离线测试证明执行契约，不证明自然语言语义识别。已知 260 条测试中，64 条直接使用 Goal/Understanding fixture，114 条使用 ScriptedSemanticProvider 或 fixture proposal，10 条使用其他 fake provider，12 条使用 fake-HTTP LiveSemanticProvider，3 条使用 Reactive provider，57 条无模型；真正调用 live LLM 的离线测试为 0。因此这些通过项主要证明“拿到正确结构化 Understanding/Proposal 后，Parser、Goal Router、Gate、执行边界和状态断言工作”，不证明真实模型理解层整体正确。

## L2：已运行，但未通过

沿用既有 CLI，仅增加 split 过滤与逐轮状态断言：

```powershell
$env:BUSINESS_DATA_MODE='demo'
./.venv/Scripts/python.exe -m app.evaluation.runner --mode live --split p1-planner
```

- 2026-09-20 使用已配置 live 端点，临时 SQLite + 既有 demo seed；没有修改运行数据库、fixture、索引或密钥。
- **1/5 passed，exit 1**，只有“无上下文的三个人先澄清”用例通过；未用平均分掩盖其余失败。
- 原始报告：[live JSON](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/evals/reports/eval-live-20260920-153841.json)。
- 历史失败包括：Case 1/2/4 的解析错误 `MALFORMED_GOAL: goal 含未知字段: people`，Case 2/5 的写入因 `MISSING_UNDERSTANDING` 被 Gate 拒绝，以及 Case 5/T1 的 `INDEX_STALE`。历史 trace/临时数据库没有保存完整 Prompt、Context、Schema 或原始模型 Response；因此不能从本地证据补写历史 JSON，也不能证明非法 `people` 的原始值类型。
- 历史报告没有出现 `READY_MADE_NOT_RAW` 的结构化证据，不能据此断言“熟食误判”发生在后端；该问题只能作为待复核语义风险，不能写成已证实的首错。
- 2026-09-20 15:42:23（北京时间）之后才加入明确的 `new_goal.constraints.people` 示例、禁止 `new_goal.people`、以及场景/风格不等于熟食等 Prompt 修订；它们不在 15:38:41 报告对应的历史调用中。
- 用例覆盖切换、只读插话、未定位人数、同目标纠错、商品增量；逐轮断言包括 plan/pending/cart 不变、task 变化/不变、人数、精确数量增量，而不只检查 route 或出现某 SKU。

## 2026-09-22：隔离索引后的真实 LLM 重跑

为单独排除 INDEX_STALE，在 work/p1-l2-evidence-20260922/ 创建了独立 SQLite 和 retrieval index；没有修改部署索引、常规运行数据库、.env 或业务源码。

- 运行总报告：[REPORT.md](../../work/p1-l2-evidence-20260922/REPORT.md)；逐次完整载荷索引：[calls/INDEX.md](../../work/p1-l2-evidence-20260922/evidence/calls/INDEX.md)。
- 索引预检：[preflight.json](../../work/p1-l2-evidence-20260922/evidence/preflight.json)：101 dishes、50 SKUs、151 docs，all_doc_hashes_match=true、verify.passed=true、describes_runtime_db=true、readiness=ready；真实“可乐”检索命中 demo:cola-330ml。
- 观测到 20 次 chat calls、2 次 embedding calls，HTTP 均 200，0 次 repair；原始 HTTP body、provider result、Parser result、Gate decision 均保存。受保护的 109 个源码/config/fixture/部署数据文件前后 hash 无变化。
- 结果仍为 1/5：Case 5 通过；Case 1/2/4 的首个可定位失败不是历史 new_goal.people，而是模型输出正确 new_goal.constraints.people=2，同时给非 product 的 dish add 了 quantity=1，Parser/Gate 接受后由 change_plan.py 以 UNSUPPORTED_OPERATION 拒绝。公开 add schema 允许该字段，但执行器禁止该组合，说明 Proposal schema、Parser 和执行器约束不一致。
- Case 3 的模型输出为 speech_act=ask_fact 加 changes.set.people，最终出现 EMPTY_PROPOSAL；这不是索引问题。Case 2/T5 的 清汤火锅 被 Gate 以 GOAL_TARGET_MISMATCH 澄清，也没有 READY_MADE_NOT_RAW 证据。
- 这次重跑使用的是 9 月 20 日报告之后已经修改过的 Prompt/loop/service，因此不是相对于历史运行的单变量实验；它只能证明：在索引匹配、检索 ready 的条件下，Case 5 能通过，而整体 L2 仍未通过。

## 根因分类与修复边界

| 类别 | 已确认事实 | 后续交付要求 |
|---|---|---|
| LLM 输出 | 历史 people 顶层错位、部分响应缺 understanding 有 trace 错误码或新运行原始 JSON 证据 | 保留逐调用 payload；用真实模型回归验证，不用 fixture 代替 |
| Prompt/few-shot | 历史错误发生在明确嵌套示例加入前；当前仍有 reply-only 指令和缺理解 few-shot | 清理冲突示例，明确 new_goal、changes、mutation 的字段边界 |
| Schema/Parser | understanding 非 required；add schema 允许非 product quantity | 将 P1 协议必填约束放到 Parser/结构化输出，并让 schema 与执行器一致 |
| Goal/Gate | 缺 Understanding 的 mutation 已 fail-closed；当前 Gate 未放行历史缺理解写入 | 保留 Gate 作为最终授权防线，不能让它承担唯一协议校验 |
| 执行器 | 非 product add + quantity 被执行器拒绝；与公开 schema 不一致 | 统一字段适用范围，避免 Parser/Gate 已 ready、执行器才拒绝 |
| 测试数据/索引 | 历史 Case 5/T1 的 INDEX_STALE 来自临时 DB 与部署 index 不匹配 | 评测前必须 preflight seed/index counts、hash、readiness；不得关闭 stale 检查 |
| Runtime 路径 | 隔离重跑已记录实际 Prompt 和 HTTP body，证明当前修改后的 Prompt 进入 live model | 将逐调用证据作为 L2 验收产物 |

## 下一次 L2 验收门槛

1. 评测启动前输出 seed counts、index counts、document-hash 对账、readiness 和一条真实代表性检索；任一不一致直接判环境失败，不进入模型归因。
2. 每次模型调用保存完整 request messages、实际发送的 schema、server context、原始 response、Parser 结果和 Gate decision；禁止只保存摘要 trace。
3. P1 新协议明确区分：聊天/只读答复是否允许继承同轮 understanding；写入提案的 understanding 是否 required；两者必须在 schema、Parser、loop、Gate 中一致。
4. add mutation 的字段适用范围必须在 schema、Parser、Gate、executor 四层一致，特别是非 product 不得携带 quantity；不能出现 Gate ready 但 executor 才拒绝的情况。
5. 五个 case 必须逐轮核对 route、readiness、missing_slots、write_blocked、reason_code、plan/pending/task/cart，且至少一次使用真实 live LLM；离线 fixture 只能作为补充。

## 仍有限制 / 未验收

1. **L2 未通过**：索引问题已在隔离环境中排除，但真实 LLM 结果仍为 1/5；必须先统一 Proposal schema、Parser、Goal/Gate 与执行器契约，再重新进行有完整载荷留存的 L2 验收。
2. 未做 SSE 真实对话回放或浏览器 UI 验收；前端仅类型适配。
3. 已生效计划当前仅支持已有业务能力范围内的字段修改。预算、忌口重算、直接 clear 活动计划人数等能力仍明确拒绝整轮，不会静默忽略或部分改人数；候选 Goal 的 set/clear 纯合并已支持。
4. 风格选项仍由既有业务能力提供/复核；未把无真实数据的口味变成默认事实。成品检索受实际目录与索引条件约束，不能把 fixture 或只读协议测试视为线上可搜。
5. 不包含 P1.5 聚合、pantry、占用分配、新表、新工作流或额外模型调用。未提交、推送或部署。
6. 未证明历史 people 错位由单一 Prompt、few-shot 或 context 因素导致；历史原始模型载荷缺失，任何更细的归因都需要上游模型审计日志或可复现的对照实验。

## 工作区保护

工作区开始时已有大量未提交与未跟踪改动。本任务以当时内容为基线增量修改，没有回滚它们。相关初始文件存于 `work/p1-planner-decision-layer/baseline/`，独立验收差异存于 `work/p1-planner-decision-layer/final-changes.patch`。这不是对整个历史 Git diff 的重新验收。
