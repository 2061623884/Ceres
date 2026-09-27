# Sale-guide 采购意图 P0 实施契约（P0-a/b）

- 日期：2026-09-19
- 状态：**P0-a/P0-b 实施依据**。本文只记录已授权的 P0 范围与最小契约，**不代表** `docs/plans/2026-09-19-purchase-intent-product-plan.md`（下称"审阅稿"）全篇获批准；审阅稿中 P1、P2 及"建议/待审"内容仍未获授权。
- 授权来源：用户授权实施审阅稿 P0，并对若干语义点给出裁决（D2 默认 partial 草稿、D3 明示主料缺口、D4 仅已有路径、D5 不联网、D8 购物车只收紧上限、D10 规则一致；D1 语义不动）。**本文中的具体取值范围（生成用 `partial_ok`、`full` 不授权不完整确认、advisory 缺口规则、cap 方式等）是本实现在该授权范围内的默认选择，不是逐条单独评审过的用户决定**；Codex 复核后若要求变更，以复核结论为准。
- 范围：**P0-a 契约 + P0-b 后端 partial**。前端（P0-c）、verification/evals（P0-d）、模型 `protocol`/prompt、确认与加购的版本/幂等/事务均不在本次范围。

## 1. 本次不做什么

- 不改 D1（成品/自做歧义）语义；不改 `agent/protocol.py`、不改 prompt、不新增模型工具。
- 不新增数据库表/列；所有新结构都落在既有 `guide_tasks.plan_json` 与既有 `PlanItem`/`PlanResponse` schema。
- 不做 P1 完整聚合（跨目标单位归一、pantry 量化扣减、购物车占用的需求分配、批量召回工具）。
- 不改 `_pack_qty` 的换算语义与签名；不改确认服务（`ConfirmationService`）与加购路径的版本/幂等/事务。
- 不接外部搜索/联网。

## 2. 最小契约（P0 冻结）

### 2.1 coverage_intent：请求 / 持久化 / 回显

- **请求**：`PlanRevisionRequest.coverage_intent` 已存在，默认值保持 `"full"`（缺省即"调用方未明示允许部分覆盖"，向后兼容）。**不新增** `TurnRequest.coverage_intent`。
- **生成默认**：所有建草稿路径（dish/product/scenario 的 `validate_plan` 调用）固定传 `coverage_intent="partial_ok"`（D2：默认产出 partial 草稿）。
- **持久化**：`plan_json.coverage_intent`。写入点：`PlanValidator.publish_snapshot`、`ShoppingPlanService.merge_plan`、`PlanRevisionService.revise`、`PlanRefreshService.refresh`（`_carry_purchase_ledger`）。
- **缺失回退**：plan 上没有该字段 → `"full"`（旧计划/合成计划保持严格；侧车与历史用例不受影响）。
- **回显**：`PlanValidator.check_constraints` 出参 → `publish_snapshot` → `PlanResponse` / `PlanRevisionResponse` / `PlanRefreshResponse` / `AddPlanItemResponse` / `plan_ready_payload` / `build_task_response`。任一出口缺字段即视为不合格（Pydantic 会静默丢弃未声明键）。

### 2.2 Gap：唯一结构化缺口权威

`plan_json.gaps` 是缺口（供给/未解析需求）的**唯一权威**；`uncovered_items` 保持既有形状与语义（**用户未勾选的 required 行**），属于兼容投影，不与之混同。

