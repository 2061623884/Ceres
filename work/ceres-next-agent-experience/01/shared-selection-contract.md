# 01 shared selection contract

后续分类气泡复用公开 `PendingClarification` 与 `TurnRequest.clarification_answer` 契约。问题返回 `question_id`、`slot`、`options[]`；每个选项以 `id` 作为身份，以 `label` 作为展示和提交文本。01 的零食类型选项示例为 `slot=product_type`、`id=product_type:potato_chips`、`label=薯片`。

用户点击选项时，调用 `POST /api/v1/guide/sessions/{session_id}/turns/stream`，body 带上该选项的原文 `message`，以及 `clarification_answer: {question_id, option_id}`。服务端要求问题和选项都仍属于当前待答问题，并检查消息文本与选项标签一致；过期或不匹配返回 409 `STALE_CLARIFICATION`。客户端应回传身份字段，不从显示顺序或标签推算选项身份。自然语言回答仍可走普通消息路径。

选类回合只解析并展示该类型下的商品，不自动生成计划或修改购物车。零食采购的数量与预算在回合间保持为已有 requirements 中的 `quantity` 与 `budget_fen`；SKU 明确后再生成清单，只有明确确认接口提交后才加购。

后续品类可以沿用这套问题/选项/答案线格式、身份校验与过期语义；品类元数据、类型 id 和选项排序需按各自可验证数据定义，不能复用零食的分类推导。
