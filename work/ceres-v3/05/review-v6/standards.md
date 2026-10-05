# 05 v6 Standards 复审

审查固定于原始 pre-ticket working ZIP `e91bbd5f…29c1382c` 及固定点 HEAD `5462e999d583a9bab6147d0b4141d98321f3cc92`；冻结 scope 在采集时记录 `commit_list=[]`。当前 HEAD 为 `0913094de203588e2e36dc7fe9a746ab4a2a798e`，后续只有一条 08 文档/证据提交，路径与 14 项无交集；这里明确记录当前历史，不把旧 scope 的空列表当作当前空历史。候选 ZIP `31983d29…bd204a` 的 306 个源摘要、14 项 review scope 摘要及 14 项 review-source ZIP 均匹配。与 v5 ZIP 比较并规范化 CRLF 后，唯一变化是 `backend/tests/test_v3_live_sampling.py` 和 `work/ceres-v3/05/fixes.md`；其余 12 项沿用 v5 Standards 结论。

**硬性规范违反：无。** v5 指出的观察缺口已修复：采样器在发出 R01 选款请求前保存原话和实际卡片，并在 `events(selected)` 解析之前保存 HTTP 状态、完整 SSE 文本与耗时。解析异常仍经 `finally` 记录为 `passed=false`、`error_type=JSONDecodeError` 并原样传播。受控探针以真实商品详情 API 取到零糖可乐卡，第二回合返回 HTTP 200 的畸形 SSE；用例按预期以 JSONDecodeError 退出 1，同时保存选款输入、卡片、原始 SSE 和正耗时，`upstream=[]`。这是观察器失败探针，不是业务或 Q20 通过证据。

**启发式代码气味：未发现新增项。** `AGENTS.md` 反对为一次性逻辑引入辅助抽象；本次只移动两处回执写入顺序，没有新增 helper、生产逻辑或模型调用。

证据：`work/ceres-v3/05/review-v6/standards-scope-check.json`；探针见 `work/ceres-v3/05/evidence/observer-malformed-selection-v6-http-boundary-20261005T232832Z-727a9df1/`。报告不代替 Spec 轴，也不把 v5 真实回执重新标为 v6。