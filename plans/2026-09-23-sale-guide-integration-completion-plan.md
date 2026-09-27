# Ceres × Sale-guide 产品功能与交互补全方案

- 版本：v1（2026-09-23）
- 性质：**方案文档**。本次交付只新增本文件，未修改任何源码、配置、测试或其他文档。
- 适用对象：产品/设计（做阶段 2、阶段 3 的取舍决策）与开发（按阶段 0、1、4 执行）。
- 未执行任何业务测试。本文所有“事实”条目均来自对两个项目当前代码与配置的只读检查；“待决策”条目尚无产品结论；“建议”是实现方向，不代表已存在。

## 0. 阅读约定

| 标记 | 含义 |
| --- | --- |
| **【事实】** | 已由 Ceres / Sale-guide 当前代码或配置核实，可直接依赖（代码/配置层面） |
| **【已实测】** | 来自 1.1.1 的验证记录（V1–V4）：此前代码审阅时实际执行，2026-09-23 记录，本轮未重跑 |
| **【未验证】** / **【待验证】** | 由事实推导或由既有实测部分推出，但该部分未实机验证；见 1.1.1 的 N1–N4 |
| **【决策】** | 需要产品/负责人拍板，未定前不要开工 |
| **【建议】** | 推荐实现方式，可在评审时替换 |

方案整体约束（先读）：

1. **不重写已接通的主链**。Ceres 的商品分类/列表/搜索、购物车增改、导购会话、SSE 流式回合、清单确认加购均已在用，本次不重构 API 封装层，也不改动 Sale-guide 的 Agent/LLM 与业务 service。
2. **不把规划能力写成已有能力**。Sale-guide 当前没有订单、结算、支付、履约、退款、账号资料、收藏、通知、门店/配送区列表、排序参数。阶段 2、阶段 3 中凡涉及这些的，都属于**新增能力**。
3. 两个仓库都存在大量未提交改动，任何阶段都不得回退、覆盖或清理他人改动（含 `git reset` / `git clean` / `git checkout --`）。

---

## 1. 事实基线

### 1.1 运行与配置事实

| # | 事实 | 依据 |
| --- | --- | --- |
| F1.1 | Ceres 是 Vite 8 + React 19 单页应用，`npm run dev` 默认端口 8443，`strictPort: true` | `Ceres/package.json`、`Ceres/vite.config.ts`（`server.port = PORT \|\| 8443`） |
| F1.2 | 只有 Ceres **dev server** 把 `/api` 与 `/media` 固定代理到 `http://127.0.0.1:8001`（超时 120s）；`preview` 未配置 `proxy`，`build` 产物同样不含代理（与 F1.9 一致） | `Ceres/vite.config.ts`（`server.proxy` 只在 `server` 段；`preview` 段仅有 host/port） |
| F1.3 | Sale-guide 后端默认端口是 **8000**，不是 8001 | `Sale-guide/README.md`（uvicorn `--port 8000`）、`Sale-guide/.env.example`（`BACKEND_PORT=8000`）、`Sale-guide/frontend/next.config.js`（`process.env.BACKEND_PORT \|\| '8000'`） |
| F1.4 | Sale-guide Next 前端把 `/api/*` 与 `/media/images/*` 反向代理到 `127.0.0.1:${BACKEND_PORT}` | `Sale-guide/frontend/next.config.js`（`rewrites`） |
| F1.5 | Ceres 通过**同源代理**访问接口，不依赖跨域；Sale-guide 的 CORS 白名单只含 3000/3001/3010，不含 8443 | `Ceres/src/lib/saleGuide.ts`（`API_BASE = ''`）、`Sale-guide/backend/app/main.py`（`CORSMiddleware`） |
| F1.6 | 身份为匿名 HttpOnly Cookie `sg_owner_id`，由 `GET /api/v1/bootstrap` 首次创建，有效期 30 天，`secure=False` | `Sale-guide/backend/app/core/identity.py`、`app/api/bootstrap.py` |
| F1.7 | 商品图片由后端静态挂载为 `/media/images/*` | `Sale-guide/backend/app/main.py`（`StaticFiles`） |
| F1.8 | Sale-guide 的 Next 前端必须为流式回合单独走 `/api/guide-stream`，原因是通用代理会压缩 `text/event-stream`，导致事件在结束时一次性到达 | `Sale-guide/frontend/next.config.js` 注释与 `beforeFiles` 规则 |
| F1.9 | Ceres 生产构建（`vite build`）与 `vite preview` 都**没有** `/api`、`/media` 代理，只有 dev server 有 | `Ceres/vite.config.ts`（`preview` 仅配置 host/port） |
| F1.10 | Sale-guide 后端仅 live 模型模式，无离线回退；缺少 `OPENAI_*` / `LLM_MODEL` 时导购回合不可用 | `Sale-guide/README.md`、`Sale-guide/.env.example` |

#### 1.1.1 验证记录（2026-09-23 记录）

下表区分“此前代码审阅时**已实际执行**的检查”与“**尚未测试**的项”。V1–V4 的结论来自此前审阅时对真实运行服务的 HTTP 调用与 Ceres 构建，2026-09-23 记录在本文档中；**本轮文档修订没有重跑这些检查**。

