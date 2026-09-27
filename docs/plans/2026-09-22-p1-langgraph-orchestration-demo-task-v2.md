# Task: P1 LangGraph Orchestration Demo

## 1. Background

本 Task 为后续独立 LangGraph Demo 建立边界，不修改 Sale-guide 生产链路。目标不是重写 `run_loop`，而是使用现有 P1 契约验证两项新增能力：

1. `clarify` 后的真实 checkpoint / interrupt / resume；
2. 与真实 Graph 节点执行对应的节点级 trace。

建议工作目录：`Sale-guide/work/p1-langgraph-demo/`。本文件更新阶段不创建 Demo、不安装依赖、不运行实现任务。

## 2. Current Baseline

当前生产链路为：

```text
api/guide.py
→ GuideWorkflow.process_turn
→ GuideService._run / understand_turn
→ app/agent/loop.py::run_loop
→ evaluate_gate / goal_router.py::decide_turn
→ GuideService._execute_proposal
→ PlanChangeExecutor.apply
→ PlanCommitService.apply_result
```

`run_loop` 已具备模型调用、协议解析、一次有界只读轮、一次协议修复、预算/硬上限、deadline、协作式 stop、只读语义冻结和 Gate 决策。它不直接写数据库。

生产中只有一个 `decide_turn` 调用点（`loop.evaluate_gate`），不存在第二套独立业务 Gate。服务层/执行器有授权、引用、anchor、version 和停止/超时复检。真实计划副作用边界是 `PlanCommitService.apply_result`。

当前已有 `on_phase`、`on_model_call`、SSE progress、TraceEvent 和事件恢复查询，但没有从 clarify 等待点恢复同一 Graph 游标的 pause/resume，也没有覆盖完整节点的持久化执行轨迹。

重要事实：代码同时存在 `plan_version` 与 `state_version` 语义，Demo 不得擅自假设二者等价。

主要证据路径：

- `Sale-guide/backend/app/agent/loop.py`
- `Sale-guide/backend/app/agent/goal_router.py`
- `Sale-guide/backend/app/agent/protocol.py`
- `Sale-guide/backend/app/agent/context.py`
- `Sale-guide/backend/app/agent/service.py`
- `Sale-guide/backend/app/agent/tools/change_plan.py`
- `Sale-guide/backend/app/services/plan_commit_service.py`
- `Sale-guide/backend/app/services/turn_stream_service.py`
- `Sale-guide/backend/app/services/trace_service.py`

相关测试：`test_agent_loop.py`、`test_goal_decision_gate.py`、`test_p1_planner_independent.py`、`test_p1_planner_decision_layer.py`、`test_agent_deadline.py`、`test_agent_concurrency.py`、`test_model_call_trace.py`、`test_m3_sse.py`。本 Task 仅基于静态审阅，未重跑测试。

## 3. Problem / Validation Question

验证重点不是把现有函数画成 Graph，而是证明：

- Graph 可以在 clarify 等待点保存执行位置并暂停；
- 用户补充信息后，Graph 从该等待点恢复，而不是重新跑完整 turn；
- Graph 能产生与真实节点执行对应的 started/completed/failed 轨迹；
- checkpoint、staged mutation 和业务权威状态彼此不混淆。

若 Demo 只是线性重写 `run_loop` 并手工拼接日志，则不构成新增价值。

## 4. Scope

- 仅在 `Sale-guide/work/p1-langgraph-demo/` 实现隔离 Demo；
- 复用现有 P1 parser、Understanding、Decision/Gate 纯规则；
- 第一阶段只用 scripted provider/fixture；
- 验证 pause/resume、节点 trace、stage/guard/commit 边界和版本冲突。

## 5. Non-Goals

- 不修改 `backend/app/agent/loop.py` 或生产决策链；
- 不建立第二套 Decision/Gate；
- 不重新设计 P1 schema、pending 或 mutation；
- 不以真实 LLM 作为第一阶段条件；
- 不修改 HTTP/SSE 契约、生产数据库 schema 或数据；
- 不把 checkpoint 当业务状态第二真相源；
- 不扩展 memory、planner、agent 层；
- 不以“LangGraph 能运行”作为成功标准。

## 6. Target Graph

```text
START
  ↓
load_context
  ↓
understand
  ↓
parse_validate
  ↓
decide_turn
  ├── read_only_tools → decide_turn
  ├── clarify → checkpoint / pause
  ├── answer/chat/refuse → respond
  └── prepare
        ↓
   stage_mutation
        ↓
   commit_guard
        ↓
      commit
        ↓
     respond
```

