# Ceres

超市智能导购：Vite + React 界面（`frontend/`）与 FastAPI + LangGraph 后端（`backend/`）。售后客服 Agent 在同仓库的 `Mercury/`，独立运行，不读导购数据库。

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