| # | 检查 | 结果 | 状态 |
| --- | --- | --- | --- |
| V1 | Sale-guide 后端在 **8000** 上访问 `GET /health`、`GET /api/v1/bootstrap`、`GET /api/v1/categories` | 三个端点均可访问 | 已实测（此前审阅，2026-09-23 记录） |
| V2 | Sale-guide 后端在 **8001** 上访问同样三个端点 | 三个端点均可访问 | 已实测（此前审阅，2026-09-23 记录） |
| V3 | Ceres dev 服务 `http://127.0.0.1:8443` 经 Vite 代理访问 `/api/v1/bootstrap`、`/api/v1/categories` | HTTP 200 | 已实测（此前审阅，2026-09-23 记录） |
| V4 | Ceres `npm run build` | 构建成功 | 已实测（此前审阅，2026-09-23 记录） |
| N1 | SSE `answer.delta` 通过 Ceres dev 代理逐字到达（真实模型回合） | — | **未测试** |
| N2 | 真实模型的多轮对话与清单确认加购全链路（Ceres 界面） | — | **未测试** |
| N3 | `vite build` 产物在部署形态下访问 `/api`、`/media` | — | **未测试** |
| N4 | Sale-guide 的 pytest、离线购物验收脚本、前端组件测试与 Playwright E2E | — | **未运行** |

**由事实推出的结论：**

- **【已实测 + 未验证】P1**：Ceres dev 代理固定指向 8001，已实测 8001 上有服务时 `/api/v1/bootstrap`、`/api/v1/categories` 经 `127.0.0.1:8443` 返回 200（V2、V3）；同时 8000 上同样三个端点也可访问（V1）。即：**8001 可用，但不是唯一可用端口**——与 F1.3 的“Sale-guide 文档默认端口为 8000”并不冲突，两者只是端口配置不同。若后端只监听 8000 而 Ceres 代理仍指向 8001，代理侧失败路径**尚未实测**（未测试项）。
- **【未验证】P2**：Ceres 走 Vite dev 代理承载 SSE，与 Sale-guide 遇到的“代理压缩导致事件堆积”不是同一实现；`answer.delta` 是否逐字到达**尚未测试**（N1）。
- **【已实测 + 未验证】P3**：Ceres `npm run build` 已实测通过（V4）；但构建产物在部署形态下能否访问 `/api`、`/media` **尚未测试**（N3），部署形态（同域反代 / 独立后端域 / 仅演示用 dev server）仍需决策。
- **【事实】** `/health` 会返回 `llm_configured`、`retrieval`、`business_data_mode`，可作为阶段 0 的一键就绪探针；`/api/v1/bootstrap` 返回 `demo_notice`（“演示门店，价格、库存及配送为模拟数据”）。

### 1.2 Sale-guide 已提供的接口（Ceres 已接入）

| 能力 | 接口 | Ceres 调用点 |
| --- | --- | --- |
| 分类 | `GET /api/v1/categories` | `listCategories()` → `ShelfScreen` 分类条 |
| 商品列表 / 关键词搜索 | `GET /api/v1/products?q&category_id&page&page_size` | `listProducts()` → `ShelfScreen`（搜索与列表同端点） |
| 商品详情 | `GET /api/v1/products/{sku_id}` | `getProduct()` **已封装但未被任何界面使用** |
| 购物车 | `GET /api/v1/cart`、`POST /api/v1/cart/items`、`PATCH /api/v1/cart/items/{sku_id}`、`DELETE /api/v1/cart/items/{sku_id}`、`GET /api/v1/cart/operations/{id}` | 前三个已接入（`getCart` / `addCartItem` / `patchCartItem`），`quantity=0` 即删除行；**DELETE 与 operations 未封装** |
| 导购会话 | `POST /api/v1/guide/sessions`、`GET /api/v1/guide/sessions/{id}?include_messages=1` | `createGuideSession()` / `getGuideSession()` → `ChatScreen` 会话恢复与新建 |
| 流式回合 | `POST /api/v1/guide/sessions/{id}/turns/stream`（SSE） | `sendTurnStream()`，已处理 `accepted` / `progress` / `answer.delta` / `plan.ready` / `clarification` / `turn.completed` / `turn.stopped` / `error` |
| 清单确认加购 | `POST /api/v1/guide/tasks/{task_id}/confirm`（带 `Idempotency-Key`） | `confirmPlan()` → `PlanDock`“确认加购” |
| 客户端事件 | `POST /api/v1/events`（白名单事件类型） | **未接入** |

版本契约事实：`initSession` 与 `send` 都携带 `store_id`、`delivery_zone_id`；`confirmPlan` 携带 `expected_state_version` / `expected_session_version`：加购写库仍由用户确认触发，模型不自动加购（与 `Sale-guide/README.md` 架构说明一致）。

后端在售前/售后状态机里还会下发 `available_actions`：`awaiting_confirmation` 时为 `["confirm","cancel","modify","send_message"]`（方案 `stale_supply` 时去掉 `confirm`、追加 `refresh_plan`），完成/取消/被取代时为 `["start_new","send_message"]`（`Sale-guide/backend/app/services/session_actions.py`）。**Ceres 只读取了其中的 `confirm`，其余动作未在界面上暴露。**

### 1.3 Sale-guide 明确**没有**的能力（不得在方案中当成已有）

