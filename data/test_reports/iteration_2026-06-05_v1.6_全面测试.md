# 迭代测试记录

- 日期: 2026-06-05
- 迭代内容: v1.6 全面测试 — Skill 自助创建与发布 + 两级运行时日志系统 + 测试策略机制
- 关联 commit: 65c98cd (phase-r-refactor) + 未提交 v1.6 变更

## 变更范围
- 修改文件: CLAUDE.md, agent/loop.py, config.example.yaml, main.py, ui/index.html
- 新增文件: TESTING.md, pytest.ini, tests/conftest.py, tools/skill_builder.py, tools/runtime_logger.py, tests/test_skill_builder.py, tests/test_runtime_logger.py
- 影响模块: agent/loop, tools/skill_builder, tools/runtime_logger, main (12 新 API)

## 测试执行
- 总用例数: 125
- 通过: 125 | 失败: 0 | 跳过: 0
- 覆盖率: 69% (总行覆盖率)
- 耗时: 17.68s

## v1.6 新增测试

### tools/skill_builder.py (14个)
- test_validate_valid_skill — 合法 Skill 通过校验
- test_validate_missing_name — 缺 name 报错
- test_validate_dangerous_sql — 危险 SQL 拦截 (DROP/DELETE/INSERT)
- test_validate_bad_name — 非法命名 (特殊字符/大写/数字开头)
- test_validate_empty_content — 空内容拒绝
- test_validate_too_large — 超大内容 (>10000字符)
- test_validate_name_conflict — 同名 Skill 冲突检测
- test_validate_missing_limit_warning — 缺 LIMIT 警告
- test_generate_skill_md — 模板渲染正确
- test_parse_llm_response — LLM JSON 响应解析
- test_parse_llm_response_invalid — 无效 JSON 返回 None
- test_draft_lifecycle — 草稿保存/加载/删除 完整生命周期
- test_publish_valid_skill — 发布合法 Skill 到 skills/
- test_publish_invalid_skill — 拒绝发布不合法 Skill

### tools/runtime_logger.py (19个)
- test_basic_mode_logs_errors — basic 模式记录 ERROR
- test_basic_mode_logs_warnings — basic 模式记录 WARNING
- test_basic_mode_logs_lifecycle — basic 模式记录生命周期事件
- test_basic_mode_skips_debug — basic 模式跳过 DEBUG
- test_basic_mode_skips_detailed_user_action — basic 跳过用户操作 INFO
- test_detailed_mode_logs_everything — detailed 全量记录
- test_detailed_mode_includes_duration — detailed 含耗时
- test_mode_switch — 运行时模式切换
- test_log_app_start — 应用启动便捷方法
- test_log_exception — 异常记录 (含 traceback)
- test_log_tool_call — 工具调用记录 (含 args/耗时)
- test_log_chat_start — 对话启动记录
- test_read_logs — 日志查询 (按日期/级别/分类)
- test_read_logs_with_filter — 多过滤条件
- test_get_log_files — 文件列表 (含大小)
- test_get_stats — 统计信息 (模式/文件数/大小)
- test_cleanup_old_logs — 自动清理过期日志
- test_init_and_get_logger — 全局单例管理
- test_session_id_in_entries — 日志条目含 session_id

## 覆盖率变化

| 模块 | 行覆盖率 | 说明 |
|------|---------|------|
| calculators/ | 98% | 合规关键，达标 |
| tools/runtime_logger.py | 87% | 新模块 |
| tools/skill_builder.py | 89% | 新模块 |
| tools/query_runner.py | 84% | 安全关键 |
| tools/data_loader.py | 82% | 编码加载 |
| agent/loop.py | 82% | 核心循环 |
| agent/tools_spec.py | 74% | 工具分发 |

## 发现问题
- 无阻塞性问题。全部 125 用例通过。
- conftest.py 的 pytest_runtest_makereport hook 实现较 hacky（内部 API），但不影响功能
- 覆盖率报告被 pytest.ini 的 --cov 参数正确生成

## 安全关键测试确认
- SQLGuard 全部规则 (11项): ✅
- calculators/ 合规计算 (15项): ✅
- Agent 工具调度安全 (5项): ✅
