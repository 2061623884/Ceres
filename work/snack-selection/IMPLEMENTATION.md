# 零食固定案例交付记录

适用日期：2026-10-04（原始 trace 为 UTC 2026-10-03）。状态见 [TASK](../../tasks/snack-selection.md)，阶段目标见 [PROJECT](../../PROJECT.md)。

两项模拟供给已写入开发库。最终固定 API 案例按同一版本、独立 owner／会话重复两次通过；相关回归 80 通过、1 跳过。页面核对了确认前后结果，但途中曾超时后手动继续。全部失败保留，不将最终两个通过窗口扩大为响应长期稳定或整个阶段已验收。

## 数据与最小改动

旧库有 319 SKU；现有花生按烹饪用途归类且无零食标签，香蕉片来源记录缺销售规格、中文名／类目映射不能支持本例。保留旧行，补两项模拟销售包装：

| SKU | 商品与包装 | 模拟单价 | 模拟库存 |
| --- | --- | --- | --- |
| `demo:snack-original-potato-chips-70g-bag` | 原味薯片70克袋装 | 590 分 | 30 包 |
| `demo:snack-soda-crackers-100g-box` | 苏打饼干100克盒装 | 690 分 | 20 盒 |

商品为 source=demo、review_status=approved、category_id=snack，带“零食”及细类标签。Offer 属于 store-demo-01、sellable=true、is_demo=true。品牌为演示品牌，图片明确为 placeholder；ingredient_ids 为主料映射，过敏原状态仍 unknown，没有完整配方或过敏原筛选验收。

业务代码只增加现有类别名称表的一项 snack 中文／英文名。真实回放发现“好的”没有加购却回复“清单已确认”，随后一版 Prompt 出现 EMPTY_PROPOSAL；最终在既有确认规则与原 ACK 示例中明确：普通回应必须有非空回复，待确认清单表示“先保留，等明确确认后再加购”。没有新增路由、抽象、业务状态、校验、fallback、重试或异常捕获。

新 [回归文件](../../backend/tests/test_snack_selection.py)构建与临时测试库匹配的词法索引，刻意改变候选显示顺序，验证第一／第二项选购、有效 ACK、确认前零写入、确认后精确 SKU／数量／金额，以及待确认清单和非空购物车状态的无匹配保留。模型替身只用于离线业务断言。

## 窄导入与索引

[import_batch.py](import_batch.py)只追加上述两项，不全量 seed 开发库。[首导入](import-first.json)为 Catalog +2、Offer +2；[重复导入](import-repeat.json)为 +0／+0，不重写旧价格、库存或版本。

before/ 保存本轮开始时的 fixture、相关源码、PROJECT、静态表和 SQLite 在线备份；SQLite 备份只保留本地，未纳入 Git。[data-verification.json](data-verification.json)的 14 项检查通过：旧 319 商品、319 Offer、review、菜谱模板、门店和配送记录未变；fixture 旧对象逐项相同，只追加两项。新索引快照、426 文档哈希与 FTS token 和当前静态库 projection 相同，零食检索能命中两款新商品。

发布版本 idx-03d6c43d4eb25aff：105 菜谱、321 SKU、426 文档、0 向量。复用既有 --no-embed 构建，未增加 embedding 配置。[健康检查](health-final.json)仍为词法降级 VECTOR_INDEX_MISSING，不是完整 hybrid 检索已验收。

复现命令从 Ceres 根目录运行，沿用本地配置，不打印密钥：

```powershell
& backend/.venv/Scripts/python.exe -X utf8 work/snack-selection/import_batch.py
& backend/.venv/Scripts/python.exe -X utf8 scripts/build_retrieval_index.py --index-root data/retrieval_index-langgraph build --candidate-db data/runtime-langgraph/sale_guide.sqlite3 --no-embed
```

## 两次固定真实模型／API 回放

[replay_live.py](replay_live.py)访问实际 127.0.0.1:8012 服务和开发库，以独立 httpx cookie jar 建不同 owner/session。配置模型为 Qwen/Qwen3-VL-30B-A3B-Instruct，trace 为 live；没有 pytest provider 替换或自动重试。

固定输入和动作在执行前定义：来点零食 → 展示真实候选 → 就第一个 → 一盒苏打饼干清单／购物车空 → 好的（等待确认）→ 来点冰淇淋（无匹配，保留待确认清单）→ 明确调用页面确认按钮所用的 tasks/confirm 接口 → 再发来点冰淇淋（保留历史清单和已有购物车）。末轮可沿用刚查询过的历史事实，不强制重复检索。

| 步骤 | 第一次 | 第二次 |
| --- | ---: | ---: |
| 零食品类最终回复 | 6.855 秒 | 7.532 秒 |
| 选择与清单生成 | 3.054 秒 | 3.136 秒 |
| 普通 ACK | 2.476 秒 | 2.206 秒 |
| 待确认时无匹配 | 4.941 秒 | 5.357 秒 |
| 明确确认接口 | 0.018 秒 | 0.014 秒 |
| 已加购后无匹配 | 2.414 秒 | 2.569 秒 |

