# Mercury 客服快速启动指南

## 前置条件

1. **环境变量配置** (`.env` 文件)
   ```bash
   OPENAI_API_KEY=your_api_key_here
   OPENAI_BASE_URL=https://api.openai.com/v1  # 可选
   ```

2. **依赖安装**
   ```bash
   # 后端
   cd backend
   pip install -r requirements.txt
   
   # 前端
   cd frontend
   npm install
   ```

## 启动步骤

### 1. 启动后端服务
```bash
cd backend
uvicorn app.main:app --reload --port 8012
```

访问 http://localhost:8012/docs 查看 API 文档

### 2. 启动前端开发服务器
```bash
cd frontend
npm run dev
```

访问 https://localhost:8443 (Vite 默认端口)

## 测试 Mercury 客服

1. 在浏览器打开前端页面
2. 点击底部导航 → **订单** 标签
3. 底部第二个按钮显示 **"问问墨墨"** 🍞
4. 点击按钮 → 客服界面从底部弹出
5. 输入消息测试对话功能
6. 点击 **"我再逛逛"** 返回订单列表

## API 测试 (curl)

### 创建会话
```bash
curl -X POST http://localhost:8012/api/v1/mercury/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user_123"}'
```

响应示例:
```json
{
  "session_id": "mercury_session_abc123",
  "created_at": "2026-09-27T10:00:00Z"
}
```

### 流式对话
```bash
curl -N http://localhost:8012/api/v1/mercury/sessions/mercury_session_abc123/turns/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "我的订单什么时候到?"}'
```

SSE 流示例:
```
event: progress
data: {"phase": "understanding"}

event: answer_delta
data: {"delta": "您好"}

event: answer_delta
data: {"delta": "!让我"}

event: answer_delta
data: {"delta": "帮您查询"}

event: turn_completed
data: {"message_id": "msg_xyz", "completed_at": "2026-09-27T10:00:05Z"}
```

## 常见问题

### 1. 前端构建失败
**症状**: `npm run build` 报错
**解决**: 检查 Node.js 版本 >= 18.0.0

### 2. 后端无法启动
**症状**: `ModuleNotFoundError`
**解决**: 
```bash
cd backend
pip install -r requirements.txt
```

### 3. API 404 错误
**症状**: 前端调用 `/api/v1/mercury/*` 返回 404
**解决**: 确保后端已启动在 8012 端口,检查 `vite.config.ts` 的 proxy 配置

### 4. 客服界面无响应
**症状**: 点击"问问墨墨"无反应
**解决**: 
1. 打开浏览器开发者工具 → Console
2. 检查是否有 JavaScript 错误
3. 确认 Mercury API 路由已注册 (`app/main.py`)

## 文件结构速查

```
Ceres/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── mercury.py          # Mercury API 路由
│   │   ├── services/
│   │   │   └── mercury_bridge.py   # Mercury Agent 适配
│   │   └── main.py                 # FastAPI 主入口
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── MercuryChat.tsx         # 客服界面组件
│   │   ├── components/
│   │   │   └── MercuryMascot.tsx   # 面包吉祥物
│   │   ├── lib/
│   │   │   └── mercury.ts          # Mercury API 客户端
│   │   ├── App.tsx                 # 主应用 (视图管理)
│   │   └── index.css               # 动画样式
│   └── package.json
└── Mercury/
    └── mercury/
        └── agent.py                # Mercury Agent 核心逻辑
```

## 下一步

- [ ] 设计并替换面包 SVG 吉祥物
- [ ] 测试 Mercury Agent 的流式输出
- [ ] 添加订单查询工具集成
- [ ] 实现会话历史持久化
