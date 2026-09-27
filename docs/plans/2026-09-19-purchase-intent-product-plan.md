# Sale-guide 采购意图驱动产品方案（审阅稿）

- 日期：2026-09-19
- 状态：**待用户审阅；本文档只描述产品建议，尚未实现，也不构成开发授权。**
- 范围：产品契约、概念模型与分期建议。不新增微服务、不新增向量库、不引入多 Agent、不引入调度平台。
- 依据：本文档的架构取舍以[购物 Agent 架构调研](C:/Users/20616/Desktop/Agent/Agent产品/Sale-guide/docs/research/2026-09-19-shopping-agent-architecture-survey.md)（2026-09-19，第三方源码只读核对）为主要外部参考；该调研本身**不是**运行验证，也不代表本文档已获批准。本文档不复制调研全文，只引用其章节并说明采纳/不采纳理由。

## 0. 一页摘要与关键审阅点

**定位。** Sale-guide 是面向**模糊购物需求**的即时零售决策辅助：先理解“生活目标”，再落到“可执行的采购方案候选”，最后经用户显式确认才写入购物车。菜谱只是**需求解析的知识来源之一**；商品、库存、价格、配送才是业务事实。

**关于检索的一句更正（相对上一稿）。** 上一稿写作“只有当用户明确要买成品时才走商品检索”，这个表述过窄。本稿改为：

- **目标未定**（“我饿了”）允许**只读的供给评估**（这家店能不能配出自做/成品两条路），不建可确认清单；
- **明确自做**（“想做可乐鸡翅”）同样需要把菜名解析成食材，再为每个食材做**商品检索（SKU 匹配）**——“自做”否定的是“买成品”，不是“检索商品”；
- 真正被禁止的是**未经授权的建单/加购**（写入购物车或创建可确认任务），不是读检索本身。

**一句话目标。** 把“我想吃可乐鸡翅 / 我饿了 / 想买点零食 / 周末吃火锅”这类输入，变成“目标 → 需求项 → 真实供给匹配 → 可确认清单”，且**永不自动加购**。

**五条核心原则。**
1. Intent（意图）、Goal（目标）、Options（方案候选）、RequiredItems（需求项）、Fulfillment（供给匹配）、PurchasePlan（待确认清单）是**不同概念**；概念分层不等于每层都要落数据库表。
2. **Execution Plan（Agent 下一步查什么/问什么）与 Purchase Plan（给用户审阅的业务对象）是两份东西**，不得混为一谈（调研 §5.2）。本方案真正的产品对象是后者：可编辑、可重校验、带版本。
3. 授权按**能力**划分，而不是按固定两轮问答划分：一条明确请求可以同时具备“选目标”和“准备清单”的能力；**最终加购必须用户显式确认**，任何条路径都不得由模型或代选触发。
4. 模糊需求不得生成可确认采购清单，但允许只读检索；不强制固定轮次的槽位问答。
5. 生成阶段允许展示部分方案；**确认时若已选 SKU 缺货、涨价或快照过期，必须拒绝旧快照并刷新重新确认**，不允许悄悄删掉缺货行后加购剩余。

### 0.1 调研发现 → 采纳/不采纳 → 本方案落点

引用格式 `调研 §X.Y` 均指 `docs/research/2026-09-19-shopping-agent-architecture-survey.md` 的章节。第三方代码只作设计参考，**本文档不声称其已在 Sale-guide 运行或验证**。

| 调研发现（章节） | 采纳 / 不采纳 | 主要理由 | 落到本方案 |
|---|---|---|---|
| Anthropic：Runtime Loop → ToolExecutor → gates → StorefrontBackend，业务能力放在 backend 而非 prompt；商品 ID 必须来自本会话的目录/订单工具或已在购物车（§3.1） | **采纳** | 与 Sale-guide 已有后端边界一致；已有同轮候选引用与后端分界，但完整 provenance 证据链待补 | §3 架构、§5.3 evidence、§10 现状（部分实现） |
| Anthropic shopping 侧模型可直接调加购工具；merchant 侧 host approval 不能当 shopping 侧已有（§3.1） | **不采纳** | 与“先确认方案再加购”的更强边界冲突；把 merchant 能力误当 shopping 能力 | §4 授权、§5 Confirmation |
| Veckomenyn：先汇总所有菜谱再搜索；单菜修改不重做全周；购物车写后回读（§3.2） | **采纳（思路）** | 跨目标聚合与局部修改是刚需，但实现要落在后端而非 prompt | §6 确定性聚合、§8 局部修改、P0/P1.5 |
| Veckomenyn：单位换算、去重、覆盖核验主要靠 prompt；同名商品不再加不等于按数量扣减（§3.2） | **不采纳** | 数量必须可复算、可审计，不能依赖模型自觉 | §6 聚合规则 |
| Redis：批量/组合检索工具减少逐项搜索轮数（§3.3） | **采纳（解耦后）** | 减少轮次有效；但不接受“食材解析与每项选一个 SKU”耦合 | §3 批量召回、P1.5 |
| Redis：对含商品结果的菜谱回复给 24h 缓存 TTL（§3.3） | **不采纳** | 稳定知识与短时价格/库存必须分开缓存 | §9 缓存与信任边界 |
| Shopify：商业系统做成 MCP 工具适配层，支付留给宿主；无独立方案确认凭证（§3.5） | **后期采纳** | 单店阶段不需要；真接商城时再做适配，不是 P2 强制项 | §11 分期 P2/远期 |
| UCP A2A：对话状态与商务状态分离、商业数据直接返回 UI（§3.6） | **后期采纳（仅状态分离思想）** | 当前单店导购不需要引入协议层 | §11 分期远期 |
| NVIDIA / AWS：Router/Supervisor 多 Agent 形态（§3.4/§3.7） | **不采纳** | 多 Agent 不天然更会规划，成本高；单 Agent 足够 | §1 非目标 |
| AWS：`confirm_purchase` 仅收 user_id，确认只写在 prompt（§3.7） | **不采纳** | 需要服务端版本化确认凭证与幂等，不能靠提示词 | §5 Confirmation、§4 授权 |
| Instacart：需求项与 SKU 分字段、pantry 独立（§3.8） | **采纳（字段思路）** | 与 RequiredItem / Fulfillment 分离一致；不依赖其平台 | §5 契约 |

**关键审阅点（请重点看）**
- §0 对“只有明确买成品才检索”的更正是否成立；
- §3 端到端架构与 LLM/后端责任划分是否符合预期；
- §4 两类授权按能力而非轮次划分是否成立；
- §5 需求/供给/方案/确认四份契约字段是否够用、是否过重；
- §6 数量聚合与“不重复抵扣”规则是否可复算；
- §7 可购买状态、匹配关系、满足程度拆分，以及 `coverage_mode`/`can_confirm` 的复用映射；
- §10 现状差距（本节为事实描述，优先按函数名核对，行号可能过时）；
- §11 分期边界：P0 只拆成合同→后端 partial→前端→验证四步，不扩大到 8 项历史失败；
- §12 验收矩阵的三层分离与 §13 待决策清单。

---

## 1. 定位与非目标

**已共识（大方向，不再重复询问）**
- 面向模糊购物需求，做决策辅助而非菜谱推荐；菜谱降级为需求解析知识源。
- 商品/库存/价格/配送是业务事实，通常来自门店实时数据；菜谱/知识可以来自用户、本地或未来外部来源。**本地 fixture 不是实时供给**，不得对外宣称“实时价格/库存”。
- **检索与写入分离**：明确买成品走商品检索；明确自己做同样要为食材匹配 SKU；两者都允许只读检索。禁止的是未经授权的建单/加购，不是检索本身。
- “我饿了 / 想吃点硬的东西”这类未选定目标的输入：可以只读评估供给，但不建可确认清单。
- 部分满足是合法结果：例如可乐鸡翅只配到可乐，应清楚显示缺鸡翅，并允许用户确认只买可乐。

**非目标（本期不做）**
- 不做通用电商搜索/比价平台的替代；不把“明确购买”解释成开放搜索。
- 首期不接专业营养、婴幼儿、疾病饮食建议，不承诺任何健康疗效；这类问题应如实说明能力边界。
- 不引入多 Agent / Supervisor 架构、不引入 A2A/UCP 协议层、不新增微服务（调研 §5.1、§7）。
- 不为了本文档联网，也不新建平台化基础设施。