```
gap_id            稳定可复算："{group_id}|{kind}|{required_item_id 或 group#key}"
group_id          例 "dish:dish-sanbei-ji"；建单/修订/刷新/合并路径都不允许为空
target_kind       dish | product | scenario
target_id
kind              not_found | out_of_stock | insufficient_stock | unknown
unknown_of        availability | quantity | null     # 仅 kind=unknown
requiredness      core | optional
required_item_id  稳定需求 id："{target_kind}:{target_id}#{ingredient_id|sku_id|component_id}"
required_item_ids 该行实际覆盖的全部需求 id（两目标共用同一 SKU 时都保留）
ingredient_id     可空
component_id      可空（scenario 组件）
name              可空（中文展示名，来自 fixture / ingredient-catalog，不编造）
sku_id            可空
required_quantity 原需求量（可空，**单位见 unit：g/ml/pc，不是件数**）
unit              原需求单位（可空）
quantity_known    需求量是否已知（可空）
requested_pack_count 包装换算想要的**件数**（可空；与 required_quantity 不同维度）
available_quantity 核验到的可售**件数**（可空）
shortfall_quantity 差额**件数**（可空）
source            {"kind": user|local_recipe|scenario|catalog, "ref": ...}（可空）
evidence          {"sku_source":"store_offer","quoted_at","stock_verified","data_mode",
                  "source_note","unknown_constraints"}（可空，见 2.5）
message           服务端生成的中文文案；仅用于展示，不作为任何事实来源
```

维度纪律（审查修复）：**需求量（g/ml/pc）与件数永远不混用**——`required_quantity`/`unit` 只能来自 requirement，件数只能进 `requested_pack_count`/`available_quantity`/`shortfall_quantity`。

身份与消解规则：gap 的身份是它的需求（`required_item_id`，没有则 group+key）。`collect_gaps` 先算所有**当前存在**的行/贡献需求身份；同一需求如果现在有行承担，旧 carried gap 一律丢弃（已解决/已补货不得留下陈旧缺口），行上的新鲜事实覆盖旧值；若一行覆盖多个目标，每个目标各得自己的 gap，删除其中一个目标只退掉它自己的缺口。

派生与合并规则（唯一权威、可复算）：
- 行上带 `shortfall_quantity > 0` 或 `availability == "insufficient_stock"` → 派生一条 `insufficient_stock` gap；
- 行上出现 `out_of_stock`/`not_found`/`unknown`（正常路径不会保留这类行）→ 派生对应 gap，且该行**不可选**；
- 无行的需求（未解析到 SKU 的必需食材、scenario 缺失组件、产品未售/缺 offer）→ 由建单方作为 carried gap 传入；
- `collect_gaps(carried, items)` 按需求身份去重：行/贡献现在承担的需求，其 carried gap 一律**丢弃**（已解决不得留陈）；行上的新鲜事实覆盖旧值，不能被旧 gap 反向覆盖；
- 按 group 合并/替换：`merge_plan` 在处理某 group 时先移除该 group 的旧 gap，再并入新 gap；`remove` 一并删除该组 gap；行派生 gap 的 `group_id` 取自行/贡献（建单路径由 validator 写入 target_context，不再出现空 group）。

### 2.3 RequiredItem / Fulfillment：最小需求与供给证据（不落 P1 数组）

P0 **不落**完整 `required_items[]`/`fulfillments[]`，但每个计划行与每条 gap 必须携带可回溯的最小证据（内嵌，不新增表）：

- 行：`required_item_id`、`requirement`（`name`/`ingredient_id`/`quantity`/`unit`/`quantity_known`/`requiredness`/`source`）、
  `availability`、`evidence`（`sku_source`/`quoted_at`/`stock_verified`/`data_mode`/`source_note`/`unknown_constraints`）、
  `pack_source`（`catalog_spec` | `assumed_one`）、`shortfall_quantity`；行的 `contributions[]` 逐项携带 `required_item_id`/`requirement`，
  两个目标共用同一 SKU 时两边的需求证据都保留。
- gap：见 2.2（含 `required_item_id`/`required_item_ids`/`source`/`required_quantity`/`unit`/`quantity_known`/`requested_pack_count`/`evidence`）。

"仅写 schema 却不落证据"视为不合格。

### 2.4 覆盖规则（单一规则，所有路径一致）