| 缺口 | 事实依据 |
| --- | --- |
| 订单、结算、支付、配送履约、退款退货 | `prd.md` §3.7 明确“V1 业务流程止于用户确认并完成加购”，并列出不负责项；§4.13 写明“购物车 → 结算 → 支付 → 配送”属于平台已有流程，不属于本导购系统；`Sale-guide/backend/app/models/` 只有 `cart / catalog / conversation / session / store / trace`，无订单模型；`app/api/` 无订单路由 |
| 结算能力 | Sale-guide 购物车页自身文案即“数据模式：{business_data_mode}（不含结算支付）”（`frontend/src/app/cart/page.tsx`） |
| 账号资料 / 会员 / 积分 / 优惠券 | 只有匿名 `owner` cookie，无用户资料模型与接口 |
| 收藏 / 心愿单 | 无模型、无路由，前端也无对应页面 |
| 通知 / 消息中心 | 无模型、无路由 |
| 门店 / 配送区列表 | `bootstrap` 固定返回 `store-demo-01` / `zone-default`，无枚举接口 |
| 排序参数 | `GET /api/v1/products` 仅支持 `q`、`category_id`、`page`、`page_size`，无 `sort` |
| 分页消费 | 接口返回 `total`，但 Ceres 未使用（见 1.5） |

> 结论：**阶段 2 的订单页、账户功能与阶段 3 的部分条目，都是“新增后端能力”，不是“把已有接口接上”。**如果产品不接受新增后端能力，唯一诚实的选择是把对应界面标注为演示态或从主路径移除。

### 1.4 Ceres 现状：已接通 vs 占位（逐屏）

**首页 `LandingScreen`**

| 元素 | 现状 |
| --- | --- |
| 吉祥物 + 问候 | 纯展示，按心情切换表情（`CeresMascot`、`ToastMascot`） |
| 今日心情（5 档） | **本地 `useState`**，带 `DemoBadge`；组件随导航卸载后选择丢失；未影响导购输入 |
| “查看全部 ↗” | **无 `onClick`**，纯文本按钮 |
| “减脂餐”卡 | 有动作：`handleDietPlan()` → 切到导购视图并预置消息“帮我配一份减脂餐” |
| “生鲜采买”卡 | 有动作：切到商品架 |

**商品架 `ShelfScreen` / `ProductCard` / `CartDrawer`**

| 元素 | 现状 |
| --- | --- |
| 地区“静安区 ⌄” | 静态文案，**无 `onClick`**；与 `bootstrap` 返回的 `delivery_zone_id` 无关联 |
| 通知铃铛 | **无 `onClick`**，无未读态 |
| 搜索框 | 已接通（与服务端 `q` 同步） |
| 分类条 | 已接通；`jumpToCategory` 对 `vegetable/meat` 做了名称兜底匹配 |
| 今日精选促销卡 | 已接通（点击跳对应分类） |
| “综合排序 ⌄” | **无 `onClick`**，带 `DemoBadge`；后端也无排序参数 |
| 商品卡“产地可溯源” / “★4.9 · 今日采摘” | **静态文案**，接口不返回产地与评分 |
| 收藏 ♡/♥ | **组件内 `useState`**，刷新即丢；无接口；商品卡本身带 `DemoBadge` |
| 商品卡加购按钮 | 已接通（`addCartItem`，含 `STALE_STATE` 重取购物车） |
| 购物车抽屉 | 已接通增减（`patchCartItem`），减到 0 即删行；**无“删除”按钮、无“去结算”入口、无加载更多/分页** |

**导购 `ChatScreen`**

| 元素 | 现状 |
| --- | --- |
| 会话恢复 / 新建 | 已接通（`sessionStorage` + `getGuideSession` / `createGuideSession`），失败时提示“会话恢复失败，请重试”，新建按钮为“+”，所有用户消息与助手消息均入库 |
| 流式输出 | 已接通（`answer.delta` 增量渲染） |
| 澄清问题 | 已接通（`pending_clarifications` → 建议气泡） |
| 清单 `PlanDock` | 已接通，仅在 `available_actions` 含 `confirm` 时显示 |
| 取消任务 / 改清单 / 刷新方案 | **未暴露**（后端 `cancel` / `modify` / `refresh_plan` 未使用） |
| 服务端停止回合 | **未调用** `POST /guide/sessions/{id}/turns/stop`；仅做客户端 `AbortController` 中断 |
| `plan_read_only` | **未使用**（后端用它标记历史只读清单） |
| 会话内购物车条 | 已接通增减 |

**订单页 `OrdersScreen`**

- **【事实】** 数据全部来自文件内常量 `ORDERS`（3 条写死的单号/时间/状态/明细/金额）；顶部“配送进度”卡（“配送员正在路上”“预计 16:10”“已接单/备货完成/送达”）也是静态文案；每条订单的 `<button>` **无 `onClick`**，但文案写着“查看配送详情 →”/“查看订单详情 →”。
- **【事实】** 标题带 `DemoBadge`，但配送进度、订单条目、金额没有额外说明。

**个人中心 `ProfileScreen`**

- **【事实】** 昵称“Ceres 会员”、手机号“138 **** 8888”、“绿金会员”、统计“12 订单数 / 3 优惠券 / 286 积分”全部为硬编码字符串。
- **【事实】** “收货地址 / 优惠券 / 会员中心 / 消息通知 / 帮助与反馈 / 关于 Ceres”六个菜单按钮与统计按钮**均无 `onClick`**，但有右箭头暗示可进二级页。
- **【事实】** 标题带 `DemoBadge`。

