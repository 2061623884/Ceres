# Sale-guide LangGraph 全量切换重构任务（同级隔离副本版）

- 日期：2026-09-22
- 状态：**未执行计划**（本文件只描述要做什么；所有验收框默认未勾选，未运行任何业务测试）
- 基线来源：源目录工作树快照（不是 HEAD，理由见 §2.1）
- 源目录（默认）：`C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide`
- 目标副本（建议）：`C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph`
- 目标证据目录：`C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph/work/langgraph-full-refactor/`
- 前置文档（**不修改**）：`docs/plans/2026-09-22-sale-guide-langgraph-production-migration-task.md`

本任务替代原计划的推进方式，但不改写原文件；原文件保留为历史记录。§1 明确两者在策略上的差异。

---

## 0. 目标与成功定义

**目标**：把当前完整 Sale-guide 项目复制为同级隔离副本，在副本内**彻底完成 LangGraph
编排架构的全量切换**——所有 Guide turn 的编排（理解 / 解析 / 决策 / 只读工具循环 / 回答 /
澄清 / prepare-stage-guard-commit / 响应 / trace）都由 Graph 承担，最终只有一条运行路径；
旧编排（`run_loop` 及其在 `GuideService` / `GuideWorkflow` 中的分支）退出生产并被清理。

**"彻底"的可核对定义**（同时满足才算完成，见 §10）：
目标副本内 Guide turn 只有 Graph 一条编排路径，不存在 `run_loop` 隐藏调用、永久双引擎、
失败自动 fallback、注入 decision-only 节点、占位 respond；领域规则/业务服务/数据库/
HTTP-SSE/前端未被重写；离线差分证明新旧编排在同一输入下业务效果一致（§9）；旧入口在生产
代码中静态引用为 0，且有动态计数或测试证明（§10.2）。

**不是目标**：见 §3.6。

---

## 1. 相对原计划的策略变更

**沿用的前置决策与边界**：

1. 原计划 Phase 2 的**优先方案是复用旧路径的 LLM 输出**（`archive/phase-02-shadow/STRATEGY.md`
   记录为用户已确认的 Option A，graph 无状态、不写 checkpoint），**并不必然成本翻倍**；只有
   备选方案（端到端双调用）才有成本与随机性归因问题。
2. 原计划 Phase 6 的"72 小时"只是**待确认建议**（`archive/phase-00-baseline/BASELINE.md:254`
   "Suggested 72 hours, to be confirmed"），且已被 Phase 0 的 **volume-based** 决策取代
   （`archive/phase-06-cutover/STABILITY-WINDOW.md`，用户确认：按请求量/路线覆盖/暂停恢复
   次数衡量）。本任务不自动沿用该文档中的请求量或观察时长阈值。
3. 原计划 §2.1/§4 的 **"commit 是唯一允许修改业务权威状态的节点"是目标不变量，不是对现状
   的描述**。现状一轮存在多处 `db.commit()` 这一事实，**不构成放宽该约束的理由**；它只说明
   本任务需要做事务归属调整（§4.3）。
4. 原计划 **不是**"只要把 `run_loop` 包进一个节点"。本任务同样要求全量节点化。

| # | 原计划 | 本任务 | 理由 |
|---|---|---|---|
| 1 | Phase 2 线上 Shadow（优先复用 LLM 输出） | **离线差分**替代长期线上 Shadow | 副本内即可判定；避免为对照而引入运行期双路径 |
| 2 | 旧目录原地渐进切换、每阶段带回滚开关 | **副本内一次性全量 Graph 单一路径**，源目录冻结可还原 | 避免"带 fallback 的永久双引擎"被误称完成 |
| 3 | commit 唯一写节点（不变量） | **保留该硬约束**：Guide 业务权威写只由 commit 节点触发；现状的多次提交通过事务归属调整收敛（§4.2/§4.3） | 不因现状复杂而降低目标 |
| 4 | Phase 6 稳定窗口（建议 72h → 后改为 volume-based） | 离线请求量按**风险与路线覆盖**确定，不强搬原计划的 10000 turn 或时间窗口 | 本任务不假设生产流量；覆盖度优先 |
| 5 | 未定义复制、基线与隔离 | 新增 R0：工作树快照 + manifest + 数据/端口/checkpoint 隔离（§7） | HEAD 不可作基线（§2.1） |
| 6 | `compat/`、`archive/` 长期保留 | 冻结源目录承担"可还原"，副本内不保留 `compat` 分支 | 减少双份维护；还原靠源快照而非运行时开关 |

保留不变的原计划原则：唯一业务权威仍是数据库；纯规则唯一实现；checkpoint 不是第二真相源；
stage 后恢复必须重新 guard；HTTP/SSE 契约兼容；旧测试不直接删除或弱化。

---

## 2. 现状核实（2026-09-22，只读源码核实）

### 2.1 已核实事实

数值型条目（版本、文件数、目录体量）均为**本次观测值**，用于理解现状与估算，**不是复制集
验收常量**——复制集以 R0 现场枚举的 manifest 为准（§7.2/§7.3）。

| 事实 | 证据（源路径:行） | 影响 |
|---|---|---|
| 生产入口有同步 `/turns` 与流式 `/turns/stream` | `backend/app/api/guide.py:226`、`:633` | 切换必须同时覆盖两条入口 |
| 编排主链：`GuideWorkflow` → `GuideService` → `run_loop`，并按 turn 形态分派（taskless / terminal / lightweight） | `backend/app/agent/workflow.py:150,290,515,565`、`service.py:301` | 需替换的是**核心编排循环及其各入口分派**，不是单个函数 |
| 纯规则：`protocol.parse_proposal:396`（内部调用 `app.agent.goal.parse_understanding`，见 `protocol.py:35,423`）、`goal_router.decide_turn:453`、`goal_router.mutation_refusal:905` | `backend/app/agent/protocol.py`、`goal.py`、`goal_router.py` | Graph 节点调用它们，不复制 |
| 模型调用契约：`provider.propose(request)`，请求含 `proposal_schema()`；`run_loop` 负责协议 repair（默认 1，硬上限）、只读轮数（硬上限）、模型调用预算、`should_stop`、`deadline` | `agent/loop.py:20-39,86,158,254,318-346` | understand/read 节点必须保留这些语义，不能简化 |
| prepare 与 commit 已是两次调用 | `change_plan.py:338`（`guarded_prepare_purchase_plan`，未发现 DB 写）→ `:391`（`self.commit.apply_result`） | stage 节点映射到 prepare；事务归属待调整（§4.3） |
| `PlanCommitService.apply_result`：`assert_turn_anchor` → merge → `before_persist` → 再 `assert_turn_anchor` → `to_db(expected_version=...)` → **`db.commit()`（内部提交）** | `services/plan_commit_service.py:78,122,127,169,188` | 规则保留；仅需把"何时提交"的归属交给 commit 节点（§4.3） |
| CAS 是条件 UPDATE（`WHERE state_version=:ver`），rowcount≠1 → `STALE_STATE` | `app/agent/state.py:102-124` | 事务级最终校验已存在，保留 |
| anchor 用 plain SQL 重读 `guide_sessions.current_task_id`（绕过 ORM identity map） | `services/task_lifecycle_service.py:87-107` | guard 复用同一手法 |
| 幂等记录 `TurnRequestRecord`：唯一约束 `(owner_id, session_id, request_id)`、`request_digest`、`status`（`pending/running/completed/retryable_failed/failed`）、`response_json` | `models/cart.py:54-73`、`workflow.py:62-95` | 幂等键持久化已存在；语义需收紧（§5.4） |
| 一轮内存在**多处** `db.commit()`：`apply_result` 内（plan/task/version）、`workflow.process_turn` 尾部（message/幂等/plan snapshot）、`service._run` 模型调用前（trace + 预写幂等） | `plan_commit_service.py:188`、`workflow.py:326-366`、`service.py:370-382` | 需按 §4.2 分类，并按 §5.3 收敛 |
| 澄清 pending 与 `session_version` 由 `turn_context.save_context` 写（仅 `flush`），最终由尾提交落盘 | `agent/context.py:325-342`、`service.py:753-763` | 澄清写也属于业务提交边界 |
| 停止/预算：`TurnCancellationRegistry`（`threading.Event`）、`turn_deadline_at`、`LoopBudget`，写入前有 `_refuse_if_unwritable`（STOPPED/TIMEOUT 拒绝） | `services/turn_execution_service.py:138-172`、`service.py:99,236`、`change_plan.py:642` | stop/deadline 必须在 commit 前重读 |
| SSE 在**工作线程**内跑同步编排（`threading.Thread` + `queue.Queue`），客户端断开只置 `client_gone`，不取消运行 | `services/turn_stream_service.py:350-410` | Graph 在线程内被调用，影响 checkpointer 选型（§6.6） |
| 已安装的 `langgraph-checkpoint-sqlite` 同时提供同步 `SqliteSaver` 与 `AsyncSqliteSaver` | 运行时 `dir()` 观测 | 线程内优先同步 saver |
| Graph 现状：`build_graph()` 只注册 `load_context`（entry=finish） | `agent/graph/graph.py:24-33` | 组装未完成 |
| `load_authoritative` 位于 `app/agent/graph/nodes/context.py:24`（**不是** `agent/context.py`）；`agent/context.py` 提供 `load_context`/`build_candidate_set`/`save_context` 等会话上下文能力 | 上述文件 | 节点调用关系按此写 |
| `nodes/decision.py` 要求**注入** decision（否则 `DECISION_REQUIRED`）；`nodes/response.py` 是占位（只置 `committed=False`） | `agent/graph/nodes/decision.py:26-45`、`response.py:20-32` | 这两处必须被消除 |
| 生产代码未引用 Graph：`rg "agent.graph" backend/app`（排除 graph 自身）无命中；引用只在 `backend/tests/agent/graph/` | 静态扫描 | 切换是净新增 |
| 依赖（观测值，`backend/.venv`，Python 3.12.10）：langgraph 1.2.12、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1、fastapi 0.141.1、SQLAlchemy 2.0.54、pydantic 2.13.5、pytest 9.1.1、pytest-asyncio 1.4.0；`pyproject.toml` 约束 `langgraph~=1.2.0`、`langgraph-checkpoint-sqlite>=3.1.0` | `pip list`（只读）、`pyproject.toml:14-16` | 副本按**当前精确版本**锁定，不猜"最新版" |
| 该 venv 含**指向源的 editable 安装**：`__editable__impl_sale_guide_backend.pth` + `direct_url.json` = `file:///C:/.../Sale-guide/backend` | `site-packages` 观测 | 锁与安装必须剔除并防串源（§7.6） |
| Graph 测试静态计数 16 个（checkpoint 4 / graph_compile 2 / load_context 6 / state 4） | `backend/tests/agent/graph/*.py` 计数（观测值） | 与 `OWNER-ID-FIX.md` 的"16 passed"一致，但**本轮未执行测试** |
| git：单次 initial commit（`f7f4e52`，`main`），工作树大量未提交/未跟踪；`backend/app/agent/graph/`、`loop.py`、`service.py`、`protocol.py` 等编排源码**全部未跟踪** | `git status --porcelain`、`git ls-files` | **HEAD 不能作为基线** |
| 隔离相关配置：`DATABASE_URL` 默认 `sqlite:///data/runtime/sale_guide.sqlite3`；`SOURCE_DATABASE_PATH` 默认 `data/sale_guide.db`；`RETRIEVAL_INDEX_DIR`、`RETRIEVAL_MODE`、`BACKEND_PORT=8000`、`FRONTEND_PORT=3000` | `core/config.py:49,66-73`、`.env.example` | 副本逐个改到独立命名空间 |
| 前端经 `BACKEND_PORT` 代理到 `127.0.0.1:${BACKEND_PORT}`；SSE 走独立 `api/guide-stream` 路由；`SALE_GUIDE_NEXT_DIST_DIR` 可切分构建缓存 | `frontend/next.config.js`、`src/app/api/guide-stream/route.ts` | 端口 + distDir 即可隔离 |
| 可复用的隔离与守卫先例：`make verify-isolated`（拒绝 runtime DB）、`scripts/verify_shopping_workflow_offline.py`（临时库 + 空闲端口 + 真实 FastAPI/Next，无 provider）、`backend/tests/test_semantic_only_architecture.py`（AST 扫描 + 活体断言） | `Makefile`、上述文件 | R4/R5 与架构守卫沿用这些模式 |
| `backend/checkpoints.db` 当前不存在 | 文件系统观测 | 无历史 checkpoint 迁移负担 |
| 体量（观测值）：`backend/.venv` ≈109M、`frontend/node_modules` 占 frontend 约 680M、`data/runtime` ≈5.9M（活动库 + 大 WAL）、`data/retrieval_index` ≈12M（派生）、`work/shopping-agent-research-2026-09-19` ≈195M（含 9 个嵌套 `.git`） | `du -sh`、`find` | 排除清单依据（§7.2） |

