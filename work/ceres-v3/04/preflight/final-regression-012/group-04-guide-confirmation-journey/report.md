# 04 最终回归组 4：失败记录

本组运行 04 当前范围相关的导购选购、确认与 V2 集成旅程测试。退出码 1；14 passed、16 failed（71.78s），stderr 为空。记录范围源码 SHA 前后匹配。原始命令、环境、stdout/stderr、测试清单和摘要见本目录的 `command.txt`、`environment-and-source.json`、`stdout.txt`、`stderr.txt`、`result.json`、`source-check-before.json`、`source-check-after.json`。

14 个通过项来自 `test_semantic_phase1_purchase.py` 和 `test_purchase_selection.py`。

失败分为两类：

- `test_phase2b_chat_confirmation.py` 的 14 个选中参数实例都在共用 helper `_new_plan`（第 96 行）失败：首轮得到 `status="understanding"`、`task_id=null`、`state_version=0)、`plan=null`，因此确认相关断言尚未执行。
- `test_v2_integrated_demo.py::test_two_run_v2_purchase_history_checkout_and_mercury_journey` 两个参数实例完成购买和 checkout 后，在未选单售后咨询断言失败：没有 `final_text` SSE 项；捕获日志显示 Mercury 调用失败，原因是测试提供的禁止 OpenAI 调用断言被触发（“Mercury must return the owner's real order choices without a model call”）。

按任务指令，此组失败后停止后续回归；没有重跑、修改源代码、TASK 或暂存区。此报告仅记录观察，不把可能的测试夹具/数据问题判定为实现缺陷。
