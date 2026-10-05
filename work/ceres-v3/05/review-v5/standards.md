# 05 v5 Standards 复审

固定于原始 05 working ZIP `e91bbd5f…29c1382c`、HEAD `5462e999…f1cc92`；审查 v4→v5 的四项差异：真实采样器、分析器、评测协议和修正记录。14 路径摘要及 candidate/review ZIP 均匹配；其余十项沿用 v4 Standards 结论，历史 V2 不计入本轮。

**硬性规范违反：无。** 分析器新增 R01 用户选款计时并将完整回复 Q20 提高为七个观测；完整五案的合成回执可通过，缺 R01 选款、缺 H01 交接或仅一案时均拒绝通过。实际 observer 的单行 `route_ms=null` 也得到 `route_q20_pass=false`、P95=null，不生成虚假零时延。`pytest --collect-only` 退出码 0，确认普通收集得到五个采样参数节点；未开启采样或调用模型。冻结的 306 个源文件在验证前后摘要一致。

**有影响的判断问题：** [backend/tests/test_v3_live_sampling.py:103](../../../../backend/tests/test_v3_live_sampling.py) 在 `events(selected)` 解析后才写入 `selection_sse` 与 `selection_backend_wall_ms`。若 R01 选款回合返回畸形 SSE 并使解析抛错，外层会保留异常并让分析器拒绝 Q20，但逐例回执会缺少该回合原始 SSE 与完整回复时长，增加失败诊断成本。建议在解析前保存响应状态、原文和耗时，并继续重抛原异常；这不会导致误报通过。

**启发式代码气味：未发现其他需处理项。** 本轮四项差异没有足够依据支持命名、重复逻辑、职责/数据聚合、重复分支、散改、推测性抽象、消息链、中间层或继承契约方面的额外重构。

分析器的正例仅验证合成回执完整性，不是 v5 真实 Q20 证据；本报告不替代 Spec 轴、真实采样或整票验收。
