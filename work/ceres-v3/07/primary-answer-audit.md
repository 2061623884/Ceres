# 主会话原始回复核对

本记录读取专职测试 Agent 已完成的原始证据，没有执行模型、测试或性能分析。适用 frozen candidate-v5 ZIP `a85bfc70c017999c01833c0969abf7217a4373c49673ca2ed750ef662a3a7dae`；全部受控/真实调用依赖实际 V2 dirty 源码，不宣称 clean HEAD 等同此 ZIP。

真实角色证据在 [role5](evidence/live-role5-v5-089d7f42ae254264b4e23d0615847335/model-evidence/)；实际响应模型为 `kev-latest` 与 `qwen3.8-27b-fp8`，远端角色模型权重 revision 未提供。

- R02：可可给出模拟门店 P-RET-01《签收后退货》的 7 天与可退货商品条件，以及 P-RET-02《不支持退货的商品》的生鲜等例外；明确当前信息不足，不能确认这个商品是否可退。没有要求先选订单，没有外部政策页措辞、实际退货资格保证或采购清单。
- R03：墨墨未选订单回答相同一般政策及例外。只把具体某单资格判断列为需选对应订单，未用选单作为一般咨询前提。
- R01：首次比较后用户明确选择返回的可口可乐零度 500ml 卡片，两瓶；原始 selection SSE 的计划数量为 2、状态 `awaiting_confirmation`。计划保存不是购物车加购授权。named-product variant 的鲜鸡蛋 10枚装数量为 1，同样待确认。
- H01：接受交接后回复包含本轮实际订单 ID，订单原值为 paid、delivered_at=null；回复是已付款、未发货及暂无物流信息，没有把模拟订单表述为真实履约。

独立留出原始证据在 [holdout4/results.json](evidence/live-holdout4-v5-16391552984743c7b6d246e2ae472a60/model-evidence/results.json)。HO01 否定旧查单意图后购物、HO02 引用一般政策均留当前角色；HO03 回答对象澄清后建议墨墨、HO04 同句自我修正后建议可可。HO03 的真实 Kev 前置 clarify 单独保留。HO03/04 terminal 的 `business_not_run` 与 Guide 版本/清单、购物车前后快照均由原记录核对，建议未自动切换或执行目标业务。四例不支持统计泛化结论；角色业务使用受控响应，不能将其计为四个真实角色回复旅程。

退出码、原始命令和前后 312 路径摘要另见 `primary-audit-v5-*.json`；模型质量、性能统计由专职测试 Agent 的原始结果和 analyzer 给出，本人工核对不替代正式前端/本人验收。
