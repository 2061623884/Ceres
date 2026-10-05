# Kev-4B 本地模型部署探查

2026-10-06 当前约定：Kev-4B 已选定为 Ceres V3 路由模型，质量与性能评测用于检验和改进该实现；此前评测后决定是否采用、未达标使用主模型的前提已撤回。用户指定 Amax GPU 1；常规请求路由新增等待目标为 P95 ≤1 秒，完整回复以 ≤15 秒为目标，冷启动单列。本探查不改 Ceres 生产配置。

当前传输路径已由用户调整为子 agent 在 Amax 直接下载固定版本权重。23 个文件的官方摘要与离线解析已通过，大小总计 9,502,510,659 字节，回执见 [Amax 直接下载](amax-direct-download/README.md)。实际缓存为 `/data/amax/services/ceres-kev4b-probe-20261005/amax-direct-download/hub`，尚未加载模型或进行中文采样。下文 Windows／U 盘及早期网络检查保留为历史过程记录，当前任务状态由 [V3 的 01 票据](../../../tasks/ceres-v3-01-kev-service.md) 管理。

## 已核对的环境

2026-10-05 SSH 核对：Amax GPU 1 为 TITAN RTX 24GB、计算能力 7.5，空闲 23,958 MiB，未发现计算进程；物理 GPU UUID 为 `GPU-5165b827-1b01-e6f0-d147-38e565ee823f`。驱动 570.133.20，主存可用约 89 GiB。这些是启动前快照，后续启动仍需核对占用。

本机 Windows 为 RTX 3060 12GB，检查时空闲显存 9,184 MiB；WSL2 Ubuntu 启动因 `HCS_E_HYPERV_NOT_INSTALLED` 失败。没有修改 Windows 系统组件或 BIOS。

官方 [模型卡](https://huggingface.co/jaredpalmer/kev-4b) 报告其 CUDA BF16 快速路径常驻约 14.3GB 显存，标注语言为英语；中文不能沿用卡上指标。已核查上游源码提供 `KEV_DTYPE=fp32`、`KEV_CUDA_GRAPHS=0`、`KEV_FUSED=0` 的路径，因此为 Amax Turing 卡准备 FP32 初步试跑。尚未证明实际显存和速度满足要求。

## 版本与产物

Kev 源码固定为 `fe64b1274ea7f80d4095866df90666abb03e9cf6`，远端克隆于 `/data/amax/services/ceres-kev4b-probe-20261005/upstream`。安装命令使用官方锁定依赖、Python 3.13、独立 `.venv`，跳过开发依赖：`uv sync --frozen --no-dev --extra serve --python 3.13`。

Windows 从官方仓库下载 Kev-4B `139fdd94f1b6a6ad80cc15e08fcb99cac885a101`，根据实际 `head.pt` 读取基础模型为 `Qwen/Qwen3.5-4B-Base`、revision `1001bb4d826a52d1f399e183466143f4da7b741b`。指针头记录的权重精度为 FP32，温度为 2.406050072164233。没有更改权重或其元数据。

U 盘包见 [usb-bundle](usb-bundle/README.md)。其中 `hub/` 为离线缓存，`SHA256SUMS` 用于拷贝核对，`weights-provenance.json` 保留权重来源；脚本和 8 条中文初步案例已准备。

## Windows／U 盘及早期验证记录

- 版本与 GPU 绑定依据：已核对。
- Windows 下载与 U 盘包完整性：已完成。23 个模型文件的大小及官方 LFS SHA-256／Git blob 摘要全部匹配；包约 9.50GB，最大单文件约 5.33GB。两个固定 revision 均可在离线模式下从包内缓存解析；快照为实文件，无未完成权重。证据见 [bundle-verification.json](bundle-verification.json) 和包内 `SHA256SUMS`。
- U 盘传输历史：Windows 上曾核对 `D:\ceres-kev4b-usb-bundle`（fan，exFAT）31 个文件共 9,502,528,527 字节。首次发现 4 个小配置文件摘要不一致，重新写入后 Windows 核对通过，记录为 [usb-transfer-verification.json](usb-transfer-verification.json)、`usb-copy.log`、`usb-integrity-scan.json`。此前 Amax 只读挂载发现整包约 156MB，基础模型目录为空，清单中 10 个文件无法读取；适配器及脚本文件通过校验。该次跨机器传输未通过，原因尚未确定，当时曾安排 SSH 补传。用户随后改为 Amax 直接下载，已校验的新缓存与旧 U 盘缓存分开；SSH 补传不再是当前下一步。
- Amax 独立依赖环境安装：已完成。锁定依赖安装退出码为 0；PyTorch 2.8.0+cu128，CUDA 12.8，进程仅可见指定 GPU 1（TITAN RTX，计算能力 7.5）。记录见 [amax-setup.log](amax-setup.log)。这只是运行环境检查，尚未加载模型。
- 模型加载、API 有效性、实际 GPU 1 推理占用、中文采样与耗时：此前未执行，当前也没有这些运行证据。权重直下与完整校验现已完成，接续步骤由 V3 的 01 票据安排，不再等待基础模型补传。

早期检查中，Amax 直连 Hugging Face、通过现有代理访问及镜像 metadata 请求曾出现连接失败或超时，当时因 Windows 官方源可用而采用 Windows 下载与 U 盘传输。后续直接下载使用 Amax 已有代理访问官方源并完成校验，详见顶部回执。早期反向代理隧道尝试被自动审批阻止，未建立隧道，未修改网络配置。
