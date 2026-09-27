# Task: Sale-guide LangGraph Production Migration

## 1. Background

P1 LangGraph 隔离 Demo 已完成并通过 23 项测试，验证了 checkpoint/resume、节点级 trace、stage/guard/commit、CAS、幂等和 `STALE_VERSION`。下一阶段目标是将 LangGraph **逐步替换**到 Sale-guide 生产架构，最终完成整体 orchestration 替换。

本 Task 不是一次性重写，也不是立即删除 `run_loop`。迁移必须可追踪、可回滚、可归档，并在每个阶段保留旧路径的验证证据。

## 2. Migration Principles

1. LangGraph 只替换 orchestration，不重写 P1 业务契约。
2. `parse_proposal`、`parse_understanding`、`decide_turn`、`mutation_refusal` 和真实 commit 规则保持唯一来源。
3. 业务权威状态仍由现有数据库和服务持有；checkpoint 只保存 Graph 执行状态。
4. 新旧路径并行期间，旧路径只读保留，不允许新增业务分支。
5. 每个迁移阶段都必须有入口、退出条件、回滚方式和归档记录。
6. 未达到阶段验收标准，不得删除或重命名旧脚本。
7. 任何文件归档必须先完成引用扫描、测试迁移和回滚窗口确认。

## 2.1 Migration Invariants

以下不变量在任何迁移阶段都必须保持。每个 Phase 验收前必须证明这些不变量仍成立：

1. **唯一业务权威状态**：plan/cart/task/confirmation/version/pending 的唯一真相源仍为现有数据库，checkpoint 不成为第二真相源。
2. **唯一 commit 点**：`commit` 是唯一允许修改业务权威状态的 Graph node；checkpoint/trace/SSE/日志等基础设施写入不得改变业务状态。
3. **唯一 P1 Decision 来源**：`parse_proposal`、`parse_understanding`、`decide_turn`、`mutation_refusal` 的规则保持唯一实现，Graph node 通过调用这些现有模块实现，不复制一套。
4. **commit_guard 不可跳过**：stage 后恢复必须重新执行 commit_guard，不得用 checkpoint 中的 guard 结果直接 commit。
5. **幂等性**：同一 commit key 重复 resume 不得产生第二次真实写入。
6. **无部分写入**：guard 失败（version/anchor/authorization/stop）不得留下部分业务状态修改。
7. **HTTP/SSE 契约兼容**：除非有批准的契约变更，请求/响应 schema 和 SSE 事件类型保持兼容。
8. **可回滚**：每个阶段必须有显式开关，默认保留旧路径，回滚不反向修改已成功提交的业务数据。
9. **旧测试不破坏**：现有 P1 contract 测试和后端定向测试在迁移期间保持通过，直到明确废弃。
10. **引用可追踪**：任何文件移动/归档/删除前完成引用扫描，不得删除唯一可回滚版本。

## 3. Current Production Baseline

生产主链路：

```text
api/guide.py
→ GuideWorkflow
→ GuideService
→ agent.loop.run_loop
→ evaluate_gate / goal_router.decide_turn
→ PlanChangeExecutor
→ PlanCommitService
→ response / persistence
```

现有能力包括模型调用、协议解析、只读轮、预算/超时/停止、Gate、pending、版本/anchor、计划提交、SSE progress 和 TraceEvent。

现有不足：没有生产级 Graph checkpoint/resume，没有覆盖完整节点的统一 trace，也没有 LangGraph 与真实依赖环境的验证。

基线代码和测试必须以实际源码为准，主要位置：

- `Sale-guide/backend/app/agent/loop.py`
- `Sale-guide/backend/app/agent/service.py`
- `Sale-guide/backend/app/agent/goal_router.py`
- `Sale-guide/backend/app/agent/protocol.py`
- `Sale-guide/backend/app/agent/context.py`
- `Sale-guide/backend/app/agent/tools/change_plan.py`
- `Sale-guide/backend/app/services/plan_commit_service.py`
- `Sale-guide/backend/app/services/turn_stream_service.py`
- `Sale-guide/backend/app/services/trace_service.py`

