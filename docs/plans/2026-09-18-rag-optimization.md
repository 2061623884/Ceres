# RAG 检索优化方案（V1）

- 日期：**2026-09-18**
- 状态：设计与规划稿。只新增只读检索能力；业务写入路径与用户加购确认不变。
- 配套：[Cursor 数据补齐提示词](./2026-09-18-cursor-data-completion-prompt.md)

路径基准：本文代码路径均相对于 `C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide`；`reference/` 资产位于其父目录。

---

## 1. 产品问题与执行总览

### 1.1 要解决的三类问法

| 用户问法 | 例子 | 依赖 |
|---|---|---|
| 精确菜名 | 「糖醋排骨要买什么」 | 确定性名称 / 别名匹配 |
| 按食材、口味、场景找菜 | 「有鸡蛋和豆腐能做什么」「清淡点的」 | 主料信号 + 语义召回 |
| 按用途找商品 | 「买点火锅用的」 | SKU 用途标签 + 语义召回 |

**不做**：烹饪步骤知识库（现有链路已如实返回 `steps_available: False`，不改这个事实）；自动食材替代。

**规模判断**：现有 101 道菜 + 运行库 296 商品 / 107 模板的量级下，优先采用全量向量比较，预计无需近似向量索引；实际耗时仍要测量。V1 **先不部署向量数据库、不加 reranker、不对 JSON 切块**。菜品数从 101 扩到约 200 由数据质量与业务需要决定，**RAG 指标不以扩量为前提**。

### 1.2 链路模型

```
用户
 → GuideService → run_loop
      → ReadTools（既有唯一只读窗口）
           → RetrievalService      只读检索：精确 / 词法 / 向量 → RRF
           → 既有业务服务          实时校验：库存 / 价格 / 包装 / 约束
      ← facts（候选 + 证据 + status）
 → 模型产出 proposal
 → PlanChangeExecutor（重新做业务校验，防数据过期）
 → 待确认清单
 → 用户确认 → 购物车
```

三条链路纪律：

1. **retriever 只读**，不在请求路径写业务库 / 会话 / 购物车 / 索引。
2. **模型只能引用候选 ref**。源数据是事实不是指令；金额与库存不进模型输出（`FORBIDDEN_KEYS` 保持不动）。
3. **业务服务重新校验**。生成清单时由执行器调用业务服务校验；用户确认加购时由确认/购物车服务再次检查当前价格、库存和版本。不要把确认加购错误接到模型或检索器里。

**工程选择声明**：本方案复用现有 Loop / ReadTools / services，因为这是当前改动成本最低的做法，所以选它。这不是「架构永远不能调整」的禁令；若实测证明需要独立的检索服务边界，属于可讨论的重构。

### 1.3 执行步骤与分工

| 步骤 | 负责人 | 内容 | 交付物 | 进入下一步的条件 |
|---|---|---|---|---|
| **S1 数据** | 用户发起 Cursor（配套提示词） | 建立数据契约、修确认的缺口、至少完成一批验证基线 | fixture / schema / seed / 审计更新 + before-after 报告 | 至少一批数据通过审计 + seed 往返 |
| **S2 检索** | RAG 实现者 | 词法索引 + 向量索引 + 离线构建 + 评估脚本 | `retrieval_service.py`、`build_retrieval_index.py`、eval | 词法基线可跑，hybrid 可离线对比 |
| **S3 接线** | RAG 实现者 | 接三个只读入口 + 实时校验 + 降级可观测 | `read.py`、`config.py`、测试 | 三入口状态一致，降级路径可观测 |
| **S4 验收** | 用户 | 验收发布 + 数据扩量后增量重建 | 验收报告 + 版本化索引 | §10 门槛达标 |

**S1 与 S2 解耦**：RAG 可以在 S1 产出的**任一合格快照**上开工，不必等 101 道菜全配齐，也不必等补到约 200 道。并行纪律：

- 同一个文件不要两边同时改。
- RAG 作者在数据补齐期间做**独立的**检索模块与 eval 文件（新文件，无冲突）。
- 共享文件（schema / seed / adapter）**串行交接**：S1 改完再动。

**快照交接**：S1 交付验证通过的临时运行库绝对路径 `candidate_db_path`、fixture 版本/静态投影哈希和 schema 版本；S2/S3 指定这份库建索引、测接口，不读取尚未迁移的日常运行库，也不混读另一版 fixture。缺少快照时先按该版本 fixtures seed 新的隔离库。开发期启动服务也使用隔离库。