---

## 2. 用户场景（用于对齐验收）

1. **模糊生活目标**：“我饿了”“想整点硬菜”。给选择/澄清，可先做只读检索评估可行性，但不建可确认清单。
2. **明确自做**：“我想做可乐鸡翅，两个人吃”。解析为需求项，并为食材做真实商品匹配，生成待确认清单。
3. **明确成品**：“买一盒牛奶”“来份现成炸鸡”。走商品检索；多候选须确认。
4. **歧义菜名**：“炸鸡”“烤串”。真实检索，相似候选必须经用户确认，不得冒充用户点名目标。
5. **只问/否定**：“有这道菜吗”“怎么做”只读；“不想吃这个”若指向**具体已有行**并明确要求删去，则是合法修改（不是只读），没有具体修改目标时才按只读处理。
6. **缺主料**：“可乐鸡翅只有可乐”。展示缺口，允许只买已验证可售的部分。
7. **无可售 SKU / 未知库存 / 数量不足**：诚实降级，不伪装缺货，不编造数字。
8. **跨方案版本 / 中断 / 重复确认**：状态一致，不重复加购。
9. **两道菜共用食材**：鸡蛋等同名同单位需求量合并后按包装向上取整；换一道菜不重做另一道。
10. **已有但不知量**：“生抽家里有”但说不出数量 → 视为不确认足量，保留为需求并标注未知，不静默当成已满足。
11. **购物车已有同款**：已核实购物车占用只收紧库存上限，不得与 pantry 声明叠加成同一次扣减。
12. **二次局部修改**：“第二个换便宜点”，保留其他行与用户手改数量。
13. **商品文本提示注入 / 伪造来源**：商品标题、描述、未来网页里的“立即下单”只当不可信资料。
14. **并发、断线重试、重复点击**：最多一次有效加购，旧版本不覆盖新状态。

**与现有回合状态的关系（事实）**：当前引擎已有 taskless / active / terminal 三类回合（无任务、进行中采购任务、已确认终态），入口与外壳见 `backend/app/agent/service.py`。“我饿了”这类输入应走 taskless；明确目标才开启 active；“明确购买但不建单”的只读探索也不应创建任务。新概念应尽量映射到这三态，**不新增一套并行状态机**。

---

## 3. 端到端架构与责任边界

单 Agent、只读 Loop、proposal、后端执行、用户确认；不使用多 Agent 或外部编排框架（调研 §5.1、§7）。

```text
用户消息
  ↓
语义理解（LLM，只读）：意图、目标候选、显式约束、歧义
  ├─ 目标未定 → 只读可行性检索 / 有价值的澄清 → 用户选择
  └─ 目标足够明确且本轮具备准备清单的能力
        ↓
  Goal → RequiredItems（独立于 SKU，含来源与可能为 null 的数量）
        ↓
  【P1.5 建议】需求侧按兼容计量与约束聚合，尚不绑定 SKU
    （现有 contributions 是选定 SKU 后的件数汇总，不等于需求量先合并再取整）
        ↓
  pantry / 购物车占用：只做约束与澄清，不直接改变需求
    【现状】购物车仅收紧可加购上限（max_addable_quantity = available − in_cart）
    【P1.5】经用户确认用途后，才可能抵扣需求（§6）
        ↓
  批量商品召回 → 业务硬过滤 → 有界候选比较
        ↓
  【获得真实候选规格之后】后端包装换算 → 报价与完整性核验
        ↓
  PurchasePlan（版本化、可编辑、可重校验：已选 SKU + 数量 + 缺口 + 证据 + 快照）
        ↓
  用户显式确认具体方案/具体已选子集（确认入口，非模型工具）
        ↓
  服务端版本/价格/库存/授权复查 → 幂等事务加购
```

这是目标架构图，不是现有调用顺序；`【现状】` 表示已核对的现有行为，`【P1.5】` 表示待审能力而非已排期承诺。包装换算必须在**拿到真实候选规格之后**才能做（否则不知道“1 件”是多少），因此它不在需求聚合阶段；完整聚合能力见 §6 与 §11。

**两份 Plan 的区别（调研 §5.2）**

| | Execution Plan | Purchase Plan |
|---|---|---|
| 是什么 | Agent 本轮下一步查什么、问什么、提交什么 | 给用户审阅的 SKU、数量、报价、缺口、替代、版本 |
| 生命周期 | 单轮内，随回合结束作废 | 持久化在任务上，跨轮可编辑、可重校验 |
| 谁负责 | LLM 提议，Loop 硬预算执行 | 后端生成与校验，用户确认 |
| 现状落点 | `agent/loop.py` 的只读阶段与 proposal | `guide_tasks.plan_json` |

**有界性（现状事实）**：整个回合模型调用硬上限 `HARD_MAX_MODEL_CALLS = 3`，只读阶段最多 `HARD_MAX_READ_ONLY_ROUNDS = 1`，协议修复最多 1 次，单次检索行数 `MAX_LOOKUP_ROWS = 5`，默认 `max_lookups = 2`（`backend/app/agent/loop.py`、`backend/app/agent/tools/read.py`）。批量工具的意义是在这个预算内覆盖更多需求项，而不是放开预算。

**LLM 与后端责任表**

| 决策内容 | 责任方 | 现状 |
|---|---|---|
| 模糊意图理解、目标候选、是否值得澄清 | LLM | 已有 |
| 从菜谱/场景/用户口述提出需求项草案 | LLM 提议，后端归一 | 待实现（协议当前只有目标级候选引用与 `mutations`） |
| 生成查询改写、选择只读检索 | LLM | 已有（`lookups`/`queries`） |
| 在**有限真实候选**中比较偏好与替代 | LLM | 已有 |
| 基于事实解释推荐与不足 | LLM | 已有；缺字段级证据挂接（§8） |
| 理解“换便宜点”“不要这个”的语义 | LLM | 已有 |
| 身份、门店、配送区、权限 | 后端 | 已有 |
| 是否有加购/交易授权 | 后端（用户操作产生） | 已有 |
| 商品 ID、价格、库存、可售状态 | 后端（门店/目录数据） | 已有 |
| 工具白名单、参数、预算、超时 | 后端 | 已有 |
| 单位/包装换算、金额、优惠、数量上下限 | 后端 | 部分（同族单位换算由 `TemplatePlanService._pack_qty` 确定性决定，见 §6） |
| 约束硬过滤、版本、快照过期 | 后端 | 已有 |
| 幂等/事务、实际加购 | 后端 | 已有 |

**工具/入口面（`现状` 与 `建议` 严格区分）**

| 面 | 名称 | 状态 | 说明 |
|---|---|---|---|
| 模型只读 | proposal 内 `lookups` / `queries` | **现状** | 只读检索与只读回答请求，硬预算执行 |
| 模型方案提交/修改 | `proposal.mutations`（`add` / `change` / `remove`） | **现状** | 模型只能提交结构化意图，看不到任何写工具 |
| 服务端执行链 | `PlanChangeExecutor` → `prepare_purchase_plan` → `PlanCommitService` | **现状** | 校验→生成真实 SKU/数量→版本化合并落库；全部由服务端调用，不是模型可任意调用的工具 |
| 批量召回 | `search_products_batch` | **建议（不存在）** | 一次为多个需求项取候选，减少轮次（借 Redis §3.3，不耦合“食材→选一个 SKU”） |
| 需求项草案 | `RequirementsProposal` | **建议（P1.5，不存在）** | 作为 proposal 的一个只读字段开放，而不是新增写工具 |
| 用户确认 | `POST /guide/tasks/{task_id}/confirm` → `ConfirmationService` | **现状** | 确认凭证只从用户操作产生 |
| 确认入口与模型工具面分离 | —— | **不变量** | 模型看不到、也不能产生确认能力 |

---

## 4. 授权与确认边界

**按能力划分的授权（不是固定两轮问答）**
- **A 类｜探索/选目标能力**：用户要求“帮我选 / 配一套 / 看着办”时，允许系统在候选中**代为选择目标**。A 类**不能**升级为清单准备或加购。
- **B 类｜清单准备能力**：允许把目标落成待确认采购清单（仍不写购物车）。
- **最终加购确认**：必须由用户对**具体版本的具体已选子集**显式确认；任何情况都不得由模型、代选或前两类授权触发。

