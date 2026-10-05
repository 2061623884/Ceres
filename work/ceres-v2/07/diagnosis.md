# 07 复现与定位

全部测试/只读数据探测由专职 tester 执行，主 Agent 阅读 stdout 和隔离数据库回执；未运行真实模型。

首 RED 两次均拒绝未知 read.kind=history。新增 owner 限定的快照查询后首 GREEN 两次通过。

扩展14项首测8通过/6失败（run-88784ad29c5847eeac757888e614f411，exit1）。三个假设分别核查：

1. 商品历史查询丢失件数，或测试来源实际没有三盒。只读 PlanSnapshot 证明原始来源只有一盒：无ref的初始目标件数没有进入已有编译路径。本票改用已有清单修订API真实保存三盒来源，再检验带真实ref的本次两盒选择；没有扩大本票去修改初次具名商品数量语义。这一既有初次数量缺口仍需单独记录。
2. 缺货路径错误生成清单，或测试误用了响应字段。原始SSE证明没有清单/加购，并明确鸡蛋库存0与是否生成部分清单；supply_preview不是该终端响应字段。验收改用已有pending_clarifications中的supply_gap_choice，业务实现未变。
3. 中文排除未生效，或测试需求缺失。提案已明确鸡蛋排除，实际却生成含蛋可确认清单。定位到历史ref直接准备跳过lookup，mutation仅在selection_goal路径执行已有expand_ingredient_terms；必需食材ID因此未与“鸡蛋”相交。最小修复为所有采购mutation复用该转换，不新增校验或兜底。

修复后结果见 validation.md；失败没有删除或算作通过。旧方案快照不恢复选择/ledger/加购授权；历史商品共享行仅返回明确shared标志，不能猜独立件数。

按“番茄炒蛋”查询的两个独立RED返回空来源。快照写入沿用json.dumps，中文被保存为Unicode转义；只读SQLite的instr对原中文返回0，对JSON编码的名称返回9641，两库一致（diagnosis-3af0a38453ae4e618764f6216e25d198）。此前两次诊断分别误用数据库路径/列名而退出1，不作定位证据，外部原始报告保留。修复只把现有contains条件转换为相同JSON编码，继续沿用LIKE自动转义；最终16历史＋5provider错误全部通过。

Standards与Spec分别发现schema允许group_id/contributions为null，以及缺历史行/共用商品数量仍被标为完整来源。新增missing_items/shared_quantity/null_association三形状各两独立RED：前四项误标完整，后两项TypeError。只在history读取处按schema可空契约处理贡献与关联；无关联或直接商品缺独立件数不标完整、不发采购ref，由现有history提示追问本次件数。不修改普通采购默认件数，不新增第二份数量状态。42项定向GREEN已通过。