```
unselected_required = role=="required" 且未勾选 且行可选
advisory_gap        = kind=="unknown" 且 unknown_of=="quantity" 且 requiredness!=core
                       （可选/自备行的包装规格未核实时仅提示，不单独降级覆盖）
degrading_gaps      = gaps 中非 advisory 的全部缺口
mode = "uncovered"  若 unselected_required 且 intent ∉ {partial_ok, user_supplied}
     | "partial"    若 (degrading_gaps 非空 或 unselected_required) 且有已选行
     | "uncovered"  若 (degrading_gaps 非空 或 unselected_required) 且无已选行
     | "user_supplied" 若 intent == user_supplied
     | "full"
can_confirm = 有已选行 且 有未买量（remaining>0） 且 无 over_stock 且 mode ∉ {uncovered}
             且 若 intent==full 则 不得存在 degrading_gaps / unselected_required
```

- `intent` 对"用户未勾选 required 行"和"真实供给缺口"都生效：`full` = 调用方**未授权**不完整确认，此时计划仍诚实地报 `partial`，但 `can_confirm=False`；只有 `partial_ok`（或生成时的默认意图、`user_supplied`）才允许确认不完整计划。生产路径（dish/product/scenario 建草稿）固定 `partial_ok`，因此草稿可确认；集成方如果在修订时不回显意图，得到的就是严格的 `full`；
- 供给缺口一律给出 `partial`/`uncovered`，绝不因 intent 为 `full` 而谎报 `full`；
- **advisory 缺口例外**：可选/自备行（pantry、scenario optional）的"用量/规格未核实"仍落 `gaps` 与文案，但不单独把整份计划的覆盖降级——覆盖度讲的是需求项满足程度，可选行不是硬需求。核心需求的未知规格、以及所有缺货/未售/库存不足缺口（无论 requiredness）都会降级；
- `over_stock`（`max_addable_quantity < quantity - added_quantity`）继续使 `can_confirm=False`：用户改量超上限仍不可确认；
- **已买完**：所有已选行 `remaining_quantity == 0` 时 `can_confirm=False`（逐行加购后不能把同一行再确认一次）；
- **零可售行**：返回形状完整的计划（`items` 可为空、`gaps` 保留、`coverage_mode="uncovered"`、`can_confirm=false`），不是"空 items + failed 丢缺口"。

### 2.5 未知供给 / 未知规格（诚实降级）

- 供给事实的**唯一来源**是本店 offer 快照：`evidence.sku_source="store_offer"`，带 `quoted_at`、`data_mode`（`business_data_mode`）与 `source_note`（明确标注"本店 offer 快照，不是外部实时库存源"）；不得暗示实时外部库存/价格；
- `offer` 缺失、`sellable`/`available_qty`/`price_fen` 为 None（本店无供给信息，或测试 stub）→ gap `unknown` + `unknown_of="availability"`，**行不进入计划、不可选**，`evidence.stock_verified=false`；缺硬属性绝不静默当作可售；
- `sellable == False`（明确未售）→ `not_found`；`available_qty == 0` → `out_of_stock`；`0 < available_qty < 需求量` → `insufficient_stock`；
- 缺规格/单位导致 `_pack_qty` 回退为 1 件 → 保留该 1 件建议，但行标 `pack_source="assumed_one"` 并产出 `unknown` + `unknown_of="quantity"` gap，文案说明"按最小包装给了 N 件建议"，绝不宣称"配齐"；购买件数确定且供给硬约束通过时允许 partial 确认；
- 单位不兼容导致 `_pack_qty` 返回 `None` 的食材 → `unknown` + `unknown_of="quantity"` gap（**没有行**），文案说明"无法换算、本次没有加入购买"，不得按名字或让模型猜换算，也不得套用"给了 1 件建议"；
- `not_found` 只描述目录/检索结果（"当前目录里没有找到/本次检索没有找到"），不得写成"本店没有/本店不卖"；
- `_pick_sku` 改为在"有货候选"里选最便宜：只有该食材全部候选都零库存时，才产生 `out_of_stock`；不得因为挑到零库存候选而误报全店缺货。
  （注意：检索层 `RetrievalService` 本身已把零库存商品从模型候选中过滤，因此"商品直购缺货"主要通过服务/建单边界与竞态触达，不由检索路径暴露。）

