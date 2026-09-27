# RAG 开发交付入口

当前结论：**检索实现和 Agent 只读接线已落地，词法链路可在隔离快照运行；真实向量质量和正式发布尚未验收。**

最终实测以 `verification/rag/final-report.md` 为准。`2026-09-19-implementation.md` 是过程记录，历史报告不代表最终代码状态。

## 文件职责

| 位置 | 职责 |
|---|---|
| `backend/app/services/retrieval_projection.py` | 菜谱/SKU 静态文档、中文分词、内容哈希 |
| `backend/app/services/retrieval_index.py` | FTS5、float32 向量、manifest 校验、不可变版本及原子发布 |
| `backend/app/services/retrieval_service.py` | 精确/词法/向量/RRF、硬过滤、实时资格校验、降级 |
| `backend/app/llm/embedding.py` | 独立 HTTP embedding 契约、指令、数值与维度校验 |
| `backend/app/agent/tools/read.py` | lookup/recommend/recipe 三入口、候选 ref、结构化约束和状态透传 |
| `scripts/build_retrieval_index.py` | 离线 build/verify/list/rollback |
| `scripts/eval_retrieval.py` | 隔离词法、mock、显式 HTTP 评测 |
| `backend/tests/test_rag_*.py` | 检索、读契约、统计和独立验收测试 |
| `verification/rag/` | 固定标注、最终报告、测试证据；indexes/ 为 Git 忽略的派生文件 |

不修改 Cursor 的 fixture/schema/seed/S1 交接物；不修改 `_pack_qty` 或 pantry 配货规则；不发布正式数据库。

## 构建与验收

在项目根目录执行。以下词法构建无模型请求，不需要凭据：

```powershell
$py = '.\backend\.venv\Scripts\python.exe'
& $py -X utf8 scripts/build_retrieval_index.py --index-root verification/rag/indexes/final-lexical build --no-embed
& $py -X utf8 scripts/build_retrieval_index.py --index-root verification/rag/indexes/final-lexical verify
& $py -X utf8 scripts/eval_retrieval.py --index-root verification/rag/indexes/final-lexical --mode lexical --embed none --live-verify --out verification/rag/lexical-final.json
```

构建默认读取 S1 handoff 指定的候选库，不读取正式运行库。CLI 均有 `--help`。向量构建不传 `--no-embed`，从进程环境读取独立的 `EMBEDDING_BASE_URL/API_KEY/MODEL/REVISION/DIMENSION/QUERY_INSTRUCTION`。模型 revision、维度、指令应先确认，**本次没有代填或实测真实模型**。

```powershell
# 仅为离线管线验证，绝不能当作真实语义效果
& $py -X utf8 scripts/eval_retrieval.py --index-root verification/rag/indexes/mock-dev --mode hybrid --embed mock --build-mock-index --live-verify --out verification/rag/mock-dev.json
```

真实评测显式使用 `--embed http`，仅在确认 endpoint、凭据和外发范围后执行。mock 索引不能配真实 provider 使用，契约不一致会降级。

## 隔离开发接入

`RETRIEVAL_INDEX_DIR` 默认留空，避免本轮未经发布的索引接管日常运行库。启用时明确设置：

```powershell
$env:RETRIEVAL_INDEX_DIR = (Resolve-Path verification/rag/indexes/final-lexical).Path
$env:RETRIEVAL_MODE = 'lexical'
```

应用还需把 `DATABASE_URL` 指向**由候选库通过 SQLite backup API 复制出的独立开发库**，不要把可写 Agent 服务直接接到交接候选库。索引与开发库应保持相同静态投影。请求时不写索引，也不把检索结果回写商品事实。

后续 Cursor 补数据：验收新候选快照 → `build --candidate-db <新快照>` → `verify` → 在隔离环境评测。构建复用同契约、未变化文档的向量；正式运行库发布仍须另行确认。

回滚：`build_retrieval_index.py --index-root <目录> rollback --to <版本>`。默认拒绝跨静态语料回滚；不能用旧索引遮蔽新库不兼容。

## 解释结果

- 菜谱 `stock_verified=false`：只证明检索候选存在，不证明配齐。
- 商品 `stock_verified=true`：只检查本店当前至少一件可售、价格存在、配送资格；不是整单数量/预算承诺。
- `degraded`：只按可用词法路回答，不能声称完成语义匹配。
- `unavailable`：没有完成检索，不能说“没有商品”。
- `unknown_constraints`：没有事实依据的条件；尤其未知过敏不等于安全。
- `fuzzy/lexical/semantic/fused`：相似候选，不能冒充用户明确点名。

## 尚待验收

真实 embedding 的 dev 阈值校准、人工复核标注和新的盲留出集、真实模型约束提取行为、分段/端到端性能、正式库发布。现有标注为自动派生初稿，不能作为强统计承诺。