### 2.2 历史报告声明 vs 当前事实（不一致项）

| 声明 | 出处 | 当前事实 | 处理 |
|---|---|---|---|
| "New production artifacts: 尚未创建" | 原计划 §14 | `backend/app/agent/graph/`、`backend/tests/agent/graph/` 已存在（未跟踪） | **过时**；原文件不修改 |
| "langgraph 未安装，故 demo 使用兼容 shim" | `work/p1-langgraph-demo/README.md` | 实测已安装 langgraph 1.2.12 等 | **过时**；shim 不得进入生产路径 |
| 全量后端失败数 "59" 与 "44" 互相矛盾 | `phase-01-adapter/VERIFICATION-REPORT.md` vs `-REVISED.md` | 本轮**未执行测试** | 不得宣称基线全绿；R0 产真实失败清单（§12） |
| Graph 测试 16 passed | `OWNER-ID-FIX.md` | 静态计数一致；未复跑 | 视为"待复跑" |
| Phase 6 建议 72 小时 | `phase-00-baseline/BASELINE.md:254` | 已被 volume-based 决策取代 | 见 §1 第 2 条 |

### 2.3 未核实 / 待确认（不得假设成立）

1. 后端全量测试的真实红绿清单与失败分布。
2. 进程被强杀后 `TurnRequestRecord.status='pending'` 的收敛责任（`cleanup_orphans` 作用于
   `GuideOperation`，不是该表）。
3. 是否已有内存态 dedupe 参与"重复 resume 不重复提交"（未找到，也未能证明不存在）。
4. 副本内 Playwright/Chromium 可用性；真实模型/embedding 端点可用性。
5. `run_loop` 内部除模型调用与只读工具外是否还有隐式写入路径（R1 前逐分支确认）。
6. `verification/rag/indexes/final-lexical`（被 gitignore，3.6M）是否为副本验证所需（§7.2 白名单）。

---

## 3. 目标架构（只在副本内生效）

### 3.1 拓扑（无悬空分支）

```text
HTTP/SSE（不变）
  ↓
GuideWorkflow / TurnStreamService（保留：owner 校验、请求外形、SSE 排空、stop 注册）
  ↓
LangGraph 唯一编排（副本内）
  START → load_context → understand → parse_validate → decide_turn
                          ↑              └─ 协议错误且 repair 预算允许：回到 understand
                          └─ read_only_tools ← decide_turn 的只读路由（有界回边）

  decide_turn ──┬─ clarify_prepare（纯计算 pending）
               ├─ mutation_prepare（纯计算 staged mutation）
               └─ answer_prepare（纯计算回答 / 预算耗尽 / 拒绝结果）
                                  ↓
               commit_guard（重读权威与最终提交前置条件；不得跳过）
                  ├─ 通过 → commit（业务效果 + receipt 同事务）→ respond
                  └─ 拒绝 → commit（仅持久化拒绝回执/审计，不改业务权威）→ respond

  respond ──┬─ answer / mutation / 拒绝 → END
            └─ clarify → wait_input（interrupt，无业务副作用）
                            └─ 恢复：鉴权及回执检查 → refresh_authority
                                      → 解析补充 → parse_validate / decide_turn
  ↓
现有领域服务（纯规则 + PlanCommitService + 业务库）——唯一业务来源
```

要点：
- `read_only_tools` 的回边**必须有界**（读轮预算 + 硬上限），且回边的目标是"下一次模型请求"
  本身，不能把整圈塞进一个节点内部循环（否则等于把 `run_loop` 藏进节点）。
- answer / clarify / mutation 三条路径都在 prepare 后汇入**同一个 commit 节点**；纯读路径同样
  经 commit 落盘消息与幂等收尾（读本身不改业务状态，但 HTTP 结果必须可重放）。
- 澄清是"先提交 pending 与该 HTTP 请求的 receipt，再 respond，然后在独立、无副作用的
  `wait_input` 节点 interrupt"。
- taskless、active-task、terminal-task 三种入口均须进入上述图；不得把原
  `_taskless_turn` / `_handle_terminal_task_turn` 的编排留在 Graph 外。新增 task、替换旧 task
  或更新 session anchor 也属于 commit 管理的业务效果。
- `understand` 每次只执行一次业务层 provider 请求；协议 repair 与下一次只读轮调用由图的
  条件边控制。预算耗尽时形成明确拒绝/回答结果，不得拿上轮 decision 继续写入。

### 3.2 GraphState 分区（7 分区，`state.py:42-51`）

| 分区 | 目标内容 | 注意 |
|---|---|---|
| `session` | session_id / **owner_id** / turn_id / logical_run_id / checkpoint_id / cursor | 已有基础字段；logical_run_id 与 HTTP 映射待实现 |
| `authoritative` | **仅最小投影**：版本号、引用（task/anchor/goal ref）、pending 的 id/摘要 | **不放大对象**；完整 authority 放本次运行上下文（§6.6）|
| `candidate` | 本轮服务端候选与 focus refs（引用/摘要，版本绑定） | 需要时可重取，不必全部进 checkpoint |
| `turn` | proposal / understanding / decision / 只读结果摘要 / 用户补充信息 | 只读结果按摘要入 state |
| `staged` | prepare 产出的 plan_result 引用、diff、preconditions、commit key | 敏感内容最小化 + 访问控制 + TTL（§6.6） |
| `result` | commit receipt（业务结果 id/版本/状态）、响应载荷引用、plan_effect | 提交后只读 |
| `trace` | 节点事件（root reducer 追加） | 基础设施 |