### 2.6 数量不足（已授权行为）

- 准备阶段：行数量取 `min(需求件数, 已核实可加购数量)`（可加购 = `available_qty − 该 owner 购物车已占用`，沿用现有 `max_addable_quantity` 口径），保留原需求件数（`recommended_quantity`）与差额（`shortfall_quantity`）→ 产出 gap 与文案，`can_confirm` 由 2.4 规则决定；
- 确认阶段不静默删减/改量（确认服务不改；确认严格比对已选子集与快照）；
- 用户修订超上限仍拒绝（`PlanRevisionService` 既有 422）或不可确认（`over_stock`）；
- 这不是加购授权：gaps 与 partial 都只存在于待确认计划。

### 2.7 scenario 与 optional

- 场景组件是"自由选购"（`role=optional`），**取消勾选本身不阻塞**（无供给缺口时 `coverage_mode` 仍为 `full`，`can_confirm` 取决于是否有已选行）；
- 场景存在真实供给缺口（组件缺货/未收录） → `coverage_mode=partial`（不再是强行 `full`），`missing_components`/`unavailable_items` 改为由 gaps 派生的兼容投影，不再独立计算。

## 3. 实施步骤

1. **P0-a**：本文件 + `backend/app/services/plan_contract.py`（纯函数：intent/gap/coverage/signature）+ `backend/app/schemas/guide.py` 向后兼容新增字段（不启用行为）。
2. **P0-b**：按消费顺序落地 —— `plan_validator` → `template_plan_service` → `shopping_plan_service`（`_validate_target`/`build_scenario_plan`/`merge_plan`/`_totals`/`_content_signature`）→ `prepare_purchase_plan` → `plan_commit_service`（如需）→ `plan_revision_service` → `plan_refresh_service` → `plan_item_service` → `agent/responses.py`（出口与文案）。
3. **测试**：新增 `backend/tests/test_p0_partial_plan.py`、`test_p0_coverage_consistency.py`、`test_p0_gap_persistence.py`；按批准契约调整 `test_dish_plan_images.py`、`test_shopping_workflow.py::test_second_dish_without_stock_keeps_the_first_plan` 的断言（不删除）。

## 4. 已实施的行为变化（需复核）

1. **追加目标带缺口不再整单拒绝**：`merge_plan`/`PlanCommitService` 统一走 partial（`backend/tests/test_shopping_workflow.py::test_second_dish_without_stock_appends_a_partial_group_and_keeps_the_first`）。旧行为是 `plan_effect=keep` 且不改动现有清单；新行为是把带缺口的新分组 append 上去，旧分组每一行仍保留。
2. **57/101 道菜含 `assumed_one` 包装回退**：这些菜的行来自缺规格的 SKU，按 D7/裁决 3 保留 1 件建议但同时产出 `unknown/quantity` 缺口；其中核心需求未知的菜由 `full` 变为 `partial`（可选/自备行属 advisory，不单独降级）。
3. **选货不再被零库存候选拖垮**：`_pick_sku` 优先有货候选，因此"把某个 SKU 库存置 0"不再等于"这道菜缺货"；测试需把同食材的全部 SKU 归零。
4. **零可售行返回计划而非错误**：`validate_template_plan` 不再返回 `failed + items=[]`，而是 `passed` + `uncovered`/`can_confirm=false` + 完整 gaps。
5. **`full` 不再允许不完整确认**（Codex 复核修复）：`full` 下真实缺口仍报 `partial`，但 `can_confirm=false`；集成方需回显计划自己的 `coverage_intent` 才能确认 partial 草稿。历史探针 `test_review_cannot_confirm_missing_required_material` 不受影响（它本来就期望不可确认）。
6. **刷新不再搬运陈旧供给事实**（复核修复）：`PlanRefreshService.LEDGER_ROW_KEYS` 只带身份/台账（`required_item_id`/`requirement`/`contributions`/`added_quantity`/`quantity_source`/`user_quantity`/group 信息）；`availability`/`evidence`/`shortfall_quantity` 以刷新时的新核算为准（`quoted_at`/`stock_verified` 也随之更新）。刷新时会把整行（含 `quantity_source`）交给校验器，不会把用户手改数量缩回推荐值。
7. **修订重算差额**（复核修复）：`PlanRevisionService._enrich_item` 按 `recommended_quantity - 用户件数` 重算 `shortfall_quantity`/`availability`（改回推荐件数就清缺口，改低就保留缺口），并刷新 `evidence.quoted_at`。

