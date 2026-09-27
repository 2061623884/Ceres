# Cursor 与 Codex 交付对照报告

- 日期：2026-09-19
- 路径基准：`C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide`
- 方案来源：`docs/plans/2026-09-18-rag-optimization.md`（S1 数据 / S2 检索 / S3 Agent 接线 / S4 正式发布）

本文是**分工与文件对照**，不是发布验收。真实 embedding 效果、人工标注复核、正式库发布均未完成。

---

## 1. 一句话结论

Cursor 负责把菜谱和商品整理成**可审计、可复现的隔离候选库**，并写清数据契约。Codex 在这份候选库上实现**检索索引、评测管线，以及 Agent 三个只读入口的接线**。两边都没有改配货计算公式，也没有发布正式运行库。

```
用户问法
    ↓
Cursor（S1）          Codex（S2/S3）           尚未做（S4）
数据底子              检索与接线               正式发布
fixture / seed        精确+词法+向量+RRF       真实 embedding 校准
规范食材表            离线 build/verify        人工金标 + 盲留出
隔离候选库            lookup/recommend/recipe  正式库迁移
审计四套分母          降级/冲突/证据           运行库 + 索引联动
```

交接点只有一份：`verification/data-completion/handoff.json` 里的 `candidate_db_path`。Codex 只从这个隔离库建索引，不读 `data/runtime/sale_guide.sqlite3`。

---

## 2. 边界（两边共同遵守）

| 允许 | 禁止 |
|---|---|
| 隔离候选库 seed、只读检索、离线索引 | 改 `_pack_qty`、pantry 静默忽略、`INGREDIENT_ALIASES` 硬编码 |
| 未知字段保持 `null` / `unknown` / 空列表 | 编造 spec、图片语义、食材替代关系、口味/时长 |
| 缺规格在审计里单独计数 | 把「方案能生成」写成「已验证可配齐」 |
| `inferred`/`pending` 映射运行时仍可用 | 把这类映射算进严口径可配齐 |
| 索引默认不接管日常服务 | 未配置索引时偷偷用旧查询冒充检索成功 |
| 检索只读，不写购物车 / 会话 / 商品事实 | 新增 mutation verb、改 `FORBIDDEN_KEYS` |
| 菜谱 `stock_verified=false` 只表示候选存在 | 用检索命中证明整单能配齐 |

---

## 3. Cursor 做了什么（S1：数据与库管理）

### 3.1 目标

把「能搜」「能出方案」「真的配得齐」「图是不是真图」拆开统计；修确认过的数据错误；交出 Codex 可复现的候选库。**不实现 RAG。**

### 3.2 数据修复

| 问题 | 处理 | 位置 |
|---|---|---|
| 可乐鸡翅：可乐在 pantry，330ml SKU 按 50g 配不上被静默丢行 | `cola` 改为 required，`quantity_ml: 330` | `data/fixtures/chinese-dishes-v1.json`（`dish-kele-jichi`） |
| 糖醋排骨用了 `pork` | 改为 `pork_ribs`，新增 `demo:pork-ribs-500g` | 菜谱 fixture + demo 商品 |
| 红烧肉别名写成「东坡肉」 | 去掉错误等价 | `chinese-dishes-v1.json` |
| `demo:pork-500g` 中文名是「猪里脊」 | 改为「猪肩肉 500克」；重 seed 会覆盖旧名 | `demo-products.json`、`scripts/seed_runtime.py` |
| 规范食材表缺 SKU 侧 id | 补 `milk`、`yeast`、`baking_powder`、`cream_cheese`、`hotpot_base`、`hotpot_beef_roll`、`lamb_slice`、`beef_neck` 等，现 101 条 | `ingredient-catalog.json` |
| 虾滑≠虾仁、白蘑菇≠香菇、`pork`≠`pork_ribs` | 禁止交叉映射，不做替代合并 | 审计 `FORBIDDEN_SKU_INGREDIENT` + 测试 |
| 商品 API 丢掉 `metadata` | `ProductSummary` / `ProductDetail` 声明字段；HTTP 往返测试 | `backend/app/schemas/catalog.py` |
| demo 重 seed 不改名称 | 现有 SKU 分支回写 `name` / `name_zh` / `brand` / `review_status` | `scripts/seed_runtime.py` |

