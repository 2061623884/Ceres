# 红阶段 003：导购政策答案使用政策条件而非商品主推 Prompt

- 测试：`tests/test_v3_policy_consultation.py::test_keke_policy_answer_uses_conditions_instead_of_product_recommendation`
- 命令、解释器/pytest 版本、隔离环境及执行前源码 SHA-256：`command.txt`、`environment-and-source.json`。
- 退出码：1；stdout：`stdout.txt`（1 failed，7.78 秒）；stderr：`stderr.txt`（空）。
- 这是有效业务红：受控 `httpx.MockTransport` 收到两次语义请求；测试桩根据 `payload.stream` 返回 SSE frame 和 `[DONE]`。失败发生在第二次答案调用，断言商品推荐 Prompt 片段不应存在，但 `payload["messages"][0]["content"]` 仍包含 `reply 只说明这款商品...`。API 因该受控断言返回 400，随后 `backend/tests/test_v3_policy_consultation.py:67` 的状态码断言失败。没有发生 stream 协议不匹配或真实网络调用。
- 执行后源码 SHA-256：`source-check-after.json`，20 个关联文件均未变化。
- 仅运行此单例；未修改源码、测试源、TASK 或 Git 状态。此失败支持答案阶段仍拼接商品主推 Prompt，不代表 TASK 02 整体状态。
