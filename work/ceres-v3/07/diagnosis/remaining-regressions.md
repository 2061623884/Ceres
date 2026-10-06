# 07 fullregression 剩余失败归因

本报告只覆盖 full run 中 11 个普通失败：P0 gap persistence 3、review probe 1、shared-SKU ledger 1、W03/M1b 3、category 2、S1 cola 1。判断依据是 full 原始输出、对应测试及当前产品/服务代码；没有执行测试或模型。

目前没有证据确认这 11 项暴露了新的生产逻辑缺陷。多数是测试 oracle 与现行契约不符；品类两项还缺少测试所要求的检索索引。多个用例在第一个断言就停止，迁移后仍需按下列最小范围复验，不能将本次归因当作绿测。

## P0 gap persistence：3 项

test_plan_json_persists_the_gap_and_the_requirement_evidence、test_every_read_surface_echoes_gaps_and_intent 和 test_the_reply_names_the_missing_main_ingredient 都在 test_p0_gap_persistence.py 的 _partial_dish 精确集合断言（约第 76 行）失败：测试只允许 enoki_mushroom，full 输出记录的实际多余项是 chili_sauce。三项都在共用 helper 停止，后续持久化、读取、修订及回复断言尚未运行（原始输出见 full stdout.txt 的对应三个失败段，约第 779、829、880 行）。

酸汤肥牛模板把辣椒酱列为 pantry；实际计划记录的是 kind=unknown、unknown_of=quantity、requiredness=optional，该商品行仍可售。plan_contract.is_advisory_gap 明确规定非 core 的未知包装量属于 advisory gap，不单独降低覆盖状态（chinese-dishes-v1.json 酸汤肥牛项；plan_contract.py:472-486, 535-544）。所以这是过窄的 gap oracle，不是错误的缺料判断。

最小迁移：保留对金针菇 core 缺料的精确断言，同时明确验证辣椒酱是 optional/advisory unknown；三项后续断言继续核对两种 gap 的 ID、来源和语义在各读写面保持一致。复验这三个 public API 用例，不能删除 gap 完整性检查或把 advisory gap 从响应中抹掉。

## Review completed-plan 快照：1 项

test_review_completed_people_change_requires_scope_clarification 到第 341 行才失败：state["plan"] == first["plan"]。此前的 completed 状态、gap_fill_scope 澄清、无计划改写、版本、购物车及 replay 断言均已通过。这里比较的是确认前的 /turns 响应与确认后 GET，两个端点阶段的 plan 序列化不完全一致。该次临时库中持久化 GuideTask.plan_json 与首次 plan 一致；GET 端点会从存储 JSON 构造 PlanResponse（guide.py:103-109），因此目前证据指向跨端点响应表示差异，而非澄清轮改写已完成方案（full 临时库 test_review_completed_people_c0/test.sqlite3）。

最小迁移：以确认后立即 GET 的 plan 作为澄清前基线，再比较澄清后的 GET；保留状态版本、plan ID/需求、pending clarification 与购物车不变断言。当前失败仅证明两个阶段的 GET 投影不完全等于最初未确认响应，未证明已存方案被改写。

## Shared SKU 已购数量：1 项

test_remove_preserves_shared_sku_manual_quantity_and_remaining_ledger 在第 198 行期望移除 group A 后 kept["added_quantity"] == 1，full 实际为 2。测试显式把两个 contribution 各设为已购 1、SKU 行总量设为 2，并传入仍有该 SKU 2 件的 cart_quantities。移除只剥离 A 的计划来源，未删除购物车中的商品；保留组 B contribution 为 1 与整行已购总量为 2 可以同时成立。merge_plan 保留原 SKU 已购数量（shopping_plan_service.py:718-723），_collapse 取基础行、贡献和保留 ledger 的最大值（shopping_plan_service.py:1211-1215）。这符合 PROJECT.md:42 所述的行级已购 ledger，以及同 SKU 汇总但保留分组来源的术语定义（GLOSSARY.md:60）。