隔离 Demo：`Sale-guide/work/p1-langgraph-demo/`。

## 4. Target Architecture

```text
HTTP/SSE API
    ↓
GuideWorkflow / TurnService
    ↓
LangGraph Orchestrator
    ├── load_context
    ├── understand
    ├── parse_validate
    ├── decide_turn
    ├── read_only_tools
    ├── clarify / interrupt
    ├── stage_mutation
    ├── commit_guard
    ├── commit
    └── respond / trace
    ↓
Existing domain services and authoritative store
```

**每个 Graph node 的职责**：

每个 node 通过调用现有模块实现，不重新定义业务规则：

- **load_context**：调用现有 context provider，加载 session/authority snapshot
- **understand**：调用现有 `protocol.parse_understanding`，不重新定义理解规则
- **parse_validate**：调用现有 `protocol.parse_proposal`，不重新解析
- **decide_turn**：调用现有 `goal_router.decide_turn`，不重新决策
- **read_only_tools**：调用现有 tool registry，不复制工具逻辑
- **clarify / interrupt**：调用现有 clarify protocol，处理 pause/resume
- **stage_mutation**：调用现有 `PlanChangeExecutor.prepare`，不重新准备
- **commit_guard**：调用现有 guard 规则（version/anchor/authorization/idempotency），不重新定义
- **commit**：调用现有 `PlanCommitService.commit_plan`，不重新实现事务
- **respond / trace**：调用现有 SSE/trace service，不重新定义事件格式

**Graph 只负责**：什么时候调用谁、下一步去哪、在哪里 pause/resume、如何 checkpoint。

**迁移完成后的硬性边界**：

- `commit` 是唯一允许修改业务权威状态（plan/cart/task/confirmation/version/pending）的节点；checkpoint/trace/SSE/日志等基础设施写入不属于业务副作用，不得改变业务状态。
- `stage_mutation` 不写数据库；
- `commit_guard` 负责 version、anchor、stop/deadline、idempotency、mutation authorization；
- `decide_turn` 负责语义路由和 mutation decision；
- checkpoint 不取代数据库；
- API、SSE、响应 schema 保持兼容，除非另有批准的契约变更。

## 5. File Management and Archive Plan

### 5.1 迁移期间目录

```text
Sale-guide/backend/app/agent/
├── loop.py                         # 旧 orchestration，迁移期间保留
├── graph/
│   ├── __init__.py
│   ├── state.py                    # 生产 GraphState
│   ├── graph.py                    # Graph assembly
│   ├── checkpoint.py               # checkpoint adapter
│   ├── tracing.py                  # node trace adapter
│   └── nodes/
│       ├── context.py
│       ├── understand.py
│       ├── validate.py
│       ├── decide.py
│       ├── read_only.py
│       ├── clarify.py
│       ├── stage.py
│       ├── guard.py
│       ├── commit.py
│       └── respond.py
├── service.py                      # 迁移期间兼容入口
└── tools/                          # 现有工具与 commit adapter
```

### 5.2 旧脚本归档规则

旧文件不得直接删除，必须按以下阶段处理：

```text
active/      # 当前生产使用
compat/      # 仅供兼容/回滚
archive/     # 已停止生产使用，保留证据
removed/     # 仅在最终批准后删除
```

建议归档目录：

```text
Sale-guide/work/p1-langgraph-migration/archive/
├── phase-01-baseline/
├── phase-02-shadow/
├── phase-03-readonly/
├── phase-04-clarify-resume/
├── phase-05-write-path/
└── phase-06-cutover/
```

每个归档目录必须包含：

- 原文件副本或 Git 路径清单；
- 迁移前后引用关系；
- 测试结果；
- 运行开关和回滚方式；
- 归档日期与责任变更记录；
- 未解决问题。

归档不是自动移动。必须先通过 `rg`/静态引用扫描、定向测试和人工审阅。

