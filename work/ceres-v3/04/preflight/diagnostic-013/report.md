# 代表测试 current / frozen-baseline 诊断

## 结论

这组 overlay 运行不能用于判断旧版与当前实现的因果差异。current `test_questions_block_a_chat_confirmation` 在空检索索引的受控环境下通过；current integrated 节点购买、确认、checkout 和订单读取均完成，但测试的 Mercury OpenAI 禁用桩按预期拦截后没有 `final_text`。两个 frozen-baseline 节点都受 overlay 根目录缺少静态数据影响：Phase2b 运行返回 `shopping-scenarios.json` 的 `FileNotFoundError`，integrated 在 fixture setup 因 `ingredient-catalog.json` 缺失报错。

我没有从当前工作区补数据、复制 `.env`、覆盖配置根路径或改测试夹具。baseline 结果保留为夹具前置失败，不能当成旧版业务 red。

## 可比性与运行环境

四次运行使用 `backend/.venv/Scripts/python.exe`，Python 3.12.10、pytest 9.1.1，开启 `-W error::pytest.PytestUnhandledThreadExceptionWarning`，每次都有独立 `--basetemp` 和数据库。测试与 fixture 留在当前 checkout；baseline 仅从 SHA-256 已验证的冻结 ZIP 导入 `backend/app` 与 `Mercury/mercury`。冻结包 SHA-256 为 `5e393ee8f99f3d976f62c55481f292013312ae688b0e504ed7a8577b3a3a5f73`，overlay 中 123 个文件逐项与其 manifest 相符，未提取 `.env`。

两侧显式设置相同的非秘密环境：`LLM_MODE=live`、`BUSINESS_DATA_MODE=demo`、`OPENAI_BASE_URL=http://127.0.0.1:9/v1`、公开 dummy key、`LLM_MODEL=codex-test-model`、`MEMORY_MODEL=`、`KEV_BASE_URL=http://127.0.0.1:9`、`RETRIEVAL_MODE=hybrid`、启动时 `RETRIEVAL_INDEX_DIR=`，以及 loopback embedding endpoint。`semantic_provider` 是测试控制桩；integrated 测试把 `mercury.llm.OpenAI` 替换为显式抛错桩。没有真实模型调用证据，也不声称进行了主模型采样。

current `Settings.ROOT_DIR` 是 Ceres checkout；baseline `Settings.ROOT_DIR` 是 `work/ceres-v3/04/preflight/diagnostic-013/baseline-overlay`。Phase2b current 的 `source_database_path` fixture 指向 checkout 内 `data/sale_guide.db`（SHA-256 `772a2d1c74bd112a01405aeefde7455f2c58e701e38d8186a29d24a52640be10`）；ordinary-client runtime DB 位于该次 basetemp。baseline Phase2b 也读同一 source DB，但在相同流程中由于 baseline ROOT_DIR 下缺少 `data/fixtures/shopping-scenarios.json`，在首轮 `_new_plan` 处失败。integrated current 使用配对的 fixture index/runtime DB 和 `no-source.sqlite3`；baseline 在 index fixture 完成前就因 ROOT_DIR 下缺少 `data/fixtures/ingredient-catalog.json` 而于 setup 失败。因此这两条 baseline 不能证明旧版的业务表现。

## 各次执行观察

| 运行 | 结果 | 观察 |
|---|---:|---|
| current Phase2b | exit 0，1 passed | 普通 `client`；源库为固定 checkout DB；`番茄炒蛋` 任务成为 `active / awaiting_confirmation`，目标为 `番茄炒蛋`；随后 assistant 提问“需要确认这份清单吗？”。此节点不是 red。 |
| baseline Phase2b | exit 1，1 failed | `_new_plan` 收到 terminal error；从该次临时 DB 的 `turn_request_records.response_json` 读得 `FileNotFoundError`，路径为 overlay `data/fixtures/shopping-scenarios.json`，HTTP 400，`retryable=false`。未进入预期确认断言。 |
| current integrated[1] | exit 1，1 failed | 购买、两个确认、checkout 和订单查询已通过；最终无选单 Mercury 回合的事件缺少 `final_text`。测试安装的 OpenAI 禁止调用桩抛出 `AssertionError: Mercury must return the owner's real order choices without a model call`。 |
| baseline integrated[1] | exit 1，1 error | fixture setup 的 `FileNotFoundError`：overlay `data/fixtures/ingredient-catalog.json`；没有进入 test body。 |

完整命令见 [commands.json](commands.json)；环境键、退出码与 raw stdout/stderr SHA-256 见 [comparison-manifest.json](comparison-manifest.json)。各运行原始输出、启动环境/模块路径和 fixture 实际路径见对应子目录下的 `stdout.txt`、`stderr.txt`、`bootstrap.json`、`fixture-observation.json` 与 `result.json`。

## 原始运行命令

```powershell
$run = 'work\ceres-v3\04\preflight\diagnostic-013\current-phase2b'; $tmp = Join-Path $run 'pytest-temp'; & 'backend\.venv\Scripts\python.exe' -X utf8 'work\ceres-v3\04\preflight\diagnostic-013\diagnostic_runner.py' current 'test_phase2b_chat_confirmation.py::test_questions_block_a_chat_confirmation' $run $tmp; $code = $LASTEXITCODE; Write-Output "RUNNER_EXIT=$code"; exit $code
```

其余三次实际命令见 `commands.json`；统一 runner 与环境清单保存在本目录。