State 只放可序列化的数据。SQLAlchemy Session/ORM 活对象、provider 客户端、回调、锁、
停止事件与本次完整 authority 均通过运行上下文传入，不写 checkpoint。`staged` 的引用必须
指向持久化且版本固定的对象；没有这样的对象时，持久化恢复所需的最小 staged 载荷，不能用
进程内对象引用冒充可恢复状态。

### 3.3 节点职责（每个节点只调用既有实现）

| 节点 | 调用 | 写入 |
|---|---|---|
| `load_context` | `app.agent.graph.nodes.context.load_context` → `load_authoritative`（**该文件**，非 `agent/context.py`）；owner 校验 | 无 |
| `understand` | 复用 `run_loop` 中的请求构造（含 `proposal_schema()`）与**真实 provider 调用**语义：协议 repair 计数与硬上限、模型调用预算、stop/deadline 检查、`on_phase`/`on_model_call` 回调；`protocol.parse_proposal` 负责解析，其中 `app.agent.goal.parse_understanding` 负责理解部分（两者分别注明、各自唯一来源） | 无 |
| `parse_validate` | `protocol.parse_proposal`（其内部调用 `goal.parse_understanding`） | 无 |
| `decide_turn` | `goal_router.decide_turn` / `evaluate_gate` / `mutation_refusal` | 无 |
| `read_only_tools` | `agent.tools.read.ReadTools`；每轮后由**有界条件边**回到下一次模型请求 | 无 |
| `clarify_prepare` | 现有 pending 协议与理解结果（纯计算） | 无 |
| `wait_input` | `interrupt` 挂起，等待用户补充 | **无**（纯等待） |
| `mutation_prepare` | `guarded_prepare_purchase_plan`（stage） | 无 |
| `answer_prepare` | 组装回答所需的结构化结果（不生成持久化消息） | 无 |
| `commit_guard` | `task_lifecycle_service.assert_turn_anchor`/`anchor_turn`、stop/deadline、authorization、幂等 key 校验 | 无 |
| `commit` | 事务协调方法调用 `PlanCommitService.apply_result` 的不提前提交路径；**协调方法**拥有事务；用现有响应构造函数固定完整 receipt，再同事务写入业务效果与 HTTP 收尾记录 | **是（唯一业务写）** |
| `respond` | 读取并发布 commit 已固定的完整响应 receipt；保留既有 HTTP/SSE 适配 | 无（不重新决策、生成消息或改写 receipt） |
| 节点 trace hooks | `trace_service.TraceService`（独立 session）；在节点开始/结束/失败时记录，不另造悬空业务节点 | 基础设施 |

### 3.4 旧组件 → 新职责 → 保留/替换

| 旧组件 | 新职责 | 处理 |
|---|---|---|
| `agent/loop.py:run_loop` | **核心编排循环**被 Graph 取代；纯逻辑（请求构造、门控事实、预算/超时/repair 判定）抽为可复用函数供节点调用 | 替换（纯逻辑保留，循环控制移除） |
| `GuideService` 各入口（`understand_turn`/`_run`/`_execute_proposal`/`_gate_pending`） | 提服务能力（模型调用、候选/focus、只读端口、proposal 编译、响应组装）；入口分派归 Graph | 保留（拆分，不重写规则） |
| `agent/tools/change_plan.py:PlanChangeExecutor` | stage 与 commit 分别调用 prepare 与 apply_result | 保留（拆两次显式调用） |
| `services/plan_commit_service.py` | commit 节点的权威写入实现 | 保留（仅事务归属调整，§4.3） |
| `GuideWorkflow.process_turn` | 请求外形、owner 校验、幂等检查、消息持久化、SSE 桥接 | 保留（编排部分改为调用 Graph） |
| `TurnStreamService` | SSE 排空、运行记录、stop 注册 | 保留（接入方式调整） |
| `nodes/decision.py`（注入 decision） | 真实调用 `decide_turn` | **替换** |
| `nodes/response.py`（占位） | 发布通过现有 `build_response` 等函数构造并已持久化的完整响应 | **替换** |
| `work/p1-langgraph-demo/p1_demo/langgraph_compat.py` | 无 | 不进入副本生产路径 |

### 3.5 文件归属简表（副本内路径）

| 区域 | 路径 | 新建/已有 | 允许改动 |
|---|---|---|---|
| Graph 组装与状态 | `backend/app/agent/graph/{graph,state,checkpoint}.py`、`graph/nodes/*.py` | 已有骨架，节点大量新建 | 全部 |
| 服务层纯函数抽取 | `backend/app/agent/{service,loop}.py`、`agent/context.py`、`agent/context_resolver.py` | 已有 | 仅抽取/接线，不改规则 |
| 写边界 | `backend/app/agent/tools/change_plan.py`、`backend/app/services/plan_commit_service.py`、`backend/app/services/task_lifecycle_service.py` 相关调用 | 已有 | 事务归属与拆分 |
| 入口集成 | `backend/app/agent/workflow.py`、`backend/app/services/turn_stream_service.py`、`backend/app/services/turn_execution_service.py`、`backend/app/api/guide.py` | 已有 | 接入编排与会话执行协调 |
| Graph 测试 | `backend/tests/agent/graph/*`（**扩展既有目录**） | 已有 | 全部 |
| 业务/契约测试迁移 | `backend/tests/test_*.py` | 已有 | 迁移旧 loop 专属用例 |
| 基础设施/脚本 | `backend/app/agent/graph/checkpoint.py`、`backend/app/services/trace_service.py` | 已有/新建 | 隔离与 TTL；运行库不是源码文件 |
| 幂等存储（仅必要时） | `backend/app/models/cart.py` 与项目现有数据库初始化/迁移入口 | 已有，具体迁移文件 R2 核实 | 仅最小兼容的 receipt/run 映射存储调整 |
| 副本证据与工具 | `work/langgraph-full-refactor/**`（清单/差分/守卫/计数器） | **计划新建** | 全部 |
| 配置 | 副本内 `.env`（不进 git）与 `.env.example` | 已有模板 | 隔离项 |

### 3.6 明确非目标

不改领域规则（plan/candidate/validation/requirements/cart 语义）；不改数据库 schema（除 §5.3
允许的最小幂等迁移）；不改 HTTP 路由与 SSE envelope/事件类型（新增 Graph 元数据须向后兼容）；
不改前端组件与交互；不做无关 RAG/检索重写；不把外部非 Guide CRUD API（`plan-refresh`、
`plan-revisions`、`confirm`、`add-item`、`cancel`、`supply-context`）图化。

---

## 4. 写边界与事务分类

### 4.1 副作用盘点（guide turn 内）

| 写点 | 现状位置 | 性质 | 目标归属 |
|---|---|---|---|
| plan / task / state_version / plan_json / candidate_products / current_step | `plan_commit_service.py:140-188` | **业务权威** | commit 节点 |
| `task.pending_clarification_json=null`、`session.candidate_dishes_json='[]'`、`session.updated_at` | `plan_commit_service.py:180-188` | **业务权威** | commit 节点 |
| 澄清 pending 列表 + `session.session_version++` | `context.py:325-342` + `service.py:753-763` | **业务权威** | commit 节点 |
| user/assistant message、`plan_snapshot`、`session_version` 回填、幂等结果 marker | `workflow.py:314-366` | **业务权威/审计** | commit 节点（与业务效果同事务，§5.3） |
| `TurnRequestRecord(status='pending')` 预写 | `workflow.py:247-257` | **协调记录（reservation）** | commit 节点之外、独立事务；仅表示"有人在做"，**不代表成功** |
| trace（`phase`、model call） | `trace_service.py:32`、`service.py:370-382` | **基础设施** | 独立 session，禁止顺带提交业务状态 |
| checkpoint | `graph/checkpoint.py` | **基础设施** | 独立 DB/连接 |
| SSE 事件 | `turn_stream_service.py` | **基础设施** | 不改契约 |
| cart/confirmation/task 的非 Guide 入口（confirm/cancel/plan-refresh 等） | `api/guide.py:410-553` | 业务权威 | **不进 Graph**，保持现有服务 |

### 4.2 硬约束与事务分类

1. **硬约束（保留原计划不变量）**：Guide turn 内对 plan/cart/task/confirmation/version/pending
   的业务权威写入，**只由 commit 节点触发**；其他节点不得提交业务状态。
2. 三类写必须分开对待：
   - **业务权威写**：只能出现在 commit 节点的同一事务里；
   - **协调记录**（幂等 reservation、run 记录）：可独立提交，且**不得**被当作成功的证据；
   - **基础设施写**（trace/checkpoint/SSE/日志）：使用独立 session/连接，**不得**在同一
     `db.commit()` 里夹带业务 dirty 状态（现状 `service._run` 的"trace + 业务 session 提交"
     是必须消除的耦合）。
3. 若某处确实需要在业务事务外提交（如 reservation），必须在 §4.1 表中登记并说明理由。

### 4.3 事务归属的最小调整（不改规则）

- `PlanCommitService.apply_result` 目前的 `db.commit()` 是**实现细节**，不是业务规则。允许的
  最小调整：让 `apply_result` 不再自行提交，改由 commit 节点调用的**事务协调方法**统一提交
  （例如新增"只 flush 不 commit"的内部路径，或把提交上移到协调方法）；
- merge/校验/anchor/CAS/`before_persist` 的顺序与语义**保持不变**；
- 若非 Graph 的现有调用者依赖 `apply_result` 自行提交，保留其明确的服务级事务入口，Graph
  调用不提前提交的内部实现；不要通过全局去掉 commit 破坏其他 API，也不要复制领域规则；