## 6. Compatibility Contracts

迁移期间必须保持：

- HTTP `/guide/...` 路由和请求响应模型；
- SSE 事件 envelope、事件类型和序列语义；
- P1 proposal/understanding/decision/mutation 契约；
- pending 与版本/anchor 语义；
- cart、confirmation、task 生命周期边界；
- 真实 commit 的事务和 CAS 行为。

允许新增但不强制外部暴露：Graph run_id、checkpoint_id、node trace。任何新增字段必须向后兼容。

## 7. State and Checkpoint Strategy

生产 GraphState 必须区分：

```text
session       # session/turn/checkpoint/cursor
 authoritative # DB snapshot：plan/task/version/pending/cart/refs
candidate     # 未提交目标与绑定
turn          # 当前 proposal、understanding、decision、read results
staged        # staged mutation、diff、preconditions、commit key
result        # commit/response 结果
trace         # 节点事件
```

恢复规则：

1. 从 checkpoint 恢复 Graph 游标，不把 checkpoint 当业务事实；
2. 恢复后重新读取 authoritative snapshot；
3. clarify resume 不重新调用原始 understand；
4. stage 后恢复不得直接 commit，必须重新 commit_guard；
5. version/anchor/authorization 失败时不得写入；
6. 同一 commit key 重试必须幂等。

Checkpoint backend 必须支持按 session/turn 隔离、版本化、过期清理和可审计读取。具体实现前确认 LangGraph 版本和 backend。

## 8. Migration Phases

### Phase 0：基线冻结与依赖决策

- 输入：当前生产源码、测试、Demo 证据。
- 产物：基线快照、依赖/版本决策、风险登记表。
- 修改范围：文档与迁移元数据。
- 验收：确认生产入口、唯一 Gate、commit 边界、旧脚本清单。
- 不包含：生产路由切换。
- 回滚：删除迁移元数据，不影响生产。

### Phase 1：生产 Graph Adapter

- 输入：P1 纯契约和 Demo State Contract。
- 产物：`backend/app/agent/graph/` 初始目录、适配器和单元测试。
- 修改范围：新增 graph 模块，不删除旧代码。
- 验收：Graph 可编译；脚本 provider 可运行；旧测试仍通过。
- 回滚：关闭 Graph 入口开关。

### Phase 2：Shadow / Dual-Run

- 输入：同一请求的旧路径和 Graph 路径。
- 产物：差异报告、route/decision/trace 对账。
- 修改范围：内部 shadow 入口和证据记录。
- Shadow 策略：
  - **优先方案**：复用旧路径的 LLM 输出（understanding / decision），将其作为 Graph 的输入，只比较 orchestration 行为（节点路由、checkpoint、trace、SSE 事件顺序）。
  - **备选方案**：如果必须端到端双调用（测试完整一致性），则必须：
    - 记录成本翻倍
    - 记录输出可能不一致（模型随机性）
    - 记录难以区分 orchestration 差异还是模型随机性
    - 不得在生产流量上长期运行
  - 具体选择在 Phase 0 结束前确认并记录到 archive/phase-02-shadow/strategy.md。
- 验收：不产生第二次真实写入；只比较结构化结果；失败自动回旧路径。
- 回滚：关闭 shadow 开关。

### Phase 3：只读与 Clarify/Resume 切换

- 输入：chat、answer、clarify、补充输入。
- 产物：Graph 主导只读与 pause/resume，旧路径保留回滚能力。
- 修改范围：路由开关、checkpoint adapter、SSE trace 适配。
- 验收：clarify resume 不重跑 understand；现有 HTTP/SSE 兼容；旧路径可恢复。
- 回滚：恢复旧只读/clarify 路由。

### Phase 4：Prepare / Stage / Guard

