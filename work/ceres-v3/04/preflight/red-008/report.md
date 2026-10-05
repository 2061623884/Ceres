# 04 已回答切换问题不再进入下一轮路由上下文 red-008

- 范围：只运行 test_v3_switch_lifecycle.py::test_answered_switch_question_is_not_pending_for_next_route 的 accept/reject 两个参数。
- 结果：pytest 退出码 1，2 failed；stderr 为空。两条路径均在 test_v3_switch_lifecycle.py:191 失败：下一条消息已得出 stay_current，但 Kev 请求 state.pending_question 仍保留“订单业务由墨墨处理，是否切换？”。
- accept 路径中墨墨订单回答已完成；reject 路径返回 rejected。失败发生在两条路径后续 current_role 断言之前，因此不把这些后续断言写成已验证。
- 执行环境：Python 3.12.10、pytest 9.1.1；独立 TEMP/TMP/basetemp、受控 fixture 与临时 DB/词法索引、MEMORY_MODEL 为空、线程异常 warning-as-error；未进行完整出站抓包。
- 本轮执行前后记录范围内 34 个源码/测试 SHA-256 一致。范围包括 graph_turn_service.py、graph/coordinator.py、graph/runtime.py 及共享测试/semantic fixtures。没有修改源码、TASK 或 Git index。
- 原始 command、environment、stdout/stderr、source hashes 与 exit code 见同目录 command.txt、environment-and-source.json、stdout.txt、stderr.txt、source-check-after.json、result.json。