**一条明确请求可以同时具备 A、B 两项能力**：例如“**帮我选一道两人做的晚饭，并配成清单**”——“帮我选”就是 A（代选目标），“配成清单”就是 B，一条消息即可同时具备，不必先问一轮再问一轮。反过来，“两个人做可乐鸡翅，配好给我看”目标已明确（不需要 A），只用到 B。系统不得为了形式强制拆分。

**约束（不变量）**
- **来源门槛 ≠ 授权**：商品 ID 来自服务端目录只证明“这个 SKU 是真实的”，不证明“用户允许买它”。
- 模型不能制造 `confirmed=true`，不能指定他人 `user_id`；身份只从认证 session 注入。
- 确认入口与模型工具面物理分离；模型不可见确认/加购能力。
- 不得绕过现有“采购意图冻结”：只读检索阶段一旦开始，本轮购买授权即固定，后续模型输出不能追加授权；只有**用户的新消息**才能新增授权（`backend/app/agent/loop.py`，只读阶段与预算冻结处）。探索与工具文本都不能把本轮升级成“已授权加购”。
- 确认/取消/修改等按钮应锚定具体目标与方案版本；“第二个”“就这个”等指代以服务端版本为准，不以本地渲染顺序为准。
- **逐行加购与批量加购同等受约束**：两者都要经过版本、事实复查、授权与幂等，逐行不是“绕过确认的快捷方式”（`PlanItemService.add_item` 维护 `added_quantity`/`remaining`，明确不是 `can_confirm` 总闸；逐行后批量确认仍不得重复加购）。
- **自然语言确认（仅远期）**：若将来支持“确认下单吧”，必须由可信控制器绑定**当前唯一待确认版本**；无法唯一绑定时重新询问，不由模型自行解析并执行。
- 只问/否定类输入：**未有明确修改目标时**只读（同现有 `READ_ONLY_VIOLATION` 行为）。但“不要这个”若指向**具体已有行**且用户明确要求删去，属于合法修改（走 `remove`），不得当成只读违规拒绝；两者不要一概而论。
- **历史验收变化（待决策 D1）**：“我想吃可乐鸡翅”在历史验收中默认生成食材清单；本方案建议在无上下文时先澄清“自己做 / 买成品”。这是行为变化，**不默认新建议已批准**。无论最终选择哪种，测试应按批准的决策调整，不得因为断言不便就删除测试。

---

## 5. 需求、供给、方案与确认契约

以下五类对象契约**均为拟议**（各自现状以 §10 为准），**不是要求逐类建表**。P0 复用现有任务与 `plan_json`；`selected_lines` 建议直接映射现有 `items`、`gaps` 映射现有 `uncovered_items`，不新造一份并行的权威数组。

### 5.1 Goal

| 字段 | 含义 |
|---|---|
| `goal_id` / `goal_version` | 目标标识与版本；目标被替换（换菜）时递增 |
| `description` | 目标的人话描述（例如“两人份可乐鸡翅”） |
| `source_turn` | 该目标来自哪一轮用户消息（回合 id），用于回溯；**可选**，用户自列或补录历史可能没有 |
| `constraints` | 用户**明确说出**的约束（人数、预算、忌口、品牌、送达时间） |
| `assumptions` | 系统显式假设（例如“按配方默认 2 人”），必须可与用户事实区分 |

### 5.2 RequiredItem（独立于 SKU）

| 字段 | 说明 |
|---|---|
| `item_id` | 需求项 id |
| `name` / `ingredient_id` | 展示名与归一后的食材/品类标识 |
| `quantity` / `unit` / `quantity_known` | 数量未知时为 `null` + `quantity_known=false`；**不编造“适量/少许”的数字**；单位未知同样为 `null` |
| `requiredness` | 至少 `core` / `optional` |
| `source` | 来源：`user` / `local_recipe` / `scenario` / 未来外部，附 `ref` 与**可选** `turn_id` |
| `pantry` | 家庭存量声明：`state ∈ {unknown, declared_partial, self_supplied, waived}` + 可空 `declared_quantity` |
| `substitution_policy` | 是否允许替代、替代边界 |

**关键纪律：需求本体不嵌入依赖 SKU 的包装换算结果。** 包装换算（“500g 规格 → 1 件”）属于 Fulfillment，因为它取决于具体门店的具体 SKU；否则同一需求项在不同门店就无法复用，也容易被误当用户事实。

```json
{
  "required_items": [
    {
      "item_id": "ri-1", "name": "鸡翅", "ingredient_id": "chicken_wing",
      "quantity": 500, "unit": "g", "quantity_known": true,
      "requiredness": "core",
      "source": {"kind": "local_recipe", "ref": "dish-kele-jichi", "turn_id": "turn-12"},
      "pantry": {"state": "unknown", "declared_quantity": null},
      "substitution_policy": "allow_equivalent"
    },
    {
      "item_id": "ri-2", "name": "可乐", "ingredient_id": "cola",
      "quantity": null, "unit": null, "quantity_known": false,
      "requiredness": "core",
      "source": {"kind": "local_recipe", "ref": "dish-kele-jichi", "note": "配方只写“一罐”，未给容量"},
      "pantry": {"state": "unknown", "declared_quantity": null},
      "substitution_policy": "allow_equivalent"
    },
    {
      "item_id": "ri-3", "name": "生抽", "ingredient_id": "soy_sauce",
      "quantity": null, "unit": null, "quantity_known": false,
      "requiredness": "optional",
      "source": {"kind": "local_recipe", "ref": "dish-kele-jichi"},
      "pantry": {"state": "declared_partial", "declared_quantity": null, "declared_by": "user"},
      "substitution_policy": "any"
    }
  ]
}
```

**规则**
- `pantry.state` 只能由**用户声明**推进；系统不得自行假设。`declared_partial`（“家里有，但不知道多少”）不等于足量，需求仍然保留。
- `self_supplied`（“这项我全有，不用买”）与 `waived`（“这项这次不买”）语义不同：前者视为本次缺口为零，后者需求未满足只是本次舍弃。
- `requiredness` 与 `pantry.state` 共同决定覆盖语义，**不能**用一个布尔 `user_has` 表达（见 §6）。
- 需求项之间不得仅凭名字相同就假定可合并：合并要看归一后的 `ingredient_id` **和规格/硬约束是否兼容**（§6）。
- 本节示例中的 `ri-2`（可乐）数量未知（`quantity: null`）：它**不能**被套用 §5.3 的假定数量或包装件数推算。

### 5.3 Fulfillment（多对多）

| 字段 | 说明 |
|---|---|
| `fulfillment_id` | 匹配记录 id |
| `required_item_ids` | **可包含多项**：一个 SKU 可同时覆盖两个需求项 |
| `sku_id` | 真实目录商品 |
| `match_kind` | `exact` / `equivalent` / `substitute`（匹配关系，不是库存状态） |
| `pack_count` | 为覆盖这些分配而买的**售卖件数**（不是需求量） |
| `allocations` | 按 `required_item_id` 拆分：每项给 `quantity`/`unit`。合计不得超过 `pack_count × spec.quantity`，且同一需求项的同一数量不得被重复分配 |
| `availability` | 供给可得性：`available` / `insufficient_stock` / `out_of_stock` / `not_found` / `unknown` / `undeliverable`（与 §7 可购买状态同口径；`undeliverable` 表示该门店/配送区送不到） |
| `pack_conversion` | 包装换算及其**依据**：`spec`（规格数量/单位）、`allocated_total`、`formula`（可复算的算式）、`source`（依据来源）、`confidence`（`declared`/`inferred`/`unknown`，是来源可信度等级，不是概率）。**`confidence` 只解释这条 spec/formula 的来源，不允许用它推断单位兼容或补足缺失单位** |
| `unmet_reason` | 未覆盖部分的类型：`not_found` / `out_of_stock` / `insufficient_stock` / `unknown` / `undeliverable` |
| `evidence` | 来源证据：`sku_source`、`quoted_at`、`stock_verified`、`unknown_constraints` |

**多对多示例**（演示假定数据，**不是 fixture 事实**，也不表示目录里真有该 SKU）：假定用户已明确两个需求——`ri-2` 可乐 330ml、`ri-4` 可乐 660ml，合计 990ml；本店候选 `demo:cola-330` 规格 330ml/件。