- 输入：合法 mutation 和 staged plan。
- 产物：生产 stage/guard 节点和一致性测试。
- 修改范围：Graph 与现有执行器适配，不改变 commit 事务。
- 本阶段职责：Graph 负责把 mutation 一路推进到 commit 门口，但真正写数据库的仍然是 `PlanCommitService`。
- 验收：stage 无写入；guard 重读 authority；stale/anchor/authorization 失败无写入。
- 回滚：Graph 继续只读，写路径回旧路径。

### Phase 5：Commit Path Cutover

- 输入：通过 guard 的 mutation。
- 产物：Graph commit 节点、幂等/CAS/并发测试、回滚开关。
- 修改范围：仅 commit orchestration；`PlanCommitService` 仍为权威写入服务。
- 验收：唯一真实写入点；重复 resume 不重复提交；旧测试和新测试通过。
- 回滚：切回旧 commit orchestration，保留已提交业务数据，不做反向回滚。

### Phase 6：全量切换与旧路径归档

- 输入：所有支持的 turn route 和运行证据。
- 产物：全量 Graph 主路径、旧 `run_loop` 归档包、最终差异报告。
- 修改范围：默认入口和归档元数据。
- 验收：
  - **稳定窗口定义**（以下条件必须同时满足）：
    - 指定测试集（P1 contract + regression + Graph acceptance）全部通过
    - 生产关键指标无异常：
      - commit 成功率 ≥ 基线
      - 重复提交率 = 0（同一 commit key 仅执行一次真实写入）
      - 版本冲突率符合预期（stale/anchor 正确阻止）
      - 超时率/错误率 ≤ 基线
    - 无 stale/anchor 绕过（所有失败 guard 均阻止 commit）
    - 无 Graph/Legacy 关键差异（SSE 事件顺序、response schema、业务状态一致）
    - 旧入口调用数 = 0（生产流量 100% 由 Graph 处理）
    - 连续观察窗口：至少 [待定：建议 72 小时] 无上述指标异常
  - 引用扫描无遗漏；
  - 回滚版本已冻结。
- 回滚：在约定窗口内恢复旧入口；归档文件不得直接删除。

### Phase 7：最终清理

- 输入：Phase 6 归档和批准记录。
- 产物：移除已确认无引用的旧 orchestration 代码。
- 修改范围：仅经批准的旧文件和测试。
- 验收：全量测试、架构守卫、引用扫描通过；变更记录完整。
- 不包含：无关重构。

## 9. Rollout and Rollback

每个阶段必须有显式配置开关或入口选择，且默认值保持旧路径，直到该阶段验收完成。禁止通过隐式环境变量改变生产行为而不留记录。

回滚顺序：

1. 关闭 Graph 路由；
2. 保留 checkpoint 和 trace 作为证据；
3. 确认未发生重复 commit；
4. 恢复旧 orchestration；
5. 不反向修改已经成功提交的业务数据。

## 10. Acceptance Criteria

- [ ] **所有 Migration Invariants（Section 2.1）在当前阶段仍成立。**
- [ ] 新旧入口均可独立测试，旧路径在迁移期间保持可用。
- [ ] 每个阶段都有基线、证据、开关、回滚和归档记录。
- [ ] LangGraph 只新增 orchestration，不复制 P1 Decision/Gate。
- [ ] `decide_turn` 与 `commit_guard` 职责分离。
- [ ] checkpoint 不成为业务状态第二真相源。
- [ ] stage 后恢复必须重新 guard，失败无部分写入。
- [ ] commit 是唯一允许修改业务权威状态的节点；checkpoint/trace/SSE/日志等基础设施写入不得改变业务状态。
- [ ] HTTP/SSE/数据库 schema 在无批准变更时保持兼容。
- [ ] Shadow 阶段不产生第二次真实写入。
- [ ] 全量切换前旧路径已停止生产调用但仍可回滚。
- [ ] 旧脚本归档包可追踪、可审阅、可恢复。
- [ ] 最终清理前完成引用扫描、架构测试和回滚版本冻结。

## 11. Test Matrix