**S4 发布顺序**：验收隔离环境 → 暂停业务写入并用 SQLite backup API 做一致性备份（或停机完整备份）→ 对正式运行库执行已验收的加列迁移和受管 seed → 验证会话/购物车保留、静态投影版本一致 → 基于最终快照构建并切换索引 → 恢复服务做冒烟验收。不能只复制正在写入的 `.sqlite3` 文件而遗漏 WAL。失败时按对应数据库/schema/索引版本成套恢复，不能只切旧索引掩盖不兼容。

---

## 2. 事实基线（上轮只读快照）

下表是**此前读取的快照**，本轮文档工作未重新测量；实施前先重跑只读审计确认没有漂移。

| 对象 | 读数 |
|---|---|
| 源库 `data/sale_guide.db` | `products` 259、`recipes` 2000、`ingredient_catalog` 52 |
| 菜品 fixture `data/fixtures/chinese-dishes-v1.json` | 101 道菜；`required` 唯一食材 55 个 |
| demo fixture `data/fixtures/demo-products.json` | 39 个 demo SKU；9 个显式 `"image_status": "placeholder"` |
| 运行库 `data/runtime/sale_guide.sqlite3` | `catalog_products` 296、`purchase_templates` 107、`offers` 296 |
| 源商品图片 | 259 行都写了 `image_file`，逐行 `Path` 验证只有 **258** 个存在，缺 `data/images/0005256051595.jpg` |
| OFF 资源 | `reference/openfoodfacts/en.openfoodfacts.org.products.csv.gz` 存在（约 1.275 GB） |
| `audit_catalog.py` | `python -X utf8 scripts/audit_catalog.py` 退出 0：源商品 259 / 隔离 2 / 285 jpg / demo baking 9 |
| FTS5 | `sqlite_compileoption_used('ENABLE_FTS5')` = 1（本机编译支持） |

**读数纪律：**

- `purchase_templates = 107` **不是 101 道菜**，它还含非菜谱场景模板。不得把 101 说成运行库总数。
- **285 张 jpg 不是图片齐备**：分母要用逐条 `Path` + 解码验证，不是目录里的文件个数。
- `audit_catalog.py` 只是行数 / 文件数小审计，**不代表任何一道菜配得齐**。FTS5 编译支持已确认，**不代表中文分词可用**（见 §3.2）。

### 2.1 已确认的数据缺口

| 事实 | 位置 |
|---|---|
| 红烧肉 aliases 里写了「东坡肉」——二者不是同一道菜，这是**错误等价**，不是「同一别名指向多道菜」的 collision | `data/fixtures/chinese-dishes-v1.json:189-192` |
| 糖醋排骨 `required` 只有 `pork` 400g（实际需要排骨） | 同上 `:209-225` |
| 可乐鸡翅 `required` 只有 `chicken_wing`，`pantry_items` 无可乐；且 39 个 demo SKU 里**没有任何鸡翅** | 同上 `:228-243` |
| `demo:pork-500g` 英文名 `Pork Shoulder 500g`、中文名「猪里脊 500克」——中英名自相矛盾 | `data/fixtures/demo-products.json:198-214` |
| `demo:shrimp-paste-200g` 是「虾滑」，`ingredient_ids=["shrimp_paste"]` | 同上 `:605-624` |
| `demo:mushroom-white-200g` 是「白蘑菇」，`ingredient_ids=["mushroom"]`；菜谱用 `shiitake` / `enoki_mushroom` / `wood_ear` | 同上 `:625-643` |
| 菜谱 `ingredient_id` 命名空间与 `INGREDIENT_CATALOG` 的 52 条**不是同一套**（`egg`/`rice`/`noodle`/`wood_ear`/`shiitake` 等无对应项；`peas` vs `green_pea` 不一致） | `scripts/import_db.py:46-101` |
| 桥接这两套命名空间的现有机制是手写 `INGREDIENT_ALIASES`，当前只有 4 条 | `backend/app/services/template_plan_service.py:22-27` |

---

## 3. 检索路线（默认）

### 3.1 优先级

1. **精确命中优先**：ID、唯一完整菜名或已登记别名 → 直接返回，**不依赖 embedding、不需要网络**。
   精确命中仍检查用户排除条件、审核状态及门店资格；与硬条件冲突时明确返回冲突，不偷偷换成语义相近的菜。
