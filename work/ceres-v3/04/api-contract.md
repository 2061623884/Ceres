# 04 最小 demo API 契约

本契约服务于 `work/ceres-v3/03/demo.html` 的同源 API demo（由 `GET /api/v1/chat/demo` 提供），不约束正式 React 页面。demo 不模拟路由或业务结果；路由、业务 SSE 和打开周期均以当前服务端接口为准。

## Owner 与角色会话

所有请求使用 `credentials: "include"`。首次创建角色会话时，服务端创建匿名 owner 记录并通过 `sg_owner_id` HttpOnly、SameSite=Lax cookie 返回身份；不在 JSON 中传 owner ID。Guide 与 Mercury session 必须由同一 cookie 创建，创建 opening 时也由该 cookie 校验归属。把其他 owner 的 session ID 传入 opening 返回 403 `SESSION_FORBIDDEN`。

进入新打开周期前，如没有保留的角色 session，可依次调用：

```http
POST /api/v1/guide/sessions
Content-Type: application/json

{"entry_context":{"page":"home"}}
```

```http
POST /api/v1/mercury/sessions
Content-Type: application/json

{}
```

分别读取响应中的 `session_id`，再创建 opening：

```http
POST /api/v1/chat/openings
Content-Type: application/json

{"guide_session_id":"<guide-session>","mercury_session_id":"<mercury-session>","role":"keke"}
```

`role` 可为 `keke` 或 `momo`，省略时默认为 `keke`。响应含 `opening_id`、两个角色 session ID、当前 `role`、`prompt_displayed` 和当前 handoff ID（GET 不返回 handoff 状态）。浏览器在当前 tab 的 `sessionStorage` 保存 opening ID 和角色 session ID。

## 打开状态与版本

```http
GET /api/v1/chat/openings/{opening_id}
```

返回同一 opening 的当前角色、两个 session ID、提示额度标记与待交接 ID。此 GET 只恢复状态，不创建 opening，也不重置额度。刷新时先 GET 已保存的 opening；只有用户明确结束后再次进入才 POST 新 opening。

每次恢复、发送完成或角色切换完成后，读取：

```http
GET /api/v1/guide/sessions/{guide_session_id}
```

以响应中的 `task_id`、`state_version`、`session_version` 作为下一次导购请求的 `expected_task_id`、`expected_state_version`、`expected_session_version`。`task_id` 是 `GuideSession.current_task_id` 的 API 字段名；无当前 task 时为 `null`，无 task 的 `state_version` 为 `0`。版本不从旧角色或聊天 SSE 缓存推断。

## 消息、提示与切换

```http
POST /api/v1/chat/openings/{opening_id}/turns/stream
Content-Type: application/json

{"request_id":"<unique-id>","message":"<原话>","expected_task_id":null,"expected_state_version":0,"expected_session_version":0,"order_id":"<可选的明确订单 ID>"}
```

`request_id` 与非空 `message` 必填；`expected_state_version` 必填且不小于 0，其余 Guide 字段遵循现有 `TurnRequest` schema。`order_id` 仅在本轮明确指定订单时附上。相同 request ID、相同 body 的已完成请求回放原 SSE；相同 ID 换 body 返回 409 `IDEMPOTENCY_CONFLICT`，相同 body 仍在处理中返回 409 `TURN_IN_PROGRESS`。

当 `service.route` 的 `prompt_mode` 为 `automatic` 时，客户端先把切换询问渲染为可见内容，再调用：

```http
POST /api/v1/chat/openings/{opening_id}/prompt-displayed
Content-Type: application/json

{"handoff_id":"<route 中的 handoff_id>"}
```

成功响应仍是 opening 状态。只有该确认消耗本次打开的自动提示额度；接受、拒绝、手动切换和 GET 均不重置。`fixed_entry` 或 `none` 不发送此确认。

回答切换询问：

```http
POST /api/v1/chat/openings/{opening_id}/switches/stream
Content-Type: application/json

{"target_role":"momo","handoff_id":"<可选 handoff ID>","accept":true}
```

自动询问使用对应的 `handoff_id`。`accept:false` 表示拒绝，当前角色继续，未处理 handoff 保留给固定角色入口；它不再作为下一轮 Kev 的待答问题。固定入口由用户直接选择 `target_role`，不需要二次确认，也可省略 `handoff_id`：若该目标正有未处理诉求，则续接一次；否则只返回 `service.switch` 的 `resumed` 状态并恢复目标会话，不重放旧消息。接受有效 handoff 才执行目标业务；已完成/失败的 handoff 按服务端回执行为处理，不由 demo 再提交原话。

## SSE 与错误

响应类型为 `text/event-stream`。读取空行分隔的完整 SSE block，兼容 CRLF 与 LF。当前业务流存在两种既有编码：可可路由事件为 `data: {"type":"...","payload":{...}}`；墨墨切换/业务流为命名 `event: ...` 加直接 JSON `data: {...}`。Guide 原业务流使用 JSON envelope 的 `type` / `payload`。客户端按 named event 优先、否则读取 envelope；不要假设只有一种角色编码。

服务路由事件可包含 `decision`、`current_role`、`target_role`、`handoff_id`、`prompt_mode` 和 `route_ms`；路由建议的本轮以 `turn.completed` 的 `business_not_run:true` 结束，须等用户选择后才执行另一角色。拒绝回执为 `service.switch` 状态 `rejected`；纯角色恢复为 `resumed`。Guide/Mercury 业务事件继续使用各自现有 SSE 事件及 payload。HTTP stream 建立前的应用错误为 JSON：`{"error":{"code":"...","message":"...","retryable":false}}`；请求校验错误为 422。业务流开始后的失败使用 SSE `error` 或 Guide 的 `turn.stopped`，不能当作成功回复。

当前可观察的错误包括：403 `SESSION_FORBIDDEN`（session 不归当前 owner）；404 `OPENING_NOT_FOUND`（opening 不存在、owner 不符或已关闭）；409 `HANDOFF_STALE`（交接 ID 已失效）、`HANDOFF_IN_PROGRESS`（交接仍在处理）、`TURN_IN_PROGRESS`（回合正在处理或退出时仍忙）、`IDEMPOTENCY_CONFLICT`（request ID 重用但消息不同）；schema 不符合时为 422。

## 结束与重新进入

```http
DELETE /api/v1/chat/openings/{opening_id}
```

成功为 204 空响应。忙碌 opening 返回 409 `TURN_IN_PROGRESS`。结束只关闭本次 opening，不删除两个角色 session；demo 清除 opening ID、保留角色 session ID。用户再次进入时用原角色 session ID POST 一个新 opening，额度重新开始。当前 opening registry 是服务进程内状态；浏览器刷新可由 GET 恢复，但服务进程重启后旧 opening 可能返回 404，session 本身仍按各自 API 生命周期处理。
