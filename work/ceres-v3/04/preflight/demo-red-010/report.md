# Red-010：demo 刷新恢复当前 Guide 状态

本次在 Node v24.14.0 的最小 DOM/VM 环境中执行原版 `work/ceres-v3/03/demo.html` inline consumer，并以 mock fetch 提供公共 API 响应；这是受控 consumer 行为检查，不是浏览器 E2E。没有启动 server、占用端口、连接 live backend 或调用模型。

运行前后 demo SHA-256 均为 `a89d73a74c324902d62e50bd4a917404b0c30891518319171fc34d182ea5f61d`，与指定冻结版一致。进程 PID 37820，退出码 1。

mock opening 恢复成功且刷新后没有 POST 新建 opening（0 次）。测试准备了完整的 Guide SessionResponse，含非零 `task_id=task-current-73`、`state_version=7`、`session_version=11`。但实际消费过程中没有 GET Guide session。第一个失败断言为“刷新必须读取当前 Guide SessionResponse”。实际 turn body 仅含 `request_id`、`message` 和 `expected_state_version=0`，缺少 `expected_task_id` 与 `expected_session_version`。

Harness 还要求恢复后 Keke 与 Momo 两个角色按钮均可用、leave 按钮可用；这些断言排在 Guide GET 断言之后，本轮没有执行。采集到的实际 UI 状态是 Keke 按钮 disabled、Momo 按钮 enabled、leave 按钮 disabled，三者均有 handler。该状态是观察值，不是本轮通过/失败的独立断言结论；待修复后按同一 harness 复验。

原始命令、stdout/stderr、fixture 请求记录、运行环境和摘要见同目录文件：`command.txt`、`stdout.txt`、`stderr.txt`、`result.json`、`environment-and-source.json`。

红阶段定位到原版 demo 刷新恢复未装载当前 Guide 状态，后续 turn 使用零状态版本且缺少 task/session 版本。
