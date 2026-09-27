# Cursor 数据补齐提示词（S1）

- 日期：**2026-09-18**
- 配套：[2026-09-18-rag-optimization.md](./2026-09-18-rag-optimization.md)（字段与 metadata 约定以该文档 §5 / §6 为准）
- 用途：把下面 fenced 块**整体复制**给 Cursor（Agent 模式），在**新会话**里执行。

`BASE` = `C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide`

````text
# 任务：Sale-guide 菜谱/SKU 数据补齐与审计（S1）

## 0. 工作目录与环境

BASE = C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide
后端 venv = C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\backend\.venv
平台：Windows + PowerShell。所有 Python 调用一律带 `-X utf8`。

开始前读取：
- C:\Users\20616\Desktop\Agent\Agent产品\AGENTS.md
- BASE\README.md
- BASE\docs\plans\2026-09-18-rag-optimization.md 的 §2（事实基线）、§5（数据结构契约）、§6（检索文本）

## 1. 本次目标

补齐菜品与 SKU 数据及 metadata，让「按食材找菜」「按用途找商品」有真实信号，并产出可复核的审计基线。

**本次完成后就停**：不实现检索服务，不建索引，不接 agent 链路。

### 1.1 必须真正补数据，不只是整理文档

只维护现有 39 个 demo SKU **不算完成**。必须：

1. 对当前 `required` 缺口按**覆盖收益**排序（补上某个食材能解锁多少道菜 / 让多少道菜变成可配货），产出排序表。
2. 按这个顺序**真正新增 SKU**，每个新 SKU 带齐：真实食材身份（不是品类相近的替代）、`spec_quantity` / `spec_unit`、
   `ingredient_ids`、模拟 offer（`price_fen` / `available_qty` / `sellable` / `is_demo`）。
3. **首批规模按覆盖收益决定：每批 5–10 个食材，或 10–20 道菜。** 跑完审计 + seed 往返、确认这批真的解锁了覆盖，再进下一批。
4. 先保证 **101 道菜里 `required` 引用的 `ingredient_id` 全部合法**。能补的补；补不了的**逐条写清为什么**。
   **不要为了凑到某个数量强补** —— 补到约 200 道是后续按数据质量与业务需要决定的事，不是本次目标。

**允许的必要范围**：新增 demo SKU / 规格 / ingredient 映射 / 模拟 offer（标 `is_demo`）；补有证据的 metadata；
必要的 fixture / schema / seed / 审计脚本 / 相关服务小修 / 测试 / 报告 / 新增图片。
**必要即可**，不做与数据补齐无关的治理、重构或顺手改动。

### 1.2 已知需要修的事实（先复核再改，不要照抄）

- `demo:pork-500g` 英文名 `Pork Shoulder 500g` 与中文名「猪里脊 500克」自相矛盾 → 查明实际身份后统一，不要两边都留。
- 糖醋排骨 `required` 只有 `pork`，实际需要排骨 → 不要用里脊 / 肩肉顶替（`pork_ribs` ≠ `pork_loin`）。
- 可乐鸡翅 `required` 只有 `chicken_wing`，`pantry_items` 里没有可乐，且现有 demo SKU 里没有任何鸡翅。
- 红烧肉挂了别名「东坡肉」——二者不是同一道菜，这是**错误等价**，直接修。
- `shrimp_paste`（虾滑）不能顶 `shrimp`（虾仁）；`mushroom`（白蘑菇 / 菌菇父类）不能顶 `shiitake` / `enoki_mushroom` / `wood_ear`。

## 2. 数据来源与图片纪律

