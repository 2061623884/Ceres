# 09 集成与真实回复诊断

首次已实现业务旅程2pass/exit0；没有人为制造RED。模型替身只在外部边界，lexical索引不冒充真实向量。

最终候选06复核仅一次8项：7pass/1fail，temporary-2=22.11秒；且用户说今天不采购，系统却问清单focus。旧18.109秒失败保留。只读Trace唯一主provider=22015ms，后台在turn_result后7.555ms启动，不能归因于后台。原提案未保存在该Trace，不能断言模型原始字段或运行时误判的具体根因。

已核静态路径：focus问题是既有goal_router标准澄清；Prompt列出人数/预算constraints，但未明确不采购的临时讨论不应触发改单。本次仅补充这条语义指令，真实验收增加无业务动作断言，不加关键词规则、运行时兜底/重试或新状态。旧真实错误作为行为RED证据；此改动是否有效待一个新候选真实批次，仍不宣称速度修复。若仍失败，停止相同源码采样并记录外部/未知阻塞。

冷重建RED：首包410文件两份hash核对通过，但seed因缺scripts.import_db实际exit1。仅将现有直接依赖加入冻结入口，不改seed或在clone临时补文件。新增Prompt亦收窄到没有改单/放弃要求的临时讨论，保留原有明确放弃边界。重新冻结后验证，旧包/失败保留。

411文件候选的两份冷seed/index及161+61离线回归通过，但tsc exit2、build exit1：vite.config.ts静态导入frontend/.figma/make/site.json，归档未包含。该298字节原文件只有公开站点描述、robots和accessibility设置；仅把原文件纳入冻结入口，不修改构建代码或临时注入clone。412文件包重新核查并补前端验证；哈希相同的后端回归明确复用。测试Agent报告原node_modules/.vite-temp执行前后已存在，未清理，不宣称目录由本轮创建或已移除。

语义指令后的真实06正式8项为6pass/2fail；临时讨论两次无focus/action且未存长期，2.265/2.172秒。stable-1=22.391秒、conflict-2=16.468秒，mode=ro/query_only Trace各一次主调用22281/16359ms，后台主完成后13/9ms才启。没有usage/finish_reason，不将其归因到思考模式、队列或网络某一环节；没有有据的新增本地速度修复。后台此前enable_thinking顶层与chat_template_kwargs均仍返回reasoning_tokens，不能将未核实参数复制给主模型冒充关闭思考。公开[官方使用入口](https://discovery.intern-ai.org.cn/token-plan/home)确认OpenAI协议地址；本轮未找到该qwen模型思考开关的可核文档，不把另一Intern模型的参数当作支持。用户已决定保留qwen3.8、速度留待工程讨论，停止新增模型采样，其他不受影响工作继续。

状态断言修复后旅程1pass/1fail；run2 history读到真实源但16.953秒，Trace两个主调用：理解1390ms，history读取，解释15452ms，repair=false。turn_result后8.5ms启动后台；只读观察时尚无completed，不凭此称成功或失败。完整回答正确，耗时门槛失败。用户已决定不再换模型/增加采样；不把额外解释调用当重试，不为该样本增加历史回复特例或兜底。

首次live旅程两参数均生成真实待确认方案、正确默认勾选与23.40元；新脚本误要求accepted而停止，未执行后续业务。response_contract.py:158–173规定有task回复保留业务step，accepted用于taskless。仅修正first/rebuilt两断言为awaiting_confirmation，其余保存/历史读断言仍accepted。新包相对已验证包只有本测试与PROJECT文档变化，生产无改；只复验修正旅程，不重发06。旧失败不算旅程完成。

页面反馈循环：CUA无可用browser surface，改用本机已有Playwright 1.62.1和系统Chrome，未安装或下载浏览器。首次启动在系统TEMP的mkdtemp报EPERM，exit1、0业务请求；仅将TEMP/TMP指向隔离外部目录。首个实际DOM批次两例都完成680分番茄显式加购，在“问问可可”定位停止；App.tsx:87的Avatar SVG aria-label参与按钮名称，exact:true错误。仅修正可可/墨墨名称为包含匹配，生产不变。下一批两例都生成真实680分模拟订单并清车，但h2包含DemoBadge的“演示”文本，精确“我的订单”定位再次错误；仅改为按heading名称匹配。两版旧场景及各批失败截图/结果保留，新BrowserContext/owner定向复验，不清旧owner、cart或订单，不发真实模型请求。它们是场景定位失败，不作为业务代码故障或通过样本；最终结果另见validation。
