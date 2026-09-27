# Sale-guide P1 理解-决策-执行最小契约（精简审阅稿）

- 日期：2026-09-20；版本：吸收评审意见后的精简稿。
- 状态：**R1–R5 主链路已实施；离线定向 260 项通过，L2 live 1/5 通过、验收未通过，尚不能标记全方案完成**。最终实现、实际测试与限制见
  [交付记录](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/docs/plans/2026-09-20-p1-planner-decision-layer-delivery.md)。下文保留原设计契约；实施前源码事实见 §11，当前验证边界见 §12。
- 上游依据：[P1 实施计划](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/docs/plans/2026-09-19-purchase-intent-p1-implementation.md)、[产品方案](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/docs/plans/2026-09-19-purchase-intent-product-plan.md)、[P0 实施契约](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/docs/plans/2026-09-19-purchase-intent-p0-implementation.md)。
- 引用基准（源目录根）：Sale-guide `C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/`（图中 `S/`）；本地 NVIDIA 参考副本 `C:/Users/20616/Desktop/Agent/Agent产品/reference/retail-shopping-assistant/chain_server/src/`（图中 `REF/`）。代码引用统一用**完整绝对路径 Markdown 链接**；行号以写作时为准，核对以符号名为主。

---

## 1. 一页结论

1. **权威状态在服务端。** 计划、版本、确认、购物车、真实候选都由服务端持有；模型只输出**语义变更提议**，不重新声明 `current_goal`、版本、价格或库存。
2. **Gate 不重理解自然语言。** 它不调用模型、不用关键词/正则猜语义，只对结构化字段做确定性校验：引用是否有效、操作是否合法、能力是否支持、版本是否新鲜。理解与动作同时错仍可能通过，所以 **Gate 不能保证模型理解正确，真实模型 eval 不可省略**。
3. **状态三分。** 已生效采购草稿（`task.plan_json`）/ 讨论中的候选目标（会话内，未生效）/ 当前待答问题（pending）。候选不写入权威计划，激活时才映射为草稿。
4. **字段更新三分。** 省略 = 保持不变；`set` = 覆盖；`clear` = 显式撤销。**不用 `null` 一义多用**。修改用服务端给出的 `ref` 定位目标，模型不复述整棵目标树。
5. **关系与言语行为正交。** `goal_relation ∈ {new, append, switch, amend}` 与 `speech_act` 是两个维度：一次纠错既可以 `switch` 换目标，也可以 `amend` 改同目标。
6. **高层目标与明确商品动作并存。** "自煮 3 人火锅"交给业务服务做配方展开/计算/商品匹配；"可乐再加 4 瓶"允许产出**受限的商品 ref + 数量增量**，不一律禁低层动作。但价格、库存、配方数量、包装换算只能由业务服务推导。
7. **不做大一统 workflow。** 只在既有节点内分配契约与纯函数（§2 主图、§4 表），不新增层、脚本、第二套 router。
8. **切换是"新目标独立构建成功才激活"。** 候选澄清未完成不触碰旧计划；构建失败旧状态继续有效；旧行/未购数量/contributions/gaps 不迁入；真实购物车与确认历史不动，旧确认不能作用于新计划。
9. **验收两层。** 脚本化 loop 测**执行契约**；真实模型 eval 测**语义识别**，沿用现有 live 入口补齐用例，未跑就不得宣称语义验收。

---

## 2. 架构边界：当前链路与目标增量（一个主图）

```text
当前（已存在，见 §11 依据）
  guide API → GuideWorkflow（请求幂等 / 版本 / 消息 / 快照壳）
    → GuideService → run_loop（模型调用 ↔ 只读工具，模型调用硬上限 3 次）
        → proposal: reply/lookups/queries/mutations/uncertainties
    → _execute_proposal → PlanChangeExecutor → 业务服务
    确认服务 = 唯一 计划→购物车 闸门（校验 plan/cart 版本 + 幂等）

目标增量（只在既有节点内加契约，不新增层）
  proposal.understanding（模型：引用目标 + 新目标或字段变更提议）
    │  服务端纯函数：goal.py 计算候选状态 + goal_router.py 决策
    ▼
  DecisionGate(decide_turn): route / readiness / missing_slots / write_blocked
    │  loop 内拒绝违规 mutations；输出决策及合法对话状态变更，不落库
    ▼
  _execute_proposal 保存合法对话状态；按 route 分派（仅回答 / 澄清 / 执行）
    │  沿用既有提交边界：版本 + 停止 + 超时 + 陈旧提交检查
    ▼
  PlanChangeExecutor → 业务服务（配方展开 / 商品匹配 / 计划构建）
```