## 5. 验收映射

| 验收 | 落地 |
|---|---|
| 契约先落盘、schema 向后兼容 | 本文件 + `plan_contract.py` + `schemas/guide.py` 新增可选字段 |
| 缺口/证据可持久化与回显、无平行权威 | `plan_json.gaps` 唯一权威 + `uncovered_items` 兼容投影 + 各出口透传 |
| dish/product/scenario/merge/revise/commit 可产出 partial | 各路径统一调用 `plan_contract.coverage` |
| 有已核验可售选中行且硬约束通过 → `can_confirm=true`；无可售行 → `false` | 2.4 规则 + 零可售行完整计划形状 |
| 未知规格不宣称配齐、未知库存不当缺货且不可选；未知硬属性不静默通过 | 2.5 + `test_p0_gap_integrity.py::test_an_unverified_supply_attribute_is_unknown_not_a_crash` |
| 旧版本拒绝/确认价格库存复查/逐行后批量不重复 | 不改确认与加购路径；新增回归用例 |

## 6. P0-c 前端实施（已落地）

范围：`frontend/src/lib/guide-client.ts`、`guide-persist.ts`、`components/guide/{GuideProvider,PlanEditor,PurchaseDock}.tsx`、`frontend/tests/`。不改模型协议/prompt/后端业务语义。

- **类型与契约**：`PlanItem` 增加 `required_item_id`/`requirement`/`availability`/`evidence`/`pack_source`/`shortfall_quantity`；新增 `CoverageIntent`、`PlanGap`、`PlanResponse.gaps/coverage_intent`、`RevisionResponse.gaps/coverage_intent`、`AddPlanItemResponse.gaps/coverage_intent`；纯函数 `normalizeCoverageIntent`/`coverageIntentOf`/`planGaps`/`isAdvisoryGap`/`isBlockingGap`。
- **意图回显**：`GuideProvider` 所有 `saveDraft` 不再写死 `'full'`——修订请求带 `coverageIntentOf(basePlan)`，草稿保存用服务端返回的 `coverage_intent`（缺失才回退）。旧计划/旧草稿（无该字段或值不可识别）一律读作严格的 `'full'`（`normalizeCoverageIntent`），**不会**被前端"升级"为 partial。
- **新版本权威**：修订/`row-add`/刷新后的 `gaps`、`coverage_mode`、`coverage_intent`、`uncovered_items` 全部合入 `currentPlan`；`applyPlanEffect`/`applySession` 始终以服务端 plan 为准，恢复会话时**不用**草稿里的 basePlanId/items/intent 覆盖服务器计划（草稿只恢复输入文本）。
- **缺口展示**：`PlanEditor` 分两类渲染——`plan-gaps` 展示阻断缺口（有 core 缺口时置顶"部分商品本次不能配齐，不能配齐原目标"），文案只用服务端 `message`（缺字段才退回 name/sku_id），不重算价格/库存/单位；`unknown` 显示为"供给信息未核实"，**不**写成缺货；可选/自备行的 `unknown/quantity` 缺口作为提示区 `plan-advisory-gaps`，不当作必需缺口；无可售行时 `empty-plan` 仍显示原因。
- **receipt 不暗示完整**：已确认单据在存在阻断缺口时显示 `receipt-gap-note`（本次只确认了已列出的商品）。
- **确认按钮**：partial（`coverage_mode==='partial'` 或存在阻断缺口）时文案为"确认已选部分"，并附 `partial-confirm-hint`；可用性仍以服务端 `can_confirm`/`available_actions` 为准（`canConfirm` 不变）。
- **confirm 载荷**：保持既有行为——用 `currentPlan.plan_id/plan_version` + 当前 `state_version/session_version` + `confirmableItems(planItems)`（已勾选且 `quantity - added_quantity > 0`），逐行加购后不重复买同一行。
- **显式请求 partial（不静默改服务端）**：当用户**自己取消勾选一个 required 行**，且当前计划意图不是 `partial_ok` 时，前端才在该次修订请求里带上 `coverage_intent: 'partial_ok'`，并显示 `coverage-notice`（"已按你的选择改为只买勾选的部分：未勾选的主料不会购买，缺口会保留在清单上"）。其他任何路径都不会改写意图：不改勾选就不改意图；服务端回显的 `coverage_intent` 一旦成为计划自身值，就是后续修订的基准。
- **前端离线测试**：`frontend/tests/purchase-intent-p0.test.tsx`（8 例）覆盖缺口分类显示、unknown 不被称作缺货、无可售行确认按钮禁用、partial 修订请求带 `partial_ok`、legacy 计划不被升级、**用户取消勾选 required 行才显式请求 partial 并给出明文提示**、草稿持久化与重载、confirm 精确版本/剩余量、恢复会话不被旧草稿覆盖。