## 7. Pause / Resume Semantics

本 Task 采用方案 A：真正 resume 原 Graph，不把用户补充信息当作全新 turn。

初始执行：

```text
load_context
→ understand
→ parse_validate
→ decide_turn
→ clarify
→ checkpoint
```

恢复执行：

```text
load_context(reload)
→ bind_pending
→ parse_validate（只解析用户本次补充输入）
→ decide_turn（重新计算当前 decision）
→ stage_mutation / answer / clarify / refuse
```

硬性语义：

- resume 不重新执行原来的 `understand`；
- 不直接信任 checkpoint 中旧的 `decision`；
- 用户补充信息必须参与当前 decision 计算；
- 补充信息与原 pending goal 冲突时，必须重新 clarify 或 refuse；
- 测试必须证明是从 checkpoint/interrupt 等待点继续，而不是重新跑完整 turn；
- 恢复时必须重新读取 authoritative plan、pending、版本、cart、server refs。

## 8. State Contract

```text
session: session_id, turn_id, checkpoint_id, resume_point
authoritative: active_plan, task_id, state_version, plan_version, pending, cart_snapshot, server_refs
candidate: candidate_goal, candidate_binding
turn: raw_proposal, parsed_proposal, understanding, decision, read_results, protocol_errors
staged: staged_plan, staged_mutations, plan_diff, commit_preconditions
result: commit_result, turn_response
trace: run_id, sequence, events[]
```

`authoritative` 字段只能来自 store；恢复后必须重新读取，不能直接信任 checkpoint 副本。`candidate`、`turn`、`staged` 是候选/中间状态，可 checkpoint，但不等于业务事实。

## 9. Execution Semantics

- `decide_turn`：负责语义路由；判断当前 turn 是否允许产生 mutation；输出 mutation authorization / decision；不写业务状态。
- `stage_mutation`：只生成 staged plan/diff/preconditions；不得真实写入。
- `commit_guard`：负责提交前安全校验，包括 authoritative version、anchor、stop/deadline、idempotency、mutation authorization。它可以复用底层纯规则，但不能实现成另一个混合式 `decide_turn`。
- `commit`：唯一允许产生真实业务副作用的节点。
- `staged_mutations` 永远不是可直接执行的授权凭证。无论 checkpoint 位于 stage 前还是 stage 后，resume 都必须重新经过 `commit_guard`。
- guard 失败返回 `STALE_VERSION` 或相应拒绝码，不得产生部分写入。
- trace 必须由节点入口/出口或失败处理器真实记录，不得在 respond 阶段手工补造。

## 10. Acceptance Criteria

- [ ] A：新目标缺信息进入 clarify 并保存 checkpoint，权威计划/cart 不变。
- [ ] B：补充信息后从 clarify 等待点 resume；重新 load authoritative state，继续到后续节点。
- [ ] C：只读问题走 answer，不产生写入。
- [ ] D：合法修改严格经过 stage_mutation → commit_guard → commit。
- [ ] E：重复 resume 不重复 commit，具备幂等证据。
- [ ] F：commit 前 version/anchor 变化返回 `STALE_VERSION`，无部分写入。
- [ ] G：非法 proposal 在 Parser/Gate 拒绝，不进入 commit。
- [ ] H：每个真实节点记录 `started` 与 `completed` 或 `failed`，可按 run_id/sequence 重放。
- [ ] I：证明 checkpoint/interrupt/resume 的增量价值：首次执行进入 clarify 并保存 checkpoint；resume 只处理用户补充输入，不重新调用原始 understand；基于 pending context 得到新的 decision，并继续到后续节点。
- [ ] J：证明 `stage_mutation → checkpoint → resume` 后禁止直接 commit；即使 checkpoint 已有 staged mutation，也必须重新经过 commit_guard，重新验证 version、anchor、authorization；guard 失败时不得发生真实写入。

## 11. Test Matrix

| 场景 | 验证 | 关键断言 |
|---|---|---|
| A | 缺少 people | clarify + checkpoint | 无计划/cart 写入 |
| B/I | resume + people | 只解析补充输入并重新 decision | 原 understand 调用次数不增加；继续后续节点 |
| C | ask_fact | answer | 无写入 |
| D | 合法 mutation | stage→guard→commit | 只有 commit 改变权威状态 |
| E | 重复 resume | 幂等恢复 | commit 最多一次 |
| F/J | stage 后 checkpoint，外部 bump version | resume→guard | `STALE_VERSION`，commit 未执行 |
| G | 非法 proposal | parser/Gate reject | commit 未执行 |
| H | 节点异常 | failure trace | started→failed，按边界无副作用 |