**导航 `BottomNav` / `App`**

- **【事实】** 导航与视图切换逻辑已接通；`keke` 视图下 `ChatScreen` 以覆盖层展示在商品架之上（保留浏览上下文，符合既有设计）。
- **【事实】** `guideViewContext` 会依据“来自首页 / 已搜索 / 在商品架或导购 / 其他”生成 `page`，取值落在后端 `Literal["home","category","search","product","cart"]` 之内。

### 1.5 契约与实现偏差清单（会影响后续开发准确性）

| 偏差 | 说明 | 影响 |
| --- | --- | --- |
| 列表分页未消费 | `listProducts` 固定 `page_size=40`，响应 `total` 被类型声明后从未使用 | 没有“加载更多/查看全部”的数据基础 |
| 单位标签失效 | 列表接口 `ProductSummary` **不含** `spec_unit`（只在 `ProductDetail` 里） | `ProductCard` 的 `/{spec_unit}` 在列表页恒为空 |
| 门店/配送区硬编码 | `bootstrap` 返回 `store_id` / `delivery_zone_id`，Ceres 未保存，直接写死 `'store-demo-01'` / `'zone-default'` | 多门店/多区一旦出现即散落多处；见 Q5 |
| 死分支 | `fetchApi` 把 `/api/v1/search` 当作公开目录路径，但后端没有该路由 | 无害，但会误导后续开发 |
| 错误提示口径 | 界面多为 `e.message` 直出或固定文案（“商品加载失败”“购物车已更新，请重试”） | 阶段 4 需统一错误呈现规范 |
| 后端已有、客户端未封装 | `DELETE /cart/items/{sku_id}`、`POST /guide/sessions/{id}/turns`（非流式）、`GET /guide/sessions/{id}/messages`、`GET /guide/turn-runs/{run_id}/events`、`GET /guide/sessions/{id}/turns/recovery`、`POST /guide/tasks/{id}/cancel`、`POST /guide/tasks/{id}/plan-refresh`、`POST /guide/tasks/{id}/plan-revisions`、`POST /guide/sessions/{id}/turns/stop`、`POST /api/v1/events` | 阶段 1/2 的低成本增强点；尤其是**掉线恢复**与**服务端停止** |

### 1.6 工作区风险（阶段 0 必须处理）

- **【事实】** 本次委派说明两个仓库均存在大量未提交改动；本次执行只新增本文件。
- **【事实】** Sale-guide 既有约定已写明“不要因为工作区有无关的未提交改动而停止。不要 `git reset` / `git clean` / `git checkout --`”（`Sale-guide/docs/plans/2026-09-18-cursor-data-completion-prompt.md`）。
- **【建议】** 阶段 0 先记录基线（`git status --short` 与关键文件 diff 摘要），改动只在既有工作区叠加；并行任务使用互不嵌套的独立 worktree，同一文件写入串行。

---

## 2. 待产品决策清单

> 未决策前，相关阶段只能执行“标注演示态/隐藏入口”这一档，不能进入“接入真数据”那一档。

| # | 问题 | 影响阶段 | 选项 | 若未决策的默认处理 |
| --- | --- | --- | --- | --- |
| Q1 | 订单页要做成**真订单**吗？（需要新的订单模型/接口/状态机，Sale-guide 明确不含） | 阶段 2 | A 新增订单能力（含从购物车生成订单）；B 保留页面但整体演示态 + 明确文案；C 从导航移除 | 选 B/C，不新增后端 |
| Q2 | 个人中心是否引入账号体系（登录/手机号/会员）？当前只有匿名 cookie | 阶段 2 | A 引入账号（新能力，含身份绑定）；B 展示匿名身份或去掉会员信息、只保留可用入口 | 选 B |
| Q3 | 收藏是否需要**跨会话/跨设备**保留？ | 阶段 3 | A 仅本地 `localStorage`；B 服务端持久化（新表+接口）；C 不做 | 选 A |
| Q4 | 心情的产品用途是什么？装饰 / 影响导购风格 / 影响推荐 | 阶段 3 | A 纯装饰（仅本地记忆）；B 作为 `entry_context` 传给导购（需定义语义）；C 移除 | 选 A |
| Q5 | 是否引入多门店 / 多配送区？列表从哪来？ | 阶段 1/3 | A 维持单店单区（改用 `bootstrap` 返回值）；B 新增门店/区域接口（新能力） | 选 A |
| Q6 | 是否要做通知 / 消息中心？消息来源有哪些（订单状态、导购完成、系统公告）？ | 阶段 3 | A 不做（铃铛标演示或隐藏）；B 做本地假通知；C 新后端能力 | 选 A |
| Q7 | 是否需要真实排序（价格/销量/新鲜度）与筛选？后端无 `sort` 参数 | 阶段 3 | A 不做（按钮标演示或隐藏）；B 新增 `sort` 参数（需定义排序口径与数据来源） | 选 A |
| Q8 | 首页“查看全部”指向什么？ | 阶段 1 | A 跳商品架（默认品类）；B 新增“为你准备”聚合页（需推荐/策展能力） | 选 A |
| Q9 | 演示标识规范：哪些保留“演示”徽标、哪些必须去除？ | 阶段 1 | A 凡假数据/假按钮一律标注；B 仅整页级标注 | 选 A |
| Q10 | 是否在 Ceres 暴露已有但未用的导购动作（取消任务、改清单、刷新方案、服务端停止、掉线恢复）？ | 阶段 1/2 | A 全部暴露；B 只暴露“停止”与“掉线恢复”；C 暂不暴露 | 选 B（成本最低、体验收益最明确） |
| Q11 | 购物车是否加“去结算”入口？无结算能力时如何呈现 | 阶段 2 | A 不加；B 加但演示态；C 与 Q1 一起做真结算 | 选 A |
| Q12 | 是否接入 `POST /api/v1/events` 客户端埋点？ | 阶段 4 | A 接入白名单事件；B 不接入（则不得引用转化率类指标） | 选 A（只读上报，不改业务） |

