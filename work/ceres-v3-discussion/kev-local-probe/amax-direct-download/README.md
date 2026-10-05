# Kev-4B Amax 权重直下与校验

状态：已完成固定版本下载、官方文件摘要核验及断网缓存解析；没有启动模型服务或使用 GPU。

## 固定版本与结果

- Kev 源码依赖：`fe64b1274ea7f80d4095866df90666abb03e9cf6`
- 路由 checkpoint：`jaredpalmer/kev-4b@139fdd94f1b6a6ad80cc15e08fcb99cac885a101`
- 基座：`Qwen/Qwen3.5-4B-Base@1001bb4d826a52d1f399e183466143f4da7b741b`
- 下载位置：`/data/amax/services/ceres-kev4b-probe-20261005/amax-direct-download/hub`
- 共 23 个文件：checkpoint 13 个、基座 10 个，总计 9,502,510,659 字节（约 8.9 GiB）。
- 每个文件大小一致；LFS 文件匹配官方 SHA-256，其余文件匹配官方 Git blob SHA-1。没有 `.incomplete` 文件。
- `HF_HUB_OFFLINE=1` 下，两个完整 revision 均成功解析，23 个文件可读。

官方摘要逐文件结果见 [verification.json](verification.json)，断网解析回执见 [offline-resolve.json](offline-resolve.json)，独立 SHA-256 清单见 [SHA256SUMS](SHA256SUMS)。来源记录在 [weights-provenance.json](weights-provenance.json)，下载和网络检查命令在 [commands.log](commands.log)，原始下载日志在 [download.log](download.log)。

## 网络与边界

Amax 直连 Hugging Face 仍发生 TLS reset。使用 Amax 已有的 `127.0.0.1:7890` 代理请求官方 Hugging Face 源；10 MiB Xet 分片 Range 探测返回 HTTP 206，随后通过 `huggingface_hub.snapshot_download` 下载两个固定 revision。没有使用凭据或从 Windows 上传权重。

本次独立缓存与此前不完整的 U 盘导入缓存分开放置。接入模型服务时应把 `HF_HUB_CACHE` 指向上述 `amax-direct-download/hub`。本次没有加载 Kev、启动 API、检查 GPU 推理占用或进行中文采样；质量和延迟仍待单独评测。
