# v3.1 timeout 诊断

本记录只诊断网络/请求生命周期，不改源码或 TASK，也未重放原 8 条案例。

## 结论与证据

`KevProvider.decide` 中每次临时创建 `httpx.Client(timeout=3.0)`。独立的一条中性诊断请求按阶段计时：Client 构造 798.876 ms，POST 往返 984.975 ms，JSON 解析 0.035 ms，Pydantic 校验 0.064 ms；服务端 `server-timing` 为 324.8 ms，Kev 模型 `latency_ms` 为 317.2 ms。另在同一进程、不发请求地构造/关闭 3 个同配置 Client，构造分别为 806.870、797.881、762.585 ms（中位数 797.881 ms），关闭均小于 0.02 ms。解析不是耗时点；每轮重新建 Client 确实固定增加约 0.8 秒。

三条 `ReadTimeout` 的服务端模型计数可由只读 `GET /v1/models` 前后相减确认。01 结束后基线为 8 requests；联网 smoke 后和三例重测前读取到 `batches.count=16, requests=17, queued=0`，即本批 v3.1 8 条全部进入并完成 Kev model worker 的 inference 计数，尽管客户端只有 5/8 收到响应。Amax `server.log` 在本批后记录了 6 条对应 POST 200；另 2 条没有正常 Uvicorn access 记录，日志无请求时间戳/ID，无法将缺失行或 1 条额外 200 精确映射到三个 timeout case。结论限于：模型 worker 已处理 8 条；三条客户端 ReadTimeout 中的 ASGI/HTTP 响应完成状态不能逐案确认。

Windows SSH 本地转发 PID 25040 仍监听 `127.0.0.1:18009`，其 stdout/stderr 为空。HTTP(S)/ALL proxy 均指向本机 7897，但 `NO_PROXY` 覆盖 `127.0.0.1`，环境值已脱敏。现有证据未显示隧道进程退出或 GPU1 冲突；只凭这些快照不能排除瞬时链路抖动。

## 新诊断样本

唯一新增的模型请求是中性问候，只用于阶段计时，不属于质量集。命令用 `backend/.venv`，未改标准。所有请求和阶段信息见 `diagnostic-timing.json`；执行记录、冻结请求、远端代码版本及 GPU 状态也分别保存在本目录。Client 构造原因未继续拆到 TLS/环境子步骤。

三条旧 timeout case 的共享 Client 复核在 `../client-reuse-verification/README.md`。该复核证明该实现能让这三次请求本轮全都返回，但不构成总体 P95 或模型验收。
