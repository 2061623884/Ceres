# 测试环境准备记录

日期：2026-10-06
范围：仅确认原仓可复用测试运行方式；未运行测试、未启动服务、未做 V3 完成度审计。当前项目代码、测试与 TASK 均未修改。`.env` 文件存在，但未读取或输出其内容。

## 本机运行时

- 后端解释器：`backend/.venv/Scripts/python.exe` 存在，Python 3.12.10；pytest 9.1.1、FastAPI 0.141.1、LangGraph 1.2.12、HTTPX 0.28.1、Pydantic 2.13.5、SQLAlchemy 2.1.1 可导入。`backend/pyproject.toml` 将测试根目录设为 `tests`，`asyncio_mode=auto`。
- 前端：原仓 `frontend/node_modules` 与 Vite 可执行入口存在；Node 24.14.0、npm 11.9.0、pnpm 11.7.0 可用。`frontend/package.json` 提供 `dev/build/preview/format`，没有 test script。`frontend/vite.config.ts` 默认 8443 端口，`/api` 与 `/media` 代理到 `127.0.0.1:8012`。不同 worktree 是否已安装前端依赖尚未确认；不能假定原仓 `node_modules` 自动出现在 worktree。

## 可复用测试方式

- 受控后端 API：在 `backend/` 使用原仓虚拟环境运行指定 pytest 用例，例如 `& '.\.venv\Scripts\python.exe' -m pytest -q tests/<ticket-test>.py`。`backend/tests/conftest.py` 的 `client` 使用 `tmp_path/test.sqlite3`，注入临时数据库会话并加载最小模拟数据；`semantic_provider` 可脚本化主模型语义提案。现有 V3 路由用例的 `kev` fixture 将 Kev 请求导向 `kev-controlled.invalid` 并在测试内返回受控选择，不访问真实 Kev。
- 索引隔离：现有 `indexed_client` 模式用 `tmp_path/index` 构建/发布索引，并通过进程环境设置 `RETRIEVAL_INDEX_DIR` 与 `RETRIEVAL_MODE=lexical`；每票应继续用自己的临时索引目录，不复用根目录运行索引。
- 公开 API 与页面：项目入口命令见 `README.md`：后端 `uvicorn app.main:app --host 127.0.0.1 --port 8012`，前端 `npm run dev`。浏览器默认访问 `http://127.0.0.1:8443`，Vite 代理至后端。实际多轮交互应在该页面点击并保留单独的浏览器记录；受控 TestClient/API 结果不代替真实前端点击。
- Mercury 集成：`docs/mercury/mercury-quickstart.md` 说明其由 Ceres 后端导入运行，前端验证不需另开 Mercury HTTP 服务。
- 真实模型：Ceres Settings 从根目录 `.env` 读取 `LLM_MODE`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`LLM_MODEL` 与 `KEV_BASE_URL`。文档记录 Kev 默认本地地址 `127.0.0.1:18009`，经 SSH 转发到 Amax 的 8009；该服务当前可用性未探测。真实调用应与受控回归分开记录；不得读取、打印或写入密钥。

## 每票隔离与记录

所有测试命令由专职测试 Agent 执行；Agent 不改源码、测试或 TASK，不提交 Git。每票分别使用临时 SQLite DB、索引和输出目录；不将根目录运行数据库、索引或共享演示库作为写入目标。记录命令、退出码、失败摘要和原始输出，并区分受控 API、真实模型、浏览器点击及人工审读。遵循 TDD 技能的垂直切片和用户可见公开接缝；本阶段已授权公开聊天/确认/交接 API 多轮旅程及真实前端点击。

## 后续页面与真实采样可用条件（2026-10-06 补查）