- **来源优先级**：可追溯的现有 OFF 资产优先；否则用明确的 demo 模拟场景，并在 metadata 里标明是模拟。
- 允许从**已有条码记录对应的公开 OFF 图片 URL** 下载图片，**必须写下 provenance**（来源 URL、条码、下载时间）。
- **不得乱配图**：无法证明对应关系的图片一律不配。**有证据就补，没证据就保留 placeholder 并登记**，不要一刀切「placeholder 保持原状即可」。**不得读凭据、不得读 `.env`**，不爬取无关网站。
- **OFF 是导入资源，不是门店在售真相**。真实 OFF 条码 **≠ 真实库存**；demo offer **必须标 `is_demo`**。
- **不得凭 `product_name` 粗写食材中文名**，也不能因为商品含某食材就把商品改名成该食材（「含花生的饼干」≠「花生」）。
  商品名保留原始名称、品牌与加工形态，没有可靠译名就保留原名并标待审。

## 3. metadata 与规范食材

字段权威定义见 BASE\docs\plans\2026-09-18-rag-optimization.md §5。

### 3.1 两处 `metadata_json`

| 表 | 新列 | 内容 |
|---|---|---|
| `PurchaseTemplate` | `metadata_json` | `{meta, meta_provenance, review}` |
| `CatalogProduct` | `metadata_json` | `{image_status, provenance, ingredient_mapping, allergens}` |

- **字段缺失一律 `unknown` / `null`，不假造。**
- 加列照抄现成先例 `ensure_purchase_template_schema`（`BASE\scripts\seed_runtime.py:444-455`），
  新函数在 `main()` 的 `create_all` 之后调用。
- **写库点在 `_upsert_purchase_template`（`BASE\scripts\seed_runtime.py:458-482`）**，注意它在 `seed_runtime.py`。
- **三处约定要一致**：菜 fixture 的 `meta` / `meta_provenance` / `review` 保持顶层；DB 读取返回用 `metadata` 外层包住三者；
  索引归一化从 `metadata` 展平。**`dish_fixture_to_dict` 必须映射同一份 `metadata`**（当前不映射，是缺口）。
- **SKU 侧必须 seed / backfill / `product_to_dict` 一起覆盖**，只做一半会出现「fixture 有、DB 有、API 没有」的静默丢失。
- `image_status` 用统一 schema：`{kind: photo|placeholder|missing, file_verified, semantic_match, source_url}`。
  fixture 里既有的 `"image_status": "placeholder"` 字符串由 seed 归一化成对象，**不要破坏现有 seed 校验**。
- **已存的 source 图**：`file_verified` 可写真实结果，`semantic_match` **保持 `unknown`**，不自动置绿。
- **`allergens` 的 `unknown` ≠ `none`**。不得宣称某菜对某过敏安全。
- **审核口径不要混**：保留 `approved` / `quarantined` 的审批和隔离语义，明确误配可以定向隔离，
  **不能只因旧 source 缺「人工 review」就把整个库停用**；metadata 里的证据强度另标 `demo_declared` / `source_verified` / `pending`。
  没证据的新增映射不能宣称可配齐；已有 approved 不等于新关系已经人工核实。

### 3.2 规范食材单一来源

- 新建 `BASE\data\fixtures\ingredient-catalog.json` 作为规范食材主数据的**单一来源**，
  替代散落在 `INGREDIENT_CATALOG`（`BASE\scripts\import_db.py:46-101`）、
  `INGREDIENT_ALIASES`（`BASE\backend\app\services\template_plan_service.py:22-27`）与菜谱 fixture 里的重复维护。
- `BASE\scripts\import_db.py` 的 `INGREDIENT_CATALOG` **保留兼容加载接口**（外部仍能从该名字取到同样的定义），
  定义源改为读规范 JSON；该文件**只改这个入口**，其余不动。
- **ID 与别名只做等价，不做替代**：`pork_ribs` ≠ `pork_loin`；虾滑 ≠ 虾仁；菌菇父类 ≠ 香菇。**父类不得当子类用。**
- 注意：**菜谱侧的 `ingredient_id` 与那 52 条不是同一套命名空间**
  （菜谱用 `egg` / `rice` / `noodle` / `flour` / `tofu` / `wood_ear` / `shiitake` / `green_pea` 等，且 `peas` vs `green_pea` 不一致）。
  规范 JSON 要把两套对齐，**不能只搬 52 条了事**。

