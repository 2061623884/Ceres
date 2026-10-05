# Semantic transport boundary regression

- 范围：一次运行 `backend/tests/test_semantic_transport.py`；命令、解释器/pytest 版本、隔离环境及 25 个相关文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。启用 `-W error::pytest.PytestUnhandledThreadExceptionWarning`。
- 退出码：1；stdout：`stdout.txt`（14 passed、1 failed，0.42 秒）；stderr：`stderr.txt`（空）。执行后 25 个相关文件 SHA-256 全一致，见 `source-check-after.json`。
- 失败：`tests/test_semantic_transport.py::test_answer_phase_examples_do_not_reopen_retrieval` 传入 `query_results=[{"status":"completed"}]`，当前 `LiveSemanticProvider._build_payload` 的政策分支读取 `result["kind"]` 时抛 `KeyError: 'kind'`（`backend/app/llm/live_semantic_provider.py:120`）。
- 该测试使用 `httpx.MockTransport`，未访问真实 API；失败为测试输入与当前读取契约不兼容的具体错误。本次不改测试/实现，也不重跑。
