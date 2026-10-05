# Ceres V2 本机候选与人工验收

此交付是现有 Ceres 工作树的候选，包含有效的继承源码；它不是干净 Git checkout，也未通过全部演示门槛。01–05、07–08 的技术结果见各 TASK。06 在两批真实样本中分别出现 18.109 秒、22.11 秒主回复，均超过 15 秒，因此 06 与 09 的最终验收保持阻塞。人工体验仍待用户本人确认。

## 固定输入与重建

当前候选的源码、测试、Prompt、fixture 图片和索引逐文件原始字节 SHA256 由 [source-inputs.json](../work/ceres-v2/09/source-inputs.json) 记录，外部 `source-inputs.zip` 的绝对位置及归档哈希也在该文件。归档不含 `.env`、密钥、运行库、虚拟环境或 node_modules；不要从当前 HEAD 单独重建并宣称是这份候选。

索引明确复用 V1 冻结的真实向量 `idx-d3e9873a747cb2d6`，包含 65 SKU、105 菜谱、170 文档及 1024 维 float32 向量。embedding 模型为 `Qwen/Qwen3-Embedding-0.6B`，revision 未指定；不宣称新建或锁定模型权重的 V2 索引。聊天与后台模型均为显式配置的 `qwen3.8-27b`；聊天服务与 embedding 服务是两个独立配置，不能互换。

先将归档解压到新的目录。Python 和 Node 的实际版本、依赖及冷启动回执由 [09 验证记录](../work/ceres-v2/09/validation.md) 提供；本轮验证复用 Python 3.12.10 的现有虚拟环境与 Node 24.14.0/npm 11.9.0 的现有依赖，未验证全新安装。前端 package-lock.json 提供安装输入，后端 pyproject.toml 描述依赖；pip freeze 因原虚拟环境的 editable 路径元数据错误失败，版本清单不能冒充完整安装锁。需要真实模型时在解压目录安全配置本机 `.env`，公开参数见 [无密钥配置](../work/ceres-v2/09/settings-sanitized.json)，凭据不进入报告。

在本机复用本轮已验证的解释器时，先设置路径、解压源码并复制安全的本机配置：

```powershell
$taskDemoRoot = 'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-demo'
$taskPython = 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\backend\.venv\Scripts\python.exe'
Expand-Archive -LiteralPath 'C:\Users\20616\Desktop\Agent\Agent产品\work\ceres-v2-release-e290536e49c64bc2a9ffde4352869893\source-inputs.zip' -DestinationPath $taskDemoRoot
Copy-Item -LiteralPath 'C:\Users\20616\Desktop\Agent\Agent产品\Ceres\.env' -Destination (Join-Path $taskDemoRoot '.env')
Set-Location -LiteralPath $taskDemoRoot
```

新环境安装的操作入口如下，**此安装路径本轮未验证**。安装后将 `$taskPython` 改为该新虚拟环境的绝对路径；依赖安装失败不能宣称重建通过。

```powershell
py -3.12 -m venv backend/.venv
& ./backend/.venv/Scripts/python.exe -m pip install -e './backend[dev]'
Push-Location frontend
npm ci
Pop-Location
```

在解压目录初始化**新的** SQLite 文件，不能指向已有 321 商品开发库。fixture-only 是 upsert，不负责把已有库缩减为 65 商品。

```powershell
$env:DATABASE_URL = 'sqlite:///data/runtime-v2-demo/run-1.sqlite3'
$env:BUSINESS_DATA_MODE = 'demo'
& $taskPython -X utf8 scripts/seed_runtime.py --fixture-only
$env:RETRIEVAL_MODE = 'hybrid'
$env:RETRIEVAL_INDEX_DIR = 'data/retrieval_index-v2-frozen'
& $taskPython -X utf8 scripts/build_retrieval_index.py --index-root data/retrieval_index-v2-frozen verify --version idx-d3e9873a747cb2d6
& $taskPython -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8012 --app-dir backend
```

另一个终端进入解压目录的 frontend，执行 `npm run dev -- --host 127.0.0.1 --port 8443`。现有 Vite 配置将 `/api` 和 `/media` 代理到 8012。运行前停用占用同端口的旧进程或为隔离环境单独配置代理，不能把测试写到正在使用的开发库。Node runner 方式加载现有 Vite 配置需要 `__dirname` shim，外部构建回执记录了具体调用方式；它是测试执行环境适配，不是项目源码修复。

新库预期 65 商品、65 Offer（56 显式、9 默认价格）、111 模板（105 菜谱、6 其他）。`seed_runtime` 初始化及 Mercury 会话创建应保留已有活动订单/政策，不运行旧 Mercury 破坏性 seed。所有价格、供给、结算、订单和售后均为模拟业务；没有支付或履约推进。

## 用户本人验收清单

每一行保持**待验收**。使用同版候选，独立新数据库和浏览器 owner 完整操作两次；第二次使用 run-2.sqlite3。记录开始/结束时间、每轮最终回复秒数、截图、实际清单/购物车/订单 ID 和不符结果。超时、错误、重新发送不算通过，不能用 API 或模型替身结果代替本人页面操作。

| 操作 | 期望 | 状态 |
| --- | --- | --- |
| 明确说“请记住，推荐时先说明理由”；新聊天查询记忆 | 明确保存内容可查，来源明确；当前需求仍优先 | 待验收 |
| 可可：“四个人自己做番茄炒蛋，预算50元” | 番茄需600g买两包500g，鸡蛋需6枚买一包；必需默认选中，pantry不选；总价23.40元 | 待验收 |
| 打开采购清单，取消番茄后重新选回 | 金额随选择为9.80元/23.40元，确认前购物车不变 | 待验收 |
| 明确确认加购 | 只加入当前所选商品，数量、金额与确认结果一致；不结算 | 待验收 |
| 新可可聊天查上次番茄炒蛋方案，再要求这次两人份 | 历史有真实方案来源；查询不加购；新方案重查供给，默认选择，人数及金额按本次 | 待验收 |
| 对新方案再次明确确认 | 新方案独立确认，购物车准确累计；旧方案不变 | 待验收 |
| 购物车独立模拟结算，刷新订单页 | 成交商品、数量、单价快照固定，购物车清空，同owner刷新仍可查 | 待验收 |
| 手动进入墨墨，订单胶囊或订单ID气泡选单，询问“这单买了什么？发货了吗？” | 只显示本人真实模拟订单；一次咨询一单；不申请售后，不承诺真实付款/备货 | 待验收 |
| 明确要求退款或退货 | 沿用既有资格；只针对当前选单；申请仅处理中，未签收的模拟订单不可退货 | 待验收 |
| 使用另一个浏览器owner查看订单/历史/记忆 | 看不到前一owner内容，不回退固定演示用户 | 待验收 |

人数、多菜共用食材、缺货适配、可乐比较等单票边界另见 TASK 中固定用例。此旅程与有限回归不代表全目录、多用户规模或长期 P95 已验证。提交本人验收结果后由任务主会话核对，未通过项目继续保持未通过。
