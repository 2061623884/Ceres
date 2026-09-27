# RAG S2/S3 实施记录（2026-09-19）

> 本文是分阶段过程记录，部分计数、命令和限制已被后续修正。当前使用说明见 `docs/rag/README.md`，最终实测以 `verification/rag/final-report.md` 为准；历史 JSON 与阶段报告位于 `verification/rag/archive/`。真实 embedding 效果及正式发布尚未验收。

对应方案：`docs/plans/2026-09-18-rag-optimization.md`（§3 检索路线 / §4 降级 / §5 数据契约 / §7 索引 / §8 接线）。
数据快照：`verification/data-completion/handoff.json` → `candidate_db_path`，只从这份隔离库构建，不读日常运行库，不混读另一版 fixtures。

本文是实施记录，**不是验收报告**。验收门槛与实测指标见 `verification/rag/`；未跑过的项一律写 `not_evaluated`。

---

## 1. 阶段清单

| 阶段 | 内容 | 交付物 | 状态 |
|---|---|---|---|
| P0 | 读取方案全文 + S1 handoff / data-contract，冻结读取面 | 本文 §2 §3 | done |
| P1 | 静态检索投影：一菜一文档 / 一 SKU 一文档、逐 doc hash、契约 hash | `backend/app/services/retrieval_projection.py` | done |
| P2 | 离线索引构建：FTS5 词法 + float32 向量 + manifest + 新目录构建 + 原子切指针 + 增量复用 | `backend/app/services/retrieval_index.py`、`scripts/build_retrieval_index.py` | done |
| P3 | embedding adapter：契约对象、维度/有限数/归一化校验、query-only instruction、可注入 provider | `backend/app/llm/embedding.py` | done |
| P4 | RetrievalService：精确/别名短路、词法 BM25 + RapidFuzz 子信号、向量余弦、RRF、硬过滤、实时校验、补召回、降级 | `backend/app/services/retrieval_service.py` | done |
| P5 | S3 接线：三入口统一 retrieval_status、recommend partial_sources、`CandidateSet.allocate` kind 校验、消除 `suggest_buildable_dishes` 前 20 条盲区 | `agent/tools/read.py`、`agent/protocol.py`、`services/template_plan_service.py`、`core/config.py`、`.env.example` | done |
| P6 | 离线 build / eval CLI（`--help`）与评测报告 | `scripts/build_retrieval_index.py`、`scripts/eval_retrieval.py`、`verification/rag/` | done |
| P7 | 标注集（20 dev + holdout，含 lint 与 snapshot 绑定） | `verification/rag/annotation-set.json` | done（实际 67 条 = 20 / 47） |
| P8 | pytest：构建/契约/降级/只读/接线/回归 | `backend/tests/test_rag_*.py` | done |
| P9 | 独立审查反馈修复（实时逐 doc 哈希、不可变版本+staging、评估统计口径、单字词典扩展、只读约束） | 见 §4.1–4.3、§5、§7 | done |

## 2. 文件管理与写入边界

**新增（本任务作者独占）**

```
backend/app/services/retrieval_projection.py   静态投影 + doc hash + 契约 hash
backend/app/services/retrieval_index.py        索引构建 / 装载 / manifest / 原子指针
backend/app/services/retrieval_service.py      唯一检索服务（无第二个 Agent、无第二条决策链）
backend/app/llm/embedding.py                   embedding adapter（可注入 provider）
scripts/build_retrieval_index.py               离线构建 CLI（build / verify / list / rollback）
scripts/eval_retrieval.py                      离线评测 CLI（强制隔离索引目录）
scripts/_build_rag_annotation_set.py           标注集生成 + lint（可复现，不只可信）
backend/tests/test_rag_retrieval.py            投影/索引/降级/接线/只读
backend/tests/test_rag_eval_metrics.py         评测统计口径回归
docs/rag/                                      本目录
verification/rag/                              评测集、报告、评测输出
data/retrieval_index/                          索引运行目录（.gitignore 忽略，不提交）
```

`backend/tests/test_rag_codex_review.py` 是**独立审查者**编写的验收用例，不由本任务作者维护，其断言未被削弱。