2. **RapidFuzz 模糊命中不得阻断向量路径**。只有 `exact` / `alias` 这种确定性命名匹配可以短路；`fuzzy` 必须继续走词法与向量。
3. 其余查询：**中文词典 + FTS5 BM25 词法路** 与 **向量路**并行召回，RRF 融合。

### 3.2 词法路

- SQLite FTS5 + `bm25()`，**不做中文分词的是 unicode61 而不是 FTS5 本身**：必须自备词典，或写入时预先把文本切成空格分隔词元。词典来源：规范食材 JSON + 菜名 / 别名 + `usage_tags`；`lexical_tokenizer_version` 进 manifest。
- **RapidFuzz 分数作为词法路的子排序信号**（子信号，不与词法并列为第三路，避免同批候选被重复计权）。
- 中文短词（`蛋` / `醋` / `油` / `虾` / `鱼` 等单字）是最易失效处，单独记录：能召回、不过召回、单字与双字差异如实写清。

### 3.3 向量路

- 模型：**`Qwen/Qwen3-Embedding-0.6B` 是待实测候选基线**，不是「已选定 / 已部署 / 最快最好」。采用与否由 §10 评估决定。
- **不假定 chat endpoint 支持 embedding**：`OPENAI_BASE_URL` / `LLM_MODEL` 与 embedding 是两套配置。当前 `backend/app/core/config.py` 与 `.env.example` 没有任何 embedding 项，实施时**新增**而非「复用」。实际 endpoint 的 transport 可以复用，但维度 / 指令 / 归一化 / 模型族都要实测确认。
- **query 侧 instruction 只加在 query 侧**，文档侧按模型卡（无则 `null`）。**不得擅自变更维度约定**。
- 存储：**SQLite 派生索引 + 内存 float32 精确余弦**。不做 int8 量化，不引入 Qdrant / Milvus / FAISS 服务。缓存 key 含 model + revision + dim + normalize + query instruction + 文本模板版本 + 规范查询文本；V1 只做进程内内存缓存，**不在只读请求里写磁盘**。

### 3.4 RRF 融合

```
rrf_score(d) = Σ_r 1 / (k + rank_r(d))     rank 从 1 开始
```

- **两路**：词法（RapidFuzz 作为其子信号）、向量。
- 初始建议：每路 Top20，`k = 60`，融合后取 Top5。
- `k = 60` 是本方案的建议值，**不是 Qdrant 默认值**，也没有必要照搬。
- 以上全部是**待标定建议**，在 §10 的评估集上定。

### 3.5 过滤顺序

```
1. 先过滤可判定的硬条件（hard_filters）
2. 两路召回 + RRF 融合
3. 融合后做实时门店资格校验（价格 / 库存 / 配送，实时 SQL）
4. TopK 被过滤到不足 K → 触发补召回
```

- `hard_filters` 来自既有 `Requirements` / `ValidationContext`。**否定与排除必须走结构化过滤，不能靠 embedding「理解否定」。**
- **补召回必须显式做**：先取 Top5 再校验库存，可能 5 条全被滤掉，而第 6–20 名里有可用的。

---

## 4. 运行模式与降级

**一个 `RetrievalService`，不是第二个 Agent，不是第二条决策链。**

```dotenv
RETRIEVAL_MODE=hybrid      # hybrid | lexical，默认 hybrid
```

`RETRIEVAL_MODE` 是**离线对照与部署操作**用的配置，不是让模型在请求期切换能力的手段；模型不能改它。

| 情形 | `status` | 行为 |
|---|---|---|
| 两路都可用 | `ok` | `retrieval_mode=hybrid` |
| query embedding 不可用，但健康词法索引可用 | `degraded` | **可显式退到 `lexical`**；`retrieval_mode=lexical`；`fallback_reason` 写真实原因；**硬过滤全部保留**；**模型不得声称完成了语义匹配** |
| 两个索引都不可用，或静态投影不兼容 | `unavailable` | 明确失败 |
| 索引健在但确实没有答案 | `empty` | 如实返回空 |
| 精确 / 别名命中 | `ok` | 无需 embedding、无需网络 |

配置为 `lexical` 时，健康词法检索返回 `ok` + `retrieval_mode=lexical`，这是主动部署模式，不是故障。默认 hybrid 下，向量索引缺失/损坏但独立版本校验通过的词法索引健康时，也可标明原因降级；整个语料契约不兼容则不能降级。
降级后没有命中时仍保留 `status=degraded`、`hits=[]` 和 `empty=true`，表示“仅词法范围未找到”，不能报告完整语义检索无答案。超时/取消走既有停止协议，不伪造 `empty`。