| 类别 | 覆盖内容 |
|---|---|
| Contract | proposal、understanding、decision、mutation、pending、version |
| Graph | 节点、边、条件路由、compile |
| Resume | clarify resume、stage 后 resume、旧 understand 不重复 |
| Guard | version、anchor、stop/deadline、authorization、idempotency |
| Commit | CAS、单次写入、重复提交、无部分写入 |
| Compatibility | HTTP、SSE、response schema、事件顺序 |
| Shadow | 新旧结构化结果对账、无重复副作用 |
| Concurrency | 同 session 冲突、不同 session 并行 |
| Archive | 引用扫描、旧入口可回滚、归档清单完整 |
| Regression | 现有 P1 和后端定向测试 |

## 12. Risks / Open Questions

1. 生产使用的 LangGraph 版本和 checkpoint backend 尚未确认。
2. 真实 LangGraph 路径尚未在当前环境验证；隔离 Demo 当前使用兼容运行时。
3. 需要决定是否先引入正式依赖，还是继续 adapter-first。
4. **Shadow 策略**：优先方案（复用 LLM 输出）vs 备选方案（双调用 + 成本容忍）的最终选择，必须在 Phase 0 结束前确认并记录到 `archive/phase-02-shadow/strategy.md`。
5. 需要确认现有 SSE 事件如何映射节点 trace。
6. 需要明确 `plan_version` 与 `state_version` 的生产对账规则。
7. 需要确认旧 `run_loop` 何时从 active 转为 compat、何时进入 archive、何时允许 removed。
8. 需要定义 checkpoint 清理、保留、审计和敏感字段脱敏策略。
9. 需要定义跨版本 GraphState/checkpoint 的迁移策略。
10. 需要确认并发、停止、超时和事务边界在新旧路径间的一致性。
11. Phase 6 稳定窗口的连续观察时长需在 Phase 0 确认（建议 72 小时）。

## 13. File Management Checklist

每次旧文件状态变化必须记录：

```text
path
old_status → new_status
reason
replacement
reference_scan
relevant_tests
rollback_target
approved_by
date
```

禁止：

- 未扫描引用就移动/删除；
- 用新 Graph 文件复制一套业务规则；
- 在同一阶段同时移动多个未验证的生产模块；
- 删除唯一可回滚版本；
- 将 `work/` 实验文件直接作为生产模块导入。

## 14. Traceability

- Source baseline: Sale-guide backend agent/service/api/tools/services and existing P1 tests.
- Demo evidence: `Sale-guide/work/p1-langgraph-demo/README.md`, `tests/test_acceptance_a_j.py`, `tests/test_state_contract.py`, `run_demo.py`.
- Related task: `Sale-guide/docs/plans/2026-09-22-p1-langgraph-orchestration-demo-task-v2.md`.
- New production artifacts: 尚未创建。
- Archive root: `Sale-guide/work/p1-langgraph-migration/archive/`，尚未创建。
- Acceptance evidence: 每阶段单独保存测试、差异、引用扫描和回滚记录。
- Production impact: 本 Task 是迁移计划，不代表已修改生产代码；任何实现须按阶段审批。

## Change Log

- 2026-09-22：创建生产 LangGraph 渐进迁移 Task，定义新旧路径并行、阶段切换、旧脚本归档、回滚与最终清理流程。
- 2026-09-22：优化 Task 文档：
  - 新增 Section 2.1 Migration Invariants，列出 10 条跨阶段不变量
  - Section 4 明确每个 Graph node 调用现有模块，不重新实现业务逻辑
  - Section 4 严格定义副作用点（业务状态 vs 基础设施写入）
  - Phase 2 明确 Shadow 策略（优先方案 vs 备选方案）
  - Phase 4 明确职责边界（推进到 commit 门口但不写数据库）
  - Phase 6 增加稳定窗口可验证指标（测试集、关键指标、观察时长）
  - Section 10 Acceptance Criteria 增加 Migration Invariants 验收
  - Section 12 Risks 更新 Shadow 策略和稳定窗口时长的待确认事项
