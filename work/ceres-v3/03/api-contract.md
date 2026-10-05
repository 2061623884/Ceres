# V3 聊天入口（03）

`POST /api/v1/chat/openings` 使用已有本人 `guide_session_id`、`mercury_session_id`，role=keke。`GET /openings/{id}` 恢复当前打开状态。每条新消息由 `POST /openings/{id}/turns/stream` 进入，body沿用可可 TurnRequest，额外 `order_id` 只能引用当前owner的实际模拟订单。

首事件 `service.route` 提供 request_id、status、decision、raw_choice/probabilities、criteria_version、route_ms、current_role、target_role/handoff_id、prompt_mode、manual_switch_available。路由从上下文准备到外部响应解析计时；常规P95目标1秒，HTTP有界3秒，无重试或主模型路由兜底。业务等待另计。

stay/unavailable复用当前角色原SSE；clarify与suggest_switch不执行角色业务，返回明确说明。路由失败status=unavailable、decision=null，保留原因，当前角色服务仍可用。可可 data envelope 与墨墨 named SSE保留。一般policy由02处理，不能当订单资格。

前端实际显示 automatic 建议后，调用 `POST /openings/{id}/prompt-displayed`（handoff_id）。明确同意才 `POST /openings/{id}/switches/stream`（target_role=momo、handoff_id、accept=true）；拒绝accept=false留原角色。同意只选择服务，不替代原业务确认。原话不改写、目标重查owner/订单A，不沿用旧选单B；同一交接回放已完成SSE，不再执行。

只用于初步demo/Cursor接口交接；04增补反向、固定入口及明确退出周期，不把刷新当新打开。未声称正式页面已接入或真实模型验收通过。
