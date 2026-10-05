# 04 Git-index 候选冲突解决记录

本记录只说明候选文件如何从冻结 HEAD 内容加上 04 handoff 增量构成；未修改工作源码、Git index、TASK 或测试文件，也未运行测试。5 个无冲突候选保持原样。候选位于 `index-candidates/`；它们是局部暂存素材，不代表在干净 HEAD 上独立验证通过。04 测试证据适用冻结工作树快照。

## 五个冲突文件

1. `backend/app/api/guide.py`：以 `index-candidates/backend__app__api__guide.head` 为底。将 HEAD 中的路由实现提取为内部 `process_guide_turn_stream`，新增仅内部可传的 `handoff_recent_messages`，并保留原 `/guide/sessions/{session_id}/turns/stream` 路由包装器。候选中 helper 通过 `TurnStreamService.stream_turn` 传入该上下文（候选第 492–551 行）。这是让已核对的 chat API 调用复用 Guide SSE 实现并带入一次性交接上下文所需的 seam；没有把它暴露成 FastAPI 请求参数。来源：`source.patch` 第 131–207 行；对应当前工作树 helper/包装器在冲突快照 `.current` 第 492–551 行。HEAD 的原始端点在 `.head` 第 492–534 行。

2. `backend/app/services/turn_stream_service.py`：只在 worker 参数、`GraphTurnService.process_turn` 调用和后台线程 kwargs 三处传递 `handoff_recent_messages`（候选第 215–366 行）。来源：`source.patch` 第 267–308 行；具体 handoff 参数/传递也见 `.current` 第 215–350 行。

3. `backend/app/services/graph_turn_service.py`：给 `process_turn` 增加可选 handoff 上下文并传递给 `run_graph_turn`（候选第 173–260 行）。来源：`source.patch` 第 309–340 行；`.current` 第 176–260 行。

4. `backend/app/agent/graph/coordinator.py`：给 `run_graph_turn` 增加可选 handoff 上下文并填入 `TurnRuntime`（候选第 38–140 行）。来源：`source.patch` 第 341–362 行；`.current` 第 38–135 行。

5. `backend/app/agent/graph/runtime.py`：新增一次性、有界来源角色消息字段，并标注不持久化（候选第 67–72 行）。来源：`source.patch` 第 363–377 行；`.current` 第 67–73 行。

五个冲突候选都从各自 `.head` 快照复制，只增加上述 handoff 传递；没有带入工作树快照中的 `plan_selection` 字段或相邻 V2 业务差异。其候选 SHA-256 为：

| 候选文件 | SHA-256 |
| --- | --- |
| `backend__app__api__guide.py` | `73733F555ADCE62A0E64C600FCCD0B69B5DA71CF046BD07C3D29B0E951F5759B` |
| `backend__app__services__turn_stream_service.py` | `DB9CE57D077BDD0EBE3F0D39FE3433D05034E0B3E6079BFA5E9205053944A753` |
| `backend__app__services__graph_turn_service.py` | `D216F6F06155E9DED0D63EC9083D727A82B7BD48C393D9E1539F7BAA8AB2B532` |
| `backend__app__agent__graph__coordinator.py` | `F8A221725956C9F7BD4B6B2B572B5613A00992A65A1917B6873476EFAE03C446` |
| `backend__app__agent__graph__runtime.py` | `E2A305DB6650A3DF4F6EF6DBF3E8DE7B440125421B7D869FBC43BD7B9AC1D99A` |
