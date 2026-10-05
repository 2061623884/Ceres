# 03 本机到 Amax 网络链路

SSH 本地转发已建立并保持运行：Windows `127.0.0.1:18009` → Amax `127.0.0.1:8009`。监听仅绑定本机回环地址，隧道 PID 记录于 `tunnel-start.json`；当前存活状态见 `tunnel-status.json`。复用此进程即可进行后续准则校准，无需重新启动隧道。

- `GET /v1/models` 经本机转发返回 HTTP 200，完整命令、响应头/体及退出信息见 `models-get.json`。
- 单条 `POST /v1/systemone` 连通性探查返回 HTTP 200，结果 `stay_current`，服务端耗时 281.7ms、本机 curl 往返 597.7ms。请求及完整回复见 `first-probe-request.json`、`first-probe.json`。这只是链路烟测，不是校准、评测或验收。
- 隧道启动与 stdout/stderr 日志见 `tunnel-start.json`、`tunnel.stdout.log`、`tunnel.stderr.log`。
