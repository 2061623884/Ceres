# Ceres1 V4 自动评测

- 产品候选：`ac895fd620af617fa31f4e0006841a4d6a89cd53`；实际源码与评测摘要见 manifest。
- 检索：lexical，无向量；hybrid 未通过。
- 场景 60；计划执行 100，实际执行 20。
- 业务达标 16/100；功能与性能均达标 12/100。
- 核心三次均达标 0/20；关键违规 0。
- 自动验收：not_passed；人工验收未执行；模型裁判未校准、仅诊断。
- 首个有用结果时延未采集：TestClient 缓冲 SSE；费用缺可靠价格及完整 usage，保持未知。

| 分组 | 计划执行 | 业务达标 | 含性能达标 |
|---|---:|---:|---:|
| aftersales | 12 | 1 | 0 |
| drink | 15 | 3 | 1 |
| memory | 12 | 1 | 1 |
| policy | 10 | 2 | 2 |
| purchase | 19 | 3 | 3 |
| routing | 11 | 2 | 2 |
| snack | 11 | 2 | 1 |
| theme | 10 | 2 | 2 |

逐次证据与失败复现见 [summary.json](summary.json)、[badcases.json](badcases.json) 和各 execution 目录。
正常/拒绝、准备失败、跳过步骤及裁判意见在逐次记录中保留；脚本结果不证明真人转化或真实履约。