- 不允许的调整：把 CAS 或 anchor 校验搬出事务、或在提交前用 checkpoint 里的旧值替代重读。

---

## 5. guard / 幂等 key / 原子性

### 5.1 guard 权威校验清单（commit_guard 节点）

- owner：`session.owner_id == state.session.owner_id`（现状 `workflow.py:182` 与
  `graph/nodes/context.py` 双重校验）；
- task anchor：`guide_sessions.current_task_id` 与回合开始时一致（plain SQL 重读，复用
  `task_lifecycle_service.py:87-107` 手法）；
- version：`expected_state_version` 与实时 `state_version` 一致（`to_db` 条件 UPDATE）；
- authorization：mutation 是否被 decision 允许（`mutation_refusal`）；
- stop / deadline：`TurnCancellationRegistry` 事件 + `turn_deadline_at`（写入前检查）；
- 幂等 key：见 §5.4；
- 任一项失败 → **零业务权威变更**，结构化拒绝，不留部分 plan/task/pending/version 状态；
  失败回执、协调记录和审计可按既有契约落盘，但不得夹带被拒绝的业务变更。
- 刷新权威状态不得把旧 staged 的 expected version/anchor 覆盖成最新值来强行过关；
  版本冲突必须拒绝或显式重新决策/prepare。澄清 pending 使用 session_version 等实际依赖的
  并发前置条件，不能只检查存在 task 时的 state_version。

### 5.2 事务与 CAS

真正的事务/CAS **保留在写入路径内部**作为最终校验；Graph 不得用 checkpoint 里的 guard 结果
直接写入。stage 后恢复必须重新执行 `commit_guard`（即使 checkpoint 记录了通过）。

### 5.3 原子性方案（默认目标，可执行）

**目标**：同一 guide 业务操作内的 plan/task/pending/session_version 等**业务变更**与
**持久化 commit receipt / 结果 marker**（幂等记录置 `completed` + `response_json`）在
**同一个数据库事务**中提交。这样"业务已写但 receipt 未写"的窗口被消除。

落地要点：

1. commit 节点调用的事务协调方法持有事务：先执行 `apply_result` 的 flush 部分（业务效果），
   再写 receipt/marker，然后**一次提交**；任一步失败则整体回滚。
2. 响应标识（message id/sequence、plan_id/plan_version、plan snapshot 内容）必须**在事务内
   确定**并写入 receipt；`respond` 节点在提交后**只发布/读取**已固定的 receipt，不再写消息、
   不再重新生成标识。
3. **预写幂等 reservation**（`TurnRequestRecord(status='pending')`）允许独立提交，但它只是
   协调记录：它不能代表成功，也不能作为恢复时的结果来源；结果只能来自同事务写下的
   receipt。
4. 基础设施写（trace / checkpoint / SSE）使用**独立 session**；禁止 trace 的 `db.commit()`
   顺带把业务 dirty 状态刷入。业务写事务内不等待模型/网络；若 trace 与业务共用一个 SQLite
   文件，事务内先收集事件、事务结束后再由独立 session 落盘，避免持有写锁时等待另一连接写入。
5. 若现有 `response_json` 结构无法承载恢复所需信息（例如消息 id/sequence、plan 引用），
   **允许仅为幂等所做的、最小的、向后兼容的 schema 迁移**（新增可空列或扩展 JSON 字段），
   并在 R0/R2 记录兼容性与回填策略。不得一边绝对禁止 schema 变更、一边要求无法实现的原子性。
6. **不接受**"先提交 A 再提交 B（两段式顺序提交）"作为最终方案；该顺序只允许作为迁移中的
   过渡状态，且必须由 §8 R2 的验收项证明最终已收敛为单事务。

### 5.4 幂等 key 与 `request_digest`（不要拼成两套操作）

- **同 `(owner_id, session_id, request_id)` + 不同 `request_digest` → 必须拒绝**
  （现状 `IDEMPOTENCY_CONFLICT`，保留）；
- **commit key**（业务提交幂等标识）在重放中必须**稳定**，且能区分"澄清 pending 的提交"与
  "后续真实 mutation 的提交"（例如 key = `(owner_id, session_id, logical_run_id, step_kind,
  step_seq)`，其中 `step_kind ∈ {clarify_pending, mutation_commit, answer_commit}`）；
- 同一 key 的重放只能返回同事务写下的 receipt，不得再次推进；
- 不混淆 HTTP 请求标识、业务操作标识与 Graph thread：HTTP request_id 可以参与业务 key，
  但不能直接充当跨澄清恢复的 thread_id；映射与 step_seq 必须可持久化重建。
- 在鉴权和 digest 校验后，**先查已提交 receipt，再判定旧版本是否 stale**；已提交操作即使
  checkpoint 落后或业务版本已被后续请求推进，也返回原 receipt，不重新 guard/prepare/commit。

### 5.5 崩溃窗口与收敛（不得人工豁免）

- 数据库提交成功但 checkpoint/响应未写 → 重试**只读取同一 receipt**，不重新执行写入；
- 协调记录僵死（进程被强杀后 `status='pending'`）必须有明确收敛责任（由谁、何时把它置为可
  重试），R2 前完成核实并落地；不足则作为**阻塞项**补足，不允许以"人工确认后可切换"绕过；
- 禁止表述：`checkpoint 自动 exactly-once`、`靠内存去重即可`。

---

## 6. 恢复协议（resume）

### 6.1 恢复入口顺序（先鉴权，再读 checkpoint，再刷新权威）

先区分 HTTP 重放与真正需要继续执行的请求：

1. **鉴权与幂等**：owner 来自可信请求上下文，校验 session 归属与 request_digest；若该请求已有
   已提交 receipt，直接返回，不要求 run 仍活跃，也不要求 checkpoint 仍存在。
2. **定位与读取 checkpoint**：只有未完成的新执行/补充请求才检查活跃 run 的归属和服务端映射，
   再读 checkpoint；客户端不能指定别人的 checkpoint。
3. **`refresh_authority`**：重读业务权威快照（最小投影）；
4. **解析补充/决策**：澄清补充作为**独立步骤**显式解析；**不重跑原始 understand**；
5. **`commit_guard`**：重新校验 owner/version/anchor/authorization/stop/deadline/幂等 key；
6. **`commit`**：同事务提交业务效果 + receipt（§5.3）。

说明：只在 guard/respond 处刷新是**太晚**的；`refresh_authority` 必须是恢复路径上的显式节点，
guard 与之互不替代。
LangGraph 的 `interrupt` 恢复会从中断节点开头重入，不会自动从 START/load_context 重跑。
对“stage 已落 checkpoint”乃至“guard 已通过”的崩溃恢复，恢复适配器必须显式重新经过
refresh_authority → commit_guard；不能让保存的游标直接进入业务写入。commit 内仍保留事务级
最终校验与 receipt 去重，避免检查后到实际提交之间的竞态。

### 6.2 logical Graph run / thread 与 HTTP request_id

- **logical run/thread** 标识一次业务操作（可跨越多个 HTTP 请求）；`thread_id` 由**服务端**
  生成与映射（如 `f"{owner_id}:{session_id}:{logical_run_id}"`），客户端不得任意指定；
- 每个 HTTP 请求有自己的 `request_id`；**澄清补充会产生新的 `request_id`**，但必须解析到
  **同一等待中的 graph thread**，不得为新 `request_id` 新建 thread（否则 resume 失效）；
- 重放同一 HTTP 请求只返回该请求自己的 receipt，**不再次推进** graph；
- 映射关系需可持久化重建（存在业务库或协调记录中，可审计）。

### 6.3 澄清闭环

1. `clarify_prepare` 纯计算产出 pending；
2. `commit` **先提交** pending 与该 HTTP 请求的 receipt；
3. `respond` 发布澄清问题；
4. 进入**独立、无副作用**的 `wait_input` 节点 `interrupt`；
5. 恢复走 §6.1 顺序。

`wait_input` 只读取已固定的澄清载荷并调用 interrupt，不生成新的 receipt，也不提交业务。
恢复重入该节点时可重新读取载荷，但不得重新发送一条有新 message id/sequence 的澄清消息。

### 6.4 并发

- 同 session 两个不同 `request_id` 的真实串行**不能只靠 `TurnRequestRecord` 唯一约束**声称；
  需复用/补充**session 级执行协调**（现有 `TurnExecutionService`/`GuideOperation` 运行记录与
  `TurnCancellationRegistry`），并保留真实 CAS 作为最终兜底；
- 不同 session 可并行，互不共享 checkpoint 连接。

### 6.5 deadline 与预算账本（跨 resume 片段）

- 暂停等人期间的时间**不得**直接沿用已过期的 monotonic 值：恢复产生**新的执行片段**，该片段
  取**新的 deadline**；
- 模型调用预算与 repair/读轮账本按明确规则延续（已消耗计入总量）并受硬上限约束；规则需在
  R2/R3 明确写出并测试（"新片段新 deadline、旧账本不清零但封顶"）。

### 6.6 checkpoint 生命周期、最小化与 TTL