**纪律：**

- **运行模式与失败原因分开**：`retrieval_mode` 说走的哪条路，`fallback_reason` / `reason` 说为什么。不要用一个笼统的布尔值掩盖具体情况。
- **`stop` 不降级**，**不违反时间预算**：用户或协作式预算要求停止时如实停止，不为出结果强撑；turn 剩余时间不足时如实返回不完整，不硬中断已在飞的调用，也不超时硬等。
- **没有高相似度时不硬塞最接近项**，低相关就返回 `empty`。**不在请求路径写索引、不拉模型**：索引构建与模型加载都在离线或启动时完成。
- 失败必须可观测：`status` / `retrieval_mode` / `fallback_reason` / `filters_applied` 一起进 facts 与 trace，便于评估分母统计。

---

## 5. 数据结构契约

### 5.1 规范食材主数据

- 新增 `data/fixtures/ingredient-catalog.json` 作为**规范食材主数据的单一来源**，替代散落在 `INGREDIENT_CATALOG`（`scripts/import_db.py:46-101`）、`INGREDIENT_ALIASES`（`backend/app/services/template_plan_service.py:22-27`）与菜谱 fixture 里的重复维护。
- `scripts/import_db.py` 的 `INGREDIENT_CATALOG` **保留兼容加载接口**（外部仍能从该名字取到同样的定义），定义源改为读规范 JSON。
- **ID 与别名只做等价，不做替代**：`pork_ribs` ≠ `pork_loin`；`shrimp_paste`（虾滑）≠ `shrimp`（虾仁）；`mushroom`（菌菇父类）≠ `shiitake`（香菇）。**父类不得当子类用。**
- **食材中文名与商品中文名不得混用**：规范 JSON 提供食材名称；商品名保留 OFF 原始名称、品牌与加工形态，只有有依据的翻译才写 `name_zh`（「含花生的饼干」≠「花生」）。

### 5.2 菜品：保持现有字段，加可空元数据

现有 `required_items` / `optional_items` / `pantry_items` / `base_people` **格式不变**。新增顶层：

```json
{
  "meta": {"description": null, "taste": null, "cooking_method": null,
           "meal_types": [], "difficulty": null, "cook_minutes": null},
  "meta_provenance": {"description": null, "taste": null, "cooking_method": null,
                      "meal_types": null, "difficulty": null, "cook_minutes": null},
  "review": {"status": "unreviewed", "reviewer": null, "reviewed_at": null}
}
```

- **全部可空**。未知就 `null` / `[]`，这是合法且期望的状态，不是缺陷。
- **`meta_provenance` 逐字段独立**：`fixture` / `manual_review` / `null`。**机器生成、未经人工审阅的字段一律不得标 `manual_review`。**
- **不得凭菜名编造时间 / 口味 / 营养。**

### 5.3 SKU：`metadata_json` 内容

```json
{
  "image_status": {"kind": "photo", "file_verified": null,
                   "semantic_match": "unknown", "source_url": null},
  "provenance": {"source": "demo", "is_demo": true, "source_barcode": null},
  "ingredient_mapping": [{"ingredient_id": "shrimp_paste", "relation": "declared",
                          "evidence": "fixture:demo-products.json", "evidence_status": "demo_declared"}],
  "allergens": {"status": "unknown", "values": [], "evidence": null}
}
```

- `image_status` 用**上面这一份对象 schema**（`kind`: `photo` / `placeholder` / `missing`；`semantic_match`: `verified` / `unknown` / `mismatch`），消费者沿用相同字段，不另造并列状态格式。
- **兼容**：fixture 里既有的 `"image_status": "placeholder"` 字符串由 seed 归一化成对象，**不破坏现有 seed 校验**。
- **`allergens` 的 `unknown` ≠ `none`**。字段缺失即 `{"status": "unknown"}`。系统不得自动宣称「本菜对某过敏安全」。
- `ingredient_mapping[].relation`：`declared`（SKU 自称） / `reviewed`（人工确认） / `inferred`（推断，**不可用于配货断言**）。

### 5.4 两处 `metadata_json` 与审核口径

