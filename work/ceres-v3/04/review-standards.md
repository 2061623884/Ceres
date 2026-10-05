# 04 Standards 审查

固定点为 `fbd9d01875eaeab5ec01e9849f4ce2bc562d1837`；提交列表为空。baseline ZIP、review ZIP 与 scope 的 13 个文件摘要均匹配，详见 [scope hash 核对](review-standards-scope-check.json)。审查仅读 `source.patch`，未运行测试、静态检查、模型/API，也未使用 `git diff HEAD`。

## 硬规范：1 项

- `backend/app/services/chat_opening_service.py`，`ChatOpenings.close`：取得 `opening.lock` 后先执行 `opening.require_open()`，再在同一锁保护期内核对 `self._openings.get(opening_id) is not opening`。关闭映射的唯一当前路径也是 `close`，它必须先取得同一 opening 锁；同一 ID 由内部 UUID 创建。因而该映射身份分支在已有状态检查之后重复防御了当前内部不可能出现的状态。违反 `AGENTS.md`「校验仅覆盖当前契约要求……内部不重复检查」及「不为不可能发生的场景增加错误处理」。移除重复身份分支，保留 `require_open`、busy 检查和受锁保护的删除即可。

## 判断性 smell：1 项

- **可能的 Mysterious Name**：`work/ceres-v3/03/demo.html` 的 hunk 增加了 `async function sync(){...}`，它读取 opening 与 Guide 状态、写回 sessionStorage 并刷新角色/控件状态。`sync` 未说明同步对象和效果；可改为 `restoreOpeningState` 或同等明确名称。它属于命名建议，不是规范违规。

未发现需要报告的其他 Fowler smell；`handoff_recent_messages` 沿既有 Guide→TurnStream→Graph→Context 调用链传递，且有 04 的实际交接调用方，不把必要传递机械判为抽象或 Shotgun Surgery。
