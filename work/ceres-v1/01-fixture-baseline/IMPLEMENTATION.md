# Ceres v1 01 交付与验证

日期：2026-10-04。范围为供给／源码基线与独立重建，不含向量构建、实际模型或九类页面验收。当前状态以 [TASK 01](../../../tasks/ceres-v1-01-fixture-baseline.md) 为准。

## 最小实现

1. 在现有 seed 加 `--fixture-only`，只跳过 `seed_from_source`；默认 CLI 及 `main()` 保持原导入行为。新增进程级回归以独立临时来源 SKU 和运行库验证这一区别。
2. 原 64 fixture 上新增一个有官方资料的 450ml 美汁源桃汁饮料，写明确模拟 Offer；其果汁和甜味资料复用当前 usage_tags／名称进入投影。完整资料边界见 [SUPPLY](SUPPLY.md)。
3. 修正 Mercury 导入路径从父目录改为 Ceres 同仓目录。原路径依赖相邻项目，在独立目录只导入该路径会得到 `ModuleNotFoundError`；冻结源码启动后断言实际 mercury 模块来自隔离检出目录。没有修改 Mercury 业务、订单或启动流程。
4. 既有未提交导购／界面代码保存在 [runtime-baseline.patch](runtime-baseline.patch)，基础 Git 版本与 137 份运行文本 hash 见 [frozen-inputs](frozen-inputs.json)。它是已存在的原型覆盖，不是本轮重新实现或验收历史语义。8 份冻结 fixture、实际依赖版本及执行脚本均留在本目录，密钥和运行库不提交。

## 已完成验证

- 最终 `test_seed_runtime_cli.py` 与 `test_seed_images.py`：7 passed。新增 CLI 用例原实现为默认模式通过、fixture-only 失败，修改后均通过。
- 两个独立源码重建：Git 基线 → 原型补丁 → 本轮 seed／导入路径与冻结 fixture，137 份运行文本 hash 一致；各使用全新独立 SQLite，source=0、65 商品／65 Offer、105 菜谱／111 模板、170 投影文档。健康、bootstrap、新商品规格／价格／库存／未知过敏原及空购物车核对通过。同仓 Mercury 路径核对通过。
- 两份商品、Offer 和投影的逻辑指纹均为 `538bf9d280861afd0934f04eb995bf2638f2ab9b704bf80556730dc407538e48`；原始记录见 [cold-start-1](cold-start-1.json)、[cold-start-2](cold-start-2.json)。独立数据随后复制到 `data/runtime-v1-fixture/sale_guide.sqlite3`，65 商品／65 Offer；旧开发库只读查询仍为 321 商品，旧索引未改。
- 前端 `npx tsc --noEmit` 与 `npm run build` 通过；这是原型源码基线的编译检查，不是页面业务验收。

验证命令：

```powershell
& backend/.venv/Scripts/python.exe -X utf8 -m pytest backend/tests/test_seed_runtime_cli.py backend/tests/test_seed_images.py -q
& backend/.venv/Scripts/python.exe -X utf8 work/ceres-v1/01-fixture-baseline/freeze_inputs.py
& backend/.venv/Scripts/python.exe -X utf8 work/ceres-v1/01-fixture-baseline/verify_cold_start.py
```

冻结脚本记录的是执行时固定版本；不为重跑随意覆盖本次证据。重建脚本的独立目录必须为空，失败会直接退出；没有重试、兜底或宽泛异常捕获。当前开发工作树已含原型补丁，用户重建入口见 [本机说明](../../../docs/ceres-v1-local.md)。

## 保留的失败与限制

- seed 子任务额外执行 `test_s1_data_completion.py`，9 passed／1 failed：既有菜谱用例硬编码 `demo:cola-330ml`，当前 64 fixture 的可用匹配返回 `demo:cn-pepsi-original-330ml-can`。本轮改动前 fixture 已包含这一商品扩充；本轮不修改该用例、菜谱或商品匹配规则，不把它报成通过。
- 第一次源码 archive 被 Git LFS 的 MSYS shell 权限错误中断，冷启动尚未开始。验证脚本随后明确取 Git blob 源码并从既有 fixture 图片取得所需资产，没有下载或忽略图片校验。一次补丁应用在仓库子目录被 Git 的路径前缀规则跳过，源码 hash 核对失败；原目录保留为 `source-apply-failed-before-verification/`，原开发源码 hash 确认未改变。修正验证命令的目标目录后才执行正式两次；这些准备失败不作为冷启动成功。
- 未执行 embedding／聊天 API，未构建向量，未采样模型，未切换现有演示服务，未恢复旧全量语义 A/B。健康中的 `RETRIEVAL_NOT_CONFIGURED` 明确表示 02 尚未部署，不能当向量成功。
- 两次冷启动只证明此固定输入与环境的重建一致，不证明所有菜谱可买齐、真实图片页面、15 秒回复或长期可靠性。