**边界不变量（设计；不改动现有不变量）**

- 模型与只读工具在 `run_loop` 内；**真正写计划仍在 `_execute_proposal` 的外层执行边界**。
- Gate 是**同一套纯逻辑**，不是第二套"脑"：loop 内决定下一步，外层执行前复核状态/版本。状态变更只提交一次，不能在两处重复应用数量增量。
- 对话状态持久化**复用会话 / pending**，不新增 Goal 表，也不每轮重建任务。
- 确认服务继续独立校验任务 / plan / cart 版本与幂等；`write_blocked=false` 只表示允许草稿操作，不等于确认授权。
- 不新增固定规划模型调用、额外 Agent、微服务。

---

## 3. 概念分层与归属（设计）

| 概念 | 含义 | 归属 |
|---|---|---|
| `speech_act` | 这句话在做什么：问事实 / 请求动作 / 纠错 / 回答澄清 / 闲聊 / 停止 | 模型识别 |
| `goal` | 持续讨论的需求：决定吃什么 / 做一餐 / 买商品等；只读查询是本轮行为，不覆盖主目标 | 模型提出，服务端维护 |
| `fulfillment_mode` | 自做 / 成品 / 混合 / 未说明 / 非餐食 | 模型识别，服务端判 `unspecified` |
| `goal_relation` | 新目标 / 追加 / 替换 / 修正 / 未定 | 模型结合上下文识别，服务端校验 |
| `focus_ref` | 指向服务端提供的草稿目标 / 候选目标 / 商品行 / 待答问题 | 模型选择引用，服务端校验有效性 |
| 权威状态 | 已生效草稿、候选目标、pending、版本 | **纯服务端** |

现状：`Goal`/`IntentState`/`route_goal`/`parse_goal` 已存在，但**运行链路未消费**，`TurnResponse` 也未回显 route/readiness（§11）。历史事故"用户说火锅、结果改了旧菜人数"正说明缺的是"本轮语义 → 允许做什么"的显式判断，而不是又一层模型。

---

## 4. 模块职责与接入文件（设计；按责任划分，不按步骤拆文件）

| 模块 | 核心职责 | 改动 |
|---|---|---|
| [schemas/goal.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/schemas/goal.py) | 语义契约：行为、目标关系、焦点引用、受限字段更新，保留禁写清单 | 扩展 |
| [agent/goal.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/goal.py) | 状态更新纯逻辑：把提议 merge 进候选目标（省略 / set / clear） | 扩展 |
| [agent/goal_router.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/goal_router.py) | 决策纯逻辑：`decide_turn` 组合已有 `route_goal`，就绪规则只维护一份 | 新增函数 |
| [agent/protocol.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/protocol.py) | proposal 外层解析调用语义契约；不重复定义 Goal 词表或业务规则 | 扩展 |
| [agent/context.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/context.py) | 适配：候选目标 / 焦点 ref 进快照，扩展既有 pending 载荷 | 扩展 |
| [agent/loop.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/loop.py) | 适配：读取理解/决策结果，继续只读工具循环或返回；不新增数据库写入 | 接入 |
| [agent/service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/service.py) | 适配：`_execute_proposal` 按 route 分派 | 接入 |
| [agent/workflow.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/workflow.py) | **不改**：只做请求 / 版本 / 消息壳，不塞决策 | 不动 |
| [agent/tools/change_plan.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/tools/change_plan.py) | 将已校验决策编译为业务操作并执行；`switch_goal` 若保留仅由此派生 | 修正 |
| [services/shopping_plan_service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/services/shopping_plan_service.py) | `merge_plan` replace 分支改为"新目标独立构建" | 修正 |
| [services/task_lifecycle_service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/services/task_lifecycle_service.py) | 复用 `create_purchase_task` / `supersede_current`，不新增状态机 | 复用 |
| [prompts/semantic.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/prompts/semantic.py) | 一致性：删"不支持替换目标"，修默认自做，补 `goal_relation` 指引 | 修正 |
| [schemas/guide.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/schemas/guide.py) | `TurnResponse` 只读回显 route/missing_slots（命名待定） | 只读回显 |

**明确不做**：不新增数据表；不新增第二套 workflow / router / service / 脚本；不新增固定规划模型调用；不改确认 / 幂等 / 版本 / 停止不变量；不引入多 Agent 或多微服务。