- 启用 checkpointer 后，Graph 会在执行步（super-step）边界持久化状态，不能只检查最终 state：
  - `authoritative` 只放**版本/引用/最小投影**；完整 authority 放**本次运行上下文**（进程内），
    **不进 checkpoint**；
  - 候选/暂存中的必要敏感内容（如 plan 明细）最小化、限制访问、设 TTL；
  - 不承诺"删掉 state 里的 plan 就等于脱敏"。
- TTL/清理：**可配置**，测试环境默认 7 天；**未结束的等待（interrupt）不得被静默清理**；
  到期应**显式失效**并明确"重开会话"，不能无声删除后当作可恢复；
- 不引入复杂平台：单机 SQLite saver + 定时清理任务即可（副本内）。
- **执行方式**：默认在现有工作线程内使用同步 `SqliteSaver` + `graph.invoke`。每次调用在
  该线程内打开 saver、保持到调用结束或 interrupt 已保存，再关闭；下次恢复打开同一目标
  checkpoint 库并使用同一 thread 映射。SQLAlchemy Session/SQLite 连接不跨线程共享。
  若保留 `AsyncSqliteSaver`，必须配对 `ainvoke` 并明确事件循环生命周期，不把 async saver
  塞给同步执行路径；沿用并扩展已有 checkpoint 测试。
- **版本策略**：副本不导入旧 Demo/Phase 1 的试验 checkpoint。记录 graph/state schema 版本；
  不兼容更新前收尾或显式终止等待中的 run，要求用户重开，不默默用新图解释旧游标。

### 6.7 stop / deadline 与 guard

保留 `TurnCancellationRegistry` 事件，每个活跃执行片段使用一个 deadline（§6.5）；commit_guard 与 commit 之间
重读 stop/deadline；写入点前的 `_refuse_if_unwritable` 语义保留。

---

## 7. R0：复制与隔离（详细规范）

### 7.1 先只读解析路径并检查，再创建目标

1. **只读阶段**（不写源任何位置）：
   - 解析源的真实绝对路径；目标尚不存在时，先解析其**已存在父目录**的真实路径，再拼接目标
     目录名，不能直接对不存在的目标调用 `Resolve-Path`；解析并检查 junction/symlink 归属；
   - 断言：目标**不存在**；目标**不是**源本身；两者**互不包含**（非父子、不重叠）；源路径
     在预期位置（默认值一致或用户显式给出）；
   - 记录检查结果（打印即可，此时尚无目标目录可写；如需留存，写入执行会话日志，不写源）。
2. **创建阶段**（检查全部通过后）：创建目标目录与其证据目录
   `<target>/work/langgraph-full-refactor/`；
3. **此后所有产物**——manifest、依赖锁、日志、报告、脚本——**只写目标**（或其证据目录），
   **绝不写回源**。

### 7.2 复制集定义（枚举算法 + 完整排除 + 白名单）

**枚举算法**（在目标证据目录中的脚本实现，只读源）：

1. `git -C <src> ls-files -z -co --exclude-standard`，按 NUL 切分（**必须 `-z`**，避免路径
   空格/中文转义问题）；
2. **去重**（同一路径多次出现只保留一次）；
3. **以当前文件系统为准**：只纳入当前存在的普通文件；tracked 但当前已删除的文件记录删除状态，
   **不从 HEAD 复活**。`git status --porcelain -z` 仅辅助记录状态；若 staged 删除后同名文件
   又作为未跟踪文件出现，应复制当前文件，不能仅凭 `D` 标记将它丢弃；
4. 应用**排除规则**（下表全部，而非只做两条路径正则）；
5. 应用**白名单**：被 `.gitignore` 忽略但功能/证据上必需的资产（下表）；
6. 路径安全：每个条目 resolve 后必须仍在源根内（拒绝 `..` 越界）；**拒绝复制指向源外的
   符号链接/junction**，且不得创建指向源的链接（禁止 junction/symlink 越界）。

**排除（全部显式处理；文件系统复制会下行进入这些目录）**：

| 排除项 | 理由 |
|---|---|
| `backend/.venv/`、任何 `**/node_modules/`、`**/__pycache__/`、`.pytest_cache/` | 依赖与缓存，副本重建 |
| `frontend/.next*`、`frontend/test-results/`、构建产物 | 构建/测试缓存 |
| `data/runtime/`（含活动 `sale_guide.sqlite3` 与 WAL/SHM） | **活动库**，禁止复制/直连 |
| `data/retrieval_index/` | 派生索引，用 `scripts/build_retrieval_index.py` 重建 |
| `work/shopping-agent-research-2026-09-19/` | 嵌套研究仓库（含 9 个 `.git`），不属于本项目 |
| `.codex/`、`.omp/`、`.vscode/`、`.idea/` | 私有/本地配置 |
| 所有 `.env`、`.env.*`、`*.local`（仅保留已确认无密钥的 `.env.example` 等明确模板） | 密钥与本地配置 |
| `checkpoints.db*`、任何 `*.db-wal` / `*.db-shm` | checkpoint 与半写 sidecar |
| 目标证据目录自身、`.git/`（源）、目标 `.git/` | 见 §7.3 比对范围 |

**白名单（被忽略但需纳入，逐项记录理由）**：

| 白名单项 | 理由 | 处理 |
|---|---|---|
| `evals/reports/*.json`、`*.md`（被 `.gitignore` 忽略） | 既有 live eval 证据 | 默认纳入（体量小）；如不纳入需记录 |
| `verification/rag/indexes/final-lexical/`（被忽略，约 3.6M） | `verification/rag/*.json` 证据引用的派生索引 | 默认纳入以保留证据可复现；或明确排除并标注"副本内重建/证据缺失" |
| 其余被忽略项 | — | **不纳入**（venv/node_modules/.env/活动库/缓存） |

> 白名单审查是 R0 的必做动作：先列出所有 `git status --porcelain --ignored` 命中项，逐项
> 判定"派生可重建 / 功能必需 / 绝不可复制"，并把结论写入 R0 报告；不得默默丢弃或默默带出。
> 白名单不得覆盖密钥、运行库等硬排除规则；历史 eval 报告先检查是否夹带认证信息或原始敏感数据。

**复制方式**：按目录/按 manifest 逐项执行（如 `robocopy <src> <dst> /E` 加 `/XD` 排除项），
**禁止 `/MIR`**、禁止"整体复制后再删除"；**不提供整段一键复制命令**，避免误伤源目录。

### 7.3 manifest 生成与比对（size + hash）

**内容比对范围**：仅 §7.2 的**固定复制集**；排除目标自生成内容（目标 `work/langgraph-full-refactor/`
证据、目标 `.git/`、副本安装后产生的配置/venv/node_modules/构建产物/运行库/checkpoint）。

1. **源静止时**生成 `<target>/work/langgraph-full-refactor/source-manifest-before.txt`：
   对每个文件记录**规范化相对路径 + 字节数 + SHA-256**，另记源绝对根路径（不使用 mtime
   作为比较依据）。目标用同一相对路径键比对，不能直接比较不同根目录下的绝对路径字符串。
2. 执行复制（只读源）。
3. **源静止时**按同一规则重新枚举文件集合并生成 `source-manifest-after.txt`；新增/删除文件
   也属于变化，不能只复查 before 已列出的文件。`before == after` 才继续。
4. 在目标生成 `target-manifest.txt`，与 `after` 就同一复制集比对（数量、逐文件 size+hash）。
5. 任一步不一致 → **停止**，重新取快照（不增量补拷），不进入 R1。
6. 源在复制期间发生变化（含只读目录库的 hash 变化，§7.4）→ 视为快照失效，同上停手。

实现说明：清单脚本本身是目标证据目录中的**计划新建产物**（§3.5），不在源中创建任何文件；
不使用"边复制边写源"的做法。比对在依赖安装和副本配置调整之前完成，后续有意改动另记变更。

### 7.4 数据与目录库冻结

- **默认（推荐）**：副本不携带运行库，从 fixtures 初始化——`data/sale_guide.db`（只读目录源）
  随复制带入；运行时库用 `scripts/seed_runtime.py` 在副本内新建到独立路径（如
  `data/runtime-langgraph/sale_guide.sqlite3`），**绝不指向源 `data/runtime/`**。
- **`data/sale_guide.db` 的处理**：它是 **tracked（已跟踪）但 track ≠ 复制时不变**。R0 需：
  1. 核查它当前是否被写入（是否存在 `-wal`/`-shm` 且非空、mtime 是否仍在变化、是否有进程
     打开）；
  2. 记录 size+hash 作为冻结基线；若它仍可能被写（例如源正在跑 seed/导入），则**等待其静止**
     或使用一致性方式（SQLite `.backup` / backup API）导出，而不是直接拷主文件；
  3. 复制后再次 hash 核对一致；不一致则停手重取快照。
- **可选（仅在需要保留真实数据时）**：对源**运行库**做一致性备份（`.backup`，而非直接复制
  `*.db` 忽略 `-wal`/`-shm`），存 `<target>/work/langgraph-full-refactor/source-db-backup/`，
  再导入副本；导入后核对表行数与关键 version 字段。
- 两条分支共同要求：`DATABASE_URL`、`SOURCE_DATABASE_PATH`、`RETRIEVAL_INDEX_DIR` 写成副本内
  绝对路径，并在启动后打印实际生效值核对（§7.8）。

### 7.5 端口 / 缓存 / 命名空间隔离