新增 11 个 demo SKU（第一批按缺口覆盖）：

`demo:wood-ear-150g`、`demo:chicken-wing-500g`、`demo:ginger-200g`、`demo:carrot-500g`、`demo:vinegar-500ml`、`demo:oyster-sauce-500g`、`demo:green-pea-300g`、`demo:shiitake-200g`、`demo:beef-slice-300g`、`demo:pork-ribs-500g`、`demo:garlic-200g`

demo 商品总数：**50**。source 商品仍为 **257**（多数缺规格，未编造）。approved 合计 **307**。菜谱仍为 **101** 道。

### 3.3 审计口径（四套分母互不替代）

实现于 `scripts/audit_retrieval_data.py`：

1. **可被检索（数据完备）**：合法食材 id、名称/别名可解析。不声称清淡/快手等属性已填充（101 道菜 `meta` 基本为空）。
2. **方案可生成（运行时现状）**：`validate_template_plan` passed。含缺规格默认 1 包、含 inferred 映射。只计数，不当成已验证。
3. **已验证可配齐（更严）**：demo SKU、规格同维非空、2 人份 pack 有定义、库存够、审批通过、映射 `declared`/`reviewed`。`inferred`/`pending` 与缺规格不计。
4. **图片**：`file_verified` 与 `semantic_match` 分报。placeholder 不算 photo 完备。`check_images.passed` 按实算，不写死 True。

`EXPECTED_UNBUILDABLE` 改为 `dish_id → 原因`，失败原因对不上则测试失败。登记 25 道仍无法出完整方案的菜。

### 3.4 实测数字（S1 after）

| 口径 | 结果 |
|---|---|
| 可被检索 | PASS |
| 方案可生成 | **76 / 101** |
| 已验证可配齐（demo 严口径） | **43 / 101** |
| demo 图片 | photo 33 / placeholder 17 / missing 0 |
| 候选库 seed | source 257 + demo 50 + dishes 101 = approved 307 |
| S1 专项 pytest | 12 passed（后含 seed 图片策略修正，相关集合 15 passed） |
| S1 当时全量后端 | 483 passed / 1 skipped / 8 failed（失败为既有 review/stream/w_dish，非本轮数据引入） |

before 基线：**未采集**。`data-audit-before.json` 的 `status` 为 `not_collected`，不得写成 FAIL→PASS。

### 3.5 Cursor 文件清单

**新增**

| 路径 | 作用 |
|---|---|
| `data/fixtures/ingredient-catalog.json` | 规范食材权威表（v1，101 条） |
| `backend/app/services/ingredient_catalog.py` | 加载、别名解析、合法性校验 |
| `scripts/_build_ingredient_catalog.py` | 从源定义重建规范表 |
| `scripts/audit_retrieval_data.py` | 四套分母审计 |
| `backend/tests/test_s1_data_completion.py` | 合法性、可乐方案、seed 改名、metadata 往返 |
| `verification/data-completion/candidate_runtime.sqlite3` | 隔离候选库（不进正式运行路径） |
| `verification/data-completion/handoff.json` | 给 Codex 的快照交接 |
| `verification/data-completion/data-contract.md` | 菜 / SKU / 食材 / API 契约 |
| `verification/data-completion/data-audit-after.json` | after 审计实测 |
| `verification/data-completion/data-audit-before.json` | 标明未采集 |
| `verification/data-completion/S1-delivery-report.md` | S1 交付报告 |
| `verification/data-completion/coverage-benefit-ranking.json` | 缺口食材排序 |

**修改（既有文件）**

