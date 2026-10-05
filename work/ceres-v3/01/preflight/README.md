# 01 Kev 服务启动前核对

核对时间：2026-10-06（Amax UTC+08:00）。所有检查均为只读，未启动模型、未发出 API 请求、未使用 GPU 推理。每条 SSH 命令的 argv、非敏感执行环境说明、退出码、stdout 与 stderr 分别保存在同目录的编号 JSON 中；`summary.json` 汇总执行情况。没有读取或输出密钥/令牌环境变量。

## 已确认条件

- SSH alias `amax` 连到 `amax` 主机，远端用户为 `amax`，Linux kernel `5.15.0-139-generic`。
- 物理 GPU 1 为 NVIDIA TITAN RTX，UUID `GPU-5165b827-1b01-e6f0-d147-38e565ee823f`，PCI `00000000:3B:00.0`，24,576 MiB；检查时占用 66 MiB、空闲 23,958 MiB、利用率 0%，compute-app 清单为空。
- 独立服务目录为 `/data/amax/services/ceres-kev4b-probe-20261005/upstream`；解释器 `/data/amax/services/ceres-kev4b-probe-20261005/upstream/.venv/bin/python` 解析到 uv 管理的 CPython 3.13.12。
- Kev worktree 固定在 `fe64b1274ea7f80d4095866df90666abb03e9cf6`，`git status --short --branch` 显示 detached HEAD 且工作树干净。
- 锁定依赖树使用 uv 0.10.11、`--locked --offline` 检查，解析 120 个包。Serve extra 包含 FastAPI 0.141.1、typesafe-sdk 0.6.0、uvicorn 0.53.0；PyTorch 2.8.0、Transformers 5.17.0、huggingface-hub 1.32.0、safetensors 0.8.0 均已安装。
- 下载回执指向独立缓存 `/data/amax/services/ceres-kev4b-probe-20261005/amax-direct-download/hub`，两个固定 revision 存在、未发现 `.incomplete` 文件。
- TCP 8009 当时没有监听。

## 启动脚本差异

远端原脚本实际路径为 `/data/amax/services/ceres-kev4b-probe-20261005/amax-start.sh`，SHA-256 `403f6660b0b075c62e36c9234dd101da866a82ce4b29a1b5377065e081b69cb8`，`bash -n` 通过。它绑定 GPU 1 UUID、FP32、关闭 CUDA graphs/fused/prefix cache，并启动固定 Kev revision 到 `127.0.0.1:8009`；但它把 `HF_HUB_CACHE` 指向旧 `/data/amax/services/ceres-kev4b-probe-20261005/hub`，而完整校验权重在 `amax-direct-download/hub`。

主会话提供的修正脚本位于 `work/ceres-v3-discussion/kev-local-probe/amax-start.sh`，本地 SHA-256 `58E4C25051EF5D4DD4257285710CF8FCEEE1544013F73163FF56292635B22B58`，其缓存指向已校验的 `amax-direct-download/hub`。后续只按授权传输该现有脚本，不在本子任务修改脚本内容。远端旧脚本、端口和 GPU1 的本次核对记录作为传输前快照保留。

执行证据文件包括 `01-amax-connection-environment.json` 至 `11-port-8009-listener.json`，采集脚本是 `collect_preflight.py`。启动和推理结果将在后续执行记录另存，不与本次只读快照混写。