---

## 5. 最小提案契约（设计，字段名待评审）

保留现有 proposal 外壳。以下仅展示 `understanding` 子对象；**新目标与已有目标的字段更新二选一**，不同时输出整份 Goal 与重复的 patch。

**已有候选火锅待人数，用户回答“三个人”：**
```json
{
  "speech_act": "answer_clarification",
  "focus_ref": "pending-goal-7",
  "goal_relation": "amend",
  "changes": { "set": { "people": 3 }, "clear": [] }
}
```
**用户明确把鸡翅改为三人自煮火锅：**
```json
{
  "speech_act": "request_action",
  "focus_ref": "active-goal-2",
  "goal_relation": "switch",
  "new_goal": {
    "kind": "meal_plan", "target_name": "火锅",
    "fulfillment_mode": "self_cook", "constraints": { "people": 3 }
  }
}
```

| 字段/规则 | 最小约定 |
|---|---|
| `focus_ref` | 引用服务端快照给出的对象；含糊时标记未定位，不默认绑定旧草稿 |
| `changes.set / clear` | 仅允许约定的目标字段（人数、预算、履约、口味、忌口等）；同一字段不能同时 set/clear；不支持任意路径操作 |
| 省略 / 未知 / 撤销 | 省略=不修改；语义未知用保守的 `unspecified`；撤销必须列入 clear；null 不表示撤销 |
| `new_goal` | 仅用于 new/append/switch；不是模型对服务端当前状态的复述；amend 只更新已有对象 |
| 候选目标的关系 | 候选建立时的 switch/append 单独保存；随后回答人数的 amend 只补候选，不能抹掉它尚待执行的 switch/append |
| 普通商品增量 | 允许现有受限 `商品 ref + quantity delta`；用户给数量，服务端校验并计算。高层餐食请求不让模型另写一套原料 mutations |
| 执行编译 | Goal 就绪后由执行器编译业务操作；`switch_goal`/`purchase_requested` 不再由模型独立授予权限 |
| 禁写字段 | 模型不填写 route/readiness、版本、确认、价格、库存或任意 SKU；使用服务端提供的 ref |

未知键/非法更新报协议错误；未知语义枚举进入保守分支，不派生写操作。系统默认只进 `assumptions`，不冒充用户事实。只读询问可以没有目标变更；`speech_act` 与关系正交，纠错可 switch 也可 amend。

---

## 6. Decision Gate：输出与转移规则（设计）

纯函数。输入 = 上述语义对象 + 服务端快照（当前任务/计划事实、pending、本会话可用候选、版本）。输出：

```jsonc
{
  "route": "answer | chat | clarify | prepare | apply_mutation | refuse",
  "readiness": "ready | needs_clarification | information | unsupported",
  "missing_slots": ["fulfillment_mode"],   // 空数组才允许 prepare / apply_mutation
  "write_blocked": true,                   // 澄清 / 只读 / 闲聊 / 纠错未定位时强制 true
  "reason_code": "DIAGNOSTIC_CODE"         // 内部诊断，不是给用户的话术
}
```

| # | 条件 | route | missing_slots | write_blocked |
|---|---|---|---|---|
| R1 | `speech_act ∈ {ask_fact, chat}` | `answer` / `chat` | — | **true** |
| R2 | `goal.kind = unsupported` | `refuse` | — | **true** |
| R3 | 本轮为只读请求（不替换持久的主目标） | `answer` | — | **true** |
| R4 | `goal.kind = meal_decision` | `clarify`（只读给真实候选） | `meal_target` | **true** |
| R5 | `meal_plan` 且 `fulfillment_mode = unspecified` | `clarify` | `fulfillment_mode` | **true** |
| R6 | 非餐食目标 | 继续判定，`fulfillment_mode` 强制 `none` | — | — |
| R7 | 需要确定与旧目标的关系，但模型给出未定关系或引用不可解析 | `clarify` | `goal_relation` / `focus` | **true** |
| R8 | `speech_act = correct` 且无法定位被纠正目标/属性/焦点 | `clarify` | `focus` | **true** |
| R9 | 有准备/修改依据；关系明确；槽位齐全；引用与能力校验通过 | `prepare` / `apply_mutation` | `[]` | **false** |
| R10 | 其它槽位缺失 | `clarify` | 对应槽位 | **true** |

四条硬规则（必须写进实现）：