| 路径 | 改什么 |
|---|---|
| `data/fixtures/chinese-dishes-v1.json` | 可乐鸡翅、糖醋排骨、红烧肉别名等纠错 |
| `data/fixtures/demo-products.json` | 11 个 SKU、猪肩肉名称、placeholder 声明 |
| `data/fixtures/store-offers.json` | 新 demo SKU 报价与库存 |
| `scripts/seed_runtime.py` | metadata 读写；demo 重 seed 覆盖名称等受管字段 |
| `scripts/import_db.py` | 从 JSON 加载规范食材（S1 未跑全量导入） |
| `backend/app/schemas/catalog.py` | `ProductSummary.metadata` |
| `backend/app/services/catalog_service.py` | `product_to_dict` 带 metadata |
| `backend/app/services/template_matcher.py` | 菜谱 metadata 进出库 |
| `backend/tests/test_catalog_search.py` | HTTP metadata 往返 |
| `backend/tests/test_dish_plan_images.py` | `EXPECTED_UNBUILDABLE` 按 dish_id + 原因 |
| `backend/tests/test_seed_images.py` | 已声明 placeholder 不要求 raster 文件 |

**明确未改**

- `backend/app/services/template_plan_service.py` 的 `_pack_qty`、pantry 静默忽略、`INGREDIENT_ALIASES`
- `data/runtime/sale_guide.sqlite3`（正式运行库）
- 未执行 `import_db.py` 全量导入
- 未建 RAG 索引、未接 Agent 检索

---

## 4. Codex 做了什么（S2/S3：RAG 实现与 Agent 接线）

### 4.1 目标

在 Cursor 候选库上实现只读检索，接到既有 `ReadTools` 三个入口，不另开第二条决策链。**不改 fixture / schema / seed / S1 交接物 / 配货计算。**

### 4.2 检索能力

请求路径：

```
用户 → GuideService → run_loop
        → ReadTools（唯一只读窗口）
             → RetrievalService   精确 / 别名 / 词法 / 向量 → RRF
             → 既有业务服务       实时库存 / 价格 / 约束
        ← facts（候选 + 证据 + status）
     → 模型 proposal（只能引用候选 ref）
     → 执行器再次业务校验
```

检索内部顺序：

1. **精确 / 别名短路**：点名菜名或别名直接命中，不拿相近菜顶替。
2. **中文词法**：规范词典最长匹配切词，FTS5 BM25 + RapidFuzz 子信号。
3. **向量**：float32 余弦；query 可带 instruction，文档默认无 instruction。
4. **RRF 融合**：词法与向量融合；硬排除（过敏/食材/预算）在融合后仍执行。
5. **实时校验**：请求期重算逐文档静态哈希；改名、改配料、改映射都会丢弃 stale 文档。用户点名但文档 stale 时返回 `dropped_exact_match` 并保持空结果。
6. **降级**：向量坏、词法健康 → `degraded`（只走词法，过滤仍在）。两路都不可用或语料不兼容 → `unavailable`，**不会**偷退到旧查询冒充成功。未部署索引（`RETRIEVAL_INDEX_DIR` 为空）才走标注过的 legacy 路径。

三个只读入口统一接线：

| 入口 | 行为 |
|---|---|
| `lookup` | 按 query 检索菜或商品；`lookups[].constraints` 可带排除/预算，与已存 Requirements **并集**（只能加严，不能静默解除） |
| `recommend` | 对同一主题分别检索菜和商品；任一路失败记入 `partial_sources`，不把半残结果说成完整推荐 |
| `recipe` | 点名菜走精确检索；排除冲突显式返回，不用相近菜顶上 |

`suggest_buildable_dishes` 增加全量扫描（`scan=None`）和超时标记，消除原先只看前 20 条的盲区。配货 `_pack_qty` / pantry **未改**。

### 4.3 索引生命周期

```
verification/rag/indexes/<root>/
  current.json                 原子指针 {"index_version": "..."}
  <version>/manifest.json
  <version>/index.sqlite3      docs / docs_fts / embeddings
  <version>.prev/              上一份可回滚副本
```

构建顺序：staging 目录写入 → 校验（逐 doc hash、计数、embedding 契约）→ `os.replace` 成版本目录 → 再切 `current.json`。校验失败不产生版本、不动指针。同名版本目录不可变，没有 `--force`。

增量复用：文档 hash + embedding 契约（model/revision/dim/dtype/normalize/两条 instruction/文本模板版本）全部一致才复用旧向量。价格、库存变化不触发重 embed。