---

## 3. 阶段拆分与执行方案

依赖关系：`阶段 0 → 阶段 1 → （阶段 2 ∥ 阶段 3）→ 阶段 4`。阶段 2、3 必须等 Q1/Q2 与 Q3–Q7 的结论；两者都在改 Ceres 界面，若并行需按文件拆分或串行。

### 阶段 0：运行配置、契约与验收基线（P0）

**目标**：任何人按文档在 10 分钟内把 Ceres 连上 Sale-guide，并确认真实链路可用；把后续开发依赖的接口/版本契约固定下来。

**范围（允许触及）**
- `Ceres/vite.config.ts`：代理目标改为可配置（建议 `process.env.CERES_API_ORIGIN || 'http://127.0.0.1:8001'`），或至少在注释中写明 8001 的约定。**【决策】D0：改配置 vs 只在文档里固化 8001**；改配置属可选增强，不改则保留 8001。
- `Ceres` 新增运行说明（建议 `Ceres/README.md` 或 `Ceres/plans/` 下补充一节，不改 `AGENTS.md`）。
- **不改** `src/lib/saleGuide.ts` 的函数签名与调用方式（仅允许补纯新增的类型/函数，见阶段 1）。

**工作项**
1. 固化启动序列：Sale-guide `seed_runtime.py` → 后端 `--port 8001` → Ceres `npm run dev`（8443）。
2. 就绪探针：`GET /health`（看 `database`、`llm_configured`、`retrieval`、`business_data_mode`）、`GET /api/v1/bootstrap`（看 `owner_id`、`store_id`、`delivery_zone_id`、`demo_notice`）。
3. 契约快照（写入文档，作为后续验收基线）：上述 1.2 的接口表 + 1.3 的缺口表 + 版本字段（`state_version`、`session_version`、`cart.version`、`plan_version`）+ 错误码（`STALE_STATE`、`TURN_IN_PROGRESS`、`IDEMPOTENCY_CONFLICT`、`TURN_NOT_FOUND`）。
4. **实测** SSE：一次真实 `turns/stream`，确认 `answer.delta` 增量到达、`plan.ready`/`turn.completed` 顺序正确（对应 F1.8 的代理压缩隐患）。
5. 记录基线：两仓库 `git status --short` 与关键文件（`Ceres/src/App.tsx`、`Ceres/src/lib/saleGuide.ts`、`Sale-guide/backend/app/**`）的 diff 摘要，作为“不覆盖他人改动”的凭据。
6. 明确部署口径（对应 P3）：Ceres `vite build` 后 `/api`、`/media` 由谁反代。

**验收标准**
- 按文档命令启动后，`curl http://127.0.0.1:8001/health` 返回 `status=ok`；Ceres 首屏能出分类与商品（无 “分类加载失败/商品加载失败”）。
- 一次导购回合在界面逐字输出，且 `plan.ready` 后出现 `PlanDock`；“确认加购”后购物车计数增加。
- 浏览器 Network 中 `/api/*`、`/media/images/*` 均 200，且无因端口不一致产生的 502/连接失败。
- 文档中“未验证”项被替换为实测结论。

**依赖**：Sale-guide `.env`（模型凭据）可用；8001 端口未被占用。
**风险 / 未决**：D0 代理目标策略；SSE 在 Vite 代理下的行为（若实测有堆积，则需在 Ceres 侧新增一条直连后端的流式处理，属配置级改动，不重写 `saleGuide.ts` 的 SSE 解析）。

---

### 阶段 1：修复现有可见交互与演示标识（P0）

**目标**：消除“看起来能点却点了没反应”“看起来是真数据其实是假的”两类问题；用后端已有能力做少量低成本增强。**不新增后端能力。**

**范围（Ceres 前端）**：`src/App.tsx`（`LandingScreen`、`ProductCard`、`ShelfScreen`、`ChatScreen`、`OrdersScreen`、`ProfileScreen`、`DemoBadge`）、必要时 `src/lib/saleGuide.ts` 只做**新增**封装。

**工作项（按价值排序）**

1. **演示标识规范化**（对应 Q9）
   - 统一 `DemoBadge` 的语义与位置：所有假数据、假按钮、假统计都必须有可见标识或改成明确文案。
   - 重点补标：订单页“配送进度”卡与订单条目、个人中心会员信息与 3 个统计、商品卡“产地可溯源 / ★4.9 / 今日采摘”。去掉重复堆叠的徽标（例如商品卡徽标与内部元素重复时合并为一处）。