| 表 | 新列 | 内容 |
|---|---|---|
| `PurchaseTemplate` | `metadata_json` | `{meta, meta_provenance, review}` |
| `CatalogProduct` | `metadata_json` | `{image_status, provenance, ingredient_mapping, allergens}` |

**为什么必须做**：`seed_chinese_dish_templates`（`scripts/seed_runtime.py:491-506`）、`template_record_to_dict`（`backend/app/services/template_matcher.py:59-71`）、`PurchaseTemplate`（`backend/app/models/catalog.py:47-57`）三者都只认已声明的列。只在 fixture 加 JSON 字段，seed 之后必然丢失，而且 DB 路径与 fixture 回落路径结果不一致。

**约定三处一致**：菜 fixture 的 `meta` / `meta_provenance` / `review` 保持在顶层；DB 读取返回用 `metadata` 外层包住三者；索引归一化由 `metadata` 展平，规则显式写出；**`dish_fixture_to_dict` 必须映射同一份 `metadata`**（当前不映射，是缺口）。

**审核口径：两套 review 不要混。** 保留现有 `approved` / `quarantined` 审核与隔离语义；已确认错误可以定向隔离，不能只因新增证据字段为空就整体停用旧目录。metadata 里另标证据强度 `demo_declared` / `source_verified` / `pending`。

- **不能只因为旧 source 缺「人工 review」就把整个库停用。新增映射在未知时不得伪造人工审核**，按证据标 `demo_declared` / `source_verified` / `pending`，再据此决定是否配货。
- 新增证据审核没有来源时不得冒写“已人工审核”；这不等于擅自改变已有目录审批。`pending` 或仅 `inferred` 的新增映射不能证明可配齐。
- 已存的 source 图：`file_verified` 可写真实结果，但 `semantic_match` **保持 `unknown`**，不自动置绿。

### 5.5 往返一致性

`fixture → seed（update + insert + schema migration）→ 模板 / 商品投影 → index` 全链路要有往返测试，**两条读取路径（DB / fixture 回落）的元数据必须一致**。

- 加列照抄现成先例 `ensure_purchase_template_schema`（`scripts/seed_runtime.py:444-455`），新函数在 `main()` 的 `create_all` 之后调用；**写库点在 `_upsert_purchase_template`**（同文件 `:458-482`）。
- SKU 侧必须 seed / backfill / `product_to_dict` 一起覆盖，只做一半会出现「fixture 有、DB 有、API 没有」的静默丢失。

---

## 6. 检索单元与检索文本

- **一菜一文档**、**一 SKU 一文档**。**不切块**：文档结构化且长度可控，固定字符切块只会破坏 `required` / `pantry` 的字段语义。**不做第三套食材向量索引**：食材表是主数据字典，只作为文档的归一化维度。
- **菜与 SKU 不混在一个集合**，各自召回、各自打分（避免用同一把尺比较「一道菜」与「一件商品」）；跨类型由模型在 facts 层组合。
- **检索文本构成**：已核实的名称与别名 + 主料中文名 + 说明用途的标签。目标是让「鸡蛋豆腐有什么菜」这类**按食材找菜**的查询有食材信号——菜名里只有「番茄炒蛋」，用户说的是「鸡蛋」。**未知的耗时 / 口味 / 营养不写进检索文本**，不编造。
- **价格 / 库存 / 配送不 embedding**，实时从 SQL 取。**无图不阻断检索与配货**，图片完备率单独报。
- `required` / `optional` 每条**有且仅有一个数量维度**（`quantity_g` / `quantity_pc` / `quantity_ml`），值为正有限数；**`pantry_items` 保持字符串数组、不带数量**；**只允许同维度换算**（g↔kg、ml↔l、pc↔pc），**没有密度不得 g↔ml**；**`oil` 用 `quantity_g` 完全合法**。

---

## 7. 索引与 manifest

### 7.1 manifest 字段

```json
{
  "schema_version": 1,
  "manifest_id": "sha256:...",
  "projection_snapshot_hash": "sha256:<仅规范静态检索投影的哈希>",
  "projection_snapshot": {"template_version": "<构建时实际值>", "ingredient_catalog_version": "<构建时实际值>",
                          "dish_count": "<构建时实际值>", "sku_count": "<构建时实际值>"},
  "lexical_tokenizer_version": "zh-dict-v1",
  "text_template_version": "v1",
  "embedding": {"model": "<实测采用的模型>", "revision": "<pin 到具体 commit>", "dimension": "<实测确认>",
                "dtype": "float32", "normalize": true,
                "query_instruction": "<逐字节记录>", "document_instruction": null},
  "doc_hashes": {"<doc_id>": "sha256:..."},
  "audit_only": {"runtime_db_path": "data/runtime/sale_guide.sqlite3"}
}
```