### 3.3 数量与单位规则

- `required` / `optional` 每条：**有且仅有一个数量维度**（`quantity_g` / `quantity_pc` / `quantity_ml`），**值为正有限数**。
- **`pantry_items` 当前是字符串数组、不带数量 —— 保持兼容**，不要给每条加 quantity，也不要要求 quantity > 0。
- **只允许同维度换算**（g↔kg、ml↔l、pc↔pc）。**没有密度不得 g↔ml。**
- **`oil` 用 `quantity_g` 完全合法**，不要标成可疑或去「纠正」它。

### 3.4 审核来源不得伪造

- **机器生成、未经人工审阅的字段，一律不得标 `manual_review`。**
- **未知保持 `null`**（`cook_minutes: null` / `taste: null` 是合法且期望的状态）。
- **不得凭菜名瞎编时间 / 营养 / 口味。**
- 菜谱 `meta` 字段统一为 `description`、`taste`、`cooking_method`、`meal_types`、`difficulty`、`cook_minutes`；
  无可靠来源填 null / 空列表，`meta_provenance` 逐字段记出处。可先补有来源的描述、主料与烹饪方式。
- 检索文本要带上**已核实的名称别名 + 主料中文名 + 说明用途的标签**，
  否则「鸡蛋豆腐有什么菜」这类按食材找菜的查询没有信号。

## 4. UTF-8 纪律

- 仓库所有 JSON / Python 一律 UTF-8，读写**必须显式指定** `encoding="utf-8"`。
- **`BASE\scripts\audit_catalog.py` 第 28 行与第 47 行两处 `read_text()` 都要加 `encoding="utf-8"`**（只修这一处，其它逻辑不动）。

## 5. 审计脚本（`BASE\scripts\audit_retrieval_data.py`，本次新建，只读）

输出 **JSON + 简表**，含 **before / after 对照、各分母、失败理由**。

1. **引用合法性**：所有菜的 `required` / `optional` / `pantry` 引用的 `ingredient_id` 合法。
2. **别名有序且唯一**（无重复、无自指）。
3. **错误等价审计**：别名指向**不同身份**的菜 → 报出（例：红烧肉挂「东坡肉」）。
   注意这与第 4 项是**两个独立检查项**：当前没有第二道菜叫东坡肉，所以它**不构成**「同一别名指向多道菜」的 collision，不要混为一谈。
4. **重复 collision 审计**：同一别名指向多道菜 → 报出。
5. **数量与单位**：`required` / `optional` 每条恰好一个数量维度且为正有限数；`pantry_items` 保持字符串数组、不带数量；
   **无密度不得 g↔ml**；**油用克是合法的**。
6. **SKU 关系语义正确**（不是品类相近）。
7. **份量换包装与库存门槛**：`spec_quantity` / `spec_unit` 与 `_pack_qty`
   （`BASE\backend\app\services\template_plan_service.py:98-114`）换算链路一致，且 `available_qty` 覆盖 `_pack_qty` 的结果。
9. **`required` 可配货**的判定**不止 `sellable`**，必须同时满足：规格同维度适配、按 2 人份的包装数、
   `available_qty` 足够、规范身份一致、审批通过且未被隔离。**缺规格时不得默认 1 包**然后当作已验证。
10. **图片两个维度分开报**（不只看扩展名）：
    - `file_verified`：PIL 只验证技术层面（能打开、非损坏、格式正确）。
    - `semantic_match`：**PIL 不能证明语义一致性**。由可追溯映射 + 人工核查给出；**无法确认一律 `unknown`**，不得自动置绿。

### 5.1 报告纪律