2. **消灭无动作按钮**（每个按钮二选一：接上动作 或 明确标注/移除）
   - 首页“查看全部 ↗” → 按 Q8 结论跳商品架（默认全品类）。
   - 商品架“静安区 ⌄” → 按 Q5 结论：改用 `bootstrap` 返回的 `delivery_zone_id` 的可读名称，或标为演示并禁用点击态（去掉 `⌄` 暗示）。
   - 通知铃铛 → 按 Q6 结论：不做则去掉按钮或加“演示”态并置灰。
   - “综合排序 ⌄” → 按 Q7 结论：不做则标演示（现已带 `DemoBadge`）+ 去掉 `⌄`/禁用点击。
   - 订单条目、个人中心菜单与统计 → 按 Q1/Q2 结论统一处理（演示态按钮用 `disabled` + 说明文案，而不是无 `onClick` 的可聚焦按钮）。
3. **复用 `bootstrap` 返回值**：在 `App` 保存 `store_id` / `delivery_zone_id`，替换 `ChatScreen` 与 `initSession` 中的硬编码；`demo_notice` 可用于页面级演示提示。
4. **列表完整性**：`listProducts` 传入并消费 `total`，实现“加载更多”（后端已支持 `page`）；或明确不做并去掉可能造成期待的元素。
5. **商品卡单位标签**：`spec_unit` 在列表接口缺失，改为仅在存在时显示（现状已是条件渲染，确认无空标签样式残留）或改为展示 `available_qty` 等列表接口真实字段。
6. **导购动作增强（Q10）**
   - 最低档：暴露“停止”（`POST /guide/sessions/{id}/turns/stop`）+ 掉线恢复（`GET /guide/turn-runs/{run_id}/events` 或 `turns/recovery`）。
   - 次档：`awaiting_confirmation` 时展示 `cancel` / `modify`（后端已下发）。
   - 说明：Ceres 目前的 `AbortController` 只中断本地连接，服务端 run 需靠下次启动清理（`main.py` 的 `cleanup_orphans` 将其标为中断），这是体验缺口而非数据错误。
7. **错误呈现统一**：`ApiError.code` 到用户文案的映射表（`STALE_STATE` 已有重试分支，其余如 `TURN_IN_PROGRESS`、`IDEMPOTENCY_CONFLICT`、网络失败），统一为可操作的提示。

**验收标准**
- 逐屏人工清单：所有可见按钮均有明确结果（导航、状态变化、弹层、或“演示”态且不可进入无效点击）；无“点了没反应”的元素。
- 打开订单页与个人中心，能在不读代码的情况下分辨哪些是演示数据。
- 任意一次加购/导购/确认流程后，刷新页面仍能恢复会话与购物车（现有能力，回归确认）。
- `npm run build` 通过（Ceres 无测试脚本，构建即类型检查门槛）。
- 【如实说明】Ceres 没有单测/组件测试框架，阶段 1 的验收以构建 + 人工清单为准；若要自动化，需先新增测试基建（属额外决策，不在本阶段默认范围）。

**依赖**：阶段 0 基线；Q8、Q5、Q6、Q7、Q9、Q10 的结论（未定则按默认档执行）。
**风险**：`App.tsx` 单文件承载全部界面（约 1200 行），多人并行修改冲突概率高；建议同一时间只有一个写入者。

---

### 阶段 2：订单与账户（P1，需先决策 Q1/Q2）

**前置事实（必须在评审中复述）**：Sale-guide **没有**订单、结算、支付、履约、退款能力，`prd.md` §3.7/§4.13 明确排除；Ceres 订单页当前是常量假数据。因此本阶段任何“真”实现都是**新增能力**，不得表述为“把已有接口接上”。

**分支 A：不做真订单（默认，若 Q1=B/C）**
- 范围：`OrdersScreen` 全页演示态化（顶部说明 + 空态或示意数据标注），或从 `BottomNav` 移除入口。
- 工作项：把常量数据收进一个显式命名的 `DemoOrders` 常量并加注释；补齐“演示”文案；去掉“查看详情 →”这类暗示可跳转的文案（或改为禁用按钮 + tooltip）。
- 验收：页面任何位置都能看出是演示；无死链按钮；导航不再引导学生流向不存在的流程。

**分支 B：做真订单（若 Q1=A，属新增后端能力）**
- Sale-guide 新增（示意范围，需按 Sale-guide 既有分层落地）：
  - 模型：`orders`、`order_items`（含 SKU 快照名称/单价/数量、金额单位分、状态、下单时间、`owner_id`、`store_id`、`delivery_zone_id`）。
  - 接口：`POST /api/v1/orders`（从当前购物车生成订单，需 `Idempotency-Key` + `expected_cart_version`，成功后清空购物车）、`GET /api/v1/orders`（分页）、`GET /api/v1/orders/{order_id}`、`POST /api/v1/orders/{order_id}/cancel`（仅限允许的状态）。
  - 状态机：至少 `created → packed → delivering → completed` 与 `cancelled`；**不得**出现“支付”相关状态或文案。
  - 与既有链路的边界：仍由用户显式点击“提交订单”触发；模型/导购不得自动下单（沿用 `prd.md` 的确认边界与 `Sale-guide/README.md` 的“模型永不自动加购”原则，扩展为“模型永不自动下单”）。
  - 库存/价格：沿用 `BUSINESS_DATA_MODE=demo` 的模拟口径，并在接口层明确“非真实库存与配送”。
