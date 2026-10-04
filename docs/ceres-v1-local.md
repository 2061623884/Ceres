# Ceres v1 本机重建

本轮交付的是任务 01 的供给与源码基线，尚未完成向量、15 秒回复或九类业务验收。范围与后续条件见 [v1 TASK](../tasks/ceres-v1.md)。原 321 商品开发库继续保留，下面命令只操作 `runtime-v1-fixture`。

## 固定源码与依赖

任务 01 提交包含 seed 入口、同仓 Mercury 导入路径、65 商品 fixture 和固定输入。既有未提交导购／界面实现单独保存在 [runtime-baseline.patch](../work/ceres-v1/01-fixture-baseline/runtime-baseline.patch)，对应 Git 基线 `956bd5148696217aab9d1cc16ed4e2cfcb518f63`；这些是原型基线，不是本轮新增功能或旧 TASK 验收。该补丁只覆盖既有 `backend/app`、`frontend/src` 修改，不含旧数据库、索引、测试产物或密钥。

前提是已安装 Git LFS。在**新检出的任务 01 源码**中应用一次补丁，并取得仓库已跟踪的图片；当前开发工作树已包含补丁，不重复应用。随后从项目根目录执行：

```powershell
git apply work/ceres-v1/01-fixture-baseline/runtime-baseline.patch
git lfs install --local
git lfs pull --include="data/images/**"
py -3.12 -m venv backend/.venv
& backend/.venv/Scripts/python.exe -m pip install -r work/ceres-v1/01-fixture-baseline/requirements-frozen.txt
Set-Location frontend
npm ci
Set-Location ..
```

验证环境为 Python 3.12.10、Node 24.14.0、npm 11.9.0；前端版本由已有 `package-lock.json` 固定，后端已安装版本见上述 requirements。上述 LFS 命令只取既有图片，不取来源数据库；新果汁使用占位图。源码文本／8 份 fixture 的 hash 见 [固定输入](../work/ceres-v1/01-fixture-baseline/frozen-inputs.json)，文本 hash 统一把 CRLF 归一为 LF。

## 从 fixture 重建

在项目根目录的新 PowerShell 进程设置现有配置，再执行现有 seed：

```powershell
$env:DATABASE_URL = 'sqlite:///data/runtime-v1-fixture/sale_guide.sqlite3'
$env:BUSINESS_DATA_MODE = 'demo'
& backend/.venv/Scripts/python.exe -X utf8 scripts/seed_runtime.py --fixture-only
```

此入口跳过来源库导入，不需要 `data/sale_guide.db` 或原始大数据文件。首次重建使用空库；seed 保留既有 upsert 行为，不负责把包含来源商品的旧库缩减为 65 件。预期为 `source=0, demo=65, dishes=105, approved_total=65`，实际库有 65 商品、65 Offer、111 购买模板，投影有 170 文档。

56 条 Offer 来自显式 fixture，另 9 条由 `default-offer-prices.json` 的既有规则生成。价格、库存及配送全部为模拟；新美汁源桃汁饮料为 450ml 单瓶，模拟价格 450 分、库存 30 瓶，商品与甜味来源见 [供给资料](../work/ceres-v1/01-fixture-baseline/SUPPLY.md)。

## 启动与后续向量

任务 01 的初始化检查尚未部署索引，故健康页的检索状态应为 `RETRIEVAL_NOT_CONFIGURED`；这不是 v1 检索验收通过。实际向量由 02 在同一供给上构建，不能指向旧 321 商品索引。02 使用既有 `.env` embedding 配置和以下独立输入：

```powershell
& backend/.venv/Scripts/python.exe -X utf8 scripts/build_retrieval_index.py --index-root data/retrieval_index-v1-fixture build --candidate-db data/runtime-v1-fixture/sale_guide.sqlite3 --env-file .env
$env:RETRIEVAL_INDEX_DIR = 'data/retrieval_index-v1-fixture'
$env:RETRIEVAL_MODE = 'hybrid'
```

上述构建命令留给任务 02，本轮没有执行。当前模型、embedding 和不含凭据的服务地址见 [配置记录](../work/ceres-v1/01-fixture-baseline/settings-sanitized.json)。聊天及 embedding 凭据仅在本机 `.env` 配置，不随供给或源码交付；不能把向量模型配置当作实际向量成功。

后端进程也须先设置同一 `DATABASE_URL`、检索目录及模式，随后按 [README](../README.md) 的端口 8012 启动；前端仍用 8443 代理。切换演示进程时先停止对应旧服务，避免端口冲突，保留旧开发库。任务 01 在隔离源码中验证健康、bootstrap、商品事实及空购物车；真实页面业务和模型调用由后续任务验收。