```json
{
  "fulfillments": [
    {
      "fulfillment_id": "ff-1",
      "required_item_ids": ["ri-2", "ri-4"],
      "sku_id": "demo:cola-330",
      "match_kind": "exact",
      "pack_count": 3,
      "allocations": [
        {"required_item_id": "ri-2", "quantity": 330, "unit": "ml"},
        {"required_item_id": "ri-4", "quantity": 660, "unit": "ml"}
      ],
      "pack_conversion": {
        "spec": {"quantity": 330, "unit": "ml", "sell_unit": "件"},
        "allocated_total": {"quantity": 990, "unit": "ml"},
        "formula": "ceil(990 / 330) = 3",
        "source": "catalog_spec",
        "confidence": "declared"
      },
      "availability": "unknown",
      "unmet_reason": "unknown",
      "evidence": {
        "sku_source": "catalog",
        "quoted_at": "2026-09-19T10:00:00Z",
        "stock_verified": false,
        "unknown_constraints": ["未核实门店实时库存"]
      }
    }
  ]
}
```

- 复算：`330 + 660 = 990`，`990 = 3 × 330`，分配总量不超过 `pack_count × spec.quantity`，两项不重复覆盖同一数量。
- 本例 `availability = unknown`（库存未核实）：按 §7，**库存未核实的候选不得进入可确认选中子集**，必须先做供给复查，或按未知降级展示。
- 若门店送不到该配送区，则 `availability = undeliverable`，不得当作“缺货”或“可买”。

不要用“需求项名称 = SKU 名称”做唯一关联；同一 SKU 出现在多个目标时按 `contributions` 记录各目标贡献（现有 `shopping_plan_service` 的 `_row_contributions`/`_collapse` 已具备这一形态）。

### 5.4 PurchasePlan（可编辑、可重校验的业务对象）

| 字段 | 说明 |
|---|---|
| `plan_id` / `plan_version` | 计划标识与版本；任何影响可执行内容的改动都要递增 |
| `requirements_version` / `goal_version` | 本计划对应的需求与目标版本，防止“新需求套旧清单” |
| `store_id` / `delivery_zone_id` | 门店与配送上下文；供给事实必须可追溯到这两个值 |
| `selected_lines` | 已选行，**建议直接映射现有 `items`**（`sku_id`、`quantity`、`contributions`、`selected`）而不另造权威数组；含用户手改来源 |
| `gaps` | 缺口：未覆盖的 `required_item_id` 及其类型（缺料/缺货/数量不足/未知/送不到），**建议映射现有 `uncovered_items`** |
| `quote` | 报价快照：`quoted_at`、`expires_at`、来源（门店 offer 或目录） |
| `coverage_mode` / `can_confirm` | 复用现有字段（见 §7） |

**P0 持久化底线**：P0 **不要求**把上面每个字段都建成表，但**可确认所必需的缺口与需求证据必须随 `plan_json` 持久化**，不能只活在内存或单次请求里。否则刷新、断线重试或第二个标签页都无法解释“为什么这单是部分可确认的”。

### 5.5 Confirmation（绑定版本与身份）

| 字段 | 说明 |
|---|---|
| `confirmation_id` | 确认记录 id |
| `owner_id` / `task_id` | 绑定用户与任务（身份来自认证 session） |
| `plan_id` / `plan_version` | 被确认的**具体版本** |
| `expected_state_version` | 任务状态版本，防止对旧状态执行 |
| `selected_digest` | 已选子集的**规范化内容摘要**：服务端按行内容重算并比对（不是数字签名，也不是客户端自证），保证“确认的就是服务端当前这些行” |
| `scope` | `selected_subset` / `single_row` 等，明确这次授权覆盖多少 |
| `expires_at` | 确认有效期；与 `plan.expires_at` 配合 |
| `idempotency_key` | 幂等键 |
| `result` | 消费结果：成功/失败、实际写入行、是否重放 |

`ConfirmationService` 已实现的版本/状态/价格/幂等检查（§10）应被理解为这份契约的**现有子集**，字段命名以现状为准；本表只是把它讲全，不表示这些字段都已存在。

---

## 6. 后端确定性聚合（P0 只做能确认所必需的部分）

**原则：数量与包装换算是后端职责，不是 prompt 职责（调研 §3.2 的反面教训）。**

1. **可合并性看归一标识与规格，不是看名字**。先按归一后的 `ingredient_id` 分组，再要求**规格/硬约束兼容**（同一计量口径、无冲突的品牌/规格排除条件）才合并。`pc`（枚、个）与售卖单位“件/盒”**不是当然同族**，必须由候选规格给出“1 件 = 多少 pc/g/ml”的依据后才能换算。**单位族不同或缺失时不得合并**，更不得凭名字或让模型猜换算；结果标为 `unknown` 并保留为两个需求或提请澄清。
2. **按贡献汇总数量**。每个目标对某 SKU 的贡献单独记录（`contributions`），冗余汇总时按贡献求和，而不是把整行数量重复相加。
3. **pantry 与购物车占用各自有唯一来源标识，同一条数量不得被扣两次**。
   - pantry：**P1.5 目标行为（P0 不实现量化扣减）**。仅当 `pantry.state == self_supplied`，或 `declared_partial` 且 `declared_quantity` **已知且单位/规格兼容**时才扣减；扣减必须记录来源标识（哪一轮的哪条用户声明）。否则保留需求并标注未知。
   - 购物车：已核实购物车占用**只用于收紧可加购上限**（现行 `max_addable_quantity = available - in_cart`），**不**再次从需求数量里减一次。
   - `user_has = true` 这类布尔声明**不证明足量**，不得据此把需求清零。
   - **“pantry 声明的 3 枚”与“购物车里的 10 枚”不天然是同一批鸡蛋**，所以不能用“会重复抵扣同一批”来论证。正确口径是：**用途未确认就不抵扣需求**；若用户后续确认购物车那件确实是本次需求的一部分、且不是 pantry 已声明的那部分，P1.5 才允许把它分配到具体需求上（每条 `required_item_id` 记录来源标识与分配量），且同一条数量只能分配一次。
   - P0 对购物车占用的行为是：**先询问/展示占用，绝不暗示必须重复购买**（参见 D8）。
4. **最后按包装向上取整**，并保留余量与缺口：`pack_remainder`（买了会多于需求的部分）与 `gap`（仍不足的部分）都要落字段，不能只留一个总数。

**可复算短例（演示菜 A / 演示菜 B 为假设输入，并非真实菜谱）**

- 演示菜 A（2 人）需鸡蛋 4 枚，演示菜 B（3 人）需鸡蛋 5 枚；归一后 `ingredient_id` 相同、都按 `pc` 计量 → 汇总 `4 + 5 = 9` 枚。
- 用户声明“家里还有 3 枚鸡蛋”，数量已知且单位一致 → `9 − 3 = 6` 枚缺口；该扣减的来源标识是“用户第 N 轮的 pantry 声明”。
- 购物车里另有 1 件鸡蛋（规格 10 枚/件）。**用途未确认时 P0 不抵扣需求**：只在界面提示“购物车已有 1 件”并询问，不把它从 6 里减掉，也**不得暗示需要再买一件凑数**。
- 若用户随后确认这 1 件就是本次需求、且与 pantry 那 3 枚不是同一批 → P1.5 把它分配到本次需求：剩余需求 `6 − 6 = 0`，购物车自身还多出 `10 − 6 = 4` 枚，**不应再买一件**。
- 若用户明确购物车那件另有用途，才按新增采购分支计算：规格 10 枚/件 → `ceil(6 / 10) = 1` 件，`pack_remainder = 4` 枚，`gap = 0`。用途仍未确认时只展示这项测算并澄清，不默认选中新增一件。
- 若出现“鸡蛋 1 盒”这类单位不可比或规格缺失的需求，则**不合并**，单独成项并标注 `unknown`。

**P0 与 P1.5 的边界**：P0 **不新增**聚合/换算能力，只复用现有确定性能力（`_row_contributions`/`_collapse` 的贡献汇总、`_pack_qty` 的同族单位换算、`max_addable_quantity` 的购物车上限），并把 partial 所必需的**缺口字段**打通，就足以支撑“可乐鸡翅只有可乐”可确认。**完整的跨目标单位归一、pantry 量化扣减、购物车占用的需求分配全部放 P1.5**；**不要让 P0 被完整聚合拖大**。