**最小修改（既有文件，逐条列出理由）**

| 文件 | 改什么 | 为什么必须 |
|---|---|---|
| `backend/app/core/config.py` | 新增 `RETRIEVAL_MODE` / `RETRIEVAL_INDEX_DIR` / `EMBEDDING_*` 字段 | 方案 §8.1 要求；现有配置里没有任何 embedding 项，是**新增**不是复用 |
| `.env.example` | 同步上述字段（值为空） | 与 config 字段一致；不写入任何真实凭据 |
| `backend/app/agent/tools/read.py` | 三入口接 `RetrievalService`，统一透出 `retrieval_status` 等事实；`lookups[].constraints` 与已存 Requirements 并集合并 | 方案 §8.3/§8.4 的漏点清单 |
| `backend/app/agent/protocol.py` | `CandidateSet.allocate` 补 `kind` 校验；`lookups` 增加可选 `constraints`（复用既有 `_parse_constraints`） | 方案 §8.3 漏点；`FORBIDDEN_KEYS` 与 mutation verb **未改**，**未新增动作** |
| `backend/app/services/template_plan_service.py` | `suggest_buildable_dishes` 增加 `scan=None`（全量）+ `deadline_expired`，超时如实标不完整 | 方案 §8.4-3 前 20 条盲区；`_pack_qty` 与 pantry 配货逻辑**未改** |
| `backend/app/agent/service.py` | `ReadTools(requirements=state.requirements)` | 硬过滤必须来自真实用户约束 |
| `backend/app/prompts/semantic.py` | 事实字段的表述纪律；`lookups` 的 query 不带否定词、否定进 `constraints` | 方案 §8.2「match_kind 必须透传」与 §9「不得宣称符合」 |

**明确不改**：数据 fixtures / schema / seed / S1 交接物 / 日常运行库 / `FORBIDDEN_KEYS` / mutation verb / `_pack_qty` / pantry 配货 / 用户确认写入契约 / 既有任务生命周期与 SSE 状态枚举。

**不读**：`.env`、任何凭据文件。embedding 凭据只从**进程环境**读，CLI 不自动载入 dotenv，不打印密钥。

## 3. 冻结的读取面（防止悄悄混读新版）

索引构建只从两个来源读：

1. `handoff.json` 指名的 `candidate_runtime.sqlite3`（只读打开），只读 `purchase_templates`（`source='chinese-dishes-v1'`）与 `catalog_products`（`review_status='approved'`）。
   `offers` 只用于记录门店资格**不作为静态投影**——价格 / 库存**不进文档文本、不进 embedding**。
2. 冻结的规范食材字典 `data/fixtures/ingredient-catalog.json`（`version` 进 manifest）。

manifest 记录构建时的实际计数与版本；构建结束后不再回读 fixtures。菜与 SKU 是**两个独立集合**（`doc_id` 前缀 `dish:` / `sku:`），各自召回、各自打分，不跨类型比较。

**`fixture_projection_hash` 说明（如实记录）**：`handoff.json` 里的 `2adbb12fd4ee…` 在仓库中**没有对应算法**——`scripts/` 与 `backend/` 全库检索无 `projection_hash` 实现，`S1-delivery-report.md` 也未记录算法。本实现因此自带一份**文档化的**投影哈希（§4），并把 handoff 值作为**审计信息**原样记录、比对结果写进 manifest 的 `audit_only.handoff_projection_hash_match`。不匹配时**不假装匹配**，也不据此阻断构建（因为无法复现对方算法），但会在报告里标明该溯源未验证。

## 4. 投影与 manifest 契约

