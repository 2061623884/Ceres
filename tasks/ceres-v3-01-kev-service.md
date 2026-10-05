# 01 Kev 模型可运行与中文判断探查

状态：待验收（模型可运行/API 探查与双轴审查已完成；不是核心路由质量或 Q20 验收）
负责人：主 Agent；Amax 专职测试子 Agent 执行和记录，主会话核对原始证据。
规格：[V3 实施规格](../docs/plans/ceres-v3-spec.md)
依赖：无。既有独立环境与固定官方版本为输入，不以旧 Windows/U 盘结果替代本次 Amax 校验。

## 交付行为

固定 Kev 及基础权重在 Amax 校验后，GPU 1 独立服务能对给定中文业务上下文返回继续／建议切换／澄清，记录可运行性、实际显存与耗时，不接入正式业务回合。

## 验收标准

- [x] 23 个官方文件大小与官方 LFS SHA-256/Git blob 摘要匹配，两个固定 revision 离线解析成功，无未完成权重；记录实际缓存路径。
- [x] 复核物理 GPU 1 UUID 与占用，独立环境实际加载指定模型；仅目标卡运行，保留进程、参数、显存和日志。
- [x] 本地 API 对三类代表中文上下文返回有效闭合结果与概率，保留原始输入/输出；8 例中 6 例命中、2 例错分，开发探查不冒充独立留出验证或质量通过。
- [x] 分别记录加载、冷启动和常规调用时长；质量或性能未满足如实记录，不重新选型或替换主模型。
- [x] 启动准备与脚本核对完成双轴审查，证据包含源码、环境、模型与测试版本；不上传权重、不触碰其他 GPU。

## 测试边界

官方文件摘要／离线缓存解析、独立服务 HTTP 及真实 GPU 进程。旧启动脚本读旧 hub，必须按下载完成回执核对路径再执行；未完整校验不得启动。外部调用链可达性在 03 接入时检验。

## 阻塞与下一步

主会话已核对原始命令、退出码、GPU 1 UUID/进程、固定模型 API 身份、8 行原始请求/响应及回收摘要。缓存为 `/data/amax/services/ceres-kev4b-probe-20261005/amax-direct-download/hub`，FP32 服务 PID 2701504，回环端口 8009，ready 后显存约 17.0 GiB。启动到首个成功 models 请求 104.411 秒，首次推理 773.0ms，其余探查与冷启动分别保留；本票的小样本不证明 Q20 已通过。

8 例只有 6 例命中：一般退货政策与无对象“取消一下”均被错误判为 suggest_switch。它们作为 03/05 的开发改进及回归输入，禁止沿用为已通过核心质量。01 交付模型可运行/API 探查与失败记录，03 仍须改进上下文和准则后检验其实际路由，既定模型不重新选型。Standards/Spec 复审有效问题各 0；本人验收保留至整体验收，03 的模型服务技术条件已具备。

## 证据

下载：[Amax 直接下载回执](../work/ceres-v3-discussion/kev-local-probe/amax-direct-download/README.md)；主会话 [回执核对](../work/ceres-v3/00-preparation/download-receipt-check.json)；本票 [执行证据](../work/ceres-v3/01/execution/README.md)、[冻结基线](../work/ceres-v3/01/baseline/baseline.json)、[审查范围](../work/ceres-v3/01/review-scope.json)、[Standards](../work/ceres-v3/01/review-standards.md)、[Spec](../work/ceres-v3/01/review-spec.md)。实际提交回执保留在 `work/ceres-v3/01/commit-receipt.json`，状态由主会话维护。
