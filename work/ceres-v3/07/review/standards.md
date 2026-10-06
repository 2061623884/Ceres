# Standards 审查

审查固定点为 `d3f426ecaf169bd01a7b86c137c61b9034d5079b`；提交差异为空，按实际前置 ZIP `c585b1d78a9f9466a127d2c4de9515ed05f4e0dd7e8c005eb79d8f516c86b722` 到候选 ZIP `094eb7d28777d5c3d7025bcad4aebd9f71a300cb275fe8679c9ec5cd825d2dfb` 的 ticket 07 范围审查。完整阅读新增的 `docs/ceres-v3.md`、`backend/tests/test_v3_independent_routing.py` 和新增的 `work/ceres-v3/07/cursor-acceptance.md`，并核对 README 入口、TASK 与回归计划。继承 V2 不计入本票。

**结果：硬性规范违规 0；确定异味 0；可能异味 1（P3）。**

- **可能 DuplicatedCode（P3）**：`backend/tests/test_v3_independent_routing.py:82` 先写入 `raw_sse=response.text, upstream=upstream[index:]`，随后同文件第 95 行对同一行再次赋相同值。保留解析前写入以保存失败证据；末次更新可删去这两个重复字段。此项是可选清理，不阻塞。

观察器符合证据与异常约定：测试第 34–35 行先保存上游 HTTP 状态和原文再解析 JSON；第 82–83 行先保存当前 HTTP 状态、原始 SSE 与上游记录再解析事件；第 99–109 行记录异常、重抛，并在 `finally` 写结果及哈希。已有探针中，第一次因临时 HTTPX guard 缺少 `req` 参数而报 TypeError，未到被测解析路径；修正后，故意返回 HTTP 200 坏 SSE，实际触发 JSONDecodeError，结果文件保留了 200 状态、原始 SSE 与失败类型，异常未被吞掉。该探针覆盖 SSE 解析失败；上游 JSON 解析顺序由源码核对，未见对应故障探针。

新增页面清单与 04 API 契约、05 的 Q20 计时口径及 07 TASK 一致，页面证据未执行状态清楚，用户本人确认前保持待验收；链接目标存在。说明文档明确模拟业务数据与后台 API/正式页面验证边界。未发现与根目录 AGENTS、issue-tracker 或 domain 约定冲突。

此次仅静态审查并读取已有探针产物；未执行测试、模型、评测或 `git diff --check`。