计数一律写构建时的实际值，**不要把预期数量写进模板**。

### 7.2 失效判定

- **不得用整个 runtime 库的哈希做失效判定**：里面有会话 / 库存 / 价格，每变一次都会让索引整体失效。
- 只对**规范静态检索投影**算 `projection_snapshot_hash`。runtime 路径只作 `audit_only` 审计信息，**不参与失效判定**。
- **逐 doc 静态内容哈希**，用于丢弃过期项与补召回；不做「先查全库大哈希再整表失效」。
- **价格变化无需重 embed。**
- 模型 / revision / 维度 / 归一化 / query instruction / 参与 embedding 的文本模板任一改变 → **离线重建**对应向量索引。纯词法分词器变动只重建词法索引。
- 查询侧用**实时库校验命中 ID**：删除或更新过的 doc 应失效，命中幽灵项丢弃并记录；新记录需重新构建索引才能被召回。语料不兼容时**不能用旧索引装成正常**，报 `INDEX_STALE`。
- **审计报告与索引版本绑定**，便于追溯结论出自哪份快照。

### 7.3 发布

- **一致读快照 → 离线在新目录构建 → 校验（计数 / manifest / 抽样）→ 原子指针切换。**
- Windows 上目标被进程持有会 `PermissionError`，所以用「写新目录 + 换指针」，失败不破坏旧索引。
- **保留上一份兼容且健康的索引用于回滚。只读请求不写任何东西。**
- **凭据纪律**：本轮只是同意开发，**不是批准发凭据或读 `.env`**。凭据从环境读，不写进仓库、fixture 或报告。

---

## 8. 只读接线

### 8.1 新增文件

| 文件 | 作用 |
|---|---|
| `backend/app/services/retrieval_service.py` | 一个 `RetrievalService`：精确 / 词法 / 向量 / RRF / 降级 |
| `scripts/build_retrieval_index.py` | 离线构建 + 校验 + 原子发布 |
| `backend/app/llm/embedding.py`（或同类小模块） | embedding adapter：**尽量复用现有 LLM transport**，否则做一个小而独立的 embedding provider |
| `backend/app/core/config.py`、`.env.example` | 新增 embedding 与 `RETRIEVAL_MODE` 配置项 |
| `backend/tests/` | 检索、manifest、降级、往返测试 |

### 8.2 返回结构

`search_dishes(query, *, context, limit=5)` / `search_products(query, *, context, limit=5)` 统一返回：

```json
{
  "status": "ok",
  "retrieval_mode": "hybrid",
  "fallback_reason": null,
  "index_version": "<已加载快照版本>",
  "filters_applied": {},
  "hits": [{"kind": "dish", "target_id": "dish-tangcu-paigu", "name": "糖醋排骨",
            "match_kind": "semantic", "evidence": ["<每条 ≤ 3 条、每条 ≤ 120 字>"],
            "review_status": "approved", "stock_verified": false,
            "unknown_constraints": ["budget"]}]
}
```

示例只展示结构，**不表示该菜已补齐或已审核**。`status` 枚举 `ok` / `degraded` / `empty` / `unavailable`；`match_kind` 枚举 `exact` / `alias` / `fuzzy` / `lexical` / `semantic` / `fused`。

- **`match_kind` 必须透传给模型**——否则模型无法如实说明「这是相似候选」。新增值 `semantic` 要同步加白名单测试，**不得灌进 RapidFuzz 的 95 阈值冒充命名匹配**；非命名命中**只能表示候选**。

### 8.3 现有漏点（真实、具体）