- 只读检查发现默认端口已被占用：`127.0.0.1:8012` 是 Python 进程，`0.0.0.0:8443` 是 Node 进程，`127.0.0.1:8009` 也是 Python 进程；`18009` 没有监听。没有停止或重启任何进程。
- `GET http://127.0.0.1:8012/openapi.json` 返回 200，OpenAPI title 为 `Sale-guide API`。该 PID 的命令行未包含 Ceres 或 Sale-guide 路径，因此无法仅凭当前证据确认其代码来源；在确认前不要将它当作本阶段 Ceres 后端。`GET http://127.0.0.1:8443/` 返回 200、title 为 `Figma Make App`；对应 Node 命令行包含本仓 Ceres 路径，可确认它关联当前 Ceres 前端进程，但标题仍是通用值。
- 前端 Vite 配置读取 `PORT` 环境变量且设置 `strictPort: true`；`/api` 与 `/media` 代理目标仍固定为 `http://127.0.0.1:8012`。因此默认前后端端口当前不可直接用于新启动的隔离页面测试；避免抢占或终止现有进程。启动候选页面前需由主会话确定隔离端口/代理方式，或明确安排释放目标端口。
- Kev 文档地址 `127.0.0.1:18009` 当前无监听；`8009` 虽有 Python 监听，但没有向其发请求，无法确认服务身份。没有执行真实模型采样，也没有读取 `.env`。
- CUA 当前浏览器与应用清单均为空；尝试创建 `iab` 本地页返回 `Browser is not available: iab`，因此目前没有可用的浏览器自动化连接。候选冻结后再进行页面点击；届时需先恢复/提供可用浏览器控制面，并确认 Ceres 前后端使用隔离且匹配的端口。
- 后续 PowerShell 测试进程应设置 `PYTHONUTF8=1` 并按 UTF-8 保存输出，避免中文诊断乱码。01 首轮红测试已保留原始记录，不为此重跑。

## 独立端口与浏览器自动化补查（2026-10-06）

- 主会话建议的 `127.0.0.1:18012`（backend）与 `127.0.0.1:18443`（frontend）在检查时均无监听，可作为隔离启动候选端口。尚未启动服务。前端默认 Vite 配置把代理固定到 8012；主会话提出的 work 证据启动脚本可用 `createServer` 临时覆盖 `/api`、`/media` 目标到 18012，不改产品配置；该启动方式尚未执行验证。
- 用原仓 `backend/.venv` 的 `Settings()` 读取非敏感运行字段并只打印安全值：`LLM_MODE=live`、`LLM_MODEL=qwen3.8-27b`、`OPENAI_BASE_URL=https://discovery-api.intern-ai.org.cn/v1`、`KEV_BASE_URL=http://127.0.0.1:18009`。未读取或打印 key。18009 当前无监听，因此暂时不具备真实 Kev 采样条件；未调用模型或 Kev。
- Codex workspace bundled Node packages 中有 `playwright` 与 `playwright-core`，没有 `@playwright/test`。Playwright 返回的 Chromium 期望路径是 `C:\dev-caches\ms-playwright\chromium-1234\chrome-win64\chrome.exe`，文件不存在；常见 Edge/Chrome 安装路径和 Playwright 缓存目录也未找到。结合 CUA 无可用 browser provider，目前没有可执行的浏览器二进制供真实前端点击/E2E 使用。

## Amax Kev 只读确认与 SSH 转发（2026-10-06）

- `ssh.exe -T -o BatchMode=yes -o ConnectTimeout=8 amax` 成功。远端 `127.0.0.1:8009` 正在监听，`ss` 仅显示进程名 `python`、PID `2701504`；只读 GET `/openapi.json` 返回 OpenAPI title `kev`。未启动、停止或重部署远端服务。
- 在确认本地 18009 空闲后，按 `docs/ceres-v3.md` 的既有转发建立隐藏 SSH 隧道：`ssh -N -L 127.0.0.1:18009:127.0.0.1:8009 -o BatchMode=yes -o ExitOnForwardFailure=yes -o ConnectTimeout=8 amax`。本机 `ssh.exe` PID `56600`，启动时间 `2026-10-06 14:14:54`（Asia/Shanghai）；该 PID 当前监听 `127.0.0.1:18009`。本机 GET `/openapi.json` 返回 200、title `kev`，确认转发可达。此检查只读元数据，不调用模型。
- 清理本地隧道时仅停止仍对应 `ssh.exe` 的 PID `56600`；不触碰 Amax PID `2701504`。本轮保留隧道供后续授权采样使用，未运行新留出或新功能样本。

