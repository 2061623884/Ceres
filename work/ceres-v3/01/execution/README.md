# Kev-4B V3 / 01 执行记录

状态：已完成一次固定版本的模型启动、只读模型清单 API 和 8 条中文开发探查；这是部署路径/行为探查，不是验收。未改上游源码、启动脚本、任务票据或 Ceres 生产代码，也未上传权重。

## 运行环境

- Amax 服务目录：`/data/amax/services/ceres-kev4b-probe-20261005`；服务 PID `2701504`，仅绑定 GPU 1 UUID `GPU-5165b827-1b01-e6f0-d147-38e565ee823f`，回环地址 `127.0.0.1:8009`。
- Kev 源码固定 revision：`fe64b1274ea7f80d4095866df90666abb03e9cf6`；checkpoint `jaredpalmer/kev-4b@139fdd94f1b6a6ad80cc15e08fcb99cac885a101`；基座 `Qwen/Qwen3.5-4B-Base@1001bb4d826a52d1f399e183466143f4da7b741b`。
- API 清单返回 HTTP 200，确认 `cuda / torch / float32` 与固定 checkpoint。启动命令到首次成功 `GET /v1/models` 为 **104.411 秒**；GET 自身 `server-timing` 为 3.5ms、SSH 往返为 2.641 秒。首条推理 wall 时间为 773.0ms，作为加载后首次推理单独记录。
- GPU1 显存快照：加载权重期间 12,030 MiB；服务 ready 后 17,004 MiB；8 例结束后 17,012 MiB。对应 compute process 为服务 PID 2701504。

## 8 例探查

单次顺序执行 8 条，runner exit code 0，结果 **6/8** 符合预期。`guide-general-return-policy` 预测 `suggest_switch`（预期 `stay_current`）；`cancel-without-object` 预测 `suggest_switch`（预期 `clarify`）。这两条显示当前探查 Prompt 对一般退货政策咨询、对象不清的“取消一下”仍有过度建议切换的倾向，需要作为路由样例反馈到后续实现/评测。其余 6 条命中预期。

wall 延迟 min / median / max 为 **235.6 / 254.3 / 773.0 ms**；8 条的最近秩样本 P95 为 773.0ms，但样本过小且这是开发探查，**不能据此宣称 P95≤1s 验收通过**。冷启动从单列数据读取，也不能混入常规路由延迟。

## 原始证据

- `launch.json`：唯一启动命令、启动时钟、非敏感运行参数、stdout/stderr/退出码。`status-01.json`、`status-02.json`：加载中与 ready 后进程、GPU1、端口和日志快照。
- `api-models.json`：首个只读模型清单请求及完整 HTTP 返回。
- `pilot-launch.json`、`pilot-status-01.json`、`pilot.exit-code`、`pilot.stdout.log`、`pilot.stderr.log`：单次 8 例 runner 启动/结束证据。
- `pilot-results.jsonl`：逐条原始请求、回复和 wall_ms；`pilot-analysis.json` 与 `execution-summary.json` 是从原始记录派生的汇总。
- `pilot-publication.json`、`pilot-fetch-verification.json`：runner/cases 发布与结果回收的 SHA-256 一致性核验。

服务当前保持运行，没有重启，也没有停止。
