# 05 Standards Review

固定点：HEAD `5462e999d583a9bab6147d0b4141d98321f3cc92`，提交清单为空；仅审阅 `review-v2/source.patch` 的 11 个 owned paths（3 个产品文件对 original working ZIP `e91bbd5...`，8 个新文件对空）。scope 中 11 个源摘要与工作区匹配。未使用 `git diff HEAD` 归因继承 V2。

## 发现

1. **硬性证据完整性问题** — `backend/tests/test_v3_live_routing.py:41-46,67-75` 捕获器把请求和网络异常暂存在 `upstream`；`send()` 抛错时会在写 `results.json` 前退出。`backend/tests/test_v3_live_sampling.py:67-70,120-125` 也在 `send()` 返回并构造 `row` 后才进入写回的 `try/finally`，故请求失败时没有逐例 receipt。与 `work/ceres-v3/05/evaluation-protocol.md:9,18` 的“保存所有失败/原始记录”要求冲突；不是测试 seam 问题。失败应在重抛前持久化原始请求和错误。

2. **依赖兼容问题** — `backend/tests/test_v3_live_sampling.py:10` 在模块导入时无条件导入 `DefaultHttpxClient`，而 `backend/pyproject.toml:20` 仍允许 `openai==1.12.0`；该版本的公开 `openai/__init__.py` 未导出此符号（[OpenAI Python v1.12.0](https://raw.githubusercontent.com/openai/openai-python/v1.12.0/src/openai/__init__.py)）。因此最低受支持版本下，即使 opt-in 测试应跳过，pytest 收集也会 ImportError。当前 venv 的 OpenAI 3.19.2 确实公开导出该类，基类为 SDK 自带的 `httpx2.Client`；无新增 `httpx2` 直接依赖，但不消除声明下界不兼容。

## 已核对

三个产品增量只把外部协议 `target.quantity` 经 `_count` 写入 `Goal.quantity`，再仅对 product candidate 编译成 set 数量；未在内部重复校验。核心及真实采样测试通过公共 API/SSE，HTTP 与 SDK 公共发送边界受控；未见测试直接调用私有生产实现。`analyze-evidence.py` 遍历实际 JSON receipts，包含 R01，不再硬编码 4 条样本。其余新增文件未见有依据的代码气味；**启发式气味：0**。