实测增量探针：**408 / 408 向量复用，新增计算 0**。候选库整文件 SHA256 保持 `baa1bd2b1cf6f6a0ab2fcaa67935b187b06bb7030b7e59a5083ee2e13b4a47e8`。

### 4.4 评测（自动初稿，不是金标）

标注 `verification/rag/annotation-set.json`，版本 `rag-anno-v3`，67 条 = 20 dev + 47 holdout。覆盖名称、别名、机械错字、食材查询、正/负约束、无答案、未知属性。

Holdout（同一候选库实时校验）：

| 指标 | 词法 | hybrid MOCK |
|---|---:|---:|
| 可回答查询分母 | 37 | 37 |
| Recall@5 | 0.9189 | 0.9189 |
| MRR@5 | 0.8477 | 0.8577 |
| 无答案误返回 | 0/10 | **6/10** |
| 硬排除违规 | 0 | 0 |

**MOCK 数字只证明管线能跑，不能证明真实语义质量。** hybrid 无答案误返回说明当前阈值（初值 0.35）不能用于发布承诺。

冒烟（隔离只读快照）：可乐鸡翅精确命中；宫保鸡丁排除花生显式冲突；火锅商品给出候选并分配 ref。

### 4.5 Codex 实测

| 验证 | 结果 |
|---|---|
| RAG 前全量基线 | 482 passed / 8 failed / 2 skipped |
| 接线后全量 | **571 passed / 8 failed / 2 skipped** |
| RAG 四个专项文件 | **89 passed** |
| 独立 S1/图片/HTTP metadata 集合 | 27 passed |
| 词法 build + verify | 408 文档通过 |
| 候选库哈希 | 未改 |

8 个失败与 Cursor S1 时同一批既有用例，无新增失败。清单：

- `tests/test_review_probes.py::test_review_completed_people_change_requires_scope_clarification`
- `tests/test_review_probes.py::test_review_combined_people_and_budget_does_not_drop_budget`
- `tests/test_review_stream_contract.py::test_s06_mixed_explain_and_budget_updates_plan`
- `tests/test_task_lifecycle.py::test_switch_goal_gongbao`
- `tests/test_w_dish_and_gap.py::test_w03_gap_fill_clarify_append_or_new_plan`
- `tests/test_w_dish_and_gap.py::test_w06_dish_negation_switches_to_new_dish`
- `tests/test_w_dish_and_gap.py::test_m1b_gap_fill_2_to_4_via_turns`
- `tests/test_w_dish_and_gap.py::test_m1b_gap_fill_second_zero_delta_via_turns`

### 4.6 Codex 文件清单

**新增（Codex 独占）**

| 路径 | 作用 |
|---|---|
| `backend/app/services/retrieval_projection.py` | 一菜一文档 / 一 SKU 一文档；中文分词；逐 doc hash；静态投影 hash |
| `backend/app/services/retrieval_index.py` | FTS5 + float32 向量；manifest；不可变版本；原子发布；增量复用 |
| `backend/app/services/retrieval_service.py` | 唯一检索服务：精确/词法/向量/RRF、硬过滤、实时校验、降级 |
| `backend/app/llm/embedding.py` | 独立 HTTP embedding 契约；维度/有限数/归一化校验 |
| `scripts/build_retrieval_index.py` | 离线 CLI：`build` / `verify` / `list` / `rollback` |
| `scripts/eval_retrieval.py` | 隔离评测：lexical / mock / 显式 HTTP |
| `scripts/_build_rag_annotation_set.py` | 标注集生成与 lint |
| `backend/tests/test_rag_retrieval.py` | 投影、索引、降级、接线、只读 |
| `backend/tests/test_rag_eval_metrics.py` | 评测统计口径 |
| `backend/tests/test_rag_read_contract.py` | 三入口契约、约束并集、全量扫描 |
| `backend/tests/test_rag_codex_review.py` | 独立审查用例（作者侧未削弱断言） |
| `docs/rag/README.md` | 使用入口 |
| `docs/rag/2026-09-19-implementation.md` | 分阶段实施记录（非最终验收） |
| `verification/rag/final-report.md` | 最终实测验收报告 |
| `verification/rag/annotation-set.json` | 67 条标注（自动初稿） |
| `verification/rag/lexical-final.json` | 词法 holdout 结果 |
| `verification/rag/hybrid-mock-final.json` | mock hybrid 结果 |
| `verification/rag/incremental-final.json` | 增量复用探针 |
| `verification/rag/build-final.json` | 构建记录 |
| `verification/rag/pytest-final.xml` | 全量 pytest 证据 |
| `verification/rag/pytest-rag-final.xml` | RAG 专项证据 |
| `verification/rag/codex-baseline.json` | RAG 前基线 |
| `verification/rag/indexes/final-lexical/` | 词法索引产物（Git 忽略，可重建） |
| `verification/rag/indexes/final-mock/` | mock 向量索引产物 |
| `verification/rag/archive/` | 过程报告，不作最终结论 |
| `data/retrieval_index/` | 运行期索引目录（`.gitignore`，默认未部署） |

