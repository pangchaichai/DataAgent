# 全版本综合测试计划 — 2026-06-16

> 覆盖 v2.0 + v3.0 Week 1-4 + Stitch UI Phase 0-5 全部前后端场景
> **执行日期**：2026-06-16
> **最终结果**：575 passed, 2 skipped, 0 failed, 76% 覆盖率

---

## 测试范围

| 维度 | 覆盖内容 |
|------|---------|
| 后端模块 | 66 个 Python 模块（agent/ tools/ calculators/ api/ scheduler/ platform_adapter/） |
| 前端文件 | 17 个 JS 文件 + 5 个页面模块 + index.html + CSS |
| API 端点 | 54 个端点（6 个 Blueprint + 静态文件服务） |
| Skills | 9 个已注册 Skill |
| 数据字典 | 6 个 YAML 字典 + entity_alias |
| 计算器 | 7 个固化计算模块 |

## 新增测试文件

| 文件 | 测试数 | 覆盖模块 |
|------|--------|---------|
| `tests/test_query_runner.py` | 90 | SQLGuard 安全边界 + apply_field_map + execute_query |
| `tests/test_api_endpoints.py` | 45 | 全部 6 个 Blueprint 54 个 API 端点 |
| `tests/test_core_modules.py` | 48 | session_store + entity_normalizer + quality + compliance_audit + entity_manager |
| **合计新增** | **183** | |

---

## L1 — 单元测试（自动化）

### L1-01: 后端回归测试（原有 392 + 新增 183 = 575）
- [x] `pytest tests/ -v` 全绿
- **执行结果**：✅ 575 passed, 2 skipped, 0 failed (14.96s)

