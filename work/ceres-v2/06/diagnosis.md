# 06 实际模型与并发边界诊断

全部执行与探测由专职测试 Agent 完成。根 Agent 读取原始日志并决定修复；模型凭据不入证据。

1. 普通回复后的后台提取尚未实现：初始2项RED确认未启动后台工作，按现有SSE worker的终止队列信号后用独立事务提取，2项GREEN。
2. 请求重放：模型等待期间重放同request曾再次调用模型，2项RED。用现有Trace持久化提取开始，已开始/已完成/已失败均不自动重新执行，14项GREEN。
3. 手动纠正与旧ORM值：通过真实另一个SQLite Session在外部模型调用期间把automatic改为explicit，extract两项重置了其有效期，Dream两项未阻止删除。4项RED后，在模型返回后expire_all并读取当前有效记录，4项GREEN。没有增加第二套业务状态。
4. 模型JSON缺少必填输出：返回{}的两个RED未抛错，曾被当成空记忆成功。memories改为schema必填，既有ValueError转换保留具体原因，相关集合中两项通过。
5. 新服务正式8项初测：4pass/4fail；普通长期偏好一次被实际保存成explicit，冲突偏好一次实际update旧explicit；从失败临时数据库的只读receipt与GuideMessage确认。不能把这些行为归为测试断言或解析默认值。Prompt已明确普通偏好陈述不构成显式管理请求并补正反例；同一消息正式复验六次主回复均未产生同步memory动作，自动保存与显式冲突保护均符合观测。
6. Dream两次输出截断：1536输出额度下最终JSON未产生。单变量thinking字段位置A/B均finish_reason=length，reasoning_tokens=1536、content长度0、reasoning_content长度3322；A10.734s/B10.172s。字段位置不是本次有效修复，不据官方示例猜测该服务必然支持关闭推理。[Qwen官方示例](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md)提供候选参数来源，结论以实际服务返回为准。只改变后台输出额度为4096后finish=stop，completion=1927/reasoning=1542，11.328s返回完整JSON并解析；同一10条自动/1条显式输入，drop_refs仅一个重复自动ID。这是容量诊断，不冒充正式两次采样，不影响主回复额度。
7. Dream原样回显会续期：真实4096诊断返回原有效内容，公共Dream测试把一个自动条目设置为5天后过期并让模型回显。两个RED实际把期限刷新成30天。共享保存逻辑现在由extract明确允许续期、Dream明确不续期已有相同内容，新整理内容仍保存；不新增持久状态。正式复验另见validation。

取消回归中旧测试记录器先缺plan_selection，再缺explicit_confirmation；仅按实际调用签名补齐，生产取消逻辑不改，最终定向1pass。每次失败原样保留，不将失败重发为成功。

复验8项7pass/1fail：显式冲突第1次主回复18.109秒，超出15秒；其记忆提取正常、显式偏好仍保留，另一次同消息2.875秒。后台Dream两次均通过。耗时定位假设依次为主模型调用变慢、额外模型调用、后台拖住主回复。只读失败Trace证实只有一次主provider调用，耗时18.016319秒；turn_result后才启动4.668181秒的后台提取。不支持额外调用或后台导致此等待，纯网络/模型处理时间仍未知。没有有据的06业务修复，不新增重试、降低门槛或反复重发；将速度失败保留为验收阻塞。原始结果与限制见validation.md。

双轴审查发现HTTP200响应外壳的错误记录缺口。公开聊天的empty-choices两次RED都缺failure Trace并抛IndexError，pytest2fail/2teardown error、exit1。provider现在仅将具体响应访问/类型/解析错误转成INVALID_MEMORY_OUTPUT并保留cause；非文本内容明确拒绝，截断继续单独报告，不扩大service捕获范围。四种外壳各两次及全部相关集合67pass/exit0，未更改正常模型文本响应业务。速度失败依然保留，没有再次请求真实模型。
