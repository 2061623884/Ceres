# 06 验证记录

全部命令由专职测试 Agent 执行，主 Agent读取原始结果并修复。cwd为Ceres/backend，解释器为backend/.venv/Scripts/python.exe（Python3.12.10）。数据写入仅外部UUID run目录的SQLite、Mercury及pytest basetemp；关闭pytest cache/pyc，开启UTF8，PytestUnhandledThreadExceptionWarning视为error。正式用例分别两次独立owner/数据库，不将失败重发算作通过。

## 红绿与相关回归

| 回执run ID | 实测 | 说明 |
| --- | --- | --- |
| ce93b2a50de24a1686d0bb057878ab50 | 2fail / exit1 | 普通回复后未启动后台提取 |
| 8b51572eec8e4f5095d485a13122ada5 | 2pass / exit0 | 后台阻塞时主回复已完成 |
| 66f05db3604a491b9932071c3664713b | 2fail / exit1 | 请求重放再调用模型 |
| 04c2e47a98a945af973e3ee4b240bf6b | 14pass / exit0 | 阈值/间隔/清过期/ownership/失败记录 |
| 1c449cff76124c5691ddb56f543f6cf1 | 4fail / exit1 | 用户纠正期间旧值使explicit过期或被删 |
| 6ce5044cc64c4d40b738c2ef07660e49 | 4pass / exit0 | 模型返回后重查当前内容，保护explicit |
| d83e5663921c47dbbc30e134e060e7d1 | 2fail / exit1 | 缺memories字段被当作空成功 |
| 6ee041d1d56a463cbcbf512f6c2e9946 | 51pass/1fail / exit1 | 52项相关集合，取消测试替身缺现有参数 |
| 06a8b55e0f9d41179c37c559bb316acc | 1fail / exit1 | 首次修正仍遗漏explicit_confirmation |
| 5bb72886b6fc4f58a4a4b11e9bc18c4a | 1pass / exit0 | 按实际两关键字参数转交，生产取消逻辑未改 |
| 886827bec14f4e52a929009bdc3e75c8 | 2fail / exit1 | Dream原样回显把5天期限变成30天 |
| b33385addd2d43fa968bf544f9708b11 | 59pass / exit0 | 最终受控相关回归，含全部22项06、12项05、18项stream/取消/修订、2项Prompt例子、5项provider错误 |

最终相关命令：
```text
python -X utf8 -m pytest -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning tests/test_v2_automatic_memory.py tests/test_v2_explicit_memory.py tests/test_phase2a_cancellation.py tests/test_reply_stream.py tests/test_turn_progress.py tests/test_revision_confirmation.py tests/test_live_retrieval_wiring.py::test_purchase_examples_declare_intent_and_lookup_in_the_same_pass tests/test_live_retrieval_wiring.py::test_supply_gap_opt_in_example_reuses_pending_real_dish_and_question tests/test_live_provider_errors.py --basetemp <external-run>/pytest-tmp
```
起止UTC2026-10-05T09:30:05.6630601Z–09:31:03.8295197Z；MEMORY_MODEL为空、检索索引为空、无live opt-in；pytest55.76s。仅保留已有template_matcher.py:21的SyntaxWarning，不顺手修改。

## 真实模型

新进程读取用户指定.env：OPENAI_BASE_URL=https://discovery-api.intern-ai.org.cn/v1，LLM_MODEL与MEMORY_MODEL均qwen3.8-27b。凭据仅本机.env，不提交；没有轻量化或对主模型性能提升的证明。

- 3ebdf4747e474beeb46e687125f71f39：/models HTTP200精确匹配；稳定偏好6.809s提取成功、临时人数预算1.909s返回空memories。各一预检，不冒充正式两次采样。
- 7a3a218b27bf4faca23759eb319128f3：正式8项初测4pass/4fail、exit1。两个主模型显式memory动作不应发生；两个Dream因finish_reason=length截断。错误原样保留。
- 6b96350ffc80443db5302bca69bad648：thinking字段位置A/B都截断，reasoning耗尽1536输出额度、JSON为空；wrapper exit0仅表示诊断完成。
- 606f34283a0a48df988be4e449d5a4ee：只加大后台额度至4096，11.328s、finish=stop、completion1927，解析成功并仅去掉重复automatic；单次容量诊断，正式复验另记。

正式复验使用test_v2_automatic_memory_live.py，CERES_LIVE_MEMORY_ACCEPTANCE=1、LLM_MODE=live，移除LLM/MEMORY/base/key环境覆盖以读取.env；其他数据库/供给/索引仍隔离。稳定/临时/冲突三类普通回复与实际后台保存，以及真实Dream，分别两次。主回复门槛<=15s，Dream后台时长另记。

07865cc22bb0476d915f9db59f79acd1：UTC09:34:27.358–09:35:55.197，实际exit1，7pass/1fail、pytest86.09s。以下为同版正式结果，失败未重发；不能声明八项全通过。

| 案例 | 两次实际主回复秒数 | 结果 |
| --- | --- | --- |
| 稳定长期偏好 | 2.750 / 2.359 | 均写入automatic并设30天有效期，没有同步memory动作 |
| 今天人数/预算 | 2.219 / 4.000 | 均未保存记忆；第二次主回复问了不必要的清单目标问题，仅满足本票临时条件不提取断言，不作为购物语义验收 |
| 与原显式偏好冲突 | 18.109 / 2.875 | 均保留原explicit且不自动到期，没有同步memory动作；第一次超过15秒，未通过 |
| Dream | 后台10.516 / 13.172 | 均去重并清理自有过期自动内容，保留显式内容、间隔门控通过 |

实跑命令为上述公共pytest参数加`-s tests/test_v2_automatic_memory_live.py`及外置basetemp。记忆业务行为在这批均符合观测，但主回复速度门槛未全通过；失败Trace继续只读定位，不通过重发或放宽门槛抹掉此记录。

## 全套结果与归因边界

cba8cb5e8e2d463b847583d51899ecd3：后台全套完整退出1，856pass/20fail/21error/47skip，09:01:15.1204295Z–09:21:56.8004918Z UTC，pytest1229.81s。该检查在后续Prompt与后台输出额度/TTL修复前，不能当作最终同版全绿。命令为上述pytest公共参数加tests，外置basetemp。虽关闭新增live opt-in及MEMORY_MODEL，旧test_live_model_unwanted_with_clear_plan_is_a_located_remove仍以配置可用为条件自行调用真实主模型，因此这批并非完全离线。

5870630ffb9d44ee87b3275028c53b3a：run_pre06_regressions.py加载本票before的config、Prompt、stream源，在独立进程内存注入，不改活动源码；20个失败nodeids复测，19fail/1pass、exit1，09:28:17.4575174Z–09:29:00.1858057Z UTC。19项相同首个症状在06前仍存在，不扩范围修复；原始双日志保留。唯一差异是上述旧真实模型移除样本，两次外部采样一败一成，从未调用后台记忆/读取memory_model，不能据此归因为06代码回归。不再重发该旧样本，不恢复历史语义A/B。

21个RAG setup error均需要只读verification/data-completion/candidate_runtime.sqlite3，当前文件无法打开；不伪造快照替代。全套仍未通过，这些记录供后续工程讨论。本票59项定向验证与真实模型样本、用户页面体验分别报告。

原始日志及直接退出码的可提交副本见test-receipts/，原始外部位置映射见receipts.json。全套日志已以实际配置key和Bearer模式检查，均未匹配；只提交无凭据证据。
