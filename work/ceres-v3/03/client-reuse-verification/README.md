# Kev v3.1 共享 Client 复核

对前一批唯一失败的 3 个开发样例，用更新后的 `get_kev_provider()` 工厂取得同一个 `KevProvider` 与同一个 `httpx.Client`；每例只发送一次，不重测原来已成功的 5 例，也不改预期标签。请求仍走本机 `127.0.0.1:18009` SSH 转发，Client timeout 维持 3.0 秒。

工厂初始化单列为 **841.661 ms**，同一进程再次调用 factory 返回相同 provider/client。三次调用都成功并符合原预期：

| 案例 | 原预期 | 选择 | 概率（stay / switch / clarify） | 服务端 latency | 本地调用 wall |
| --- | --- | --- | ---: | ---: |
| momo-new-shopping | suggest_switch | suggest_switch | 0.2590 / 0.4556 / 0.2854 | 321.0 ms | 755.898 ms |
| cancel-without-object | clarify | clarify | 0.1759 / 0.0783 / 0.7459 | 263.4 ms | 415.961 ms |
| cancel-shopping-list | stay_current | stay_current | 0.6419 / 0.1798 / 0.1782 | 279.6 ms | 424.135 ms |

Amax access log 为三条响应记录相同的来源端口 `43508`，支持连接被复用；之后 GPU1 仍是 PID 2701504、显存 17012 MiB、util 0%，端口 8009 在监听。只读模型计数为 20 batches / 21 requests / 0 queued，纳入前序 8 例、smoke、v3.1 八例、一次计时样本和本轮三例。

本轮 source SHA-256（provider）：`dc3cfa00e8e161c9d84cade8a14c095e3e5b27ccb440e74cf2443e296ed15345`；`chat.py`、`main.py` 的启动/调用/关闭路径 SHA 与本轮起始一致。三份文件全程未变；Client 最后关闭并清空 factory cache。证据包括 `execution.json`、`frozen-requests.json`、`results.json`、原始 stdout/stderr、models GET 和 Amax 状态 JSON。

结果支持将 Client 初始化从每一轮路由移至应用启动，并复用 HTTP 连接。它只证明这 3 个旧 timeout 样例在一次共享 Client 运行中恢复成功；不代表其余业务质量、完整端到端链路或 P95 达标。
