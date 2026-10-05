# 09 集成与真实回复诊断

首次已实现业务旅程2pass/exit0；没有人为制造RED。模型替身只在外部边界，lexical索引不冒充真实向量。

最终候选06复核仅一次8项：7pass/1fail，temporary-2=22.11秒；且用户说今天不采购，系统却问清单focus。旧18.109秒失败保留。只读Trace唯一主provider=22015ms，后台在turn_result后7.555ms启动，不能归因于后台。原提案未保存在该Trace，不能断言模型原始字段或运行时误判的具体根因。

已核静态路径：focus问题是既有goal_router标准澄清；Prompt列出人数/预算constraints，但未明确不采购的临时讨论不应触发改单。本次仅补充这条语义指令，真实验收增加无业务动作断言，不加关键词规则、运行时兜底/重试或新状态。旧真实错误作为行为RED证据；此改动是否有效待一个新候选真实批次，仍不宣称速度修复。若仍失败，停止相同源码采样并记录外部/未知阻塞。

冷重建RED：首包410文件两份hash核对通过，但seed因缺scripts.import_db实际exit1。仅将现有直接依赖加入冻结入口，不改seed或在clone临时补文件。新增Prompt亦收窄到没有改单/放弃要求的临时讨论，保留原有明确放弃边界。重新冻结后验证，旧包/失败保留。

411文件候选的两份冷seed/index及161+61离线回归通过，但tsc exit2、build exit1：vite.config.ts静态导入frontend/.figma/make/site.json，归档未包含。该298字节原文件只有公开站点描述、robots和accessibility设置；仅把原文件纳入冻结入口，不修改构建代码或临时注入clone。412文件包重新核查并补前端验证；哈希相同的后端回归明确复用。测试Agent报告原node_modules/.vite-temp执行前后已存在，未清理，不宣称目录由本轮创建或已移除。
