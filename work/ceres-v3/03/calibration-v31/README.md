# Kev v3.1 校准执行记录

## 结果

对 01 的 8 条 `chinese-pilot.json` 开发案例按原顺序各调用一次本地 `KevProvider.decide`，共收到 5 个有效响应，5/5 与原预期一致；另外 3 条为 `ReadTimeout: timed out`，没有可记录的选择或概率。未重试，也未改预期。`results.json` 中 `status=complete` 表示 8 条都已尝试并写入结果，不代表 8 条都成功。

01 的两项已观察错分在成功响应中符合原预期：一般退货政策返回 `stay_current`（概率 0.4888），无对象取消返回 `clarify` 的该次请求超时，**因此无对象取消是否修复尚未验证**。无对象取消在本次没有有效响应，不能计入 5/5。

| 案例 | 原预期 | Kev选择 | 服务端 latency_ms | 本机调用耗时 |
| --- | --- | --- | ---: | ---: |
| guide-shopping | stay_current | stay_current | 324.0 | 1429.516 ms |
| guide-order-logistics | suggest_switch | suggest_switch | 286.1 | 1369.013 ms |
| guide-general-return-policy | stay_current | stay_current | 287.1 | 1576.109 ms |
| momo-order-return-eligibility | stay_current | stay_current | 285.6 | 1449.935 ms |
| momo-new-shopping | suggest_switch | 超时 | — | 3873.267 ms |
| cancel-without-object | clarify | 超时 | — | 3838.089 ms |
| cancel-shopping-list | stay_current | 超时 | — | 3842.047 ms |
| cancel-placed-order | suggest_switch | suggest_switch | 561.7 | 3146.064 ms |

本机耗时按调用开始到 `KevProvider.decide` 返回/抛错测量；服务端 latency 来自成功原始响应中的 `latency_ms`。模型侧 3 条超时的确切原因未查明。本批成功响应调用耗时范围约 1.37–3.15 秒；`httpx.Client(timeout=3.0)` 配置是网络阶段超时，不保证函数总墙钟耗时不超过 3 秒。

## 可复核证据

- `execution.json`：解释器、完整启动命令、cwd、KEV_BASE_URL 覆盖、退出码及日志位置。解释器是 `backend/.venv/Scripts/python.exe`，实际启动 cwd 为仓库根目录；runner 显式将 `backend` 加入 `sys.path`。本次没有按建议将 cwd 设为 `backend`，为遵守单次采样约束未重跑案例。
- `run-calibration.py`：一次性执行器，从 provider 源码 AST 读取字面量常量；直接导入并调用真实 `KevProvider.decide`，未调用主模型。
- `frozen-requests.json`：由固定 source 常量和 01 输入状态生成的 8 个完整请求 payload 及摘要。
- `results.json`：8 条逐案状态、选择、完整概率、原始 JSON 响应、服务端 latency、耗时和错误。
- `stdout.log` / `stderr.log`：原始执行输出；PowerShell 退出码为 0（所有样本结果都已保存，单例请求失败由 provider 转为 `KevUnavailable` 并记录）。

本次标准版本：`ceres-service-v3.1`。provider 源码 SHA-256：`dd1e58bd681668b8c007d2d10161f9b5eed3bdd81c7fe1179c96dd031b285259`；01 案例文件 SHA-256：`0a92aa350431b752fd6fb4d37ce5b659ff4e6140a52a3077f1d98bfc28dd83d1`。执行期间源码哈希未变。目标经 Windows 本机 `127.0.0.1:18009` SSH 转发访问 Amax 的 Kev 服务，未重启隧道。