- Ceres 新增：`src/lib/saleGuide.ts` **追加**订单类型与函数（不改既有函数与 `fetchApi` 语义）；新增订单列表/详情视图；`OrdersScreen` 改接真实数据（含空态、加载、错误、分页）；购物车抽屉加“去结算/提交订单”入口（Q11）。
- 账户（若 Q2=A）：涉及登录方式、身份与匿名 `sg_owner_id` 的绑定/迁移策略、资料读取接口——均属新能力，需单独设计后再排期；若 Q2=B，个人中心改为“匿名身份 + 可用入口”，会员/积分/优惠券去除或标演示。
- 验收（分支 B）：
  - 用临时数据库跑 Sale-guide 后端相关新增测试（新增表必须走既有 `client` fixture 建库路径），并在报告中给出实际命令与结果。
  - 手工链路：加购 → 提交订单 → 购物车清空 → 订单列表出现该单 → 详情与列表金额一致（分为单位，展示层 `/100`）。
  - 幂等：同 `Idempotency-Key` 重复提交只产生一单；`expected_cart_version` 过期返回 `STALE_STATE` 且界面提示重试。
  - 任意路径都不得出现支付、扣款、真实物流承诺等文案。

**依赖**：Q1、Q2、Q11 结论；若分支 B，还需 Sale-guide 侧数据层与迁移约定（与现有 SQLite + `init_db` 一致）。
**风险**：订单是唯一涉及金额与持久化的新增能力，属不可逆数据写入，必须由负责人确认范围后再实施；两仓库写操作需串行并记录基线。

---

### 阶段 3：收藏 / 心情 / 地区 / 通知（P2，按产品优先级取舍）

按 Q3–Q7 结论分档执行，每项都给“最小实现 / 完整实现 / 不做”三档。

| 项 | 最小实现（前端本地，不新增后端） | 完整实现（新增后端能力） | 不做 |
| --- | --- | --- | --- |
| 收藏（Q3=A） | 新增 `Ceres/src/lib/favorites.ts`（`localStorage`，按 `owner_id` 或本地键隔离），`ProductCard` 接入；可选在商品架加“收藏”筛选 | 新表 + `GET/POST/DELETE /api/v1/favorites`，与 `owner` cookie 绑定 | 移除 ♡ 按钮，保留商品卡其余功能 |
| 心情（Q4=A） | `localStorage` 记忆 + 登录/首屏恢复上次选择；保证切页不丢 | 存入会话/用户上下文；若 Q4=B，还需定义它如何进入 `entry_context`（后端 `entry_context` 是自由 `dict`，但语义需产品定义，否则模型行为不可预期） | 移除心情条，或改为纯装饰且不声称被记忆 |
| 地区（Q5=A） | 展示 `bootstrap` 的 `delivery_zone_id` 对应名称（单区时为常量映射），去掉下拉暗示 | 新增门店/配送区枚举接口 + 选择持久化；`store_id`/`delivery_zone_id` 需贯穿购物车与导购请求 | 去掉“⌄”，仅静态展示门店名 |
| 通知（Q6=A） | 去掉铃铛，或改为演示态且明确无消息 | 新模型 + `GET /api/v1/notifications`、已读接口，消息来源需产品定义 | 保留按钮但永久禁用并标注 |

**验收标准（按所选档位）**
- 最小实现：刷新/切页后收藏与心情仍在；`localStorage` 键使用带前缀命名，清空存储不影响购物车与导购会话。
- 完整实现：接口层有测试或至少用真实临时库手工验证；越权（不同 `owner` cookie）不可读写他人数据。
- 不做档：界面上找不到对应入口，或入口为明确的演示态。
- 全部档位：不得新增任何暗示“已接入真实零售平台”的文案。

**依赖**：Q3–Q7；阶段 1 的演示标识规范（避免同一元素换了真数据却仍挂“演示”徽标）。
**风险**：`localStorage` 与后端购物车/会话的状态不一致（例如换浏览器后收藏为空）；需在产品文案上区分“本机收藏”与“账号收藏”。

---

### 阶段 4：端到端与部署/配置验收（P0，收口）

**目标**：把前面阶段的改动按可复现的方式验收一遍，并固化部署形态。

**范围**：Sale-guide 验证入口运行记录、Ceres 构建与人工清单、部署配置说明（文档）。

**场景矩阵（每条给出预期与失败表现）**

| 场景 | 预期 |
| --- | --- |
| 首次进入（无 cookie） | 自动 bootstrap，分类与商品出现，购物车为空 |
| 搜索 / 切换分类 | 结果与服务端 `q` / `category_id` 一致，加载态与空态正确 |
| 加购 / 改数量 / 删行 | 计数与合计更新；`STALE_STATE` 时自动重取并提示 |
| 导购回合（流式） | 逐字输出；澄清建议可点；无事件堆积 |
| 清单确认加购 | `PlanDock` 消失、购物车刷新；重复点击不重复加购 |
| 中断与恢复 | 停止后界面状态自洽；刷新或重进可恢复会话/回合（取决于 Q10 档位） |
| 新对话 | `sessionStorage` 会话键清除，界面回到欢迎语 |
| 异常与降级 | 后端未启动 / 模型未配置 / 404 商品等错误有明确提示，不白屏 |
| 演示标识 | 所有假数据/假入口可识别，无死链按钮 |
| 部署形态 | 构建产物能找到 `/api` 与 `/media`（反代或同源后端） |

