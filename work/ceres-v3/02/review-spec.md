# 02 Spec 审查

基准：`a81a39d3a40f9f1bbb270961366cb5f6e930c664`；按 `review-scope.json` 的 14 个文件和 `source.patch` 审查，未使用当前 HEAD 比较。

**Findings：0。** 未发现规格遗漏、越权范围或实现错误。Spec 要求两角色共享政策事实、未选订单仅开放一般咨询且订单资格/操作仍须选单、未命中不编造（`docs/plans/ceres-v3-spec.md:78-82`）。当前实现由启动时非覆盖初始化并走共享检索（`backend/app/main.py:68-77`、`backend/app/services/policy_service.py:9-29`）；政策排序复用 Mercury 同一函数（`Mercury/mercury/policy.py:24-47`）。可可的 `policy` read 经协议和 ReadTools 到该服务，答案阶段采用政策 Prompt（`backend/app/agent/protocol.py:47,819-820`、`backend/app/agent/tools/read.py:526-529`、`backend/app/llm/live_semantic_provider.py:116-123`）。墨墨无选单时同时限制工具 schema 与执行入口，选单继续保留订单列表事件（`Mercury/mercury/agent.py:36-40,46,60`、`Mercury/mercury/tools.py:78-94`、`backend/app/api/mercury.py:82-99`）；均符合政策票与政策章节。

**证据核对：** 后续 fix-005 回执为 V3 政策 8/8、Mercury 政策 8/8、V2 订单隔离 16/16、语义传输 15/15，均记录退出码 0、stderr 空及 warning-as-error（`work/ceres-v3/02/preflight/fix-005-v3/report.md:3-7`、`fix-005-mercury/report.md:3-8`、`fix-005-v2/report.md:3-8`、`fix-005-semantic/report.md:3-7`）。旧 boundary-004 失败报告保留为历史；后续对应回归重新覆盖，不能把旧结果当当前失败，也不能据此宣称真实角色质量已验证。真实角色采样仍归 05（`tasks/ceres-v3-02-policy-consultation.md:21-23`）。本审查未运行测试。
