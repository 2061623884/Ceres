# Sale-guide P1 实施计划：用户意图理解、Goal 建模与导购路由

- 日期：2026-09-19
- 状态：**P1 第一切片（理解层纯函数）已实施**；`protocol`/`loop` 接入**未实施**，见 §7 顺序。
- 上游依据：[产品方案审阅稿](2026-09-19-purchase-intent-product-plan.md)（§11 P1/P1.5 分期仍待审）、[P0 实施契约](2026-09-19-purchase-intent-p0-implementation.md)。
- 裁决来源：用户要求把原 P1“完整需求层、聚合与感知比较”降为 **P1.5 采购规划增强**，把 P1 正式重构为“用户意图理解、Goal 建模与导购路由”。
- 范围：理解层的**纯函数切片**与测试。不调用 LLM、不接入现有 loop、不产生采购或写入副作用、不改数据库模型、不改确认/加购不变量。

## 1. 为什么先做理解层

P0 已让“缺主料也能给出可确认的 partial 方案”成立，但“用户到底在要什么”仍隐式散落在 prompt 与 proposal 里。目标没建模清楚时，需求项聚合、包装换算、购物车分配越精细，只会把错误目标执行得越快。因此：

- 先有**受约束的 Goal**（模型只能提出理解结果）与**纯函数路由**（服务端决定下一步）；
- 再有 P1.5 的 RequiredItem / 聚合 / 分配。

本切片故意不接协议与 loop：先把“输入 → 结构化 Goal → route/readiness/fulfillment_mode/missing_slots”做成可离线验证、无副作用的一层，接入时才有稳定契约可依赖。

## 2. 本切片范围

**做**
- `backend/app/schemas/goal.py`：受约束的 `Goal` / `GoalConstraints` / `RouteDecision` / `IntentState` 模型与 `GoalKind` / `FulfillmentMode` / `Readiness` / `GoalRoute` 枚举，以及规范化函数。
- `backend/app/agent/goal.py`：`parse_goal`（把受约束的原始结构规范化为 `Goal`）、`parse_intent_state` 与 `GoalParseError`。
- `backend/app/agent/goal_router.py`：`route_goal` 纯函数，产出 `readiness` / `fulfillment_mode` / `route` / `missing_slots`。
- `backend/tests/test_goal_understanding.py`：离线单测。
- 产品方案文档 §11/§12/§13 的 P1/P1.5 分期更正。
- 本文档。

**不做（保持 P0 与现有 loop 不变）**
- 不改 `agent/protocol.py`、`agent/loop.py`、prompt、`agent/state.py`、`schemas/guide.py`。
- 不新增数据库表/列，不改 `guide_tasks.plan_json` 形态。
- 不调用 LLM / 不联网 / 不读环境变量。
- 不实现 RequiredItem / 聚合 / 单位归一 / pantry 扣减 / 购物车分配 / 批量召回（这些属 P1.5）。
- 不做语义质量验收（真实 LLM + 检索 + SSE）。

## 3. 概念模型

### 3.1 受约束的 Goal

`Goal` 只包含“模型可以提出的理解结果”：`kind`、`fulfillment_mode`、`description`、`target_name`、`category_id`/`category_name`、`items`、`constraints`、`notes`、`assumptions`。`IntentState` 将这个 Goal 与服务端计算出的 `RouteDecision` 组成一次理解层快照；它不是 PurchasePlan，也不包含授权。

受约束体现在两点：

1. **模型不能自定权威字段**：`route`/`readiness`/`missing_slots` 不在 Goal 上（由路由函数产出）；`plan_id`/`plan_version`/`price*`/`stock`/`available_qty`/`sku_id`/`confirmed` 等出现在原始结构里会直接报 `FORBIDDEN_FIELD`，而不是被静默丢弃。
2. **未知键是错误**：Goal 与 constraints 都 `extra="forbid"`，未知键报 `MALFORMED_GOAL`，避免“模型说了一个我们不认识的东西”和“模型什么都没说”看起来一样。

`constraints.budget_yuan` 是唯一允许模型带的钱字段，单位为元（与现有 `agent/protocol.py` 的 `budget_yuan` 一致）；本层不做任何金额运算，转 fen 仍由协议适配层负责。系统默认值只能进 `assumptions`，不得写进 `constraints.people`（与方案 §5.1 “显式假设必须可与用户事实区分”一致）。

### 3.2 枚举与规范化

