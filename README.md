# Ceres

超市智能导购：Vite + React 界面（`frontend/`）与 FastAPI + LangGraph 后端（`backend/`）。Mercury（墨墨）是同仓独立售后模块，当前由 Ceres 后端导入并提供 API，使用独立演示订单库，也可单独运行 CLI。

## 项目与任务入口

- [Ceres v1 TASK](tasks/ceres-v1.md) / [本机重建](docs/ceres-v1-local.md)：64 fixture 基础与最少果汁补齐，按已确认六任务编排实现；向量和业务验收分别记录。

## 启动（PowerShell）

终端 1 — 后端（端口 **8012**）：

```powershell
Set-Location -LiteralPath "C:\Users\20616\Desktop\Agent\Agent产品\Ceres\backend"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

终端 2 — 前端（端口 **8443**，`/api` 与 `/media` 代理到 8012）：

```powershell
Set-Location -LiteralPath "C:\Users\20616\Desktop\Agent\Agent产品\Ceres\frontend"
npm run dev
```

健康检查：http://127.0.0.1:8012/health

环境变量见根目录 `.env.example`；本机配置复制为 `.env`（不入库）。