1. **只读与澄清阻断采购写入。** 只要 `write_blocked = true`，服务端不执行本轮 mutations；**可以保存焦点与 pending**，但计划、购物车不能变化。冲突记内部诊断码，必要时对用户说"清单尚未修改"。现有 `READ_ONLY_VIOLATION` 只覆盖"只读后再补 mutations"，不覆盖闲聊/澄清类纯写入，需在 Gate 层补齐。
2. **已知菜名不构成写入许可。** 菜名命中真实候选只满足"目标明确"，仍需 `fulfillment_mode` 与 `goal_relation` 就绪（R5/R7）才可编译 mutation。
3. **契约一致性。** `switch` 不得执行旧组的 `change.people`；成品不得编译为原料采购；`append` 不得替换全单。模型只提议关系，执行器据已校验决策派生动作，不能让两套字段各自决定执行。
4. **Gate 的能力边界。** Gate 只校验结构与能力契约，不重新理解原话、不保证模型理解正确、不调用模型；**缺人数只阻断确实按人数生成的能力**，普通商品采购不问人数。

`write_blocked = false` 仅表示本轮允许对应的**草稿计划操作**，绝不是确认或购物车授权；确认入口继续检查任务 / plan / cart 版本与幂等。
停止、超时、非法引用及陈旧版本优先走既有拒绝/终止分支；不能落入“信息齐全所以可执行”。Gate 不自动改写矛盾提案；诊断留内部，用户只看到必要澄清或未修改说明。

---

## 7. 缺口槽位由"执行能力 + 真实事实"决定（设计）

| 维度 | 触发 | 不触发 |
|---|---|---|
| `fulfillment_mode` | `meal_plan` 且未说明 | 非餐食目标 |
| `meal_target` | `meal_decision`，或餐食目标无菜名/items | 已有明确菜名 |
| 味道 / 风格 | 该目标在**真实候选**中确有多个可执行风格，且改变配料或方案 | 服务端无该维度事实 → 如实说"无法确认"，**不得发明口味** |
| `people` | 目标方案**确实按人数缩放**（餐食/场景类）且用户未给 | **`product_purchase` 一律不问人数** |
| 预算 / 忌口 | 用户主动提出时记录 | 不主动追问 |

- 默认值（如配方默认份数）只进 `assumptions`，**不进** `constraints.people`。
- **不每轮必问**：有准备/修改依据且其它校验通过时，不为无关槽位继续追问；仅槽位齐全不构成写入授权。
- 同一槽位不重复追问，复用既有 `merge_pending` 的"一槽一问、回答即替换"语义。
- 探索"吃什么"给少量真实选项或关键问题，**不直接建单**；查询无结果只说明本轮检索没命中，**不得**据此断言全店无此类商品。

---

## 8. 目标切换、激活与跨轮隔离（设计）

```text
模型提出 goal（候选，独立容器）
   ├─ Gate: write_blocked? ──是──► 只回显 / 澄清，不构建任何计划
   └─ readiness = ready ─► 服务端构建新计划（既有 build/validator + 业务服务）
         构建失败 ──► 如实报错，旧任务保持 active，什么都不激活
         构建成功 ──► 在既有提交边界激活：create_purchase_task / supersede_current
                     （旧任务 superseded 终态，不可再编辑）
```

- **候选与已生效分离**：候选目标（本轮理解结果）与 `task.plan_json` 不共用一个容器，避免"理解了一半就污染权威计划"。
- **不迁移旧行**：新目标不继承旧目标未加购的行、未购数量、contributions、gaps；`merge_plan` 的 replace 分支应改为"新目标独立构建"，而不是在旧计划上搬行。
- **真实购物车与确认历史不动**：计划 ≠ 购物车，唯一计划→购物车闸门是确认服务；切换只影响**未确认**计划与任务状态。
- **陈旧提交拒绝**：构建成功不等于可激活；沿用版本 / 停止 / 超时校验，在同一提交边界完成激活与取代；构建期间旧计划变化则拒绝陈旧提交；**旧确认请求绝不能被转接到新任务**。

**跨轮状态更新规则（复用会话 / pending，不新增 Goal 表）**