最小迁移：断言整行已购总数仍为 2、只剩 group B 且其 contribution ledger 为 1；另确认移除方案目标不会静默删购物车里的两件商品。若后续产品要让“移除目标”同时撤销已加购商品，需要另有明确业务动作和契约，本失败没有提出该要求。

## W03/M1b 变更人数状态：3 项

test_w03_gap_fill_clarify_append_or_new_plan:72、test_m1b_gap_fill_2_to_4_via_turns:206 和 test_m1b_gap_fill_second_zero_delta_via_turns:225 都把确认后追问的顶层 task status 断言为 clarifying；full 返回 completed。当前 test_review_completed_people_change_requires_scope_clarification 的契约说明已完成任务仍保持 completed，澄清由 pending_clarification 与 clarification receipt 表达；Step 是 task step（schemas/guide.py:12-23），不能用它替代回答状态。三个用例均在这个 status 断言停止，后续“另做一份”、四人份差额和零差额路径没有在该轮得到验证。

最小迁移：改为断言 task 仍 completed，并核对 pending_clarification.slot == gap_fill_scope；随后继续原有用户回答和业务断言，确认独立新任务、差额数量及零差额响应。重点复验这三个 /turns 场景，不把失败改成只测状态字段。

## Category：两项测试配置/场景不匹配

- test_the_category_page_retrieves_real_products_then_asks（test_workflow_category.py:39-66）断言该用户消息一定没有 plan；full 实际给出 demo:cake-flour-250g，名称为“低筋面粉 250克（小包装）”，当前 offer 为 680 分。消息明确说“小包装，20元以内”，结果符合包装条件且价格低于预算。测试注释只依据模型 target/query 中较短的“面粉”来认定歧义，未反映完整用户输入和实际返回商品，故该失败没有证明错误选品。若要验证歧义追问，应构造至少两个可售候选且用户话语不含能区分它们的条件；若保留当前输入，则应检查所选商品、包装和价格。
- test_a_category_turn_can_plan_a_real_product_but_writes_no_cart（test_workflow_category.py:71-95）的 lookup receipt 为 retrieval_status=unavailable，所以 == "ok" 失败。原始运行环境记录 RETRIEVAL_INDEX_DIR 为空（full command-environment.json）；该测试使用普通 client，而 test_semantic_phase1_purchase.py:16-34 的 indexed_client 才会从临时库构建并发布 lexical index。该失败是测试 fixture 没有提供被断言的真实检索能力，尚不能说明 category runtime 的索引查询坏了。

最小迁移：两例使用 indexed_client；歧义例准备能产生多个有效候选的查询并验证澄清，正例保留真实 lookup receipt、方案可展示且购物车为空的断言。当前第一例计划满足显式输入，但其请求约束经过了哪些筛选步骤尚未单独验证，因此迁移时应让检索候选和约束命中可观察。

## S1 可乐 SKU：1 项

test_cola_chicken_wing_plan_includes_cola 在 test_s1_data_completion.py:80 固定要求 demo:cola-330ml。full 的 TemplatePlanService.validate_template_plan 返回 validation_status=passed，选中 SKU 是 demo:cn-pepsi-original-330ml-can。该商品 fixture 标注 ingredient_ids=["cola"]、330 ml、百事品牌（demo-products.json:1186-1205）；菜谱仅要求 ingredient cola 330 ml（chinese-dishes-v1.json:226-243），没有品牌条件。因此固定 generic SKU 是过度指定的 fixture oracle，不是配错食材的证据。

最小迁移：保持 validation 与鸡翅 SKU 断言；对可乐行验证 ingredient identity 和所需容量/单位，不固定品牌 SKU。只有菜谱或用户要求明确指定品牌时，才断言该品牌。

## 复验范围与限制

修正后优先复验上述 11 项原 public API/service 用例：P0 三项需完整经过 opt-in、持久化、刷新和读取；review 用例以确认后快照作基线；W03/M1b 需走完澄清回答；category 两例必须确认索引确实加载；cola 保持模板验证。full 中 21 个 setup errors、此前单独报告的 P0 coverage 失败以及其他已归因项不在本文重复范围。本文仅归因失败，不代表修正后的用例已经通过。
