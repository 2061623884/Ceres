# Demo SSE consumer diagnostic (不复现疑点)

- 对象：work/ceres-v3/03/demo.html 内联 consumer。demo 源 SHA-256 前后均为 a89d73a74c324902d62e50bd4a917404b0c30891518319171fc34d182ea5f61d，未修改。
- Headless Edge 尝试未形成有效测试结果：PowerShell 在访问仍被占用的重定向 stdout 时失败；Edge 原生退出码未取得，stdout/stderr 均为空。之后没有发现带本次独立 profile 或 harness 路径的 Edge 进程。没有启动服务器/监听端口，也没有结束用户现有 Edge 进程。细节见 browser-attempt.json 和 browser.stdout.txt / browser.stderr.txt。
- 按授权改用 Node vm：Node v24.14.0，PID 24804，exit 0；无服务器、无端口，进程已退出。将 demo 的原始 inline consumer 原文放入 vm，以最小 DOM、mock opening GET 和含 CRLF 分帧的标准 SSE Response 执行。消费者确实显示 service.route（“路由：clarify，12 ms”）及 turn.completed（“请补充说明”），仅发生一个被 mock 的 opening GET。
- 因而这次受控 consumer 测试没有复现“换行符导致帧不能拆分”。源码中 JSON 展示的双反斜杠是序列化转义；运行时按 JavaScript 字符串转义处理。此结果只验证真实 demo consumer 对合成 SSE 的解析，不等于正式浏览器端到端或实时后端验证。
- 原始命令、运行输出、摘要与 Node 执行脚本见同目录 node-vm-command.txt、node-vm.stdout.txt、node-vm.stderr.txt、node-vm-diagnostic.cjs、result.json。
