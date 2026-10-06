# Ceres V3 后台与 Cursor 接入

当前状态与验收见 [总 TASK](../tasks/ceres-v3.md)。本页是启动和接口入口，不替代各票证据。价格、库存、配送、订单与售后均为模拟数据。

## 启动

Kev 固定部署在 Amax GPU 1，独立目录 `/data/amax/services/ceres-kev4b-probe-20261005`，本地监听 `127.0.0.1:8009`；模型、基础 revision、FP32 及冷启动证据见 [01 TASK](../tasks/ceres-v3-01-kev-service.md)。需要启动时使用已经校验的 [amax-start.sh](../work/ceres-v3-discussion/kev-local-probe/amax-start.sh)；正在运行时不要再次启动。停止时在 Amax 核对该目录 `server.pid` 与进程命令行后终止对应 PID。

Windows 到 Amax 的调用经 SSH 转发：

```powershell
ssh -N -L 127.0.0.1:18009:127.0.0.1:8009 amax
```

`KEV_BASE_URL` 默认 `http://127.0.0.1:18009`。后端和正式前端沿用 [README 启动方式](../README.md)。本次 V3 候选使用现有配置 `LLM_MAX_OUTPUT_TOKENS=3072`，依据是 05 实测的 1536 输出预算截断；模型和温度保持原配置。更改配置后须重启后端才能用于原已运行进程，评测中的新进程已读取新值。

后端使用单进程。本次打开状态及 Mercury 对话历史保存在进程内；重启后旧 opening 和 Mercury 对话历史失效，数据库中的会话记录、导购持久历史和业务数据保留。恢复失败需明确重新进入，不能把页面刷新当作重置额度的动作。

后端启动后访问 `http://127.0.0.1:8012/api/v1/chat/demo` 使用最小真实 API demo。该页面外观与正式 React 接入由 Cursor 后续完善。用户在浏览器操作产生的等待与自动测试的后台 API 时长分别验收。

## 聊天与两角色传输

先按原接口建立本人导购与墨墨会话，再以两者 ID 创建 `/api/v1/chat/openings`。每条新消息使用 `/openings/{id}/turns/stream`，保留原可可 TurnRequest 的 request_id、任务/状态/会话版本等字段，可额外指定本人实际 `order_id`。当前 owner 由原匿名 cookie 决定，不映射到固定演示用户。

第一事件 `service.route` 包含服务是否可用、三类 decision、原始 choice/概率、准则版本、新增 route_ms、当前/目标角色、handoff_id、提示方式及固定入口可用性。`stay_current` 继续当前业务；`suggest_switch` 和 `clarify` 尚未执行目标业务。Kev 不可用会显示失败与原始原因，当前角色和固定入口仍可用，不由主模型接管路由。

可可沿用 `data: {type,payload}`；墨墨沿用 named SSE（`event:` 与 `data:`），最终回复字段为 `final_text`。两者的原业务确认和版本检查继续有效。一般政策无需先选订单，答案应说明模拟门店、适用条件及 policy_id/标题；具体资格和申请依赖本人当前订单。

## 切换与本次打开

前端实际展示 automatic 建议后才调用 `/prompt-displayed`，不是收到路由事件就自动消耗额度。一次打开共用一次额度，拒绝或来回切换不恢复；用完仍逐条判断，只显示必要边界及固定入口。

用户明确接受建议才向 `/switches/stream` 发送 `accept=true`、目标角色与 handoff_id；目标重新读取 owner 和当前事实，携原话及必要上下文处理。切换不是加购或售后授权。相同交接的重复提交回放回执；失败也保留失败，不当作完成。

固定主动入口不另弹确认：明确未处理的目标诉求才续接，否则恢复目标会话，避免重发旧问题。新的明确诉求使旧交接失效。刷新恢复原 opening 与目标角色的当前业务版本；退出/重新进入使用同一个明确生命周期协议。04 的完整 body、恢复与退出契约见 [接口约定](../work/ceres-v3/04/api-contract.md)。

## Cursor 与本人验收

生产 `frontend/src` 由 Cursor 负责。接入后需真实页面验证：两向建议均先询问、接受/拒绝、主动续接/纯恢复、一般政策不选单、原订单 B 不覆盖本次 A、刷新不重置、明确退出重入恢复额度、路由故障仍可手动切换。本人确认体验是独立条件，后台 API 通过不代表正式页面已验收。

固定评测与证据见 [05 执行约定](../work/ceres-v3/05/evaluation-protocol.md)、[06 TASK](../tasks/ceres-v3-06-prompt-refinement.md) 和 [07 TASK](../tasks/ceres-v3-07-final-acceptance.md)。常规路由新增 P95 ≤1 秒、完整回复 ≤15 秒目标保留；冷启动、失败和样本数单列。未达标时不得写为技术全部通过或 V3 已验收。

同版后台结果、历史回归缺项与实际源版本见 [07 验证记录](../work/ceres-v3/07/validation.md)；正式前端按 [Cursor/本人清单](../work/ceres-v3/07/cursor-acceptance.md) 接入和验证，当前仍待验收。