---

## 7. 部分满足分层（重点）

**三个正交维度**
1. **可购买状态**：`available` / `insufficient_stock` / `out_of_stock` / `not_found` / `unknown` / `undeliverable`。
2. **匹配关系**：`exact` / `equivalent` / `substitute`。替代是“匹配关系”，**不是库存状态**。
3. **用户选择与满足程度**：已选/未选、是否满足核心需求、是否用户自备或主动舍弃。

**语义纪律**
- `not_found` 只表示“本次检索 / 当前目录未找到”，**不是**“全店不卖”的断言。
- `unknown`（库存/属性未知）不得伪装成 `out_of_stock`；未知就是未知。
- **未知库存/未验证行不得混成缺货，也不得进入可执行选中子集**：未验证的行可以展示为待确认线索，但不能被静默勾选。
- **未知硬约束同样不能视为通过**：预算、明确排除成分、配送等硬条件未核实时须补证或澄清；仅库存可售不足以允许确认。`stock_verified` 的菜谱检索标记不能直接代替最终 SKU 的门店供给核验。
- **无已验证可售 SKU 时不可确认**：至少一个已验证可售 SKU 且用户清楚缺口，是“部分可确认”的门槛。
- **配齐程度**与**是否允许确认**是两件事。
- **主料缺失**必须突出“不能配齐原目标”，不得用“找到 2/3 个调料”包装成任务成功。
- **缺料 / 缺货 / 数量不足**是不同缺口类型，字段上分开，提示上也分开。
- **库存不足**允许用户选择已核实的可买数量，未买差额保留在需求项上，供后续补买。
- **用户自备（声明）**部分不计入本次采购缺口；**用户主动舍弃**不等于需求已满足，只是本次不买。
- **用户明示的“只买这些”与确认时静默删减是两种授权**：前者可在缺口可见时确认；后者必须生成新版本并重新确认。
- 生成阶段允许展示部分方案；**确认阶段**若已选 SKU 缺货/价格变化/快照过期，应拒绝旧快照并刷新后重新确认（`STALE_PLAN`/`PLAN_EXPIRED`/`PRICE_CHANGED`/`PRODUCT_UNAVAILABLE` 等现有码）。
- 重复确认、逐行加购后批量确认不得重复加购；stop、流中断、恢复后应统一到权威版本。
- **方案合并后语义一致**：合并/局部修改后 `coverage_mode`、`can_confirm`、缺口列表必须与单据内容一致，不能出现“行都齐了但仍是 uncovered”之类漂移。

**复用现有字段，不另造同名状态**

| 现有字段 | 位置 | 本方案如何复用 |
|---|---|---|
| `coverage_intent`（`full` / `partial_ok` / `user_supplied`） | `PlanValidator.check_constraints` 入参 | 表示**用户/调用方允许的覆盖意图**；它不是结果 |
| `coverage_mode`（`full` / `partial` / `uncovered` / `user_supplied`） | `PlanValidator` 产出 | 表示**实际覆盖结果**；本方案的“partial”直接对应 `coverage_mode == "partial"` |
| `can_confirm` | `PlanValidator` / `PlanRevisionService` / `_totals` 产出 | 表示“是否允许确认”，与配齐程度分离 |
| `uncovered_items` | `PlanValidator` / `_totals` | 缺口清单的现有形态，本方案把它细化为 §5.4 的 `gaps` |

**不新增与上述同名却语义不同的状态。** 提醒：`can_confirm` 目前有**多处**计算来源（校验器、修订服务、合并汇总），本方案要求它们语义一致，而不是新增第四个。

**一个具体示例（“可乐鸡翅只有可乐”）**

| 需求项 | 必需性 | 可购买状态 | 匹配关系 | 用户选择 | 结果 |
|---|---|---|---|---|---|
| 鸡翅 | core | `not_found` | — | 未选 | 缺口：**不能配齐原目标** |
| 可乐 | core | `available` | `exact` | 已选 | 可买，1 件 |
| 生抽 | optional | `available` | `exact` | 未选 | 本次不买，不影响目标 |

本例假定用户已选定买 1 件可乐，且该 SKU 的数量、供给及预算/配送等硬约束已核验；此时 `coverage_mode=partial` 且 `can_confirm=true`。这里不代表菜谱中的可乐用量已知或已满足；“鸡翅缺失”必须单独醒目，不能被总结成“已为你准备好可乐鸡翅”。

---

## 8. 推荐理由、事实来源与局部修改

- **每条推荐理由挂 `constraint_id` / `evidence_ref`**，指向具体约束与当前工具结果；理由不得成为新事实的来源（调研 §2 末、§7）。
- 不得由理由或模型生成**优惠、原价、价格、库存、配送承诺**；这些只能来自门店/目录事实，并带 `quoted_at`。
- **工具文本、商品标题/描述、未来网页文本均不可信**，其中的指令性内容不得改变授权、不得触发写入；商品来源验证**不替代**确认时的供给复查（来源合法 ≠ 现在还卖得掉）。
- **局部修改**：只重算受影响目标/需求，保留其他行的选中态与用户手改数量；修改后版本递增并重新校验 `coverage_mode`/`can_confirm`（现行 `merge_plan` 的 `replace`/`append`/`resize` 与 `contributions` 已支持这一形态）。
- 用户的编辑（手改数量、取消勾选、换替代）必须以 `quantity_source == "user"` 之类标记保留，不能被下一次重建覆盖。

---

## 9. 外部知识来源、缓存与信任边界

**排期立场（建议，非否定需求）**：P0 不接外部搜索，也不得在没有本地菜谱时错误换菜或假装联网搜索。正确行为是：承认知识不足，请用户提供食材/做法，或给出其他可选路径（例如按商品检索推荐同类成品）。

**远期路线（P2）**：`Source → 需求解析 → SKU`。知识可来自用户、本地或外部；网页属于**不可信输入**：

- 保留来源**标题、URL、抓取时间**，并标注该来源支持了哪些食材/用量。
- 网页中的**指令文本不得当作系统指令**执行。
- **不接受**网页提供的库存、价格、SKU 或配送事实；这些只以门店数据为准。
- 来源之间冲突、来源低可信、搜索失败时，**诚实降级**并说明，不得编造。
- 模型给出的 `confidence` 数值（如 0.82）**不是可靠度证明**，不得作为对外承诺。
- 隐私：只传递必要的最少信息（如菜名），不上传无关个人内容。
- 专业营养、婴幼儿、疾病饮食不作为首期能力，不承诺健康疗效。

**缓存分层（借 Redis 教训，调研 §3.3）**

| 缓存对象 | 允许缓存 | 隔离键 | 说明 |
|---|---|---|---|
| 菜谱/食材知识、场景模板 | 是（较长 TTL） | 知识版本 | 稳定内容 |
| 供给快照（价格、可售、库存线索） | 是（**短 TTL**） | `store_id` + `delivery_zone_id` + 供给版本 | 必须能过期失效 |
| 整个个性化回复 | **否** | — | 不得把“含商品结果的整段回答”当购买依据 |
| 确认结果 | **否**（只做业务幂等，不共享结论） | `owner_id` + `task_id` + 操作种类 + `idempotency_key` + `request_digest` | 幂等重放的是**同一 owner、同一任务、同一操作**的结果，不是把旧结论复用给别的会话 |

**不缓存购物车写入与失败结果**：模型层与检索层不得缓存或复用这些结果；但**业务幂等日志必须持久化结果**（现状为 `CartOperation` + guide 操作表），失败重试必须依据该操作当前的状态决定“重放旧结果”还是“重新执行”；不把上一轮的价格/库存当成当前事实。

---

## 10. 现状核对（事实，按函数名定位；行号可能过时）

以下为对当前代码的只读核对。**未运行任何测试**，分类为“已实现 / 部分实现 / 待实现”，不把拟新增字段说成已存在。