| 资源 | 源（观测） | 副本建议 | 核验方式 |
|---|---|---|---|
| 后端端口 | 8000 | 8100 或任意空闲端口 | `BACKEND_PORT` 生效值 + 实际监听 |
| 前端端口 | 3000 | 3100 | `FRONTEND_PORT` + dev server 实参 |
| Next 构建缓存 | `.next` | `.next-langgraph`（`SALE_GUIDE_NEXT_DIST_DIR`） | 目录确实分离 |
| 运行库 | `data/runtime/` | `data/runtime-langgraph/` | 路径与内容不来自源 |
| checkpoint | `backend/checkpoints.db` | 副本内独立路径 | 文件位置独立 |
| 检索索引 | `data/retrieval_index` | `data/retrieval_index-langgraph` | 重建后路径核对 |
| 外部写接口 | 源库/源服务 | 一律不连 | 启动日志 + 目标核对 |

### 7.6 依赖锁与安装（防串源）

1. 在源环境只读收集**当前精确版本**（不作为下限使用，也不直接落地 `pip freeze` 的原始输出）；
2. **清洗**：剔除 editable/本地路径条目（本环境确有
   `__editable__impl_sale_guide_backend.pth` / `direct_url.json` → `file:///.../Sale-guide/backend`）、
   任何 `file://` 源路径、任何含 token 的 URL；清洗后的锁存
   `<target>/work/langgraph-full-refactor/requirements-lock.txt`；
3. 副本内**新建 venv**，按清洗后的锁安装，并**以副本自身**安装后端项目（`-e .` 指向副本
   backend，不复制源 venv、不让锁把源项目重新装回来）；
4. 校验（写入 R0 报告）：
   - `python -c "import app; print(app.__file__)"` → 必须落在**副本** backend 内；
   - `python -c "import langgraph, langgraph.checkpoint.sqlite"` 与 `pip check`；
   - 前端按 `package-lock.json` 安装（不复制 `node_modules`）。

### 7.7 git 策略

- 目标初始化**新历史**（`git init` + 首次提交由执行者手动完成，本任务不自动提交）；
- `<target>/work/langgraph-full-refactor/SOURCE-BASELINE.md` 记录：`source_path`、
  现场读取的 `source_branch` / `source_head`（本文观测为 main / f7f4e52，不写死）、
  dirty/untracked 数量、manifest 引用与生成时间；
- 明确不共享 `.git`、不添加 worktree、不 push；源目录保持原路径原状（不重命名、不替换）。

### 7.8 隔离核验清单（逐条执行并记录输出）

- [ ] 目标不存在→已创建；源与目标不重叠、不嵌套；未创建任何指向源的链接/junction；
- [ ] 复制集与排除/白名单结论一致；删除态条目未被复活；manifest 三方比对通过（size+hash）；
- [ ] `data/sale_guide.db` 的冻结/一致性核查记录完整（静止条件或 `.backup` 路径）；
- [ ] 副本启动打印的 `DATABASE_URL` / `SOURCE_DATABASE_PATH` / `RETRIEVAL_INDEX_DIR` 均为副本绝对路径；
- [ ] **连接归属核查**：确认生效 URL 指向副本文件（而非源），核对 SQLAlchemy engine/session
      实际绑定的绝对路径与文件位置（不只是看环境变量字符串）；
- [ ] **写入探针只在目标**：在副本执行一次受控写（如创建会话/seed），然后核查副本文件被写入、
      源库文件未被写入；
- [ ] **源侧核查在源静止时进行**：同时核对源主库文件**与 `-wal`/`-shm`** 的 size/hash（只比
      主文件 mtime 不足以证明未写入）；源仍在活跃（有用户/服务在写）时，**不得把"hash 未变"
      当作唯一判据**，应记录"源活跃、互斥性依赖隔离配置与探针"；
- [ ] 端口/构建缓存/checkpoint/索引路径与源不同（上表逐项）；
- [ ] 未复制任何 `.env`/密钥；副本配置来自 `.env.example` 派生且只存在于副本内；
- [ ] **不擅自停源服务**：任何"停源写"动作必须先与用户协调并记录。

### 7.9 切换条件

- **测试/验证副本**：数据独立、可丢弃，验证失败不影响任何真实数据；
- **正式接管（生产）**：若源存在真实数据或在线用户，切换前必须满足——旧版代码**能读当前
  权威库**（不通过恢复旧快照抹去新数据）、在途请求处理方案（收尾或显式失败，不静默丢弃）、
  跨库/跨版本的数据同步与回滚方案；
  **跨库切换方案未准备就不得上线**；
- 切换只在人工明确启动时执行（默认不启动）；不把测试库直接当生产库。

---

## 8. 阶段计划 R0–R6

阶段串行；每阶段自带输入/范围/产物/验收/失败处理；验收不过不进入下一阶段。**无阶段依赖倒置**
（guard 在 R2 建，因此 R1 不含 guard 验收）。

**R0 复制冻结基线**：见 §7。
输入=源工作树；范围=目标副本与证据目录；产物=manifest/锁/隔离与连接核查记录/真实测试基线清单；
验收=§7.8 全勾选 + §12 失败清单；失败处理=manifest 或路径检查不合格即停手，不进入 R1。

**R1 纯读 Graph 链路**（无写入、无 guard）
输入=R0 副本 + 现有 Graph 骨架。
范围=副本 `graph/graph.py`、`graph/state.py`、`graph/nodes/{context,understand,validate,decide,read_only}.py`；
**允许**在 `backend/app/agent/{loop,service}.py`、`agent/context.py`、`context_resolver.py` 中做
**必要的纯函数抽取**（把请求构造、门控、候选/focus、预算/repair 判定提出来供节点调用），以及
`agent/graph/checkpoint.py` 的最小适配；**不允许**改规则、改 commit 路径、改 HTTP。
产物=只读链路可编译可运行；`decide` 节点真实调用 `goal_router.decide_turn`（删除注入语义）；
`read_only_tools` 有界回边到下一次模型请求；理解走现有 provider 请求 schema/repair/budget/stop。
验收=节点级测试通过（扩展 `backend/tests/agent/graph/`）；同一输入下决策路由/候选/focus 结构与
旧路径一致（离线差分子集）；只读路径**零写入**（断言 DB 无变更）。
失败处理=修节点或补抽取；**不得**回退到"注入决策"或"把 loop 包成单节点"。

**R2 全部 stage / guard / commit 与原子 receipt**
输入=R1 只读链路 + 现有 executor/PlanCommitService。
范围=`graph/nodes/{stage,guard,commit,respond}.py`；`change_plan.py` 的 prepare/commit 拆分；
`plan_commit_service.py` 的**事务归属**调整（§4.3）；§5.3 的同事务业务效果 + receipt/marker；
§5.4 幂等 key 语义；§5.5 崩溃收敛。
产物=commit 成为**唯一业务提交边界**（含澄清 pending 与 HTTP 收尾消息/幂等）；receipt 可重放；
幂等最小 schema 迁移（如需要）与其兼容性记录。
验收=stale/anchor/authorization/stop/deadline 失败零业务权威变更；此阶段先验证 commit 节点/服务
同 key 重试不产生第二次效果，完整 Graph resume 在 R3 验收。必须分别覆盖两个故障点：
①业务 flush 后、receipt 或事务提交前失败 → 全部回滚；②数据库已提交、checkpoint/响应落盘前
崩溃 → 重试只读原 receipt，**不反向回滚成功数据**。两段式顺序提交已消除。
失败处理=原子性或鉴权或重复写未达成 → **硬阻塞**，不得以"人工确认后可切换"降级通过。

**R3 澄清与 resume**
输入=R2 完整写入链路。
范围=§6 全部（resume 顺序、logical run/thread 与 request_id 映射、wait_input 澄清闭环、
session 级并发协调、deadline/预算账本、checkpoint 最小化与 TTL、刷新 authority 节点）。
产物=澄清→提交 pending+receipt→respond→`wait_input` interrupt→恢复（鉴权→读 checkpoint→
refresh_authority→解析补充→决策→guard→commit）的可运行闭环。
验收=恢复不从 START 重跑；不重跑原始 understand；补充信息为独立步骤；`wait_input` 无副作用；
stage 后与 guard 通过后分别中断/崩溃再恢复，均重新刷新权威并执行 guard，拒绝旧 staged 越权写；
同 session 并发受协调且 CAS 兜底；新片段新 deadline、账本延续且封顶；TTL 不静默清理等待中的会话。
失败处理=先修恢复入口与协调机制；不得引入"从头重跑"作为隐藏路径。

**R4 唯一入口集成（SSE / 异步 / stop / 预算）**
输入=R3 闭环。
范围=`GuideWorkflow`/`TurnStreamService`/`api/guide.py` 接入 Graph；SSE 事件与响应 schema 兼容；
stop/deadline 传递；同步 saver 与工作线程的集成。
产物=`/turns` 与 `/turns/stream` 的 taskless / active-task / terminal-task 路径全量走 Graph；
旧 `run_loop` 及 Graph 外的旧入口分派在生产路径不再被调用。
验收=SSE 因果顺序与旧路径一致（离线差分）；前端关键流程兼容；架构守卫证明旧入口调用为 0（§10.2）。
失败处理=修适配层；不允许"临时双路径"兜底。