| 漏点 | 位置 |
|---|---|
| `search_dishes` 把非 `ok` 结果变成 `[]`：`NO_MATCH` / `CONSTRAINT_CONFLICT` / `RETRIEVAL_FAILED` 全被抹平 | `backend/app/agent/tools/read.py:186-190` |
| `_lookup` 无条件返回 `STATUS_COMPLETED`，空结果与失败无法区分 | 同上 `:175-184` |
| `_recommend_topic(query)` 调用菜谱/商品查询后返回 `STATUS_COMPLETED`，菜谱查询失败此前已被裁成空列表 | 同上 `:309-342` |
| `recipe` 的有 query 分支调完被裁剪的 `search_dishes` 后返回 `STATUS_COMPLETED` | 同上 `:236-240` |
| `_lookup` 只回 `{ref, name, target_id}`，丢失 `match_kind` / 证据 / review / `stock_verified` | 同上 `:181-183` |
| `match_kind` 已经产出（`exact` / `fuzzy` / `ambiguous`，阈值 95.0）但**从未被消费** | `backend/app/agent/tools/search_dishes.py:16,84,91,96,107,112` |
| `suggest_buildable_dishes(limit=3)` 的调用点**没传 `scan`**，默认 20 → 只考察 fixture 顺序前 20 道 | `backend/app/services/template_plan_service.py:202,206`；调用点 `read.py:223` |
| `CandidateSet.allocate` **不校验 `kind`** | `backend/app/agent/protocol.py:132-159` |

### 8.4 接线要求

1. **三个入口（`_lookup` / `_recommend_topic` / `recipe`）一致透传检索状态** `ok` / `degraded` / `empty` / `unavailable`，不再吞掉错误；同时透出 `match_kind`、`evidence`、`review` 状态、`stock_verified`、`unknown_constraints`、`index_version`。这些是工具事实中的检索状态，不直接替换既有任务生命周期/SSE 状态枚举。
2. **候选 ref 由现有 `CandidateSet` 分配**（SKU 内部 `kind` 是 `sku`，映射到协议里的 `product`）：检索服务**不自造 ref**，`allocate` 补上 `kind` 校验。候选数上限沿用 `MAX_LOOKUP_ROWS = 5`（`read.py:43`），`evidence` 限长以免 facts 膨胀。
3. **`suggest_buildable_dishes` 消除前 20 条盲区**：批量预取门店目录，分批遍历全部菜谱，收满结果或耗尽候选 / 剩余时间时结束；时间耗尽**如实标不完整**，不能说「没有可做的菜」。它在 `services/template_plan_service.py`，不在 `read.py`。
4. **`recommend` 合并菜谱/商品两种来源时要定义部分失败**：一类成功、另一类失败或降级 → 总体标 `degraded`，用 `partial_sources` 记录每类状态/原因；全部不可用才 `unavailable`。只有两类都完整成功且都无结果才报告完整 `empty`，不得把查询失败说成没有商品。
5. **`build_plan` / `check_constraints` 只读复用现有服务**（`TemplatePlanService.build_plan`、`PlanValidator`）；**绝不 `publish_snapshot`、绝不创建计划、绝不写库**。**不改** `protocol.py` 的 `FORBIDDEN_KEYS`、**不新增 mutation verb**，`test_semantic_only_architecture.py` 必须继续通过，也不去动不需要的用户确认写入契约。

---

## 9. 无答案、歧义与约束

- **无答案不能靠 TopK 自然产生**：向量检索总会给出最近邻，**RRF 分数不是置信概率**。用标注集里的正例、硬负例、无答案例校准接受门槛，结合原始语义相似度、词法 / 食材证据与领先差距；**不给 RRF 排名设万能阈值**。低相关 → `empty`；多个近似候选 → `ok` 并要求澄清，**不自动建单**。门槛只在 dev 集上定，holdout 不调参。
- **两种结果必须分开**：「可作为候选被检索到」可以是 `unknown`；「可购买 / 满足预算」**必须校验**，没证据就写 `unknown`，**不得写「候选存在即能买」**。
- **没有证据的维度不得宣称符合**：metadata 里没有时间证据时，「20 分钟以内」不能算满足；**过敏未知不得做安全承诺**。
- **pantry 口径**：未知**默认不勾选**并说明未知；**不新增 pantry 状态机**；用户说「家里有」时**不得替用户假定数量充足**，只能标「已备（数量未知）」。菜品侧的 `required` / `optional` / `pantry` 是菜谱声明，与用户侧 pantry 声明是两件事，不互相覆盖。
- **预算按整单算**，不按单价冒充；份量换包装由现有 `_pack_qty`（`backend/app/services/template_plan_service.py:98-114`）与 `PlanValidator` 负责，检索层不复制业务规则。**`required` 可配货的判定不止 `sellable`**：还要同时满足**规范身份一致、规格同维度适配、按 2 人份的包装数、`available_qty` 足够**。**缺规格时不得默认 1 包**然后当作已验证。

---

## 10. 评估与验收

### 10.1 标注集