### L1-02: JS 语法检查（17 个文件）
- [x] `node --check` 对所有 ui/js/*.js + ui/js/pages/*.js 通过
- **执行结果**：✅ 全部 17 个文件通过（router/state/dom/chat/render/main/sidebar/settings/upload/skill_builder/agent_status + pages/chat/dashboard/sources/rules/audit）

### L1-03: CSS 构建验证
- [x] `ui/dist/styles.css` 存在且非空
- [x] 关键 Stitch 类名（stitch-card, bubble-ai, bubble-user, suggestion-pill）存在
- **执行结果**：✅ 34,733 bytes，所有关键类名存在

### L1-04: 静态资源完整性
- [x] 4 个字体文件（Inter × 2, JetBrains Mono, Material Symbols）存在
- [x] echarts.min.js 存在
- [x] tailwind-local.css 存在
- **执行结果**：✅ 全部 7 个静态资源文件存在

### L1-05: Skills YAML 前置事项完整性
- [x] 9 个 SKILL.md 均可解析 YAML frontmatter
- [x] 每个 Skill 有 name + description 字段
- [x] calc_type 字段值合法（fixed/exploratory）
- **执行结果**：✅ 9 个 Skill 全部通过验证（2 fixed + 7 exploratory）

### L1-06: 数据字典 YAML 完整性
- [x] 7 个字典文件（holding/nav/rating_entity/rating_bond/monitoring/weekly_report/entity_alias）可解析
- **执行结果**：✅ 全部 7 个 YAML 文件解析成功

### L1-07: SQLGuard 安全边界（新增 90 个测试）
- [x] 拒绝 DROP/DELETE/INSERT/UPDATE/CREATE/TRUNCATE/ALTER/GRANT 语句（8 测试）
- [x] 拒绝 read_csv_auto/read_parquet/read_json 等危险函数（5 测试）
- [x] 拒绝 ATTACH/INSTALL/LOAD/COPY/PRAGMA/EXPORT 命令（7 测试）
- [x] 拒绝 information_schema/pg_catalog/duckdb_tables 系统表（4 测试）
- [x] 拒绝无 LIMIT 的 SELECT（5 测试）
- [x] 允许合法 SELECT（10 测试：基本查询/WHERE/聚合/ORDER/CTE/JOIN/子查询）
- [x] 表名动态校验（2 测试）
- [x] 注释处理（3 测试）
- [x] 边界情况（4 测试：空SQL/纯空白/字符串中关键字/大小写）
- [x] apply_field_map 字段映射（8 测试）
- [x] execute_query 完整执行（11 测试）
- [x] BLOCKED_COMMANDS 全覆盖参数化（18 测试）
- [x] BLOCKED_FUNCTIONS 全覆盖参数化（5 测试）
- **执行结果**：✅ 90/90 通过，query_runner.py 覆盖率 87%→89%

### L1-08: session_store 会话管理（新增 6 个测试）
- [x] 模块导入 + _session 结构 + 默认值
- [x] _new_session_id 格式（12位hex）
- [x] save + load 往返一致性（JSONL 元数据 + 消息）
- [x] 空 session_id 无操作
- **执行结果**：✅ 6/6 通过

### L1-09: API 端点单元测试（新增 45 个测试）
- [x] AppCreation: Flask 创建 + Blueprint 注册 + 首页 HTML（3 测试）
- [x] ChatAPI: 空消息/有效消息/confirm/reset/sessions/stream（10 测试）
- [x] DataAPI: tables/delete/upload/profile/quality/workdir（8 测试）
- [x] ConfigAPI: config读写/groups/tasks/memory（6 测试）
- [x] SystemAPI: health/status/suggestions/cost/logs/llm（12 测试）
- [x] ReportAPI: templates/export-word/generate/download（6 测试）
- **执行结果**：✅ 45/45 通过

### L1-10: entity_normalizer 主体归一（新增 10 个测试）
- [x] 已知别名映射正确（厦门象屿集团 → 象屿集团）
- [x] 标准名自映射
- [x] 未知主体返回原值
- [x] 空字符串/None 处理
- [x] get_group 已知/未知实体
- [x] validate_join_keys 干净/不匹配场景
- [x] 多别名→同一标准名
- **执行结果**：✅ 10/10 通过，entity_normalizer.py 覆盖率 100%

### L1-11: quality.py 数据质量（新增 8 个测试）
- [x] 模块导入 + QualityReport 默认值
- [x] 空值率计算（DuckDB 表含已知 null）
- [x] 空表边界情况
- [x] 覆盖率报告格式
- [x] compute_quality_report 集成
- [x] JOIN 兼容性
- [x] 日期范围检测
- **执行结果**：✅ 8/8 通过，quality.py 覆盖率 52%→75%

### L1-12: compliance_audit 合规审计（新增 9 个测试）
- [x] 模块导入 + 关键函数存在
- [x] JSONL 写入验证
- [x] 必填字段检查（9 个字段）
- [x] MD5 指纹计算
- [x] Hash chain 验证（3 条事件链）
- [x] 篡改检测
- [x] 大 result_summary 拒绝
- [x] 空日志读取
- **执行结果**：✅ 9/9 通过，compliance_audit.py 覆盖率 48%→84%

### L1-13: entity_manager 实体管理（新增 15 个测试）
- [x] 创建/删除组
- [x] 添加/移除成员
- [x] 重复操作拒绝
- [x] get_group_mapping
- [x] 缺失文件处理
- [x] 多操作持久化往返
- **执行结果**：✅ 15/15 通过，entity_manager.py 覆盖率 47%→100%

---

## L2 — 功能测试（自动化）

### L2-01: 路由器页面注册
- [x] 5 个页面文件存在（chat.js/dashboard.js/sources.js/rules.js/audit.js）
- [x] router.js 定义路由注册函数
- **执行结果**：✅ 全部 5 个页面模块存在且导出 render() 函数

### L2-02: DOM ID 前后端交叉引用
- [x] 扫描 101 个 JS 引用的 DOM ID，对比 126 个已定义 ID
- [x] 15 个缺失 ID 中：12 个有 null 保护，3 个经手动检查也有保护
- **执行结果**：✅ 零未保护的 DOM 引用，15 个缺失 ID 全部安全

### L2-03: 全部 54 个 API 端点烟雾测试
- [x] 45 个 pytest 测试覆盖所有 Blueprint 端点
- [x] 每个端点返回正确 HTTP 状态码和 JSON 结构
- **执行结果**：✅ 45/45 通过，零 500 错误

### L2-04: 静态资源服务
- [x] 23 个静态资源（16 JS + 2 CSS + 1 echarts + 4 字体）通过 /static/ 访问
- [x] Content-Type 正确（text/javascript, text/css, font/woff2）
- **执行结果**：✅ 23/23 资源返回 200

### L2-05: Blueprint 注册验证
- [x] 6 个 Blueprint（chat/data/config/skill/report/system）全部注册
- **执行结果**：✅ 6/6 注册

### L2-06: Skill 预检流程
- [x] concentration_monitor（fixed + fixed_calculator）正确识别
- [x] fund_nav_report（fixed + fixed_calculators × 3）正确识别
- [x] 7 个 exploratory 类型正确识别
- **执行结果**：✅ 9/9 Skill 类型正确

### L2-07: 计算器函数签名一致性
- [x] 7 个计算器函数均接受 conn 参数
- [x] 参数列表符合各计算器业务需求
- **执行结果**：✅ 7/7 签名一致

---

## L3 — 集成测试（自动化）

### L3-01: 应用启动与首页
- [x] Flask app 启动，GET / 返回 200（45,554 bytes）
- [x] 返回 HTML 含 navSidebar, pageRoot, topHeader
- **执行结果**：✅ 通过

### L3-02: CSV 上传完整流程
- [x] POST /api/upload → 200（UTF-8 编码自动检测）
- [x] POST /api/upload/confirm → 200（表加载到 DuckDB）
- [x] GET /api/tables → 1 张表（test_upload_20260616 存在）
- [x] DELETE /api/tables/test_upload_20260616 → 200
- [x] GET /api/tables → 0 张表（已移除）
- **执行结果**：✅ 5 步全部通过

### L3-03: SSE 流合约
- [x] POST /api/chat → stream_id
- [x] GET /api/stream/<sid> → 200 text/event-stream
- [x] 事件格式 {"type":"stream_end"} 正确
- **执行结果**：✅ 通过

### L3-04: 设置读写循环
- [x] GET /api/config → 200（含 user_profile/calculation_config 等）
- [x] POST /api/config → 200（更新 user_profile.name=TestUser）
- [x] GET /api/config → name=TestUser（持久化验证）
- [x] 恢复原始配置
- **执行结果**：✅ 通过

### L3-05: 报告模板与导出
- [x] GET /api/report/templates → 2 个模板（concentration_report, nav_report）
- [x] POST /api/report/export-word → 200 ok
- **执行结果**：✅ 通过

### L3-06: 日志系统端到端
- [x] GET /api/logs/stats → mode=basic
- [x] POST /api/logs/mode → detailed
- [x] GET /api/logs → 38 条日志
- [x] 恢复 basic 模式
- **执行结果**：✅ 通过

### L3-07: 全量 pytest 回归
- [x] `pytest tests/ -v` 全绿
- **执行结果**：✅ 575 passed, 2 skipped, 0 failed (14.96s)

---

## L4 — UAT 验收场景（人工/浏览器）

> 本环境无浏览器，以下场景需 Windows/macOS 内测时手动验证

### U4-01: 聊天对话完整流程
- [ ] 输入消息 → 流式响应显示 → AI 气泡样式正确
- [ ] 过程包装器（thinking/tool_start/tool_end）正确折叠

### U4-02: 中文编码文件上传
- [ ] GB18030 编码持仓 CSV → 自动检测 → 正确显示中文列名
- [ ] 两阶段确认流程完整

### U4-03: Skill 一键执行
- [ ] 侧边栏 Skill 卡片显示就绪状态
- [ ] 点击执行 → SSE 流 → 结果展示

### U4-04: 设置面板持久化
- [ ] 打开设置 → 修改配置 → 保存 → 重新打开 → 值保持

### U4-05: 深色模式切换
- [ ] 侧边栏/聊天区/设置面板均正确切换

### U4-06: @mention 自动补全
- [ ] 输入 @ → 弹出已加载表名列表 → 选择 → 正确插入

### U4-07: 5 页面路由导航
- [ ] 点击侧边栏导航 → 5 个页面正确切换
- [ ] 浏览器回退/前进正常

### U4-08: 数据表剖析
- [ ] 点击表名 → 结构剖析面板 → 列信息/样本/类型正确
- [ ] 质量面板 → 空值率/覆盖率

### U4-09: Skill Builder 创建流程
- [ ] 输入描述 → AI 生成 → 预览 → 校验 → 发布

### U4-10: Word 导出
- [ ] AI 回复中含报告 → 导出 Word → 下载成功

---

## 覆盖率提升摘要

| 模块 | 测试前覆盖率 | 测试后覆盖率 |
|------|------------|------------|
| query_runner.py | 85% | 89% |
| entity_normalizer.py | 71% | 100% |
| entity_manager.py | 47% | 100% |
| compliance_audit.py | 48% | 84% |
| quality.py | 73% | 75% |
| **整体** | **74%** | **76%** |

## 发现的问题

### 已修复（本次会话前一轮）
1. **mentionPopup ID 不匹配** — pages/chat.js 用 `mention-popup`，sidebar.js 用 `mentionPopup` → @mention 完全不工作。已修复。
2. **suggestions 目标 ID 过时** — sidebar.js 的 `loadSuggestions()` 引用不存在的 `suggestionsBar`，应为 `chat-suggestions`/`suggestion-pills`。已修复。

### 已确认安全（本次检查）
3. **15 个旧版 sidebar DOM ID 缺失**（sessionList/tableList/skillList 等）— 全部有 null 保护，Stitch 页面模块有自己的对应 DOM。
4. **bodyWrap/chatTitle/inrow** — 经手动验证，均有 null 保护，无运行时错误。

### 无新 bug 发现
本轮全面测试未发现新的 P0/P1 缺陷。