- `TEXT_TEMPLATE_VERSION = "v1"`：文档文本 = 已核实名称与别名 + 主料中文名（required + optional 的规范中文名）+ 用途标签。**未知的耗时 / 口味 / 营养不写进检索文本**；**价格 / 库存 / 配送不 embedding**。
- `LEXICAL_TOKENIZER_VERSION = "zh-dict-v1"`：中文词典（规范食材名/别名/`ner_terms` + 菜名 + 别名 + `usage_tags`）最长匹配优先切词，写入时就把文本切成空格分隔词元，FTS5 用 `unicode61` 只做词元索引。
- 单字控制：单字词元只在**冻结词典确实登记过**时才进入索引与查询（`蛋`/`醋`/`油`/`虾`/`鱼` 一类以词典为准），否则丢弃——避免单字把整库召回。
- 逐 doc `sha256` 静态内容哈希；`projection_snapshot_hash` 只覆盖规范静态检索投影（版本 + 逐 doc hash），**runtime 路径只进 `audit_only`，不参与失效判定**。
- `embedding` 段逐字节记录 `model / revision / dimension / dtype=float32 / normalize / query_instruction / document_instruction`。

## 4.1 部署门控（`RETRIEVAL_INDEX_DIR`）

`RETRIEVAL_INDEX_DIR` **默认为空 = 本机未部署检索**，此时三入口走原有的 pre-index 路径，并在结果里标明 `retrieval_status=unavailable` / `fallback_reason=no_published_index`。这是显式的部署开关，不是隐式回退：

- 一旦配置了该目录，**缺索引**报 `INDEX_MISSING`、**索引与当前运行库语料不一致**报 `INDEX_STALE`，都返回 `unavailable`，**不会**用 legacy 候选伪装成检索成功。
- 语料一致性用两个计数（菜谱数 / approved SKU 数）比对 manifest，每个 service 实例只做一次，不做每请求全库哈希。
- 需要真正启用：在部署环境设置 `RETRIEVAL_INDEX_DIR=data/retrieval_index`（`.env.example` 已给出）。

## 4.2 实时逐 doc 静态投影哈希

请求期对每个候选 doc 用**构建期同一个投影器**重算 `static_hash`，与 manifest 的 `doc_hashes` 比对。改名、改配料、改商品映射、改用途标签都会改变该哈希，因此都会让该 doc 判为 stale 并被丢弃；只比名字会漏掉后面三种。比对时用的是索引里冻结的规范食材名映射，不读磁盘上的 fixture。

用户点名的菜如果 stale，返回 `dropped_exact_match` 并**保持空结果**——不会用相近的菜顶上。

## 4.3 只读查询约束（`lookups[].constraints`）

`lookups` 支持可选的 `constraints`（`excluded_ingredients` / `budget_yuan`），复用既有 `_parse_constraints` 解析，**未新增 action verb，未改 `FORBIDDEN_KEYS`**。它让首次对话里的「不要花生」直接成为结构化硬过滤，而不是交给 embedding 去"理解否定"。

与已保存 `Requirements` 的合并是**并集**（预算取更严的一侧）：一次只读可以**增加**排除，**不能静默解除**已保存的排除。

## 5. 索引目录与回滚

```
data/retrieval_index/
  current.json                 {"index_version": "<version>"}   ← 原子指针
  <version>/manifest.json
  <version>/index.sqlite3      docs / docs_fts / embeddings
  <version>.prev/              上一份兼容且健康的索引（保留用于回滚）
```

- **构建三步，顺序即保证**：① 写进唯一 staging 目录 `<root>/.staging-<random>`；② 在 staging 上校验（逐 doc hash、计数、embedding 契约、norm）；③ `os.replace` 提交为 `<version>`，然后才换 `current.json`。校验失败则 staging 删除、**不产生 version 目录、不动指针**。
- **version 目录不可变**：`write_index` 遇到已存在的 `index.sqlite3` 直接拒绝（`INDEX_EXISTS`），**没有 `--force`**。version 名由投影与 embedding 契约派生，所以已存在的同名目录就是这次构建的结果，staging 被丢弃。
- 增量复用：逐 doc 比对 `doc_hash` 与完整 embedding 契约 key（model/revision/dim/dtype/normalize/两个 instruction/文本模板版本），命中才复用旧向量；价格、库存、纯 tokenizer 变化都不触发重 embed。
- **回滚**：`rollback --to <version>` 先校验目标结构，再用 `load_index` 装载（会复算 content hash），并比较目标的 `projection_snapshot_hash` 与当前值；不同则拒绝，除非显式给 `--allow-corpus-change`。CLI 子命令：`build` / `verify` / `list` / `rollback`。
- **内容哈希而非版本字符串**：manifest 的 `content_hashes` 记录 `dictionary_hash` 与 `text_template_hash`，装载时从**实际存储**重新计算并比对。声明自己是 `zh-dict-v1` 不算数，被换掉的字典会被判 `INDEX_STALE`。