**实际可用的验证命令（Sale-guide 既有入口，需在对应目录执行）**
- 后端测试（**必须用临时库，禁止对用户运行库跑测试**）：在 `Sale-guide/backend` 下设置临时 `DATABASE_URL` 后运行 `pytest tests -q -p no:cacheprovider --deselect tests/test_llm_provider.py::test_smoke_live`（命令样式见 `Sale-guide/README.md`）。
- 离线端到端购物验收：在 `Sale-guide` 根目录运行 `backend\.venv\Scripts\python.exe scripts\verify_shopping_workflow_offline.py`（真实 FastAPI + 真实 Next 代理 + 临时库，不需要模型凭据）。
- 前端：`Sale-guide/frontend` 下 `npm test -- --run`、`npx tsc --noEmit`；浏览器 E2E `npx playwright test`（需先启动前后端并安装浏览器）。
- Ceres：`npm run build`（构建通过 + 人工清单）。
- **【事实】** 本机未安装 `make`，`Makefile` 的 `verify-*` target 不作为本机入口；`LLM_MODE=live` 的评估会调用真实模型并可能产生费用，默认不跑。

**验收标准**
- 上述每条命令的**实际执行结果**被记录（通过/失败/未跑，均如实写出），不得用历史记录替代。
- 场景矩阵逐条勾选，失败项有复现步骤与 owner。
- 部署形态有明确结论：`vite build` 产物的 `/api`、`/media` 由谁提供，以及 Ceres 与 Sale-guide 是同源还是跨域（若跨域，需同步扩展 Sale-guide 的 CORS 白名单，属配置改动）。
- 未验证项在文档中显式列出，不使用“应该可以”的表述。

**依赖**：阶段 1（必需）、阶段 2/3（已完成的部分）。
**风险**：真实模型质量无法由离线测试证明；`verification/` 与后端 `tests` 是隔离的两套验收，不能互相替代。

---

## 4. 优先级与延期汇总

| 优先级 | 内容 | 说明 |
| --- | --- | --- |
| P0 | 阶段 0 运行配置与契约基线 | 不做则后续所有验证都缺前提 |
| P0 | 阶段 1 可见交互与演示标识 | 成本最低、演示风险最高收益 |
| P1 | 阶段 4 端到端与部署验收 | 与阶段 1 绑定，阶段 2/3 增量再补 |
| P1 | 阶段 2 分支 A（订单/账户演示态化） | 无后端依赖，可与阶段 1 合并交付 |
| P2 | 阶段 3 收藏/心情本地化（Q3/Q4=A 档） | 纯前端，收益明确 |
| 延期 | 阶段 2 分支 B（真订单、真账户） | 依赖 Q1/Q2 与新增后端能力，需单独排期与金额/数据风险评审 |
| 延期 | 阶段 3 的服务端收藏、真通知、真排序、多门店 | 均为新增后端能力，等核心链路稳定后再评估 |
| 明确不做 | 支付、真实库存锁定、真实物流、退款售后、模型自动下单 | 与 `prd.md` §3.7 边界一致 |

---

## 5. 明确不做（本方案的边界）

1. 不重写 Ceres 的商品、搜索、购物车、导购主链，不改 `saleGuide.ts` 中既有函数的签名与 SSE 解析逻辑（只允许追加）。
2. 不改动 Sale-guide 的 Agent 编排、LLM 适配、既有业务 service 与既有测试；新增订单/收藏等能力时按既有分层新增，不替换现有链路。
3. 不引入新的前端框架（路由库、状态库）作为前置条件；如需，必须单独评审。
4. 不做支付、扣款、真实库存预留、真实配送与售后，不在任何界面声称已接入真实零售平台。
5. 不删除 Sale-guide 保留的提示词资产与既有文档。

## 6. 本次交付说明

- 交付物只有本文件 `Ceres/plans/2026-09-23-sale-guide-integration-completion-plan.md`（本次先后为新增与窄范围的事实校正修订），未修改任何源码、配置、测试或其他文档，未触碰两个仓库中的既有未提交改动。
- 文档中标记 **【事实】** 的条目均可由第 1 节所列文件核实；标记 **【决策】**/**Q1–Q12** 的条目尚无产品结论，不构成承诺；标记 **【建议】** 的是实现方向。
- **本轮未执行任何业务测试**：本轮修订只改本文件，未启动 Sale-guide 后端/前端，未运行 pytest / playwright / 离线验收脚本，也未重跑 Ceres 构建。
- 本文档标注为“已实测”的条目（1.1.1 的 V1–V4）来自**此前代码审阅时实际执行**的检查——Sale-guide 8000/8001 的 `/health`、`/api/v1/bootstrap`、`/api/v1/categories` 访问，Ceres dev `127.0.0.1:8443` 经代理的 bootstrap/categories HTTP 200，以及 Ceres `npm run build` 成功——于 2026-09-23 记录在此。**这些不是本轮重跑的结果**，引用时按“此前实测记录”对待。
- **仍未验证**：SSE 增量到达（N1）、真实模型对话与清单确认加购（N2）、构建产物在部署形态下的 `/api`、`/media` 代理（N3）、Sale-guide 全部测试套件（N4）。阶段 0 的 SSE 验收项与阶段 2/3/4 中依赖真实模型或部署形态的结论均属未验证。