## 7. P0-d 验证实施（已落地）

- `verification/test_purchase_intent_p0.py`：使用 `verification/conftest.py` 的合成无网 fixture（不连真实库/不调用模型），覆盖部分确认写入、旧版本/涨价/不可售/过期拒绝且不动购物车、重复确认幂等重放、逐行加购后批量不重复；矩阵由 `evals/v1/purchase-intent-p0-offline.jsonl` 驱动（每个 case 声明 `layer: offline_contract` 与真实 test nodeid，测试读取并校验映射后再执行）。
- `evals/v1/purchase-intent-p0-offline.jsonl`：独立 P0 离线矩阵，**不修改** `evals/v1` 既有 live 用例，也不把离线契约混称为语义验收。

## 8. 未验证项（不得写成全绿）

- **真实 LLM + 检索 + SSE 的语义验收未做**（本机未接真实 provider/索引）：P0-c/P0-d 只证明"离线工程闭环"，不证明"模糊需求 → 目标 → 需求项 → 供给匹配"的语义质量，也不证明歧义/指代类场景。
- 后端全量套件未由本阶段重跑；已知基线为 **11 个历史失败**（`test_read_tools` 2、`test_review_probes` 2、`test_review_stream_contract` 1、`test_shopping_workflow::test_partial_shorthand...` 1、`test_task_lifecycle::test_switch_goal_gongbao` 1、`test_w_dish_and_gap` 4），本阶段未修复、也未把它们写成通过。
- 前端 79 例（基线 71 + P0-c 新增 8）与 `tsc --noEmit` 已通过（退出码 0）；verification P0 文件 10 例已通过（退出码 0）。这三项均为**离线**结果。

## 9. 最终复核修复（合并台账 / 未知供给 / 手改差额 / 版本与预算）

四个独立复现的问题与修法：

