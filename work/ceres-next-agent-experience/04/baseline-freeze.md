# 04 Prompt 模块化前基线冻结

## 冻结身份

- 不可变 before worktree：`work/.ceres-next-04-before`
- Git：detached clean HEAD `91ca0b80161dada5c83fa5955b8a27043172299d`（与04开发树起点相同）
- 04开发者在另一工作树 `work/.ceres-next-04` 写入新增首条 red 测试；本冻结的源码不随开发树变化。
- 证据目录：`work/ceres-next-agent-experience/04/`。真实 baseline/candidate 样本必须分别从冻结 before 和冻结后的 candidate 版本运行；每个代表 case 每 arm 最多一次，失败照录，不重试刷绿。

## 代码与调用链版本

SHA256（before tree）：

- `backend/app/prompts/semantic.py`: `5C4E4F3C4737C417C9FCC0F4882E2FEB0EBED6C5AA262CCA711B28AEBFCB7352`
- `backend/app/llm/live_semantic_provider.py`: `4BD7CE310988D26B88B04B66AF4D632B0AEDA6C24941A796D60E2CD1E6401FF2`
- `backend/app/llm/kev_provider.py`: `C674577CD038C82443E3B064BE58A40504812E65C52AD7F51180D761E55A370D`
- `backend/app/agent/graph/nodes/capability.py`: `6579EC3AED46943FBFF71192594E7ACA548E82CC44E44FEA80DC3768A9CE0C22`
- `Mercury/mercury/prompt.py`: `CFB8F701D4AEA1642C64DAA2B6F56703E351D0F7B4D00249A9F03883194FD870`
- `scripts/seed_runtime.py`: `BA4EFABE4287A6A9A7534CC303EF4E4A80878574B9156F6951BD9FF0993436B4`
- `backend/tests/conftest.py`: `673B1E1547AE054D44A852B199086ACF3667C90EE9BDEA1F4FB5185A14486572`
- `backend/tests/support/semantic_agent.py`: `AB85050744C3ABD05B2CC7EEF9392EC18487644BF61B69BADBF04DC3EEBA075E`

## 数据、索引与测试模式

- before tree 中 `data/sale_guide.db` 不存在；`seed_runtime.seed_from_source` 对不存在源 DB 返回 0。不要把原工作树被忽略、带 WAL/SHM 的数据库当作此冻结数据。
- 可复现 demo fixtures 位于 `data/fixtures/`，分别记录 SHA256：
  - `demo-products.json` `0A54260D2AB18788D630D0BEFC9C8EBE8E7BF0773EE507562FAAA32688508DE7`
  - `store-offers.json` `CCF76B3908DEAB2F904D52DB820316F288D8B75BA105099DD30B221D7530E3FA`
  - `catalog-review.json` `937EE32E6378622D3163B050CDECFF7520CA1536EAA35BD938CDB13463602C8B`
  - `default-offer-prices.json` `CF694736A5A0EB4A369B7792784D128116E5358A1BD755A72DA2DB32D73844A0`
  - `purchase-templates.json` `8DB52FAEC481BEFFDDDA8776E5D2940523E91635A90711E61E91EBAE0121DE33`
  - `shopping-scenarios.json` `A223FB587120BCDB36185E1A86EA1E1AEB62826CBE06735FD4866636BF268697`
  - `chinese-dishes-v1.json` `930DFB18EC7E27BB4FE0549D88A3EE705058550327FF289D3FA3987BE5C88CEC`
  - `ingredient-catalog.json` `3EC018051B0B95D5C1C1F5505F63C960C89C984CFBABB5F8F34068F4C3862607`
- 受控业务测试通过独立 SQLite fixture seed；`test_semantic_phase1_purchase.indexed_client` 从各自临时 DB 重建 lexical index，`embedding=None`、`vectors=None`，并显式设 `RETRIEVAL_MODE=lexical`。这不是默认 hybrid runtime 的验证。
- before/candidate 实际 prompt 对照应复用同一冻结 demo fixture、同一业务输入/上下文和同一检索结果，仅改变 prompt 组织；记录模型、实际发送的 `model/messages/temperature/max_tokens/response_format`、响应、usage、各阶段耗时。无 usage 必须记 `null`。不采 headers、Settings 或凭据。
- 依据：`backend/tests/test_semantic_phase1_purchase.py` fixture；`backend/tests/conftest.py`；`scripts/seed_runtime.py`。

## 固定代表案例

以下刺激来自 before tree 已有用例；case 文本和执行上下文应在两 arm 保持相同。真实模型样本仍待本文件更新样本证据链接。

1. `snack_type_first`：可可当前页，用户“来点零食”；从 `backend/tests/test_ceres_next_snack_choice.py` 的宽泛零食旅程及 `test_ceres_next_capability_routing.py` 的公共分类场景取证。检查分类/商品事实由同一业务数据支撑。
2. `same_category_cola_filter`：可乐比较/筛选多轮。来自 `backend/tests/test_v2_cola_comparison.py::test_comparison_choice_revision_ack_and_explicit_confirmation`：首轮“比较可口可乐多件装，整包不超过20元”；选择商品生成计划但不加购；确认后再输入“只看1元以下的可乐”。这是同类筛选且保留既有计划的案例，不代表一般购买筛选的全部范围。
3. `keke_return_policy`：可可商品页上下文 `demo:cn-coke-zero-500ml-bottle`，用户“这个商品不喜欢能退吗”，仅根据 policy source 回答且无订单/购物写入。来自 `backend/tests/test_v3_core_evaluation.py::test_keke_policy_stays_and_answers_with_source[R02]`，策略 `P-RET-01`。
4. `momo_selected_order_return`：先分别创建两个鸡蛋模拟订单，显式选中第一单，再输入“我要求退这件商品”；模型对选中订单请求 `create_return`，因为订单未签收应答拒绝并且不写 return。来自 `backend/tests/test_v2_order_mercury.py::test_explicit_aftersale_uses_selected_order_and_existing_eligibility[create_return-1]`。每个 arm 必须各自创建新 owner/session/order，不复用订单或状态。

## 04验收边界与当前待办

- 04验收要求核对两角色聊天链路实际行为，四类可可能力及墨墨一般咨询/明确订单业务不退步；仅模块组织变化作对照，见 `tasks/ceres-next-agent-experience-04-prompt-modules.md:19-23`。
- 本文件冻结代码、数据来源和已有案例；真实请求/响应/usage/耗时还未执行。待完成：在 before tree 对以上案例建立隔离 arm 并各采样一次；候选模块版本稳定后用完全相同的 fixtures/cases 再各采样一次；先运行新增公开红绿和必要的两角色回归。不要将07新增商品数据混入04/05对照。
- current evaluation manifests: `evals/v3/core-cases.json` SHA256 `48795E7F53608091CB00F1A85A5662B75EAF704761851EE4F86C2B9391BB1464`; `evals/v3/holdout-cases.json` SHA256 `8D071C4725EC3FF95CD5E078F3E5DB5A0528BCB9F70D42010E99C4558E09F792`。本票固定代表集是用于开发对照，不等同独立 holdout。
