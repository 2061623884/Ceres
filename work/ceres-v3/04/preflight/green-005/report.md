# 04 DELETE 生命周期回归 green-005

- 范围：仅执行 test_v3_switch_lifecycle.py::test_display_quota_survives_get_rejection_and_role_switch_until_explicit_close。
- 结果：退出码 0，pytest 输出 1 passed in 3.58s；stderr 为空。
- 断言覆盖：首次建议切换为 automatic，确认展示后 ACK 返回并保存 prompt_displayed=true；GET、拒绝建议切换、继续当前角色、手动切换到 Momo 再切回 Keke 均保留额度；第二次建议切换为 fixed_entry；DELETE 返回 204，随后 GET 返回 404；重新打开生成不同 opening ID，保留原 guide/Mercury session IDs，并将新会话额度置为 false。
- 环境：Python 3.12.10、pytest 9.1.1；单独 TEMP/TMP 与 pytest basetemp；隔离 indexed_client 数据库/词法索引；MEMORY_MODEL 为空；线程异常 warning 提升为 error；Kev、semantic、Mercury 使用测试控制替身。没有完整出站流量抓包，因此不作“绝无真实外连”断言。
- 源码哈希：测试前后所列源码/测试文件摘要一致，未修改源码。原始命令、环境、stdout/stderr、摘要和退出码见同目录 command.txt、environment-and-source.json、stdout.txt、stderr.txt、source-check-after.json、result.json。