- 经主会话授权，用 bundled Playwright CLI（1.62.1）将匹配的 Chrome for Testing 151.0.7922.34 / Chromium rev 1234 下载到 `work/ceres-next-agent-experience/00-preparation/playwright-cache`，未触碰产品 `package.json` 或 `node_modules`。安装原始输出在 `playwright-install-output.txt`。
- 当前进程设置 `PLAYWRIGHT_BROWSERS_PATH` 指向上述目录后，headless Chromium 启动并关闭成功，版本 `151.0.7922.34`；smoke 输出在 `playwright-smoke-output.txt`。未加载 Ceres 页面或执行交互。后续真实页面可用 bundled Playwright 控制该工作缓存浏览器，不依赖 CUA。

## 01 UI 隔离依赖与受控点击 probe（2026-10-06）

- 原仓 `frontend/node_modules` 的 pnpm 虚拟存储存在缺失依赖链接：`magic-string@0.30.21/node_modules/@jridgewell/sourcemap-codec` 未链接，导致 Vite ESM 配置加载失败；`--preserve-symlinks` 又触发 Vite/Rolldown 导出不匹配。没有修补原仓依赖。
- 在 `.ceres-next-01-ui/frontend` 内移除仅由本测试 Agent 创建的 `node_modules` Junction（仅删除链接本身，原仓目标仍在），用 `corepack pnpm@10.34.3 install --frozen-lockfile --store-dir=work/ceres-next-agent-experience/00-preparation/pnpm-store` 安装独立依赖。pnpm 报 43 包完成，exit 0；UI worktree `package.json`、`package-lock.json`、`pnpm-lock.yaml` 安装前后 SHA256 全部一致。命令和原始输出见 `work/ceres-next-agent-experience/01-ui/pnpm-install-frozen-output.txt`。一个外层 PowerShell 比较表达式错误曾使包装命令退出 1，已单独逐文件核对哈希均匹配；pnpm 安装本身退出 0。
- 受控 UI probe 使用 bundled Node 24.19.0、bundled Playwright 和本阶段 `00-preparation/playwright-cache` 下 Chromium。probe 曾因自身把 cache 路径相对 UI worktree 计算错误而未启动浏览器；修正为尊重调用进程的 `PLAYWRIGHT_BROWSERS_PATH` 后已到达页面行为断言。有效红是点击第二个同标签薯片气泡后，`/turns/stream` body 的 `clarification_answer` 为 undefined；预期提交当前 `question_id` 与被点击 `option_id`。原始输出/命令见 `work/ceres-next-agent-experience/01-ui/ui-clarification-red-final-output.txt` 与 `ui-clarification-red-final-run.txt`。这是受控前端契约检查，不是真实后端或模型验收。

## Integration 前端依赖与 Kev OpenAPI 预检（2026-10-06）

- 按主会话要求在 `work/.ceres-next-integration/frontend` 安装独立物理 `node_modules`（安装前不存在，不使用01 UI的junction）；命令 `corepack pnpm@10.34.3 install --frozen-lockfile --store-dir=work/ceres-next-agent-experience/00-preparation/pnpm-store`，exit 0，共 43 包。`package.json`、`package-lock.json`、`pnpm-lock.yaml` 的 SHA256 安装前后均一致。执行记录在 `integration-frontend-pnpm-install.txt`。未运行测试/构建。
- 03 的只读 Kev 协议检查 GET `http://127.0.0.1:18009/openapi.json` 返回 200，OpenAPI title `kev`、version `0.1.0`。`SystemOneRequest.questions` 允许 `Noul`/`Choice`/`Score`，其中 `Choice.criteria` 是任意 object，可表达四类能力标签；文档未定义 Ceres 四类标签或强类型四选一响应，200 response schema 为空。此项只证明请求形状可承载，不证明能力判断质量；尚未发送真实判断样本。详细操作及 schema 摘要在 `work/ceres-next-agent-experience/03/kev-openapi-summary.txt`。
