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
| b33385addd2d43fa968bf544f9708b11 | 59pass / exit0 | 审查前受控相关回归，含全部22项06、12项05、18项stream/取消/修订、2项Prompt例子、5项provider错误 |
| a8c2d93a6e4947b1b06380ad16f392b0 | 2fail/2teardown error / exit1 | 审查外壳红测：空choices未记后台失败，worker抛IndexError |
| fc958213e4524738a1b1a75bfb1a1f72 | 67pass / exit0 | 审查修复后最终相关集：原59项及四种外壳各两次；06共30项 |

最终相关命令：
```text
python -X utf8 -m pytest -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning tests/test_v2_automatic_memory.py tests/test_v2_explicit_memory.py tests/test_phase2a_cancellation.py tests/test_reply_stream.py tests/test_turn_progress.py tests/test_revision_confirmation.py tests/test_live_retrieval_wiring.py::test_purchase_examples_declare_intent_and_lookup_in_the_same_pass tests/test_live_retrieval_wiring.py::test_supply_gap_opt_in_example_reuses_pending_real_dish_and_question tests/test_live_provider_errors.py --basetemp <external-run>/pytest-tmp
```
起止UTC2026-10-05T09:30:05.6630601Z–09:31:03.8295197Z；MEMORY_MODEL为空、检索索引为空、无live opt-in；pytest55.76s。仅保留已有template_matcher.py:21的SyntaxWarning，不顺手修改。

审查修复后使用同一集合与外置新run环境，LLM_MODEL与MEMORY_MODEL均为空，无live opt-in，UTC10:00:18.484–10:01:21.695、pytest60.78s、67pass/exit0。command-argv.json保留实际参数，command/environment/timing/exit原始文件见对应test-receipts。源注释的普通数值曾被tester宽泛TOKEN扫描误报成凭据，主Agent与tester用精确OPENAI_API_KEY均核查原日志无实际key/Bearer；纠正记录保留，不改红测业务结论。

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

这批真实采样对应ab77e63及ticket-delta.patch的实际源码版本；之后审查修复仅改变错误响应的转换与其验证，未更改正常文本响应的Prompt或后台业务流程。没有为新的provider哈希再重发真实批次，不宣称最终同版八项全绿。

失败样本的只读SQL时间线见该run下`latency-trace-readonly.txt`，命令、`mode=ro/query_only=ON`和实际退出码0均保留，没有新增模型请求。该request只有一组主`model_call_started/completed`，stage=understanding、call_number=1：事件间18.016319秒，存储duration_ms=18000。其后23.936ms记录turn_result，再后9.290ms才memory_extract_started；后台4.668181秒另行完成。这支持耗时集中在一次主provider.propose调用，不支持后台提取导致18秒等待；Trace无法进一步区分纯网络与provider本地/模型处理耗时，也没有精确的SSE客户端返回时间戳。不凭此猜测远端排队，不用更短超时冒充成功回复。当前速度门槛仍未通过。

## 全套结果与归因边界

cba8cb5e8e2d463b847583d51899ecd3：后台全套完整退出1，856pass/20fail/21error/47skip，09:01:15.1204295Z–09:21:56.8004918Z UTC，pytest1229.81s。该检查在后续Prompt与后台输出额度/TTL修复前，不能当作最终同版全绿。命令为上述pytest公共参数加tests，外置basetemp。虽关闭新增live opt-in及MEMORY_MODEL，旧test_live_model_unwanted_with_clear_plan_is_a_located_remove仍以配置可用为条件自行调用真实主模型，因此这批并非完全离线。

5870630ffb9d44ee87b3275028c53b3a：run_pre06_regressions.py加载本票before的config、Prompt、stream源，在独立进程内存注入，不改活动源码；20个失败nodeids复测，19fail/1pass、exit1，09:28:17.4575174Z–09:29:00.1858057Z UTC。19项相同首个症状在06前仍存在，不扩范围修复；原始双日志保留。唯一差异是上述旧真实模型移除样本，两次外部采样一败一成，从未调用后台记忆/读取memory_model，不能据此归因为06代码回归。不再重发该旧样本，不恢复历史语义A/B。

21个RAG setup error均需要只读verification/data-completion/candidate_runtime.sqlite3，当前文件无法打开；不伪造快照替代。全套仍未通过，这些记录供后续工程讨论。审查修复后的最终67项相关定向验证与真实模型样本、用户页面体验分别报告。

原始日志及直接退出码的可提交副本见test-receipts/，原始外部位置映射见receipts.json。全套日志已以实际配置key和Bearer模式检查，均未匹配；只提交无凭据证据。

[执行索引](execution-index.md)汇总33个既有run及其实际留存的命令、环境、时间和退出文件；未留存字段明确标“未记录”，没有从文件时间或日志猜补。部分早期元数据不完整，因此不宣称所有历史实验都能独立复现。关键正式真实采样、最终受控GREEN、外壳RED、全套和06前对照的已留存元数据另复制到各test-receipts目录。索引链接保留本机外部原始位置，09干净源码/数据完整冻结未启动。

## 用户恢复后的09候选复核

用户已恢复原计划。live-memory-final-59d75e570d3b43cf92879a50ce5c32b8仅一次正式8项，UTC12:48:31.863–12:50:06.274，7pass/1fail、exit1。稳定3.172/5.860秒，临时3.547/22.110秒，冲突3.469/2.797秒；Dream后台10.391/14.438秒。temporary-2无采购需求却询问清单focus，不能只凭记忆不提取断言当作语义通过。只读Trace唯一主provider22015ms，后台在turn_result后7.555ms启动；原提案未留存，不能推测其字段。environment-correction.txt纠正原记录器错误的backend/.env路径，实际Settings使用项目根.env；原文件未覆盖。

09补充临时讨论且不采购/不改单/不放弃时省略业务字段的Prompt指令，live用例增加无业务动作断言。旧失败记录保留，新源码仅允许一次正式复验；真实结果见[09验证](../09/validation.md)，未执行或未过门槛时仍阻塞。

语义修复后正式有效批次09-final-candidate-83f1c39408e649a495c633c23a4bbe4c：UTC13:55:34.174–13:57:18.800、8项6pass/2fail、exit1，pytest102.89秒。stable-1=22.391、stable-2=3.703；temporary=2.265/2.172；explicit-conflict=3.047/16.468；两Dream完成且保留explicit/清过期。主回复均accepted、无actions，临时条件未存。两超15秒失败分别保留，不刷样本。前一basetemp父目录未建导致8setup ERROR，零用例/模型请求；补外部环境后这批才是有效采样，不将setup错误当模型重试。

只读Trace各一次主call22281/16359ms；后台turn_result后13/9ms启，约3.187/5.731秒，不拖主回复。usage/finish_reason未留存。conflict-2只说“这次”理解当前陈述，未宣称更新长期记忆，existing explicit未变。生产不因09旅程状态断言修正而改变，06此批按相同生产哈希复用，不在新的测试归档上重发。原始完整回执见09/test-receipts及外部UUID run。