- **至少 60 条**：**20 条 dev + 40 条 holdout**。两条分组轴**不要混为一谈**（不能说「精确组就是 dev」）：

| 轴 | 取值 |
|---|---|
| 类别 | 精确 / 模糊 / 约束 / 硬负例 / 无答案 |
| split | dev（调参） / holdout（不调参） |

- **同一道菜的改写不得跨 split**，否则调参泄漏到留出。
- 每条字段：`query`、`entity_kind`、`gold_ids`、`relevance`、`answerable`、`constraints`、`expected_unknown`，以及**当时的 catalog snapshot 标识**。
- **无答案样本少时就报「错误数 / 总数」**，不要拿 5 条算出一个「≤5%」的统计承诺。

### 10.2 建议的发布门槛（建议，不是已达成的验收事实）

质量至少报告分组 Recall@5、MRR@5，以及无答案误返回数/样本数；精确命名行为单列。比较词法与 hybrid 时固定同一语料、门店快照、硬过滤和 holdout，避免把“补了数据”误算为“换检索算法”的提升。

| 条件 | 建议 |
|---|---|
| 精确行为回归 | 0 |
| 已知硬条件违规 | 0 |
| 候选事实 ID 有效率 | 100% |
| 语义质量 | 在**同一 holdout** 上达到或超过词法 baseline，并改善已识别的核心弱项 |
| 降级质量 | **单独统计**，不与正常 hybrid 混报 |

**不强制「提升 10 个百分点」**这类指标——baseline 已经很高时不现实。阶段指标都是建议，报告里必须写清哪些已实测、哪些还没有。

### 10.3 报告纪律

- **延迟实测并分别报告 `p50` / `p95`**：`embed` / `retrieve` / `live_verify` / `turn` 四段分开；**不写没测过的性能数字**，也不把全链耗时冒称「RAG 优化显著」。**mock 与真实模型分开跑、分开报。**
- **离线 hybrid 正式评估里，`degraded` 结果算可用性，单独统计，不能算作 hybrid 质量成功。**
- 成功 coverage 的分母写清楚（全部 query，还是排除无答案后的 query）。**未完成 / 未验证的项如实标 `unknown` 或 `not_evaluated` 并给依据**，不伪造。

---

## 11. 技术参考

以下官方链接此前已核实可达；**未安装、未 benchmark 其中任何一项**。

```
SQLite FTS5（BM25 与分词器语义，§3.2）
https://www.sqlite.org/fts5.html

SQLite Online Backup API（S4 一致性备份参考）
https://www.sqlite.org/backup.html

Qdrant Hybrid Queries（RRF 算法说明，§3.4；只引用算法，不引入该服务）
https://qdrant.tech/documentation/search/hybrid-queries/

Qwen3-Embedding-0.6B model card（§3.3 候选基线）
https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
```

---

## 12. 启动后续 RAG 实现的短提示词

S1 数据批次通过后，把下面这段整体复制给实现者（新会话）开始 S2：

````text
在 C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide 工作。先读父目录 AGENTS.md、README，以及
docs/plans/2026-09-18-rag-optimization.md 全文（尤其 §3 检索路线、§4 降级、§5 数据契约、§7 索引、§8 接线）。

本次做 S2：词法 + 向量离线检索与评估。不动 agent 架构，不建第二个 agent。

- 新增 backend/app/services/retrieval_service.py、scripts/build_retrieval_index.py、embedding adapter
  （优先复用现有 LLM transport）、backend/tests/ 下的检索与 manifest 测试。
- 词法：FTS5 + 中文词典 + BM25。向量：SQLite 派生索引 + 内存 float32 精确余弦。两路 RRF（k 初值 60，待标定）。
- 读取 S1 报告提供的 candidate_db_path、fixture/schema 版本；只从这份合格隔离运行库构建，不混读日常运行库或另一版 fixtures。一致读 → 新目录 → 校验 → 原子指针切换，保留兼容旧索引用于回滚。
- 评估用 RAG 文档 §10 的 60 条标注集（20 dev / 40 holdout），dev 调参、holdout 不调参；mock 与真实模型分开报。
- 遇多个合理做法取合理默认继续做，不要逐项提问；不确定的标 pending 并继续。
- 新 CLI 参数由你定义并提供 --help；不要假定 .env 里已有 embedding 配置，也不要读取凭据。

结束时报告：改动文件、实际执行的命令与真实输出、未执行项及原因、指标与分母、仍待验证项。
````
