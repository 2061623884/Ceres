# 红阶段 002：墨墨无选单时咨询政策

- 测试：`tests/test_v3_policy_consultation.py::test_momo_can_consult_policy_without_selecting_an_order`
- 执行环境、完整命令及执行前源码/测试 SHA-256：`environment-and-source.json`、`command.txt`。
- 退出码：1；stdout：`stdout.txt`；stderr：`stderr.txt`（空）。pytest 结果：1 failed，2.31 秒。
- 失败断言：`backend/tests/test_v3_policy_consultation.py:60` 的 `assert "P-RET-01" in response.text`。HTTP 状态为 200，但 SSE 最终回答为“你目前没有模拟订单，可先在购物车完成模拟结算。”，没有返回政策来源。受控客户端要求本轮工具列表仅含 `search_after_sales_policy`，但回答表明无选单路径先要求购物车模拟结算，因此该工具调用没有产生可供断言的政策回答。
- 执行后源码和测试 SHA-256：`source-check-after.json`，14 个涉及文件均未变化。受控测试客户端，无真实模型/API调用；本例使用 fixture 临时 SQLite。
- 范围：只运行此红用例；未运行其他测试、修改源码/测试源/TASK 或提交 Git。失败符合当前阶段预期，不能据此判断 TASK 02 整体状态。