- **必须报告「真正缺什么」**；**不得用「零缺失目标」逼自己造假**。
- **允许留下「明确不齐的菜」清单**，但不得以 skip / 删菜 / 加错 SKU 冒充成功。
- **分母分开报**：① 菜可作为文档被检索 ② `required` 全部可配货 ③ 受控 scenario 下可完成 ④ 展示图片完备率。
- **没有用户上下文时，不得输出「用户本次完成率」这类编造指标**，报 `not_evaluated`。
- **用户说「家里有 X」时不得替用户假定数量充足**，只能标「已备（数量未知）」。

## 6. 测试要求

### 6.1 修掉虚通过

- **`BASE\backend\tests\test_dish_plan_images.py` 里 `failed → continue` 的虚通过路径必须改掉。**
- 改成**显式成功**，或**明确登记为 `expected_unbuildable` 并带上理由**。
- **新增的缺失必须 fail**，不得默默 continue。**不要简单要求「101 道菜全部 passed」** —— 那会逼出造假；
  允许存在**登记在册**的 `expected_unbuildable`。

### 6.2 本次必须新增的测试

- **UTF-8**：fixture 与报告文件读写都用 UTF-8（含 `audit_catalog.py` 两处修复的回归）。
- **合法 id**：`required` / `optional` / `pantry` 引用的 `ingredient_id` 全部合法。
- **不混品类**：`ingredient_ids` 不出现跨品类冒充（虾滑 ≠ 虾仁、白蘑菇 ≠ 香菇）。
- **份量规格**：`spec_quantity` / `spec_unit` 与 `_pack_qty` 换算正确；**metadata 往返**：`fixture → DB → 读 API`
  （`PurchaseTemplate.metadata_json` 与 `CatalogProduct.metadata_json` 两条都要）。
- **连续 seed 两次**：第二遍结果与第一遍一致。**受管集合对齐**：种子的删除 / 隔离只作用于受管集合，**不得删除事务数据，不得破坏购物车与会话**。

## 7. 命令：已有 vs 本次新增

### 7.1 现在就能跑（已有脚本）

```powershell
& "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\backend\.venv\Scripts\python.exe" -X utf8 "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\scripts\audit_catalog.py"
```

### 7.2 现在就能跑（临时库，不碰运行库）

两段都用 `try/finally` 恢复 `$env:DATABASE_URL`，并检查 `$LASTEXITCODE`。

```powershell
Set-Location -LiteralPath "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide"
$previousDb = $env:DATABASE_URL
$tmpDir = Join-Path $env:TEMP ("sale-guide-s1-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$tmpDb = Join-Path $tmpDir "seed-probe.sqlite3"
try {
  $env:DATABASE_URL = "sqlite:///" + $tmpDb.Replace('\', '/')
  & "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\backend\.venv\Scripts\python.exe" -X utf8 "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\scripts\seed_runtime.py"
  if ($LASTEXITCODE -ne 0) { throw "第一次临时 seed 失败，退出码 $LASTEXITCODE" }
  & "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\backend\.venv\Scripts\python.exe" -X utf8 "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\scripts\seed_runtime.py"
  if ($LASTEXITCODE -ne 0) { throw "第二次临时 seed 失败，退出码 $LASTEXITCODE" }
} finally { $env:DATABASE_URL = $previousDb }
```

两遍都要成功。**幂等以两次执行后的受管实体、关联、metadata、报价与逻辑行数相同为准**（忽略技术时间戳），
**不要只比较日志里的新增 / 更新计数**。由定向测试保存第一遍的逻辑快照，在第二遍后逐项断言。