**R5 差分 / 并发 / 崩溃注入验证**
输入=R4 单入口。
范围=验证脚本放目标 `work/langgraph-full-refactor/`，测试用例放既有 `backend/tests/agent/graph/`
及相应契约测试目录；不改业务规则。
产物=§9 差分报告、并发报告、崩溃注入报告（均存目标证据目录）。
验收=决策路由/业务效果/响应 schema/关键 SSE 因果顺序一致；业务效果次数一致；无重复写入。
失败处理=差异定性并**回到对应阶段修复**（R1 结构差异、R2 事务差异、R3 恢复差异、R4 契约差异）；
不暗示自动 `git` 回滚，由执行者按 §7.7 策略手工处理。

**R6 清理旧编排与交付**
输入=R5 通过 + 引用扫描。
范围=副本内移除 `run_loop` 编排与其专属路径（及其在 `GuideService`/`GuideWorkflow` 的分支）；
迁移旧 loop 专属测试为新验收；**不**删弱 contract 测试。
产物=唯一 Graph 运行路径、迁移后的测试集、交付说明（含回滚方式）。
验收=§10 全部勾选；无隐藏 `run_loop`、无占位 respond、无注入 decision-only、无 fallback 开关。
失败处理=清理导致测试下降 → 停止清理，先迁移测试；不得删除或弱化测试。

---

## 9. 离线差分验证（替代线上 Shadow）

**原则**：同一初始 snapshot + 同一模型原始输出/工具返回，分别在两个隔离测试数据库中运行
旧代码与新代码，**两边各自独立计算**，再比较结果。

**"反自证"的正确表述**：把旧路径的 decision 作为对照的 expected 是**允许的**；禁止的是
（a）把它当作**新版的执行输入**（例如注入 decision 让 Graph 跳过决策），或（b）两边原样回显
同一份输入充当"一致"。因此实现上必须：两侧分别完成自己的决策与执行，再比较字段。

| 维度 | 做法 |
|---|---|
| 初始状态 | 固定 fixtures + 固定 seed；归一化 `created_at`/`updated_at` |
| 模型输出 | 录制/注入**原始 provider 响应**（非解析后的 decision），两侧共用同一份原始输入 |
| 工具返回 | 固定只读工具返回值（检索结果集固定） |
| 时钟 | 冻结时钟/注入 monotonic 源，deadline 与 TTL 可复现 |
| 非确定 ID | 注入固定 id 生成器或归一化（message_id/plan_id/run_id/checkpoint_id） |
| 比较项 | 新算的 decision 路由字段、业务效果（plan/task/version/pending/cart 的最终值与**变更次数**）、响应 schema、**关键 SSE 因果顺序**、幂等记录终态 |
| **不比较** | `db.commit()` 次数（事务合并后旧≥2 次、新 1 次，属预期差异，不能被当成回归）；Graph trace 与旧 loop 的逐节点一致 |

**provider 分层验证**：

| 层次 | 内容 | 是否需外网 |
|---|---|---|
| L1 scripted provider | 覆盖 Graph 内的请求构造/协议 repair/预算/stop 分支（脚本化响应） | 否 |
| L2 真实 provider 类 + mock transport | 用真实 provider 实现与 mock HTTP transport，验证 **schema 校验、流式解析、错误映射** | 否 |
| L3 真实模型 smoke | 小规模真实端点调用（可选） | 是；密钥/网络不可用时**列为未执行**，不得当作通过 |

L1/L2 是必做；L3 可选且**不默认外发业务数据**。

**请求量**：按**风险与路线覆盖**确定（chat / 只读 / 澄清 / 计划生成 / 修改 / 停止 / 超时 /
冲突拒绝），同时覆盖无 task、活跃 task、终态 task 三种上下文，不强搬原计划的 10000 turn
或时间窗口。旧路径重现出已确认缺陷时，不要求新路径复制缺陷：登记为批准的预期差异，
增加独立契约断言；未经判定的差异不得直接忽略。

---

## 10. 验收标准（默认全部未勾选）

### 10.1 复制、隔离与基线

- [ ] 目标为源同级隔离副本；路径检查先于创建；源未被写入任何文件（含 manifest/日志）；
- [ ] 复制集固定、去重、剔除删除态条目未复活；排除与白名单结论完整；
- [ ] manifest（size+hash）三方比对通过；比对范围排除目标自生成内容；
- [ ] `data/sale_guide.db` 的冻结/一致性核查记录完整；
- [ ] 业务库、checkpoint、端口、缓存命名空间、外部写接口已隔离；生效 URL 与连接归属已核实；
      写入探针仅在目标；源侧核查在源静止时进行，且未擅自停源服务；
- [ ] 依赖锁已清洗（无 editable/`file://` 源路径/token URL）；副本从副本安装；
      `import app` 指向副本；按当前精确版本锁定；
- [ ] 真实测试基线清单已生成，关键路径失败列为阻塞。

### 10.2 架构守卫（证明"彻底"）

- [ ] 生产代码静态引用扫描：旧 `run_loop` 编排入口引用为 0；
- [ ] 动态证明：运行期调用计数或测试证明旧入口被调用 0 次；
- [ ] 无未连接/悬空节点；无占位 `respond`；无注入 decision-only；无隐藏 `run_loop`；
- [ ] `read_only_tools` 回边有界，未把整圈循环藏进单节点；
- [ ] 不存在永久双引擎、失败自动 fallback 或默认回旧路径的开关；
- [ ] 领域规则/业务服务/数据库/HTTP/SSE/前端未被重写，纯规则唯一来源保持。

### 10.3 写边界、guard 与原子性

- [ ] Guide 业务权威写入**只由 commit 节点触发**；其他节点零业务写入；
- [ ] 业务效果与持久化 receipt/marker 在**同一事务**提交；响应 id/sequence 在事务内确定，
      `respond` 只发布已固定 receipt；
- [ ] 预写 reservation 仅作协调记录，未被当作成功依据；trace/checkpoint 使用独立 session；
- [ ] commit_guard 权威重读并校验 owner/version/anchor/authorization/stop/deadline；
- [ ] 同 `(owner,session,request_id)` 不同 `request_digest` 被拒绝；commit key 稳定且区分
      clarify pending 与后续 mutation；
- [ ] 崩溃后重试只读取同一 receipt；协调记录僵死有明确收敛责任；
- [ ] 未使用内存 dedupe 作为幂等依据；未声称 checkpoint 自动 exactly-once；未保留两段式
      顺序提交作为最终方案。

### 10.4 恢复与并发

- [ ] 先鉴权和校验 digest；已完成 HTTP 请求直接返回原 receipt；其余真正恢复按
      活跃 run 校验 → 读 checkpoint → refresh_authority → 解析补充/恢复 staged → 决策或 guard → commit；
- [ ] 澄清闭环：先提交 pending+receipt → respond → `wait_input` interrupt；
- [ ] 澄清补充产生新 `request_id` 但解析到同一 graph thread；客户端不能自选 thread；
- [ ] 不重跑原始 understand；`wait_input` 无副作用；重复 HTTP 重放不推进 graph；
- [ ] 同 session 并发有 session 级协调 + 真实 CAS 兜底（不依赖唯一约束宣称串行）；
- [ ] 新执行片段新 deadline；预算/repair/读轮账本延续且封顶；
- [ ] checkpoint 最小化：`authoritative` 仅版本/引用/最小投影，完整 authority 不入 checkpoint；
      staged 敏感内容最小化 + 访问控制 + TTL；TTL 可配置（测试默认 7 天）；未结束等待不被静默清理。
- [ ] saver 生命周期与同步/异步执行方式匹配；旧试验 checkpoint 不导入，不兼容版本的在途 run
      显式收尾/失效；stage 后和 guard 后恢复均通过重新校验测试。

### 10.5 差分与测试

- [ ] 离线差分覆盖 decision 路由、业务效果与变更次数、响应 schema、关键 SSE 因果顺序；
- [ ] 两侧各自独立计算（旧 decision 未被当作新版输入，也未原样回显冒充一致）；
- [ ] 未把 `db.commit()` 次数当回归判据；未要求结构 trace 与旧 loop 逐节点一致；
- [ ] L1 scripted + L2 真实 provider 类/mock transport 通过；L3 未执行则如实标注；
- [ ] 定向测试覆盖 Graph、contract、resume、guard、commit、并发、Compatibility（HTTP/SSE）；
- [ ] 新增 Graph 测试位于 `backend/tests/agent/graph/`（未新建重复目录）；
- [ ] 未把未运行的验证写成通过。

### 10.6 交付与回滚

- [ ] 切换只在人工明确启动时发生；先验证副本，旧版保持原路径不重命名替换；
- [ ] 回滚区分两种情形：**测试验证副本**（数据独立可丢）；**正式接管后**（旧代码必须能读
      当前权威库，不恢复旧快照抹去新数据，跨库方案已准备）；
- [ ] 文档、manifest、差分报告、失败清单可逐项核对；
- [ ] **硬阻塞项**（数据原子性、鉴权、重复写、关键契约兼容）无未解决项；仅**明确无关**的
      基线测试失败可作为例外，且需记录接受人与理由。

---

## 11. 测试与命令

统一约定：先 `Set-Location` 到目标仓库对应子目录，再用该目录下的相对路径调用**该目录的**
解释器/包管理器；或使用"绝对 Python + 绝对测试路径"。不使用裸 `pytest`/`python` 混环境。