原始 [live-1.json](live-1.json)、[live-2.json](live-2.json)均 passed=true，owner/session/task 不同。确认前每轮 cart 与空基线一致，确认后仅一行苏打饼干 ×1、690 分。SSE accepted 在 2–5 ms，表示已接收请求，不能算最终答复或模型已理解。

live 记录 SSE、服务端会话、语义上下文、购物车和调用 trace；终态 API 不暴露 lookup.matches。真实无匹配证据为只读完成、空展示 refs、回复及持久化计划／购物车不变；精确查询 matches=[] 由离线索引回归断言。没有声称保存了 live 原始模型提案或完整查询结果。

## 保留的失败与边界

- [harness 尝试1](live-harness-attempt-1.json)：空候选时上下文省略该键，脚本直接读取导致 KeyError；业务未匹配回复及清单／购物车保持。只修正证据脚本。
- [harness 尝试2](live-harness-attempt-2.json)：ACK 真实回复“清单已确认”，购物车仍空；末轮沿用历史，脚本强制再次检索导致断言失败。改正脚本；ACK 措辞进入 Prompt 修复。
- [仅补否定规则的尝试](live-ack-before-example.json)：仍出现“清单已确认”，未算通过。[示例修改后尝试](live-empty-proposal-before-final-prompt.json)：ACK 为 EMPTY_PROPOSAL，保留清单／购物车。最终在原规则和示例正面明确必须有等待确认的非空 reply。
- [模型超时](live-model-timeout.json)：三次上游读取超时，约 45.3 秒，包含一次 API 尝试、一次页面初始需求及一次页面选择。全部未计为通过，没有新增自动重试。最终两次 API 无超时不代表这些失败被消除。
- 早期离线脚本误把 model candidates 当作带 sku_id 的事实、误把已有计划项 refs 当成查询新命中、把 ACK 写成无效 ack，均已修正；未用早期运行验收。最终回归使用合法 none 并断言该轮无失败。

本例按本次“展示匹配商品”授权列两款候选；PROJECT 的单款主推、推荐理由、饮品偏好和完整比较另待验证。两次真实模型正向选择均为苏打饼干；薯片选择及价格由离线回归覆盖，不能宣称两款的全部真实模型路径都通过。

## 页面与最终验证

页面 127.0.0.1:8443 核对零食品类及价格、两款候选、一盒 ¥6.90 的计划、确认前空购物车、点击确认和确认后购物车。选择曾超时，手动新发选择后完成，属于恢复后的页面验证。[ui-verification.json](ui-verification.json)将消息／trace 与 user_confirmed=1、正确购物车行对应。

截图：[候选](ui-candidates.png)、[待确认计划](ui-plan-before-confirm.png)、[确认前空购物车](ui-empty-cart-before-confirm.png)、[确认后购物车](ui-cart-confirmed.png)。失败截图：[初始需求超时](ui-timeout.png)、[选择超时](ui-selection-timeout.png)。

[最终相关回归](related-final.xml)：80 passed、1 skipped，73.59 秒。跳过为既有 test_confirm_respects_existing_cart_qty，原因 baking plan not ready；未计为通过。按 AGENTS 的小改动约定运行商品检索、读工具、RAG 契约、清单确认和新用例，没有恢复历史全量 A/B。Python 编译检查仅覆盖本轮文件。

[frozen-version.json](frozen-version.json)记录配置与源码／fixture SHA-256；最终回放后校验哈希不变。[current-task.diff](current-task.diff)只记录相对本轮初始本地快照的改动；[tested-working-tree.patch](tested-working-tree.patch)保存基于 28d796b 的被测既有未提交源码差异，含其他任务原有代码，仅用于版本证据。

复测固定两次 API 案例会为新匿名 owner 建会话／购物车；不重置供给或旧 owner 数据：

```powershell
& backend/.venv/Scripts/python.exe -X utf8 work/snack-selection/replay_live.py
& backend/.venv/Scripts/python.exe -X utf8 -m pytest backend/tests/test_catalog_search.py backend/tests/test_confirmation.py backend/tests/test_read_tools.py backend/tests/test_rag_read_contract.py backend/tests/test_snack_selection.py backend/tests/test_phase2b_chat_confirmation.py -q
```

审查：Standards 与 Spec 两轴最终均为 0 项新问题；已修正审查指出的早期无效 ACK 测试。SQLite 备份、运行索引及 PNG 截图保留本地；PNG 的 Git LFS filter 在本机触发 MSYS NtCreateDirectoryObject 错误，因此没有纳入本次提交，也没有修改 LFS 规则。