```powershell
Set-Location -LiteralPath "C:\Users\20616\Desktop\Agent\Agent产品\Sale-guide\backend"
$previousDb = $env:DATABASE_URL
$testDb = Join-Path $env:TEMP ("sale-guide-s1-" + [guid]::NewGuid().ToString('N') + ".sqlite3")
try {
  $env:DATABASE_URL = "sqlite:///" + $testDb.Replace('\', '/')
  & .\.venv\Scripts\python.exe -X utf8 -m pytest tests -q -p no:cacheprovider `
    --deselect tests/test_llm_provider.py::test_smoke_live
  if ($LASTEXITCODE -ne 0) { throw "测试未全通过，退出码 $LASTEXITCODE；按基线如实记录失败，勿伪报成功" }
} finally { $env:DATABASE_URL = $previousDb }
```

### 7.3 现在不可直接运行（本次实施时才新增）

- `BASE\scripts\audit_retrieval_data.py` 及其参数（如 `--out`）：**本次新建**，参数由你定义。报告里必须注明「本次新增」，并在交付时给出它的 `--help` 输出。
- **不要直接跑 `BASE\scripts\import_db.py` 的导入流程**：它会先删后建，缺 CSV 时会把库搞坏。本次不需要重建源库。
- **正式运行库的迁移 / seed 发布不在本次执行**：留到验收阶段，先备份再显式执行。本次只写临时库。

## 8. 遇到选项怎么办

- **有多个合理做法时，不要停下来问。** 取一个合理默认直接做，并在报告里写明选了什么、为什么。
- **证据不确定时**：标 `pending` 或隔离该条目，**继续做本批其余部分**。
- **只有在阻塞、且无法保守完成时**，才问**一个问题**。
- **不要因为工作区有无关的未提交改动而停止**。不要 `git reset` / `git clean` / `git checkout --`。
- **不要启动后端 / 前端服务**，不要向业务 API 发 HTTP 请求，不要碰运行库及其 `-wal` / `-shm`。

## 9. 交付清单（缺一不可）

1. **实际执行的命令**（逐字）+ **每条的真实输出摘要**（通过 / 失败数、退出码）。
2. **没有执行的项**及原因。
3. **补了哪些 SKU / 哪些 metadata 字段**，以及**还缺哪些字段 / 映射**（逐条）。
4. **`required` 缺口按覆盖收益排序表**（补前 / 补后覆盖变化）。
5. **改动文件清单** + 每个文件的改动摘要。
6. **审计 before / after 对照表** + 各分母（`data-audit-before.json` / `data-audit-after.json` 写到
   `BASE\verification\data-completion\`，不覆盖既有报告）；**数据集版本标识**（本次用到的 fixture 快照）与**受管变更清单**。
   同时交付验证通过的临时库绝对路径 `candidate_db_path`、schema 版本和静态投影哈希，供后续 RAG 构建/接口测试使用；
   保留这份交接库，不让后续实现误用尚未迁移的日常运行库。
7. **明确不齐的菜清单**（每道菜为什么现在配不齐）。
8. §1.2 各疑点的**逐条复核结论**：确认 / 否定 / 不确定 + 依据（文件:行）。
9. **seed 幂等**验证命令与两遍结果对比；**既有测试基线** vs 本次结果对照（先跑基线，不得把既存失败算作本次新引入）。
10. 本批**声明为 `pending` / 隔离**的条目清单。

## 10. 事实基线（2026-09-18 快照；执行时重跑只读审计确认未变化）

- 源库 `BASE\data\sale_guide.db`：`products` 259、`recipes` 2000、`ingredient_catalog` 52。
- 菜 fixture：101 道菜；`required` 唯一食材 55 个。
- demo fixture：39 个 demo SKU、9 个显式 placeholder。
- 运行库：`catalog_products` 296、`purchase_templates` 107、`offers` 296。
  **`purchase_templates = 107` 含非菜谱模板 —— 不要把 101 说成运行库总数。**
- 259 个源商品都写了 `image_file`，但逐行 `Path` 验证**只有 258 个路径存在**，缺 `BASE\data\images\0005256051595.jpg`。
  **不能用「285 张 jpg」当作图片齐备。**
- `python -X utf8 scripts/audit_catalog.py` 退出 0：259 / 隔离 2 / 259 image_file / 285 jpg / 9 demo baking。
  **它只是小审计，不代表任何一道菜配得齐。**
- `sqlite_compileoption_used('ENABLE_FTS5')` = 1（本机编译支持 FTS5）。**仍不代表中文分词可用** —— 本次不做 FTS。
````