```powershell
# 后端（在副本 backend 内）
Set-Location "C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph/backend"
& ".\.venv\Scripts\python.exe" -m pytest tests/agent/graph -q          # Graph 适配器（已存在，扩展此目录）
& ".\.venv\Scripts\python.exe" -m pytest tests -q                      # 后端全量（R0 生成失败清单）
& ".\.venv\Scripts\python.exe" -m pytest tests/test_p1_planner_decision_layer.py tests/test_p1_planner_independent.py tests/test_goal_understanding.py tests/test_decision_policy.py tests/test_semantic_shared_contracts.py -q   # contract 定向
& ".\.venv\Scripts\python.exe" -m pytest tests/test_review_stream_contract.py tests/test_events_trace.py -q   # HTTP/SSE（已有，待扩展）
& ".\.venv\Scripts\python.exe" -m pytest tests/test_semantic_only_architecture.py -q   # 架构守卫（待扩展 Graph 守卫）

# 前端（在副本 frontend 内）
Set-Location "C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph/frontend"
npm test -- --run
npx playwright test e2e/purchase-task.spec.ts e2e/category-selection.spec.ts

# 离线端到端（用副本 Python，脚本位于副本 scripts/）
Set-Location "C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph"
& ".\backend\.venv\Scripts\python.exe" ".\scripts\verify_shopping_workflow_offline.py"
```

绝对路径等价写法（不依赖 cwd）：把 `& ".\.venv\Scripts\python.exe" -m pytest tests/...` 换成
`& "C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph/backend/.venv/Scripts/python.exe" -m pytest "C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph/backend/tests/..."`；
注意 pytest 的 rootdir/conftest 解析依赖工作目录，**优先用 `Set-Location` 版本**。

| 目标 | 命令/位置 | 现状 |
|---|---|---|
| Graph 适配器与新增 Graph 用例 | `backend/tests/agent/graph/` | 已有目录，**扩展**（不新建重复目录） |
| 后端全量 | `tests/` | 基线未知，R0 生成失败清单 |
| contract 定向 | `test_p1_planner_decision_layer.py`、`test_p1_planner_independent.py`、`test_goal_understanding.py`、`test_decision_policy.py`、`test_semantic_shared_contracts.py` | 已存在 |
| HTTP/SSE | `test_review_stream_contract.py`、`test_events_trace.py` | 已存在，待扩展 Graph 场景 |
| 前端单测 / e2e | `frontend/tests/*`、`frontend/e2e/*.spec.ts` | 已有；需浏览器与本地端口 |
| 离线端到端 | `scripts/verify_shopping_workflow_offline.py` | 已存在（临时库 + 空闲端口） |
| 隔离校验 | `make verify-isolated`（需先设副本 `DATABASE_URL`） | 已存在 |
| 离线差分 / 旧入口计数 / manifest | `<target>/work/langgraph-full-refactor/{diff_runner,legacy_call_counter,manifest}.py` | **计划新建** |

---

## 12. 基线与失败处理规则

1. R0 实际运行一次后端测试并保存失败清单（`-q --tb=no` 汇总 + 关键用例详情）。
2. **基线已红不等于与本任务无关**：逐条给出失败原因分类。
3. 关键路径（guide 入口、幂等、版本/anchor、plan 提交、SSE 契约、Graph 适配器、contract）
   上的失败**阻塞**阶段推进。
4. 例外只允许用于**明确无关**的失败：必须列出、记录接受人与理由，并在最终报告如实报告。
5. 不得把失败统一归因为"旧问题"；不得用历史报告替代本轮实测。

---

## 13. 风险与未决

| # | 风险 / 未决 | 影响 | 处理方向 |
|---|---|---|---|
| 1 | `apply_result` 内部提交需改为事务协调（§4.3） | 改动触达业务写入服务 | R2 仅改提交时机，规则与顺序不变，用回滚注入测试证明 |
| 2 | `response_json` 可能不足以承载恢复信息 | 原子性目标无法实现 | 允许最小兼容 schema 迁移并记录（§5.3 第 5 条） |
| 3 | 协调记录僵死收敛责任未核实（§2.3） | 请求永久 409 / 重试语义不明 | R2 前核实并落地；不足则阻塞 |
| 4 | Graph 在工作线程内运行 | 异步 saver 需自建事件循环 | 默认同步 `SqliteSaver`（§6.6/§3.1） |
| 5 | checkpoint 每节点持久化，暂存含敏感内容 | 隐私与体量 | 最小投影 + 访问控制 + TTL + 到期显式失效 |
| 6 | `run_loop` 是否存在未发现的隐式写入 | 写边界清单不完整 | R1 前逐分支确认 |
| 7 | 基线测试红绿未知 | 阶段验收基线不可靠 | R0 生成真实失败清单 |
| 8 | 前端 e2e / 真实模型端点可用性 | 兼容性与 smoke 可能无法执行 | 未执行则如实标注 |
| 9 | 源活跃写入与快照一致性 | manifest 冻结失效 | §7.4 静止/一致性备份；不擅自停源 |
| 10 | 共享工作区其他贡献者改动 | 冲突或误回退 | 只写副本与本任务文档；不覆盖他人改动 |

---

## 14. 执行交接提示（可直接交给 agent）

- **第一步（只读，不写源）**：解析源与目标的真实绝对路径，断言目标不存在、两者不重叠；
  打印/记录检查结果。
- **第二步**：创建目标目录与 `<target>/work/langgraph-full-refactor/`；此后的 manifest、锁、
  日志、脚本、报告**只写目标**。
- **第三步**：按 §7.2 枚举复制集 → 生成 source-before → 复制 → 重新枚举并生成 source-after
  → 生成 target manifest → 三方比对；不一致即停手（不进入 R1）。
- **工作目录**：所有执行动作在副本
  `C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide-langgraph` 内进行，证据放
  `work/langgraph-full-refactor/`。
- **禁止**：修改/移动/重命名源目录任何文件（包括不在源写 manifest/日志）；不使用 `/MIR`；
  不删除源；不自动 `git commit`/`push`；不连源数据库；不复制 `.env`/密钥/venv/node_modules/
  活动库；不创建指向源的链接/junction；不递归委派；不把 demo 的 `langgraph_compat.py` 带入
  生产路径。
- **验收范围**：先完成 R0 的 §7.8 核验与 §12 基线清单，再进入 R1；每阶段按 §8 逐条核对，
  未运行的一律不勾选；硬阻塞项不得以人工豁免通过。
- **分工**：按仓库 Codex/Pi 约定执行——原地实现与定向测试由执行者完成，最终结论由 Codex 做
  定向验收；不展开多 agent 流水线，不新增脚手架。

执行授权只覆盖“按本文在副本实现并验收”时，完成 R6 即交付，不自动接管真实用户流量。
本文件的撰写本身不代表 R0 已执行，也不代表源目录已被实际冻结。

---

## 变更记录

- 2026-09-22：创建"同级隔离副本 + 副本内全量 LangGraph 切换"任务文档。
- 2026-09-22（修订）：按审阅意见修正——
  1) §1 纠正对原计划的描述（Phase 2 优先复用 LLM 输出、72h 为待定建议且已被 volume-based
     取代、唯一 commit 节点是目标不变量）；保留业务权威写只由 commit 触发的硬约束，并明确
     事务/基础设施写分类与 `apply_result` 事务归属的最小调整；§2 把"唯一需替换函数"改为
     "核心编排循环及各入口分派"；数值型条目统一标注为观测值；
  2) §7 重写 R0：先只读路径检查再创建目标；所有产物只写目标；删除写回源的 PowerShell 示例，
     给出枚举/去重/删除态/排除/白名单/越界防护/`-z` 算法与 size+hash 三方比对（排除目标自生成
     内容）；目录库冻结与一致性核查；依赖锁防串源（editable 指向源）；隔离核验含连接归属与
     目标侧写入探针；
  3) §5.3 给出可执行的同事务原子性方案（业务效果 + receipt/marker、事务内确定响应标识、
     `respond` 只发布、独立 session 跑 trace/checkpoint、允许最小幂等 schema 迁移、禁止把
     两段式顺序提交作为最终方案）；删除"人工确认后可切换"与宽泛验收逃逸；
  4) §3.1/§3.3 补齐 answer 路径、有界读循环回边、澄清先提交再 respond 后 `wait_input`
     interrupt；§6 恢复顺序改为鉴权→读 checkpoint→刷新 authority→解析补充→决策→guard→commit，
     并补 logical run/thread 与 `request_id` 映射、session 级并发协调、deadline/预算账本、
     每节点 checkpoint 最小化与 TTL；
  5) §7.6/§11 修正安装与命令环境；新增 Graph 测试扩展既有目录；§8 阶段重排为 R1 纯读、
     R2 写边界与原子 receipt、R3 澄清与 resume、R4 集成、R5 验证、R6 清理，并更新交叉引用；
  6) §9 修正反自证表述与 provider 分层，明确不比较 `db.commit()` 次数；§10 明确硬阻塞；
  7) 符号纠正：`load_authoritative` 位于 `app/agent/graph/nodes/context.py`；`parse_understanding`
     归属 `app.agent.goal` 并由 `parse_proposal` 调用。

（本次修订仅添加/调整本文件内容；原有条目中的事实性证据（文件:行）保留。）