## 12. Risks / Open Questions

1. LangGraph 版本、隔离环境和 checkpoint backend 尚未确定。
2. 需要确定 interrupt/resume 的具体 API 与序列化格式。
3. 需要确定恢复后如何让 Graph 从等待点继续，而不是重新入口。
4. 需要确认可直接复用的纯函数及其 ORM 隔离边界。
5. 需要定义 Demo trace 是否与现有 TraceEvent/SSE 兼容。
6. `plan_version` 与 `state_version` 的语义差异需要在 Demo contract 中显式记录。
7. 需要定义 fake store 的 CAS、anchor 和 idempotency 行为。

## 13. Implementation Phases

### Phase 0：代码基线审阅
- 输入：P1 源码、测试、交付记录。
- 产物：本 Task 的事实基线和开放问题。
- 修改范围：仅本文档。
- 验收：事实可回溯到源码/测试路径。
- 不包含：Demo、依赖安装、实现任务。

### Phase 1：Demo State / Contract
- 输入：State Contract、P1 parser/decision 契约。
- 产物：隔离 Demo state/fixture/contract。
- 修改范围：仅 Demo 目录。
- 验收：权威/候选/staged/trace 分区明确。
- 不包含：生产接入、真实 LLM。

### Phase 2：Graph 编排
- 输入：State Contract、Target Graph。
- 产物：可编译 Graph 和条件边。
- 修改范围：仅 Demo 目录。
- 验收：图结构符合第 6 节；复用现有 Gate；stage 不写库。
- 不包含：生产 API。

### Phase 3：Pause / Resume
- 输入：clarify checkpoint、用户补充输入。
- 产物：interrupt/checkpoint/resume 流程和测试。
- 修改范围：仅 Demo 目录。
- 验收：B/E/I 通过；原 understand 不自动重跑；恢复先 reload authoritative state。
- 不包含：生产数据库接入。

### Phase 4：Trace / Observability
- 输入：真实节点执行。
- 产物：结构化节点事件和失败事件。
- 修改范围：仅 Demo 目录。
- 验收：H 通过；事件来自节点执行，不是响应阶段拼接。
- 不包含：修改现有 SSE/TraceEvent。

### Phase 5：Commit / Concurrency
- 输入：staged mutation、版本扰动、fake store。
- 产物：CAS/idempotency 测试。
- 修改范围：仅 Demo 目录。
- 验收：D/E/F/J 通过；stage 后恢复仍先过 guard。
- 不包含：生产数据库迁移或执行器重构。

### Phase 6：验收
- 输入：A-J 测试矩阵。
- 产物：定向测试报告、trace 样例、checkpoint/resume 证据。
- 修改范围：仅 Demo 目录。
- 验收：每条硬性标准有可定位证据，并区分 fixture 契约验证与 live 语义验证。
- 不包含：生产部署。

## 14. Traceability

- Source baseline: `Sale-guide/backend/app/agent/loop.py`; `goal_router.py`; `protocol.py`; `context.py`; `service.py`; `tools/change_plan.py`; `services/plan_commit_service.py`; `services/turn_stream_service.py`; `services/trace_service.py`.
- Related P1 contracts: `Sale-guide/docs/plans/2026-09-20-p1-planner-decision-layer-delivery.md`。
- Existing tests: `Sale-guide/backend/tests/test_agent_loop.py`; `test_goal_decision_gate.py`; `test_p1_planner_independent.py`; `test_p1_planner_decision_layer.py`; `test_agent_deadline.py`; `test_agent_concurrency.py`; `test_model_call_trace.py`; `test_m3_sse.py`.
- New Demo artifacts: 尚未创建；计划目录 `Sale-guide/work/p1-langgraph-demo/`。
- Acceptance evidence: 尚未产生。
- Production impact: 本 Task 与 Demo 计划不修改生产代码、依赖、数据库 schema、HTTP/SSE 契约。

## Change Log

- 2026-09-22：重新生成 v2 Task 文档；根据评审明确真正 resume 语义、decide_turn/commit_guard 边界，并新增 I/J 验收。