| 枚举 | 取值 | 说明 |
|---|---|---|
| `GoalKind` | `meal_decision` / `meal_plan` / `product_purchase` / `category_purchase` / `replenishment` / `information_only` / `unsupported` | `meal_decision` 是“目标未定”，不是“缺菜名的 meal_plan” |
| `FulfillmentMode` | `self_cook` / `ready_made` / `mixed` / `unspecified` / `none` | `unspecified` 是真实答案（用户没说），不得当成 `self_cook`；`none` 表示不是餐食履约问题 |
| `Readiness` | `ready` / `needs_clarification` / `information` / `unsupported` | 只有 `ready` + 空 `missing_slots` 才允许准备方案 |
| `GoalRoute` | `clarify_goal` / `answer_information` / `prepare_meal_plan` / `prepare_product_purchase` / `prepare_category_purchase` / `prepare_replenishment` / `refuse_unsupported` | 服务端下一步动作；模型不可自定 |

规范化函数 `normalize_goal_kind` / `normalize_fulfillment_mode` / `normalize_readiness` / `normalize_route` / `normalize_meal_time` 把无法识别的值收敛到保守默认（`unsupported` / `unspecified` / `needs_clarification` / `clarify_goal` / `None`），保证“不认识”永远不会驱动采购路径。

### 3.3 RouteDecision

`route_goal(goal)` 返回结构化 `RouteDecision`：`kind`、`readiness`、`fulfillment_mode`、`route`、`missing_slots`、`reason`。`parse_intent_state()` 再把 Goal 与 RouteDecision 组合为运行时交接对象。`reason` 只是诊断文案，不是事实来源；调用方应基于 `route` 与 `missing_slots` 分支。

## 4. 路由规则

| 输入 | readiness | fulfillment_mode | route | missing_slots |
|---|---|---|---|---|
| `unsupported` | `unsupported` | `none` | `refuse_unsupported` | — |
| `information_only` | `information` | `none` | `answer_information` | — |
| `meal_decision`（不知道吃什么） | `needs_clarification` | 原样（缺省 `unspecified`） | `clarify_goal` | `meal_target` |
| `meal_plan` 且 `fulfillment_mode=unspecified` | `needs_clarification` | `unspecified` | `clarify_goal` | `fulfillment_mode` |
| `meal_plan`（自做/成品/混合）且无目标名与 items | `needs_clarification` | 原样 | `clarify_goal` | `meal_target` |
| `meal_plan` 且目标明确 | `ready` | 原样 | `prepare_meal_plan` | — |
| `product_purchase` 且无商品 | `needs_clarification` | `none` | `clarify_goal` | `items` |
| `product_purchase` 且有商品 | `ready` | `none` | `prepare_product_purchase` | — |
| `category_purchase` 且无类目 | `needs_clarification` | `none` | `clarify_goal` | `category` |
| `category_purchase` 且有类目 | `ready` | `none` | `prepare_category_purchase` | — |
| `replenishment` 且无对象 | `needs_clarification` | `none` | `clarify_goal` | `items` |
| `replenishment` 且有对象 | `ready` | `none` | `prepare_replenishment` | — |

设计取舍：

- `meal_decision` 一律 `clarify_goal`，即使等价于 A 类“帮我选”授权也不直接准备清单（D15 待审，现为保守行为）。
- `meal_plan` 的成品/自做歧义不默认自做，与 D1 一致（D13 待审）。
- 非餐食路由的 `fulfillment_mode` 固定为 `none`；用户已声明的 `people` 等约束不构成 `missing_slots`（人数缺省由后续计划层以 `assumptions` 处理，不在理解层编造）。

## 5. 代码落点与纯度保证

| 文件 | 内容 | 依赖 |
|---|---|---|
| `backend/app/schemas/goal.py` | 枚举、`Goal`/`GoalConstraints`/`RouteDecision`/`IntentState`、规范化函数 | 仅 `pydantic` |
| `backend/app/agent/goal.py` | `parse_goal`、`parse_intent_state`、`GoalParseError` | `pydantic` + `schemas.goal` |
| `backend/app/agent/goal_router.py` | `route_goal` 纯函数、槽位常量 | 仅 `schemas.goal` |

已验证：导入这三个模块不会加载 `sqlalchemy` / `app.models` / `app.services` / `app.llm` / `fastapi`（见 §6 记录）。函数不读写文件、不发网络请求、不读环境变量、不修改输入对象。

## 6. 离线验收（已实施）

命令：

```
cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_goal_understanding.py -q
```

结果：**20 passed，exit 0**（Python 3.12.10，pydantic 2.13.5）。用例覆盖：

