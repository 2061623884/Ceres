# 05 行为验证

测试全由专职 v2_test_executor 执行，根审阅原始记录。不输出凭据、不修改活动DB。
RED b4053d600a984d8fa3ea6583d93eeeca：2fail/exit1；07:36:38.6845476–07:36:43.6823714UTC。协议已接受但没有memory action result；未到达跨会话断言。GREEN ffdfbb65965b494c98ce23feffd04d07：2pass/exit0；07:40:46.2480519–07:40:50.8924434。
扩充0799b86931424f9c8af99605b2259aed：10项8pass2fail/exit1，07:44:09.8178363–07:44:25.5929465。失败是测试GET默认不返回messages，before.messages=None；按真实API加include_messages=1，未改产品。
定向删除2项+相关revision confirmation/semantic constraints/display refs共31pass/exit0，c9c7c33f04cc4de5a740c3b47e110b94，07:47:07.3564710–07:47:46.4810777。先前8项无需重复：无随后产品改动。
命令: .venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning <targets> --basetemp <external-run>/pytest-tmp。cwd Ceres/backend；PYTHONUTF8=1，PYTHONDONTWRITEBYTECODE=1，DATABASE_URL/MERCURY_DB_PATH独立外部run目录；RETRIEVAL_INDEX_DIR空，fixture source是tmp/no-source.sqlite3。原始logs位于父目录work/ceres-v2-test-env/run-<ID>。旧SyntaxWarning保留。
四类显式内容无自动期限、跨session/重新打开SQLite、查询完整8条与recall5/2000、真实CRUD与owner隔离、删除不改计划/消息、临时人数预算不保存、本次品牌例外不改旧偏好，代表行为均两独立owner。
模型语义受控；相关召回user/feedback通用，project/reference按中文二字/英文词词法重合，显式先于自动。当前明确语义优先通过独立只读memories输入和prompt落实，不把memory混入hard requirements。真实模型/页面及reference业务流程仍09验收。