- **当前明确表达优先**：本轮纠正 > 之前同一目标的明确表达 > 系统推断。**只继承明确适用的约束**；省略不等于删除，明确否定才清除；不继承旧菜名 / 旧口味。会话级忌口保留，目标局部人数只在同一目标延续或用户明确指定时继承。
- **查询只是插话**：待答"火锅选什么风格"时用户问"有熟食吗"，本轮只做只读检索，**不把候选火锅改成 information_only、不冲掉主目标**；之后"清汤"继续补火锅。
- **问题绑定目标**：澄清回复绑定候选目标与问题 ID；切换或取消后，**旧问题不能继续给新目标填槽**；绑定版本变化时重新校验，不凭陈旧 pending 写入。
- **关系可从充分上下文推断**：正当讨论主餐草稿时明确改选火锅，可识别为 `switch` 并复述；真正无法判断是加一道还是换一道时才问。已有确认历史时不改写历史，另起新草稿。
- **P1 复合边界**：每轮只处理一个目标级变更，支持同一目标的多项补充（三人 / 自煮 / 清汤），也允许向已有清单追加一个目标。跨多个目标的混合写操作**不部分执行、不静默忽略**，先问“先处理哪项”；不把此限制误解为清单永远只能有一道菜。

---

## 9. 代表性多轮案例（设计；均需 L1 断言，语义识别另测 L2）

| # | 输入序列 | 期望 |
|---|---|---|
| A | 已生效草稿"可乐鸡翅 2 人"；候选"火锅 / 待人数"；用户"三个人" | 人数改到**候选火锅**，旧鸡翅草稿不变；若当前焦点是鸡翅而用户本意不清，先澄清指代 |
| B | 没有火锅讨论或待答问题，用户只说“三个人” | 无法定位时先澄清，不能凭空创建火锅；L1 测未定位分支，L2 测模型是否编造目标 |
| C | 候选火锅待口味 → 用户"有熟食吗" → "清汤" | 查询轮 `write_blocked=true`，候选目标与 pending 保留；"清汤"只补火锅，仍为三人自煮 |
| D | 旧清单=鸡翅；"不是鸡翅，是火锅" / "不是两人，是三人" | 前者 `correct + switch`，后者 `correct + amend`；不因同为 correct 执行同一动作；未定位焦点才澄清 |
| E | "自煮 3 人火锅" / "可乐再加 4 瓶" | 前者交业务服务做配方展开、商品匹配；后者允许受限 `商品 ref + 数量增量`，价格/库存/配方数量仍由服务端算 |

---

## 10. 实施顺序、验收、非目标（设计）

**P1-R 顺序子步**（消费者先适配再启用）：

| 子步 | 范围 | 门槛 |
|---|---|---|
| R1 契约与 Gate（纯函数） | 词表扩展 + `decide_turn` + 规则表 + 离线单测 | 纯函数可离线验证，不改运行链路 |
| R2 协议接入 | proposal 增 `understanding`；旧字段兼容策略 | 现有协议解析测试不回归 |
| R3 loop/service 接入 | 强制执行 `write_blocked`；澄清走 pending；ready 才允许 executor | 只读 / 澄清不再产生写入 |
| R4 切换语义修正 | `goal_relation` 取代单布尔；replace 独立构建；prompt 一致性 | 新计划不含旧行 / 旧缺口；购物车与确认历史不变 |
| R5 只读回显 | `TurnResponse` 透出 route/missing_slots | 前端字段命名定稿后启用 |

**验收分层**

- **L1｜脚本化 loop 测试（离线执行契约）**：用 [tests/support/semantic_agent.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/tests/support/semantic_agent.py) 的 `ScriptedSemanticProvider` 驱动真实 loop / 执行器 / 数据库 / API。证明**执行契约**，不证明语义质量。
- **L2｜真实模型语义 eval**：沿用 [evaluation/runner.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/evaluation/runner.py) 的 `--mode live` 入口（[Makefile](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/Makefile)）与 `evals/v1/*.jsonl`，补跨轮状态断言。**未跑就不得宣称语义验收**；SSE / UI 另做真实对话回放。

**关键断言（L1 可核对，保留原关键行为）**