**已实现、可复用**
- 商品直购独立于菜谱：`LOOKUP_KINDS = ("dish", "product")`（`backend/app/agent/protocol.py`）；建单 `_prepare_product` → `build_product_plan`（`backend/app/agent/tools/prepare_purchase_plan.py`、`backend/app/services/shopping_plan_service.py`）；多候选返回真实列表并要求确认（`AMBIGUOUS_PRODUCT`，同文件 `build_product_plan`）。
- 场景（scenario）独立于菜谱：`build_scenario_plan`（`shopping_plan_service.py`），数据在 `data/fixtures/shopping-scenarios.json`（当前仅“火锅”1 个）；场景候选由 fixture 注入候选集（`backend/app/agent/context.py` 的 `build_candidate_set` → `load_scenarios`）。场景组件缺失/不可用记录为 `missing_components`/`unavailable_items`，但仅在整体 `status=="ok"` 时附加（`build_scenario_plan`）。
- 部分覆盖字段：`PlanValidator.check_constraints` 支持 `coverage_intent`，产出 `coverage_mode`（full/partial/uncovered/user_supplied）、`uncovered_items`、`can_confirm`（`backend/app/services/plan_validator.py`）；`PlanRevisionService.revise` 也接受 `coverage_intent` 并产出相同的 `coverage_mode`/`can_confirm`（`plan_revision_service.py`）。
- 确认不是“只拒绝 uncovered”：`ConfirmationService._validate_snapshot` 先拒绝 `validation_status == "stale_supply"`，再拒绝 `can_confirm is False`，再拒绝 `coverage_mode == "uncovered"`，并逐行核对“待买数量 = 行数量 − 已加数量”、门店可售与价格一致（`backend/app/services/confirmation_service.py`）。**上一稿“只拒绝 uncovered”的说法以偏概全，本稿更正。**
- 逐行加购与防重复：`PlanItemService.add_item` 维护 `added_quantity`/`remaining`，明确不是 `can_confirm` 总闸（`plan_item_service.py`）。
- 版本/幂等/过期：确认前检查 `STALE_PLAN`、`PLAN_EXPIRED`；有 `CartOperation` + guide 操作表的幂等键与 `request_digest` 冲突检测；任务/会话版本锚定见 `task_lifecycle_service.py` 的 `TurnAnchor`/`assert_turn_anchor`/`_cas_task_update`。
- 有界只读与意图冻结：`HARD_MAX_MODEL_CALLS=3`、`HARD_MAX_READ_ONLY_ROUNDS=1`、`HARD_MAX_PROTOCOL_REPAIRS=1`、`MAX_LOOKUP_ROWS=5`；采购意图在只读阶段开始时冻结（`backend/app/agent/loop.py`）。
- 检索事实字段：命中含 `match_kind`、`evidence`、`review_status`、`stock_verified`、`unknown_constraints`（`backend/app/services/retrieval_service.py` 的检索结果结构）；`stock_verified` 对所有菜谱恒为 `False`，其 docstring 明确“构建成功不等于已验证可售”。
- 聚合去重形态：`contributions` / `_row_contributions` / `_collapse` 已按 (SKU, group) 记录各目标贡献，跨菜谱合并时不会把整行数量重复相加（`shopping_plan_service.py`）。
- 购物车占用只收紧上限：`_collapse` 中 `max_addable_quantity = available - in_cart`，`in_cart` 来自 `CartService.quantities_for`（按 `owner_id` + `store_id` 限定），**不从需求数量里再减一次**。
- 包装换算：`TemplatePlanService._pack_qty` 在规格完整且单位同族时做确定性换算（`pc`、质量、体积）；单位不兼容返回 `None`。**但缺少规格数量或单位时，现实现直接回退 1 件**（`template_plan_service.py`），不能把该回退当成数量足够的证据。

**部分实现**
- 包装取整存在（`_pack_qty` 用 `math.ceil`），但**余量/缺口不落结构字段**：只留下件数，没有 `pack_remainder`/`gap`；缺规格时默认 1 件的行为尚不满足未知数量契约，P0 至少不得将其宣称为已配齐，完整换算改造留 P1.5。
- pantry 有 `pantry_items`→`role="pantry"` 的形态与 `Requirements.pantry_confirmed` 字段，但没有 §5.2 的 `pantry.state`/`declared_quantity`，因此“有但不知量”与“全有”无法区分。
- 局部修改已支持（`merge_plan` 的 replace/append/resize + `contributions`），但**用户手改数量的来源标记与后续重建的一致性**依赖 `quantity_source == "user"` 的既有约定，缺少契约化说明。
- 来源证据只到检索层：`unknown_constraints` 存在（`retrieval_service._unknown_constraints`），但**不进计划/确认**，计划行也无 `evidence_ref`。
- `ConfirmationService` 有版本/价格/可售/幂等检查，但没有独立的 `confirmation_id`/`selected_digest`/`scope`/`expires_at` 一等对象（`guide_tasks` 上有 `confirmation_id`，其余靠计划版本与操作表约束）。

**待实现（缺口）**
- **菜谱缺料即整单失败**：`TemplatePlanService.build_plan` 把无法解析 SKU 的必需项放入 `missing`，`validate_template_plan` 一旦 `missing` 就返回 `failed`、`items=[]`；`_prepare_dish` 转为错误，且其错误分支的 `missing` 实际取不到值（`validated.get("missing")` 在 failed 返回体里不存在，只能回退 `uncovered_items`）。因此“只有可乐”无法生成部分方案。
- **缺货/不可售同样整单拒绝**：`plan_validator.check_constraints` 对 `not sellable`/`insufficient stock` 直接记 `errors`，场景的 `unavailable_items` 提示在失败分支会丢失。
- **初始建单未打通 partial 意图**：现有 builder 默认 `coverage_intent="full"`，缺项可能直接失败，不能概括成所有结果都是 full；`_totals` 又把任一必需项未选重算为 `uncovered`，并把 `can_confirm` 置为 `False`。
- **前端无法请求 partial**：`revisePlan` 请求体不传 `coverage_intent`（`frontend/src/components/guide/GuideProvider.tsx`），服务端默认 `full`；草稿持久化多数写死 `'full'`，仅一处用 `existing?.coverage_intent ?? 'full'` 保留已有值（同文件；类型见 `frontend/src/lib/guide-persist.ts`）。
- **RequiredItem 与来源证据缺失**：协议只有 `add/change/remove` 引用候选（`protocol.py`），没有“未绑定菜谱 ID 的需求项清单”，计划行也无 provenance。
- **当前无外部搜索接入**（未见运行时联网检索路径）。
- **计划缺口的持久化形态未定义**：缺口当前散落在 `uncovered_items`/`errors` 文本里，未形成 §5.4 的 `gaps` 结构。

**当前可见文档中无独立现行 PRD。** 现有 `README.md`、`docs/plans/*`、`docs/rag/*`、`docs/2026-09-19-cursor-codex-delivery.md` 是架构说明、实施计划与分工对照，均不等同 PRD。本文档不删除或替代旧 RAG 文档。

---

## 11. 分期建议（每阶段含价值 / 范围 / 非目标 / 门槛）

**P0｜产品契约 + 已有路径的 partial（价值最高、范围最小）**

价值：让“缺主料也能给出可确认的部分方案”成立，覆盖可乐鸡翅、火锅、单商品等已落地路径。

非目标：不接外部搜索；不改 8 项历史失败的整体范围；不引入新表/平台；**不把 §6 的完整聚合能力塞进来**；不改确认/加购的现有版本与幂等不变量。

四个**顺序依赖**的子步（不得并行发布；每一子步要等其协议消费者适配完成后再启用，**本文档不承诺“每步可单独回滚”**）：

