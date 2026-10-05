# 05 真实采样捕获范围诊断

生成时间：2026-10-05 22:00 UTC。只读检查；未发起模型/API请求，未修改源码、测试、TASK、索引或原始采样回执。

## 结论

05 原版 `test_real_role_and_kev_sample` 的捕获钩子只替换 `httpx.Client.send`。本机后端虚拟环境安装的 OpenAI SDK 为 `openai 3.19.2`，其同步 HTTP 客户端使用独立的 `httpx2 2.13.1`，不是 `httpx 0.28.1` 的 `httpx.Client`。SDK 的调用落在 `httpx2.Client.send`，所以对 `httpx.Client.send` 的 monkeypatch 不会捕获 Mercury/Momo 的 SDK 请求。

因此，R03 与 H01 的既有回执中，`upstream` 只含 Kev 的 `http://127.0.0.1:18009/v1/systemone` 请求；没有 Momo 主模型的实际请求体和原始响应。尽管公开 API 返回了 Momo 文本，也不能据此证明记录了实际发送给 qwen 的 prompt、工具参数或模型响应，不能声称角色请求模型已全部捕获，也不能据这些回执比较 Momo prompt。保留原始回执和原分析，不重采、不补造。

## 证据路径

- 捕获器：`backend/tests/test_v3_live_sampling.py:8,32-52` 导入标准 `httpx`，保存并 monkeypatch `httpx.Client.send`。
- Momo 调用链：`backend/app/api/mercury.py:96-103` 创建 `OpenAIChatClient` 并调用 `run_mercury`；`Mercury/mercury/agent.py:59` 调用 `llm.chat`；`Mercury/mercury/llm.py:3,17-26` 通过 `openai.OpenAI(...).chat.completions.create(...)` 请求主模型。
- SDK 实际传输链：安装的 `openai/_base_client.py:37` 导入 `httpx2`；`:932` 的 `_DefaultHttpxClient` 继承 `httpx2.Client`，`:952` 的 `SyncHttpxClientWrapper` 继承该客户端；`:1061-1068` 的 `SyncAPIClient._send_request` 调用 `self._client.send(...)`。
- 当前运行时反射确认：`openai=3.19.2`、`httpx=0.28.1`、`httpx2=2.13.1`；`SyncHttpxClientWrapper` 的 MRO 包含 `httpx2.Client`，其 `send` 定义于 `httpx2._client`。`httpx2.Client.send is not httpx.Client.send`。
- 原始回执：`work/ceres-v3/05/evidence/20261006T054335257-4b3698ab82f34a9a9026c70781b92a3d/role-samples/R03.json` 与 `H01.json` 的 `upstream` 均仅有 Kev `systemone` 请求。两份回执各自保留，未改写。

## 修正边界

下一版采样捕获应覆盖实际使用的 OpenAI SDK 外部 HTTP 发送边界，并显式排除 Authorization 等凭据；应分别保存 Momo 请求体、响应状态/正文和耗时，再以一次定向采样验证 R03/H01 的捕获完整性。当前结论只解释既有证据为什么缺失，不证明此前未发生 Momo API 调用。

## 检查对象 SHA-256

```text
8807779441c0f47bd8d78824fc11d80979073ad7621834adb26120dd4398cdf8  backend/tests/test_v3_live_sampling.py
b626c62dc07b925665e6e7099d85e144d8930ae3d2a31e9b73c3379b167ceeba  Mercury/mercury/llm.py
c14a2ce94825009c86fc405f56881e8d6bf5c644d6205b0d5ce4bf80227a6e51  Mercury/mercury/agent.py
ddc3e575bbbfebc6cf990be1de3eed60b200d454b76d70001fb5d1f5cae7ab67  backend/app/api/mercury.py
683c30b6d70fbe4ed9756d4c4d1083176c34c56786d228c7cadc846fd329616e  backend/.venv/Lib/site-packages/openai/_base_client.py
59e6f4fb84db1305a836fdef234e86bad8664dac9fd717118a819a98b86aa66e  .../role-samples/R03.json
41b7a6abdb10c1d478d879b48dafac8378c7820d676502d27cfb5941326eac30  .../role-samples/H01.json
8aba1489617b1a01500e650e998fff175092b06e05777cab2772766e9ac74616  .../analysis.json
```