**最小修改（既有文件）**

| 路径 | 改什么 | 未改什么 |
|---|---|---|
| `backend/app/core/config.py` | `RETRIEVAL_MODE`、`RETRIEVAL_INDEX_DIR`、`EMBEDDING_*` | 既有业务配置语义 |
| `.env.example` | 同步上述字段，值为空 | 不写入真实凭据 |
| `backend/app/agent/tools/read.py` | 三入口接 `RetrievalService`；统一 `retrieval_status`；约束并集 | 不新增写入动作 |
| `backend/app/agent/protocol.py` | `CandidateSet.allocate` 补 kind 校验；`lookups` 可选 `constraints` | `FORBIDDEN_KEYS`、mutation verb |
| `backend/app/agent/service.py` | `ReadTools(requirements=state.requirements)` | 循环与执行器 |
| `backend/app/prompts/semantic.py` | 事实字段纪律；否定进 `constraints` 而不是 query | 既有 prompt 结构 |
| `backend/app/services/template_plan_service.py` | `suggest_buildable_dishes` 全量扫描 + 超时标记 | `_pack_qty`、pantry、`INGREDIENT_ALIASES` |

**明确未改**

- 全部 S1 fixture / schema / seed / `handoff.json` / 候选库内容
- 正式运行库
- 商品事实回写、配货计算、用户确认写入契约
- 任务生命周期与 SSE 状态枚举

---

## 5. RAG 文件路径地图

日常使用只看第一行。其余是实现、测试、证据。

### 5.1 使用入口

| 用途 | 路径 |
|---|---|
| 怎么构建 / 启用 / 回滚 | `docs/rag/README.md` |
| 最终实测结论 | `verification/rag/final-report.md` |
| 过程记录（可能过时） | `docs/rag/2026-09-19-implementation.md` |
| 原始设计方案 | `docs/plans/2026-09-18-rag-optimization.md` |
| Cursor 数据任务提示词 | `docs/plans/2026-09-18-cursor-data-completion-prompt.md` |

### 5.2 运行时代码

| 层 | 路径 |
|---|---|
| 静态投影 | `backend/app/services/retrieval_projection.py` |
| 索引存储 | `backend/app/services/retrieval_index.py` |
| 检索服务 | `backend/app/services/retrieval_service.py` |
| embedding 适配 | `backend/app/llm/embedding.py` |
| Agent 只读入口 | `backend/app/agent/tools/read.py` |
| 候选 ref / 约束协议 | `backend/app/agent/protocol.py` |
| 配置 | `backend/app/core/config.py` |
| 环境变量样例 | `.env.example` |

### 5.3 离线脚本

```
scripts/build_retrieval_index.py      构建 / 校验 / 列表 / 回滚
scripts/eval_retrieval.py             词法 / mock / HTTP 评测
scripts/_build_rag_annotation_set.py  标注生成
```

词法构建（无需模型）：

```powershell
$py = '.\backend\.venv\Scripts\python.exe'
& $py -X utf8 scripts/build_retrieval_index.py --index-root verification/rag/indexes/final-lexical build --no-embed
& $py -X utf8 scripts/build_retrieval_index.py --index-root verification/rag/indexes/final-lexical verify
```

启用隔离检索（不要把可写服务直接接到交接候选库）：