- 不知道吃什么 → `meal_decision` + `clarify_goal` + `missing_slots=[meal_target]`；
- 清淡约束 → `constraints.dietary` 原样保留，并随明确目标进入 `ready`；
- 早餐类目采购 → `category_purchase` + `prepare_category_purchase` + `meal_time=breakfast`；缺类目时先澄清；
- 三个人火锅 → `meal_plan`/`self_cook`/`people=3` + `ready` + `prepare_meal_plan`；
- 明确做菜 → `ready` + `self_cook` + `prepare_meal_plan`；
- 明确买商品 → `product_purchase` + `prepare_product_purchase`；缺商品时先澄清；
- 只读提问 → `information` + `answer_information`；
- 无法支持 → `unsupported` + `refuse_unsupported`；
- 成品/自做未说明 → `missing_slots=[fulfillment_mode]`；
- 补货 → `prepare_replenishment`；
- 未知枚举值保守规范化；服务端字段与未知键被拒绝；约束形状错误被拒绝；`parse_goal` 幂等且路由纯函数；`IntentState` 能组合 Goal 与服务端路由。

> 该结果只证明**离线纯函数切片**；不代表真实 LLM 的语义理解质量，也不代表已接入对话链路。

## 7. 后续接入顺序（未实施）

按“契约消费者先适配、再启用”的顺序，逐步接入，避免未适配的消费者收到新字段：

1. **协议暴露（只读）**：在 `agent/protocol.py` 的 proposal 中新增可选 `goal` 字段（JSON Schema + 严格解析），模型只能提 `Goal`；`route`/`readiness` 仍由服务端纯函数产出。此步不改任何写路径。
2. **loop 只读阶段调用路由**：`agent/loop.py` 在理解阶段后调用 `parse_goal` + `route_goal`，把 `RouteDecision` 作为本轮的执行计划输入；`clarify_goal` 必须复用现有澄清/候选机制，不得新建并行状态机。
3. **responses/SSE 回显**：`agent/responses.py` 与 SSE 载荷透出结构化 `goal_kind`/`route`/`missing_slots`（字段命名先评审），前端据此渲染；不改确认/加购。
4. **持久化演进（评审后）**：若确需跨轮保存 Goal，优先做 `Requirements` 字段映射（D14），不新建权威数组。
5. **P1.5 再启动**：只有以上契约稳定并被消费后，才接 RequiredItem / 聚合 / 购物车分配。

每一步的启用门槛：该步的消费者已适配 + 定向离线测试通过 + 不改变 P0 的 `can_confirm`/确认/幂等不变量。

## 8. 与 P0、P1.5 的边界

- **P0（已实施）**：partial 方案、`gaps` 唯一权威、确认/加购不变量。本切片不触碰。
- **P1（本切片）**：Goal 建模 + 路由决策，纯函数、无副作用。
- **P1.5（未实施）**：RequiredItem 需求项、跨目标聚合与单位归一、pantry 量化扣减、购物车占用的需求分配、`RequirementsProposal`、批量召回。它们依赖 P1 的路由稳定，故排在其后。

## 9. 待决策（与产品方案 §13 对齐）

- **D12 路由归属**：模型只提 Goal，`route`/`readiness`/`missing_slots` 由服务端纯函数决定（当前实现）。是否确认？
- **D13 成品/自做歧义**：`meal_plan` 未说明时一律先澄清（当前实现），与 D1 保持一致。是否确认？
- **D14 Goal 与 `Requirements` 关系**：Goal 作为解析层对象、接入时映射到 `Requirements`，而非并行状态机。是否确认？
- **D15 `meal_decision` 授权级别**：`meal_decision` 只授权只读给选项/澄清，不自动准备清单。是否确认？
- **协议字段命名与回显位置**：`goal` 字段名、`route`/`missing_slots` 在 `TurnResponse`/SSE 中的落点。接入第 1、3 步前需定。

## 10. 未验证 / 限制

- **真实自然语言 → Goal 的 LLM 适配尚未实现**：本切片从受约束的 Goal-shaped proposal 开始；真实 LLM + 检索 + SSE 的语义验收未做。
- **未接入现有 loop/protocol**：`parse_goal`/`route_goal` 目前无运行链路消费者（这正是“无副作用切片”的预期状态）。
- **未做 UI/前端改动**。
- 本文件与产品方案中 P1/P1.5 分期仍属**待审**内容；用户裁决改变分期命名，但具体字段与默认行为仍以 §9 决策与后续评审为准。