| 子步 | 责任模块 | 改造内容 | 验收 |
|---|---|---|---|
| P0-a 合同 | `docs/plans` + 后端业务契约/schema 最小字段（**不动模型 `protocol`**） | 冻结 §5 的 RequiredItem/Fulfillment/PurchasePlan 最小字段与 `gaps` 结构；**不在 P0 打开需求项草案字段，不新增写工具** | 契约评审通过；现有协议解析测试不受影响（本次不改模型协议） |
| P0-b 后端 partial | `template_plan_service.build_plan`/`validate_template_plan`、`prepare_purchase_plan._prepare_dish`/`_prepare_product`、`plan_validator.check_constraints`、`shopping_plan_service.build_scenario_plan`/`_totals`/`merge_plan`、`plan_revision_service.revise`、`plan_commit_service.apply_result` | 缺料/缺货/数量不足不再整单 `failed`+空 items，改为带缺口的 partial；`coverage_mode`/`can_confirm` 在 dish/product/scenario/merge/revise/commit 各路径一致；缺口与需求证据写入 `plan_json`；不改确认与加购的版本/幂等不变量 | 离线契约测试覆盖上述各路径（缺主料/缺货/数量不足三类产出 `coverage_mode=partial` 且 `can_confirm=true`，有可售行时），**并包含确认与逐行加购的必要回归**（partial 能确认、逐行后批量不重复） |
| P0-c 前端 | `frontend/src/components/guide/GuideProvider.tsx`、`guide-persist.ts` | 能请求并展示 partial、缺口行可读、确认已选部分；草稿保留后端返回的 `coverage_intent` 而非写死 `'full'` | 前端契约测试/手测：缺口可读、确认请求带正确版本与选中集 |
| P0-d 验证 | `verification/`、`evals/v1` | 新增/调整覆盖 partial 生成、显示、确认的离线契约用例 | **离线工程闭环**（生成/显示/确认）通过即可。**语义功能对外验收另算**：若涉及 D1（成品/自做歧义）或任何 LLM 语义变更，必须以真实 LLM + 检索 + SSE 验收；未做则只能宣称“离线闭环通过”，不得宣称语义功能已验收 |

P0 门槛（建议）：产品契约评审通过；P0-b/P0-c 离线契约测试通过；缺口信息对用户可读；若宣称对外可用则额外完成真实 LLM + 检索 + SSE 验收。**未运行过的测试不得写成已通过。**

P0-b 表中的“有可售行”只是必要条件：还须选中数量明确、硬约束通过、版本/供给有效。`coverage_intent` 当前不是各返回体都具备的字段，P0-a 须明确其请求、持久化与回显契约，P0-c 不得假定后端已经返回；D2 的默认 partial 只允许准备草稿，不替代用户确认该子集。

> **分期更正（用户裁决）**：原 P1“完整需求层、聚合与感知比较”整体降为 **P1.5 采购规划增强**；**P1 正式重定义为“用户意图理解、Goal 建模与导购路由”**。理由：目标没建模清楚时，聚合与采购规划没有可靠输入。本节只改分期与命名，不改动 §10 记录的 P0 事实。

**P1｜用户意图理解、Goal 建模与导购路由（理解层优先）**

- 价值：先稳定回答“用户到底要解决什么”——决定吃什么、做一餐、买商品、按类目采购、补货、只读提问，还是超出能力——再决定下一步是澄清、只读回答还是准备方案。缺少理解层时，聚合与采购规划越细，只会把错误目标执行得越快。
- 范围：
  - 受约束的 Goal 模型与枚举，以及由 Goal + 服务端路由组成的 `IntentState`（`goal_kind` / `fulfillment_mode` / `readiness` / `route` / `missing_slots`），模型只能提出理解结果，不能自行决定路由、价格、库存、版本或确认；
  - Goal 解析结果 → 路由决策的**纯函数**服务（不调用 LLM、不接 loop、无写入副作用）；
  - 覆盖 `meal_decision`（不知道吃什么）、`meal_plan`（明确一餐，区分自做/成品）、`product_purchase`、`category_purchase`、`replenishment`、`information_only`、`unsupported`；
  - 把澄清优先级与槽位缺口（成品/自做歧义、目标缺失、类目缺失、商品缺失）显式化为结构化 `missing_slots`，而不是散落在 prompt 里；`IntentState` 作为后续 workflow 的只读交接对象，不是 PurchasePlan。
- 非目标：**本阶段不实现采购规划增强**（RequiredItem 需求项、跨目标聚合、单位归一、pantry 量化扣减、购物车占用分配、批量召回）；不接外部搜索；不做专业营养；不引入多 Agent。
- 门槛：Goal/路由纯函数可独立离线验证（典型输入 → 结构化 Goal + route）；不改变 P0 确认/加购与 `can_confirm` 不变量；不宣称语义质量已验收（真实 LLM + 检索 + SSE 验收另算）。实施顺序见 `docs/plans/2026-09-19-purchase-intent-p1-implementation.md`。

**P1.5｜采购规划增强（原 P1：RequiredItem / 聚合 / 购物车分配）**

- 价值：在目标已明确、路由已稳定的前提下，把目标转成可比较、可复算的采购方案（预算、已有食材、库存感知）。
- 范围：需求项独立化与来源证据（§5.2）；§6 的完整单位归一与聚合（含 pantry 量化扣减、购物车占用的需求分配，D8）；§8 的 `constraint_id`/`evidence_ref` 推荐理由；用户自备/多目标去重；批量召回工具（建议新增，按需，见 D11）；`RequirementsProposal`（§3 工具面）接入；方案候选比较与预算超标处理。
- 非目标：不做专业营养；不做全店推荐系统；不引入多 Agent。
- 门槛：P1 的 Goal/路由契约稳定并已被协议/loop 消费；需求项契约稳定；模糊场景与库存感知在离线契约可验证；批量工具与现有限额一起回归。

**P2｜外部知识搜索**

- 价值：支持本地菜谱未收录时，从可信来源解析需求项。
- 范围：§9 的来源→解析→SKU 路线与信任边界；搜索失败/来源冲突诚实降级。
- 非目标：不建微服务、不多 Agent、不新增向量库；不做健康建议。
- 门槛：明确“当前不支持未收录菜谱自动可靠拆料”的限制；独立验收。

**商城/商家系统适配（远期，不是 P2 强制项）**：借鉴 Shopify/UCP 的工具适配与状态分离（调研 §3.5/§3.6、§7 第 8 条），**只在真实需求（真接商城、需要跨商家交接）出现时**再引入；当前不预建协议层、不预建适配器。

---

## 12. 验收矩阵（建议）

三层严格分开：**离线契约**（无真实模型，验证后端确定性逻辑与契约）、**真实 LLM + 检索 + SSE**（验证语义理解与链路）、**将来商家集成**（真接商城后的适配验收）。脚本注入的替身不能替代真实模型的语义验收。**“阶段”列说明该用例属于哪一期门禁**；同一用例在不同阶段可能有不同的门槛，语义/歧义/指代类用例不能用离线替身充当对外验收。

| # | 场景 | 期望 | 层级 | 阶段 |
|---|---|---|---|---|
| 1 | 明确自做 | 生成食材需求项与清单 | 离线契约 | P0 |
| 2 | 明确成品 | 商品检索 + 候选确认 | 离线契约 | P0 |
| 3 | 模糊输入（我饿了） | 只读评估/给选择，不建可确认清单 | 离线契约；**语义变体需真实链路** | P0 |
| 4 | 自做目标的食材 SKU 匹配 | 明确自己做仍做商品检索，不因“不是买成品”跳过 | 离线契约 | P0 |
| 5 | 炸鸡/烤串歧义 | 真实检索，相似须确认 | **真实 LLM + 检索 + SSE** | P0（语义对外验收） |
| 6 | 只问/否定（无具体修改目标） | 只读，不升级；“不要这个”指向具体行时走合法修改 | 离线契约；**语义变体需真实链路** | P0 |
| 7 | 缺主料只买可乐 | `coverage_mode=partial` 可确认，突出缺口 | 离线契约 | P0 |
| 8 | 无可售 SKU | 无已验证可售行 → `can_confirm=false`，不伪装缺货 | 离线契约 | P0 |
| 9 | 未知库存 | `unknown`，不当作缺货，不进可执行选中子集 | 离线契约 | P0 |
| 10 | 数量不足 | 可选已核实数量，差额保留 | 离线契约 | P0 |
| 11 | 两菜共用食材合并 | 需求量按贡献合并、包装可复算（§6 短例） | 离线契约 | P1.5 |
| 12 | 已有但不知量 | 不视为足量，保留需求并标注未知 | 离线契约 | P1.5 |
| 13 | 用户“全有/不用买” | `self_supplied` 与 `waived` 区分，缺口计算不同 | 离线契约 | P1.5 |
| 14 | 购物车已有同款（防双扣） | P0 只提示/收紧上限、不抵扣；P1.5 经确认用途后才分配 | 离线契约 | P0 上限；P1.5 需求分配 |
| 15 | 第二个换便宜点 | 绑定候选与版本，保留其他行与手改数量 | 离线契约；**“第二个”语义需真实链路** | P0 |
| 16 | 商品文本提示注入 | 只当不可信资料，不获得授权、不触发写入 | 离线契约 + **真实 LLM** | P0 |
| 17 | 伪造商品来源 | 目录外/未验证 SKU 不被采纳 | 离线契约 | P0 |
| 18 | 推荐理由事实证据 | 每条理由挂 `evidence_ref`，不造价格/优惠/库存 | 离线契约 | P0（不造事实）；P1.5（逐条证据） |
| 19 | 确认时涨价 | `PRICE_CHANGED`，重新确认 | 离线契约 | P0 |
| 20 | 确认时缺货/过期 | `PRODUCT_UNAVAILABLE` / `PLAN_EXPIRED`，旧快照不复用 | 离线契约 | P0 |
| 21 | 用户明示只买子集 | 缺口可见下可确认该子集（`scope=selected_subset`） | 离线契约 | P0 |
| 22 | 确认时静默删减 | 必须新版本 + 重新确认，不得沿用旧确认 | 离线契约 | P0 |
| 23 | 重复确认/逐行后批量 | 不重复加购（最多一次有效写入） | 离线契约 | P0 |
| 24 | 并发/断线重试 | 旧版本不覆盖新状态，重试命中幂等 | 离线契约 + SSE | P0 |
| 25 | 预算超标 | 明确拒绝或给替代，不静默超支 | 离线契约 | P0 |
| 26 | 搜索缺失/失败、来源冲突 | 诚实降级，不编造 | **真实检索** | P2 |
| 27 | 商城适配（真接商城后） | 工具适配层与状态分界正确，支付交给宿主 | **将来商家集成** | 远期（非本期） |
| 28 | 不知道吃什么 | Goal=`meal_decision`，route=`clarify_goal`，不准备可确认清单 | 离线契约；**语义变体需真实链路** | P1 |
| 29 | 成品/自做歧义（未说明） | `fulfillment_mode=unspecified`、`readiness=needs_clarification`、`missing_slots=[fulfillment_mode]`，不默认自做 | 离线契约；**语义变体需真实链路** | P1 |
| 30 | 超出能力边界 | route=`refuse_unsupported`，不编造方案、不写入 | 离线契约；**语义变体需真实链路** | P1 |