```powershell
$env:RETRIEVAL_INDEX_DIR = (Resolve-Path verification/rag/indexes/final-lexical).Path
$env:RETRIEVAL_MODE = 'lexical'
```

`RETRIEVAL_INDEX_DIR` 默认为空 = 未部署。一旦配置了目录，缺索引或不兼容必须 `unavailable`。

### 5.4 索引与证据

当前词法指针：`verification/rag/indexes/final-lexical/current.json` → `idx-95582d7e22627653`。

该版本 manifest 记录：101 道菜 + 307 个 approved SKU = **408 文档**；`vectors_embedded=0`（纯词法）；候选库路径指向 S1 `candidate_runtime.sqlite3`。

静态检索投影 hash（Codex 口径）：`sha256:a3c1f40dc4798a0221df72d341ee939edd2bb8e86a34686b3dfb3909b395b082`。

说明：S1 `handoff.json` 的 `fixture_projection_hash=2adbb12f…` 仓库内没有对应算法实现，Codex 把它记为审计信息，`handoff_projection_hash_match=false`，**不据此阻断构建，也不假装匹配**。

---

## 6. 前后对比

### 6.1 能力

| 能力 | RAG 之前 | RAG 之后 |
|---|---|---|
| 点名菜名 | `ReadTools` 本地别名 / 模板匹配 | 精确/别名短路，命中带 `match_kind` 与证据 |
| 错字、别名、食材问法 | 无独立词法索引；易漏或只看前 20 条可构建菜 | FTS5 中文词法 + 全量扫描选项 |
| 语义相近（「火锅用的」） | 无向量 | 管线已接；**真实 embedding 未测**，hybrid 测试为 mock |
| 排除「不要花生」 | 主要靠后续约束，首次结构化排除不稳定 | `lookups[].constraints` 硬过滤；冲突显式返回 |
| 索引没有 / 坏了 | 直接走旧查询，调用方不易区分 | 未部署才走标注过的 legacy；已部署则 `unavailable` / `degraded` |
| 检索是否写库 | 无索引 | 请求路径仍只读；构建在离线 CLI |
| 菜能否配齐 | 与检索混在一起容易误读 | 检索命中 ≠ 配齐；沿用 S1 四套分母 |
| 日常服务是否已切索引 | 无 | **默认未切**。需显式 `RETRIEVAL_INDEX_DIR` |

### 6.2 数据口径（Cursor 修复后的诚实数字）

这些数字 **Codex 未改数据**，因此 RAG 前后相同：

| 项 | 数值 | 含义 |
|---|---|---|
| 菜谱 | 101 | fixture 规模未扩到 200 |
| demo SKU | 50 | 含第一批 11 个补货 |
| source SKU | 257 | 多数缺 spec，未编造 |
| approved 商品 | 307 | 进检索的 SKU 文档数 |
| 方案可生成 | 76/101 | 运行时 validator，含默认 1 包 |
| 已验证可配齐 | 43/101 | 严口径，demo only |
| 仍登记无法出方案 | 25 | `EXPECTED_UNBUILDABLE` |
| 菜谱属性 meta | 基本为空 | 不能声称已有清淡/快手数据 |

可乐鸡翅：**之前**可乐在 pantry，方案经常没有 `demo:cola-330ml`；**之后** required + 330ml，2 人份方案含可乐与鸡翅。这是 Cursor 数据修复，不是 RAG 效果。

### 6.3 文件对照总表

把「没有 → 有」和「有但语义变了」分开，避免把 S1 数据文件算进 RAG。

**A. Cursor 让数据层从缺口变为可交接**

```
之前                                      之后
无规范食材 JSON                           data/fixtures/ingredient-catalog.json（101）
菜谱/SKU 引用合法性只扫菜                 同时扫菜谱 + demo ingredient_ids
可乐鸡翅 cola 在 pantry                   required + quantity_ml 330
商品 HTTP 响应丢掉 metadata               ProductSummary/Detail 声明并往返
demo 重 seed 保留错误中文名               fixture 覆盖 name/name_zh/brand
审计把 76 当成「配齐」                    四套分母分开
EXPECTED_UNBUILDABLE 只对菜名             dish_id + 原因必须对上
无隔离候选库交接                          verification/data-completion/*
正式库未动                                仍未动
```

