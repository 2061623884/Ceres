# V2 order/Mercury boundary regression

- 范围：一次运行 `backend/tests/test_v2_order_mercury.py`，保留选单、owner 订单可见性、未选单订单工具不可执行及真实订单选项相关断言。
- 命令、解释器/pytest 版本、独立 TEMP/TMP/basetemp、测试 DB 说明及 25 个关联文件执行前 SHA-256：`command.txt`、`environment-and-source.json`。
- 退出码：0；stdout：`stdout.txt`（16 passed，12.69 秒）；stderr：`stderr.txt`（空）。执行后关联文件 SHA-256 全一致，见 `source-check-after.json`。
- 本次测试按 fixture 使用临时 SQLite；Mercury OpenAI 客户端由测试 monkeypatch 控制，无真实模型/API 请求。
- 未修改源码、测试源、TASK 或 Git 状态。
