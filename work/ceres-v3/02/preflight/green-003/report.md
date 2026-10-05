# 绿阶段 003：政策答案不使用商品主推 Prompt

- 测试：`tests/test_v3_policy_consultation.py::test_keke_policy_answer_uses_conditions_instead_of_product_recommendation`
- 解释器、pytest 版本、精确命令、隔离环境及执行前 21 个相关文件 SHA-256：`environment-and-source.json`、`command.txt`。
- 退出码：0；stdout：`stdout.txt`（1 passed，12.97 秒）；stderr：`stderr.txt`（空）。
- 执行后 SHA-256：`source-check-after.json`，21 个相关文件均未变化。受控 MockTransport 按流式请求返回 SSE，无真实网络请求。
- 仅执行本例；未修改源码、测试源、TASK 或 Git 状态。通过仅证明该场景下政策答案路径断言成立。