1. 只读查询 / 闲聊 / 澄清轮：`write_blocked=true`，计划与购物车不变，pending 与焦点可保存。
2. 未说自做/成品：`missing_slots=[fulfillment_mode]`，不建单、不默认自做；未知口味/风格必须问或如实说明，不默认口味；普通商品采购不问人数。
3. 跨轮插话不冲掉候选目标；切换后旧问题不给新目标填槽；只继承明确适用约束。
4. 纠错 `switch` 与 `amend` 行为可区分；未定位焦点才澄清；Gate 判 switch 而 proposal 改旧组人数 → 拒绝写入，清单不变。
5. 明确商品增量（如"可乐加 4 瓶"）产出受限 ref + 数量增量，不越权推导价格/库存/配方。
6. 切换后新计划无旧目标未购行、无旧缺口；真实购物车与已确认历史不变；旧确认不能确认新计划。构建失败不激活；构建期间旧版本变化则拒绝陈旧提交。
7. 原料 / 成品区分：成品不落成生料采购；缺成分资料不承诺过敏安全；版本 / 幂等 / 停止 / 超时不回归。
8. set/clear 冲突拒绝；省略不清除旧值；同一增量只应用一次；候选补槽不丢失切换关系。所有安全/隔离断言须通过，L2 中误写计划、绑错目标等关键错误不能被平均得分掩盖。

**非目标（本轮不做）**：RequiredItem 需求项、跨目标聚合与单位归一、pantry 量化扣减、购物车占用分配、批量召回（产品方案 P1.5）；新增数据表；第二套工作流；外部知识搜索（P2）。

**数据配套**：成品/熟食 SKU 缺失**只阻塞成品真实检索验收，不阻塞目标切换 R4**；补齐时沿用既有 seed / import / index，不新造脚本，不把 fixture 修改称为线上可搜。

---

## 11. 实施前源码依据（历史记录，不代表当前实现）

- **理解契约未接入运行时**：已有 `Goal` / `parse_goal` / `route_goal`，当前消费位于 [test_goal_understanding.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/tests/test_goal_understanding.py)；现有 loop/service 尚未消费该契约。模块位置见 §4。
- **执行边界已存在**：[service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/agent/service.py) 的 `understand_turn` 调用 `run_loop`，随后 `_execute_proposal` 调用执行器；本方案沿用此边界。
- **协议与提示词矛盾**：协议已有 `switch_goal`，但 [semantic.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/prompts/semantic.py) 仍默认“想吃可乐鸡翅”可准备食材，并写着“不支持替换目标”。
- **旧计划污染风险**：[shopping_plan_service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/services/shopping_plan_service.py) 的 `merge_plan` 在 replace 中保留 `added_quantity>0` 旧行，且提前从 base 提取 `carried_gaps`。
- **确认独立于理解**：[confirmation_service.py](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/backend/app/services/confirmation_service.py) 管理确认、版本与幂等；Goal 就绪不能替代这些检查。

---

## 12. 当前验证边界与限制

- R1–R5 主链路与直接相关测试已实施，原“全部未实施”的描述已失效。离线命令与最终结果见交付记录。
- L2 已使用现有入口运行一次：**1/5 通过，语义验收未通过**。存在协议输出错误、熟食事实错误和 `INDEX_STALE`；提示词修正后尚未复跑，不以离线测试代替 L2。
- 未改运行数据/索引，未做 SSE/UI 真实对话回放；未提交或部署。
- 已生效计划的预算/忌口重算和直接 clear 活动计划人数等能力仍明确拒绝整轮；候选的 set/clear 已支持。其余边界与未验收项以交付记录为准。

---

## 附：本地 NVIDIA 参考的短事实摘要

- [REF/planner.py](C:/Users/20616/Desktop/Agent/Agent产品/reference/retail-shopping-assistant/chain_server/src/planner.py) 是**每轮一次、不传历史上下文**的三选一路由器（`cart`/`retriever`/`chatter`），模块自述"Query routing agent":5，注释明说只传 query 避免路由偏置:182-186。它**不是**需求分解器，不持有对话状态。
- [REF/graph.py](C:/Users/20616/Desktop/Agent/Agent产品/reference/retail-shopping-assistant/chain_server/src/graph.py) 的输入 guardrail 与业务节点**并行**、事后汇合（:250-270），是内容安全而非写入前授权闸门。**不借鉴**作为写入闸门。
- [REF/chatter.py](C:/Users/20616/Desktop/Agent/Agent产品/reference/retail-shopping-assistant/chain_server/src/chatter.py) 在载荷里显式区分 `CURRENT CART (authoritative)` / `AVAILABLE CATALOG (only NEW products)` / `RECENT DISCUSSION (NOT authoritative)`:127-134；长期上下文是被压缩的散文摘要。**借鉴**"权威事实与参考上下文分离"（Sale-guide 已有等价物：`current_plan` vs `recent_messages`），**不借鉴**用摘要承载目标状态、多节点拓扑与多服务部署。
