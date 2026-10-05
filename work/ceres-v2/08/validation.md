# 08 验证

全部命令由专职tester执行；Python3.12.10、UTF8、无pyc/cache、线程异常转失败。所有写入在外部UUID SQLite/Mercury/basetemp；主案例65商品fixture-only，SDK外部边界受控，无真实模型调用。

| 回执 | 实际结果 | 范围 |
| --- | --- | --- |
| ab564c74b97c46e2b0e40dea82804d3d | 2fail/exit1 | SKU测试前置错误，加购422，未测checkout |
| 664048b4e33f4612b271f6ef43064426 | 2fail/exit1 | 修正真实SKU后checkout404 RED |
| 6ce3e50096c7444b978538c182223239 | 2pass/exit0 | 持久订单/成交快照/cart事务首GREEN |
| 6de86e4dfcff4194844904211f1f732a | 2fail/exit1 | Mercury会话无selected_order_id RED，后续未触及 |
| 430de212874b4a099fd85145163e89c9 | 4pass/exit0 | 持久会话、同库选单查询、owner边界GREEN |
| 949c1cc88c5d4c3b984533759df116db | 16pass/exit0 | 独立代表各两次：成交快照、事务回滚、stale/empty、初始化保持、无focus选项、显式售后/错误ID限制 |
| frontend-tsc-325478d9aa9b4d0f884dea312611324d | exit0 | Node24.14，TS noEmit，UTC12:26:21.408–12:26:23.421 |
| frontend-build-a0a472ccc6a64941925ef8a3e4c3bb97 | exit0 | Vite8.0.5外部构建20模块，UTC12:28:54.572–12:28:55.900 |
| mercury-regression-8e2f2416ff0e4561987ee3ea33b85a65 | 61pass/exit0 | 原模块agent/tools/services/policy离线回归，UTC12:30:00.821–12:30:06.430；无live_llm |

TS启动记录器被误交给Node的错误未运行tsc，见launch-diagnostic回执；首次Vite runner缺__dirname的build exit1见dfb25回执。之后明确外部globals shim与runner配置构建成功，.vite-temp前后均不存在，仓库无构建写入。失败未算成功、未改项目源码规避验证。

各回执根文件保留实际executable/argv/cwd、环境、UTC、真实退出码及stdout/stderr；临时数据库/编译产物只在外部保留。16代表项＋61相关回归，不累计重复执行。真实模型/浏览器及本人页面验收留09；06速度阻塞依旧。
