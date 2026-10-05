# Ceres V3 / 02 test preflight

日期：2026-10-06。用途：供 02 政策问答票的受控测试执行复用。未改源码、测试源、TASK 或 Git 暂存区。

## 环境与配置

- 项目测试解释器：`backend/.venv/Scripts/python.exe`，Python 3.12.10 x64；pytest 9.1.1。
- 测试从 `backend/` 目录启动；配置来自 `backend/pyproject.toml`：`testpaths = ["tests"]`、`asyncio_mode = "auto"`、忽略 DeprecationWarning。
- Mercury 独立测试从 `Mercury/` 目录启动，复用 backend 虚拟环境；`Mercury/pyproject.toml` 配置 `tests`，`live` 标记要求 `MERCURY_LIVE=1`。不运行 live-marked 测试。
- `backend/tests/conftest.py` 的 `client` 为每例创建 pytest `tmp_path` 下 SQLite 数据库；`test_v3_policy_consultation.py` 使用 `support.v2_fixture.source_database_path` 指向同一临时目录的 `no-source.sqlite3`，避免读取或写入仓库运行库。
- `semantic_provider` 注入脚本化语义提供器，替代可可链上的模型调用。选定首个红例不访问真实 API。墨墨公共 API测试通过 `monkeypatch` 注入受控 OpenAI 客户端，亦不应联网。
- 当前进程环境中 `LLM_MODE`、`BUSINESS_DATA_MODE`、数据库路径及 OpenAI 凭据均未设置；测试 fixture 会为单例覆盖数据库，并由 `conftest.py` 将业务模式默认设为 demo。没有在记录中保存凭据。

## 02 回归命令候选

首个红例与后续红绿测试在 `backend/` 执行，使用当前 backend `.venv`、`-p no:cacheprovider`、独立 `--basetemp`，并将 `TEMP`/`TMP` 指向对应 `work/ceres-v3/02/preflight/<run-id>/os-temp/`。先执行具体新增单例；绿阶段按其涉及行为再选必要的 `test_v2_order_mercury.py` 和 V3 测试，不默认全量回归。

政策模块已有隔离回归候选：从 `Mercury/` 执行 `tests/test_policy.py` 与 `tests/test_agent_flows.py::test_policy_flow`。公共 API 与 owner/选单/申请边界优先从 `backend/` 执行 `tests/test_v2_order_mercury.py`，按首个绿实现挑选节点。所有命令运行前确认使用本文件记录的解释器和隔离路径。

## 证据

每次测试在独立子目录保留：实际完整命令、工作目录、解释器与必要环境、test/source SHA-256、独立 TEMP/TMP 与 pytest basetemp、stdout、stderr、退出码及简要解释。测试失败、失败断言与环境失败分开记；此处不汇总为通过。