1. **合并台账**（`ShoppingPlanService._collapse`）：`max_addable_quantity` 是"还能再加多少"的余量，不能当总上限。旧实现把它当总量上限，导致 `需求3/已加2/库存3/车内2` 得到 `quantity=1, added=2, remaining=0`（总量小于已加）。现在 `capacity = added + max_addable`，`quantity = max(added, min(wanted, capacity))`：上例得 `quantity=3, added=2, remaining=1, shortfall=0`；`max_addable=0` 且未加时保留 1 件 + 差额（仍 `over_stock ⇒ can_confirm=false`，不谎报）。
2. **校验旧行时重查真实 offer**：合并路径重新读取 offer——缺 offer / `sellable`/`available_qty`/`price_fen` 为 None ⇒ `unknown`（不可执行、不当作缺货，None 不再抛异常）；`sellable=False` ⇒ `not_found`；`available_qty=0` ⇒ `out_of_stock`。旧行**不删除**，保留为不可执行 + gap + `can_confirm=false`（不自动加购，UI 可读），`evidence.stock_verified=false` 并附 `unknown_constraints` 原因。
3. **手改数量不抹掉需求差额**：`_collapse` 对手改行同样按 `recommended_quantity - quantity` 重算 `shortfall_quantity`/`availability`（并保证不低于已加台账），故 `用户1/推荐3` ⇒ `shortfall=2`、`insufficient_stock`、`coverage_mode=partial`（不再 `full`）；`PlanRevisionService._enrich_item` 与刷新路径仍按同一规则重算。
4. **可执行事实改变推进版本**：`_content_signature` 增加 `unit_price_fen`/`max_addable_quantity`/`availability`/`shortfall_quantity`（**不含** `evidence.quoted_at` 之类易变时间戳），价格/库存变化不再复用旧 `plan_version`。
5. **合并后的预算硬约束**：单目标校验只看自己的行，合并总额可能超出任务已存预算。`PlanCommitService.apply_result` 在写入前加窄门：`selected_total_fen > requirements.budget_fen` ⇒ `can_confirm=false` + `budget_exceeded=true`（不改预算模型；确认路径原有的预算拒绝保持不变）。

## 10. 验收记录（截至 2026-09-19 本轮）

**独立复跑（Codex）**
- 后端全量：`612 passed / 11 failed / 1 skipped / 1 deselected`，**exit 1**，日志 `work/purchase-intent-p0/codex-backend-full.log`；失败 nodeid 与基线 11 项**完全一致**（`test_read_tools::test_a_named_product_query_returns_that_product`、`test_read_tools::test_two_topics_do_not_return_the_same_rows`、`test_review_probes::test_review_completed_people_change_requires_scope_clarification`、`test_review_probes::test_review_combined_people_and_budget_does_not_drop_budget`、`test_review_stream_contract::test_s06_mixed_explain_and_budget_updates_plan`、`test_shopping_workflow::test_partial_shorthand_resolves_against_the_shown_candidates`、`test_task_lifecycle::test_switch_goal_gongbao`、`test_w_dish_and_gap::test_w03_gap_fill_clarify_append_or_new_plan`、`test_w_dish_and_gap::test_w06_dish_negation_switches_to_new_dish`、`test_w_dish_and_gap::test_m1b_gap_fill_2_to_4_via_turns`、`test_w_dish_and_gap::test_m1b_gap_fill_second_zero_delta_via_turns`），**没有新增失败，但也不是全绿**；本阶段未修复这 11 项。
- 前端：`npm test -- --run` = `79 passed`（基线 71 + P0-c 8），`npx tsc --noEmit` exit 0。
- `verification/`：组合侧车验收为 `54 passed`（含本文件 10 例；P0 文件单独复跑为 10 passed）。

**本阶段实际运行的测试**（日志均在 `work/purchase-intent-p0/`）
- `tests/test_p0_gap_integrity.py` + `tests/test_p0_coverage_consistency.py` → **29 passed，exit 0**（`p0-final-backend-2.log`）。
- `verification/test_purchase_intent_p0.py` → **10 passed，exit 0**（`p0-final-verification-2.log`）。新增两例为真实生成/持久化/修订/确认闭环与合并预算门；矩阵 `evals/v1/purchase-intent-p0-offline.jsonl` 增至 10 条并由该文件读取校验后执行。

**未验证 / 不得宣称**
- **真实 LLM + 检索 + SSE 的语义验收未做**；歧义、指代、模糊需求类场景未验。
- **浏览器手测（Playwright/390px/1440px）未做**。
- 侧车（`verification/`）只证明离线工程闭环：不发真实模型、不连真实运行库、不覆盖语义质量。
- `budget_exceeded` 目前只持久化在 `plan_json`（`can_confirm=false` 会在 UI 上禁用确认），**没有专门的 UI 文案**，属 P0-c 冻结范围外。