**B. Codex 让检索层从「本地查询」变为「可版本化的 RAG」**

```
之前                                      之后
无 retrieval_* 模块                       projection / index / service 三件套
无 embedding adapter                      backend/app/llm/embedding.py
lookup/recommend/recipe 各走本地匹配      统一 RetrievalService + retrieval_status
无离线索引 CLI                            build_retrieval_index.py / eval_retrieval.py
无标注与 holdout                          annotation-set.json + lexical/hybrid 报告
RETRIEVAL_INDEX_DIR 不存在                默认为空；配置后必须与语料一致
suggest_buildable_dishes 前 20 条         可全量扫描，超时如实标记
候选库内容                                哈希不变，只被只读打开建索引
```

**C. 两边都没动的文件（对照时不要误读）**

- `data/runtime/sale_guide.sqlite3`
- 配货核心：`_pack_qty`、pantry `_append_item` 静默忽略、`INGREDIENT_ALIASES`
- `FORBIDDEN_KEYS` 与加购确认契约
- 101 道菜的口味/时长/营养（仍未知）
- source 商品缺失的 `spec_quantity` / `spec_unit`

### 6.4 pytest 规模

| 时间点 | 全量后端 | 说明 |
|---|---|---|
| Cursor S1 结束 | 483 passed / 8 failed / 1 skipped | 数据修复后；RAG 代码尚未接入 |
| Codex RAG 前基线 | 482 passed / 8 failed / 2 skipped | 隔离配置下独立复测 |
| Codex 接线后 | **571 passed** / 8 failed / 2 skipped | 增加约 89 个 RAG 专项；既有 8 失败未变 |

通过数变多，主要是新测试文件，不是那 8 个既有失败被修掉。

---

## 7. 二者如何衔接

1. Cursor 写出 `handoff.json`：候选库绝对路径、schema 版本、fixture 版本、四套分母、缺口清单。
2. Codex 只读打开该 sqlite，投影为 408 篇文档（`dish:*` 与 `sku:*` 两套，不跨类型打分）。
3. 价格与库存**不进**文档文本、**不进** embedding；请求期再查 offer。
4. Cursor 以后若补数据：先验收新候选快照 → `build --candidate-db <新快照>` → `verify` → 隔离评测。同契约未变的向量可复用。
5. 正式发布仍须单独批准：隔离验收 → 备份正式库 → schema/seed 迁移 → 按最终快照切索引 → 冒烟。不能只复制正在写入的 sqlite 而漏 WAL。

---

## 8. 尚未完成（S4 及数据债）

**检索发布前**

1. 真实 embedding endpoint / model / revision / 维度实测；在 dev 集上校准无答案阈值。
2. 人工核对标注，按商品名称族处理同名多 SKU，重新冻结未用于调试的盲 holdout。
3. 真实模型下：首次结构化排除是否稳定、相似候选是否先澄清。
4. 分段耗时与完整 Agent 回合性能（当前只有本机 search 调用计时）。
5. 正式运行库迁移与索引联动。

**数据侧仍登记的缺口（不归 RAG 修）**

- 25 道菜缺 demo SKU（粉丝、鲈鱼、带鱼、牛腩等）。
- 257 个 source SKU 多数无规格。
- 配货：缺规格默认 1 包、pantry 静默忽略、硬编码别名。若要「缺规格不得配进方案」，需单独改配货，不要塞进检索任务。

---

## 9. 相关文档

| 文档 | 用途 |
|---|---|
| 本文 `docs/2026-09-19-cursor-codex-delivery.md` | Cursor / Codex 分工与文件对照 |
| `docs/rag/README.md` | RAG 操作说明 |
| `verification/rag/final-report.md` | Codex 最终实测 |
| `verification/data-completion/S1-delivery-report.md` | Cursor S1 交付 |
| `verification/data-completion/data-contract.md` | 数据契约 |
| `verification/data-completion/handoff.json` | 快照交接机器可读入口 |
| `docs/plans/2026-09-18-rag-optimization.md` | 原始方案 |