## 6. 降级语义

| 情形 | `retrieval_status` | 行为 |
|---|---|---|
| 两路可用 | `ok` | `retrieval_mode=hybrid` |
| 向量缺失/坏，词法索引健康且契约兼容 | `degraded` | `retrieval_mode=lexical` + 真实 `fallback_reason`；硬过滤全部保留 |
| 两个索引都不可用，或静态投影/major 契约不兼容 | `unavailable` | 明确失败，`code=INDEX_STALE` 或 `INDEX_UNAVAILABLE` |
| 索引健在但确实没有答案 | `empty` | 如实返回空 |
| `RETRIEVAL_MODE=lexical`（主动部署） | `ok` | `retrieval_mode=lexical`，不是故障 |
| `degraded` 下没有命中 | `degraded` + `empty=true` | 只声明「仅词法范围未找到」 |

`stop` / 时间预算耗尽走既有停止协议（`REASON_DEADLINE`），不伪造 `empty`。

## 7. 评估纪律

标注集 `verification/rag/annotation-set.json` 由 `scripts/_build_rag_annotation_set.py` 生成并 lint（版本 `rag-anno-v2`，绑定 `projection_snapshot_hash`）。当前 67 条 = 20 dev（调参）+ 47 holdout（只报告）；split 按 dish id 分配，同一实体的改写不跨 split。

**标注语义必须写死，不能事后解释**（第一版就是在这里自欺的）：

| 字段 | 含义 |
|---|---|
| `answerable` | 语料里**存在**正确答案时为 true；`gold_ids` 就是那整个集合 |
| `gold_ids` | 全部正确答案 id；为空**当且仅当** `answerable=false` |
| `constraint_conflict` | 点名菜与被排除项冲突 → 正确答案是**没有命中**，绝不是相近的菜 |
| `constraint_ok` | 点名菜不含被排除项 → **必须**召回，用来抓过度排除 |
| `unknown_attributes` | 语料没有该维度证据 → 正确输出是显式 unknown，不是猜 |

指标口径：

- **Recall@5 按 gold id 逐条算再平均**（多 gold 不会因为命中一个就算满分）；**MRR@5 把未命中按 0 计入平均**（不能只对命中的求平均）。
- 无答案样本报「误返回数 / 总数」，且**只有真的返回了候选才算误返回**：`empty` / `unavailable` / `degraded 且空` 都是正确结果，不计入。
- 硬条件违规按**结构化 ingredient id** 判定（从索引 payload 取），不是在渲染文本里搜英文字符串——渲染证据是中文，那种检查永远为真。
- ID 有效率的分母是**返回过候选的 query**，不是全部 query。
- 延迟只报实际测到的 `search_call` 的 p50/p95；`retrieve` / `embed` / `live_verify` / `turn` 未单独测量一律 `null`。
- eval 强制 `--index-root` 指向**隔离目录**（否则直接拒绝），数据库以 `mode=ro` 打开 **snapshot**，不用正式运行库；mock 索引在该隔离目录内构建。
- mock 向量用 **sha256** 而非 Python `hash()`（后者跨进程加盐，建索引与查询会不一致）。
- **mock 与真实 embedding 分开跑、分开报**；mock 结果不得称真实语义达标。

统计口径本身有回归测试：`backend/tests/test_rag_eval_metrics.py`。

## 8. 边界与已知限制（实施时如实保留）

- 未获准调用外部 embedding / 未获准读取凭据：本轮真实模型路径**未运行**，报告里所有语义指标都标注为 mock provider 结果。
- 时间预算内优先交付核心与接线；未完成项在最终报告与 `verification/rag/` 中逐条列出，不冒充已完成。