**指标（定义观测口径，不编造数值或 SLA）**

| 指标 | 观测口径 | 目标方向 |
|---|---|---|
| 未授权写入次数 | 服务端审计：每次加购写入是否绑定真实用户操作（`owner_id`/`task_id`/plan 版本/行与数量/`scope`）且携带有受信授权证据；**无论是否新增独立 confirmation 对象都按此判定**（现行逐行加购不需要 `confirmation_id`，不得把“无 ID”直接当成越权） | **0**（硬目标） |
| 重复执行次数 | 同一 `owner_id` + `task_id` + 操作种类 + 幂等键/被消费的计划数量 下发生多次实际写入的计数。**单独的 `selected_digest` 相同可能是用户合法地再次购买同一子集，不得直接计为重复** | **0**（硬目标） |
| Goal 澄清正确率 | 模糊输入中“不擅自建单且给出有效选择”的占比 | 越高越好 |
| 需求覆盖率 | `gaps` 为空的需求项占比（区分 `unknown` 与真实缺口） | 越高越好，但不得靠隐去缺口刷高 |
| 包装换算正确率 | `pack_conversion.formula` 与目录规格一致的比例 | 越高越好 |
| 价格/库存事实一致性 | 对外展示的价格/库存均带当前 `quoted_at` 来源的比例 | 越高越好 |
| 局部修改保留率 | 未被修改行在修订后保持选中态与手改数量的比例 | 越高越好 |
| 工具调用数与回合耗时 | 从 trace 统计，与硬预算（3 次模型调用等）对照 | 观察值，不设 SLA |

不以建单率/加购商品数为唯一目标；**本期不编造 SLA 数字，也不声称这些指标已跑过**。

---

## 13. 待决策清单

- **D1 成品/自做歧义**：“我想吃可乐鸡翅”无上下文时是否先澄清自己做/买成品？建议：澄清。影响：历史验收行为变化与相关测试调整。待审。
- **D2 部分交付默认**：默认生成 partial 还是先问？建议：默认生成 partial 并明确缺口。待审。
- **D3 主料缺失时的告知**：只买调味料时是否必须显著提示“不能配齐原目标”？建议：必须。待审。
- **D4 P0 范围**：P0 是否只覆盖已有菜谱/商品/场景路径？建议：是。待审。
- **D5 外部搜索排期**：是否确认 P0 暂缓、固定到 **P2**（不在 P1/P1.5 提前）？建议：P0 暂缓，固定 P2。待审。
- **D6 代选授权粒度**：A 类授权是否允许系统直接选定目标（仍不建清单、不加购）？建议：A 类允许选定目标；**B 类可与同一条明确消息一并具备**（如“帮我选一道两人做的晚饭，并配成清单”），不再强制“先选目标再要授权”的两轮；**最终加购确认另行绑定具体方案版本**。待审。
- **D7 未知数量策略**：`quantity=null` 时默认建议最小包装，还是先问？建议：核心项先问，非核心项给最小包装建议并标注未知。待审。

新增（本稿补充的关键决策）：

- **D8 购物车占用是否抵扣需求**：已核实购物车占用只收紧可加购上限（现状），还是也抵扣需求数量？若抵扣，如何证明那件商品是本次用途、如何登记唯一来源标识以避免同一条数量被分配两次？建议：P0 维持“只收紧上限 + 提示/询问占用”，抵扣留到 P1.5 且必须先确认用途（§6）。待审。
- **D9 pantry 半知状态的默认行为**：`declared_partial` 且数量未知时，是保留需求并提示，还是直接按“有就不用买”处理？建议：保留需求并提示（不得静默清零）。待审。
- **D10 `can_confirm` 单一来源**：`PlanValidator`、`PlanRevisionService`、`_totals` 三处各自的 `can_confirm` 是否收敛到同一规则？建议：P0 至少做到“同一计划任意路径产出的 `can_confirm` 一致”，不强行合并实现。待审。
- **D11 批量召回工具**：是否在 P1.5 新增批量检索入口（建议名 `search_products_batch`）？建议：先量化现有限额下的缺口再决定，不预先实现。待审。

P1 理解层新增的关键决策：

- **D12 路由归属**：`route`/`readiness`/`missing_slots` 由服务端纯函数根据 Goal 决定（模型只提 Goal），还是允许模型在协议里直接给出 `route`？建议：模型只提 Goal；路由、就绪度与缺口槽位一律服务端纯函数决定，模型不得自定路由。待审。
- **D13 与 D1 的一致性**：`meal_plan` 的 `fulfillment_mode` 未说明时是否一律先澄清自做/成品（而不是默认自做）？建议：与 D1 一致，先澄清；该规则已在 P1 纯函数中实现为 `missing_slots=[fulfillment_mode]`。待审。
- **D14 Goal 与 `Requirements` 的关系**：Goal 是新增的解析层对象，还是直接扩展既有 `Requirements`？建议：`Requirements` 继续作为任务持久化形态，Goal 只在理解/路由层存在，接入时做字段映射，不新建并行状态机。待审。
- **D15 `meal_decision` 的授权级别**：`meal_decision` 是否等同 §4 的 A 类“代选目标”授权？建议：`meal_decision` 只授权只读给选项/澄清，**不**自动升级为清单准备；目标仍需用户选定后才进入准备，最终加购确认始终独立。待审。

---

## 14. 现状证据与历史失败处理原则

- 本文档 §10 的事实来自对当前业务源码的只读核对，优先用函数名定位；行号会随在途改动过时，**以函数名与当前代码为准**。**未运行任何测试**，因此不构成功能通过证据。
- 调研引用指向 `docs/research/2026-09-19-shopping-agent-architecture-survey.md` 的本地章节；那份调研同样未运行第三方项目，其“有实现”不等于“已验证”。
- 上一轮历史失败（完成后改人数补差、改预算、换菜等 8 项）不应被本文档一次性扩进 P0；逐项按“保留需求 / 适配断言 / 真缺口”分别裁决，不得因为断言不便就删除测试。
- 历史测试与模型调用只作为**问题线索**，不作为新功能的通过证据；新链路验收需按 §12 重新采样（离线契约 + 真实模型/检索/SSE）。

*本文档为审阅稿，所有“建议/待审”内容在获得授权前不作为开发依据。*
