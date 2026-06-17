# DataAgent 开发进度记录

> 每次完成一个 Step 后在此记录，下次会话开始时让 Claude Code 读取此文件。

---

## 当前阶段：v2.0 完成 + Stitch UI 重构完成 + 计算器字段映射参数化完成 → 等待内测反馈 / Phase 4 模板确认

## 计算器字段映射参数化（Path B）✅ 完成（2026-06-17）
✅ 已测（L1+L2+L3 通过）— 测试计划：`data/test_plans/20260617_calculator_field_mapping.md`

### 改动范围
- [x] `calculators/columns.py`（新建）— 语义列名常量 + `resolve_columns()` + `ColumnResolutionError`
- [x] `calculators/concentration.py` — 新增 `cols=None` 参数，SQL 使用映射后的列名
- [x] `calculators/nav_metrics.py` — 新增 `cols=None` 参数，11 个净值字段全部参数化
- [x] `calculators/asset_structure.py` — `calc_asset_structure()` + `calc_top_n_holdings()` 均参数化
- [x] `calculators/credit_distribution.py` — 新增 `cols=None`，评级字段通过映射解析
- [x] `calculators/position_diff.py` — 新增 `cols=None`，3 个关键列参数化
- [x] `calculators/leverage.py` — 新增 `cols=None`，产品名列参数化
- [x] `calculators/liquidity.py` — 新增 `cols=None`，3 个关键列参数化
- [x] `agent/tool_dispatch.py` — 新增 `_resolve_cols_for_table()` + `_resolve_mv_field()` + 所有 `_run_*` 函数传入 cols
- [x] `tools/data_loader.py` — 新增 `get_field_map_for_table()` 接口
- [x] `tests/test_column_resolution.py`（新建）— 26 个测试全部通过

### 测试结果
- L1 新增测试：26 passed, 0 failed
- L2 全量回归：601 passed, 2 skipped, 0 failed (77% 覆盖率)
- 向后兼容：全部既有 30 个计算器测试无修改通过

---

## 回归测试 + UAT 验证 ✅ 完成（2026-06-17）
✅ 已测（L1+L2+L3+UAT 通过）— 测试计划：`data/test_plans/20260617_regression_uat_testing.md`

### 测试执行
- [x] L1 单元测试：575 passed, 2 skipped, 0 failed (76% 覆盖率)
- [x] L2 功能测试：16 JS 语法 / 14 API 端点 / 9 Skills / 7 字典 / 7 计算器 / DOM 安全 / CSS 类名 / 静态资源 — 全通过
- [x] L3 集成测试：应用启动 / CSV 上传 / SSE 流 / 设置读写 / 报告导出 / 日志系统 / 集团 CRUD / Skill Builder / 数据表剖析 — 全通过
- [x] UAT 字段一致性：路由绑定 / @mention / 深色模式 / 前端-API 字段对齐 — 全通过
- [ ] L4 UAT 浏览器：10 个场景待 Windows/macOS 内测时业务方验收

### 发现并修复的 Bug（4 个 P1/P2）
- [x] `sources.js` 数据预览空值率：`c.null_pct` → `c.null_rate`（永远显示 `--`）
- [x] `sources.js` 数据预览示例值：`c.sample` → `c.samples`（永远显示 `--`）
- [x] `dashboard.js` LLM 状态：`health.llm_ok` → `health.llm_status === 'online'`（永远显示"离线"）
- [x] `sources.js` 数据源列数：`t.columns` → `t.cols`（永远显示 0）

## 全版本综合测试 ✅ 完成（2026-06-16）
✅ 已测（L1+L2+L3 通过）— 测试计划：`data/test_plans/20260616_comprehensive_full_version_testing.md`

### 新增测试（183 个）
- [x] `tests/test_query_runner.py` — SQLGuard 安全边界 90 个测试（覆盖率 89%）
- [x] `tests/test_api_endpoints.py` — 全部 54 个 API 端点烟雾测试 45 个
- [x] `tests/test_core_modules.py` — session_store/entity_normalizer/quality/compliance_audit/entity_manager 48 个

### 发现并修复的 Bug（4 个）
- [x] mentionPopup ID 不匹配 → @mention 自动补全完全失效
- [x] suggestions 目标 ID 过时 → 推荐功能永久隐藏
- [x] 集团系 CRUD UI 在 SPA 迁移后无入口 → 集成到 Sources 页面
- [x] 工作目录上传 UI 在 SPA 迁移后无入口 → 集成到 Sources 页面

---

## Stitch Design System UI 重构 ✅ Phase 0-5 完成（2026-06-16）

### Phase 0+1（基础设施 + 导航）
- [x] Tailwind CSS v4 standalone CLI + `ui/src/input.css` MD3 token 系统
- [x] Inter / JetBrains Mono / Material Symbols Outlined 字体本地化
- [x] 客户端 hash 路由（5 页面：Dashboard / Sources / Rules / Chat / Audit）
- [x] 深色海军蓝侧边栏 + 56px 顶栏 + 5 个页面模块

### Phase 2-5（图标迁移 + 聊天气泡重构）
- [x] `ui/js/render.js` 完整 Stitch 重写（气泡/表格/图表/卡片）
- [x] `ui/js/chat.js` 流式气泡 + 过程包装器 Material Symbols
- [x] `ui/js/main.js` 欢迎面板 Material Symbols 卡片
- [x] `ui/js/dom.js` 兼容新旧 DOM 结构
- [x] `ui/js/upload.js` / `settings.js` / `sidebar.js` / `skill_builder.js` 图标迁移
- [x] `ui/src/input.css` 流式光标动画 + CSS 重编译
- [x] 遗留 CSS 保留在 `index.html` 内（设置面板/技能构建器/上传确认/状态栏）

## Windows 内测包构建 ✅ 完成（2026-06-09）

### 构建脚本
- [x] `scripts/package_windows.py` — 三阶段依赖解析（全量 → 替换 Win 原生 → 扫描 Win-only 传递依赖）
- [x] 自动清理 Linux wheel，包体 45.6 MB (44 deps)
- [x] `dist/DataAgent-v2.0-beta1.zip` — 离线安装包

### Bug 修复（5 项）
- [x] **setup.bat**：CRLF 换行 + 去掉 chcp 65001 + 补充 Win-only dep + 路径修正
- [x] **run.bat**：cd DataAgent + config 检测
- [x] **上传确认对话框**：I-10 遗漏的 8 个 DOM 元素补回 ui/index.html + ui/js/upload.js 联动
- [x] **.claude/settings.json**：PreCommit 移除 + Stop 数组化
- [x] **Win-only 传递依赖**：Phase 3 METADATA 扫描自动发现 pythonnet/clr_loader/cffi/colorama

### 测试
- [x] 311/311 全通过（含 DeepSeek 集成测试），0 跳过

## v2.0 UX 修复 ✅ 完成（2026-06-07）

### Bug 修复
- [x] **Issue 1**: SSE 流挂起 — 增加后台线程存活检测，心跳超时从 120s 改为 30s，线程死亡时自动推送 stream_end
- [x] **Issue 2**: Skill Builder 发布流程 — validate 端点响应格式修正（增加 `validation` 外层 key）
- [x] **Issue 3**: 文档上传支持 — file_reader.py 支持 .docx/.pdf/.txt，前端文件选择器更新
- [x] **Issue 4**: 图表功能 — 每个数据表新增「📊 图表」按钮，支持柱状/饼/折线/散点图
- [x] **Issue 5**: Word 导出 — report_builder.py Markdown→Word，下载端点，报告自动显示导出按钮
- [x] **优化 2**: 设置按钮从右上角迁移至左侧边栏底部

### 优化 1 评估（会话并行）
单全局会话架构，建议 Phase 5 实现多租户隔离，工作量约 2 天。

## v2.0 Evolution I-1~I-10 ✅ 完成（2026-06-06）

> 详见 `docs/evolution-master-plan.md`

| 迭代 | 内容 | 状态 |
|------|------|------|
| I-1 | 工程基建 + macOS + 本地 LLM（LM Studio）| ✅ 完成 |
| I-1b | ETCLOVG Harness 加固（Schema 校验/SelfChecker/工具过滤/超时）| ✅ 完成 |
| I-2 | 报告生成管线（Jinja2 + Word 导出 + 模板）| ✅ 完成 |
| I-3 | 图表生成（chart_builder + generate_chart 工具）| ✅ 完成 |
| I-3b | 上下文三级压缩 + 成本追踪 | ✅ 完成 |
| I-4 | 数据持久化 + 智能上传两阶段确认 | ✅ 完成 |
| I-5 | 前端增量改进（推荐 API + 欢迎面板）| ✅ 完成 |
| I-5b | Hook 系统 + 审计 Hash Chain | ✅ 完成 |
| I-6 | 文档解析（Word/PDF/TXT）+ 联网搜索（DuckDuckGo）| ✅ 完成 |
| I-7 | Blueprint 拆分准备（api/ 6 模块 + session_store）| ✅ 完成（2026-06-08）|
| I-8 | Plan-Execute 两阶段 Agent | ✅ 完成 |
| I-9 | 计算器补齐（position_diff/leverage/liquidity）| ✅ 完成（2026-06-08）|
| I-10 | 前端 JS 模块化（ui/js/ 9 文件）| ✅ 完成（2026-06-08）|

### 技术债清零（2026-06-08）
- I-7：main.py 从 1062 行压缩到 156 行，6 个 Blueprint 全部注册，新增 7 个 API 端点
- I-9：3 个新计算器已加入工具枚举，SelfChecker 新增对应校验规则
- I-10：index.html 从 2233 行降至 854 行，12 个函数迁移到模块，全面模块化完成

### UAT 修复 ✅
- [x] macOS 客户端 + Skill Builder + 文档上传 + LLM 错误处理 + UI 改进
- [x] Blueprint API 结构与 UX 特性对齐

## Phase R — Agent 内核重构 ✅ 完成（2026-06-04）
- [x] R1: Agent 内核重构为 tool-calling Agent（5 工具 + function-calling + 暂停续跑）
- [x] R2: 数据质量诊断 — 上传即输出质量报告 + 自适应编码
- [x] R3: UI 重建 — 全本地资源 · 状态透明 · 确认不可忽略
- [x] R4: 未知表内联推断（sanitize + 字典草稿→正式）
- [x] R5: 收窄版跨会话记忆（BM25+SQLite，仅口径纠正，默认关闭）
- [x] R5-r: 测试优化 + 内测反馈修复（10 新 API / 8 缺陷修复 / UI v2.3 / PyWebView 4.4.1）
- [x] 收尾: CLAUDE.md v1.5 回灌 + 编码规范更新

## Phase 0 — 环境搭建 ✅ 已完成
- [x] 虚拟环境创建 + 开发依赖安装
- [x] data/ 目录结构创建
- [x] 冒烟测试通过
- [x] **项目结构调整**：platform/ → platform_adapter/，详见 docs/project-changes.md
- [x] scheduler/task_manager.py 占位桩（Phase 3 完整实现）

## Phase 1 — 核心数据链路 ✅ 已完成（57/57 单测 + 45/45 联调通过）
- [x] Step 1：main.py（随机端口 + 平台适配启动）
- [x] Step 2：ui/index.html（聊天界面 + ECharts后置钩子 + @mention + 文件拖拽）
- [x] Step 3：tools/data_loader.py（chardet + DuckDB + 字典映射 + 实体归一 + 千分位清洗）
- [x] Step 4：tools/query_runner.py（sqlglot SQLGuard + 动态表名 + 危险函数拦截 + CTE支持）
- [x] Step 5：agent/llm_client.py（DeepSeek SQL生成 + report_text + 意图分类 + 流式 + 降级）
- [x] Step 6：agent/skill_loader.py（8 Skill 渐进式加载 + 关键词意图匹配）
- [x] Step 7：agent/loop.py（Agent 主循环 + 错误分类自愈 + SSE 事件流）
- [x] Step 8：前后端联通（/api/chat SSE + /api/upload + /api/tables）
- [x] 联调验证：3条真实查询全部成功（DeepSeek + 283行持仓CSV）

## Phase 2 — 语义层 + 报告生成 ✅ 已完成（2026-06-01，72/72 单测通过）
- [x] tools/entity_normalizer.py（64行，10+别名映射）
- [x] data_dictionary/holding_dict.yaml（12字段，投资团队+研究员）
- [x] data_dictionary/nav_dict.yaml（14字段，投资团队）
- [x] data_dictionary/rating_entity_dict.yaml（19字段，研究员+投资团队）
- [x] data_dictionary/rating_bond_dict.yaml（24字段，研究员+投资团队）
- [x] data_dictionary/monitoring_dict.yaml（15字段，投资团队，外部监控结果校验）
- [x] calculators/concentration.py 单元测试（7/7 通过）
- [x] calculators/nav_metrics.py + 单元测试（2/2 通过）
- [x] calculators/asset_structure.py + 单元测试（3/3 通过）
- [x] calculators/credit_distribution.py + 单元测试（3/3 通过）
- [x] tools/compliance_audit.py（JSONL 审计日志，含 MD5 指纹）
- [ ] skills/fund_nav_report/ 改为调用 calculators（模板待 C-02 确认后实现）

## Phase 3 — 合规监控 + 参谈要点 ✅ 验收通过（2026-06-07）
- [x] tools/entity_manager.py（集团系 CRUD + 逆向索引 + 持久化）
- [x] scheduler/task_manager.py（完整补跑检测 + 数据时效校验 + 运行记录）
- [x] tools/notify.py（超标告警/数据过期/报告完成/任务失败 业务通知）
- [x] skills/concentration_monitor/（SKILL.md calc_type:fixed + fixed_calculator）
- [x] skills/meeting_report/（SKILL.md + template.md.j2 就绪）
- [x] Phase 3 验收通过

## Skill v3 — 数据感知与自定义需求支持（进行中，branch: feature/skill-data-awareness）

### 背景与问题
Windows 内测发现 Skill 系统的根本缺陷：**工具与数据脱钩**。
- Skill Builder 生成的 SQL 引用不存在的表/列名
- `required_table_types` 声明从未在运行时校验
- Skill 执行前无数据就绪检查，缺数据时静默失败

### 三类 Skill 重新划分（扩展 CLAUDE.md 第六章）

| 类型 | 特征 | SQL 角色 | 示例 |
|------|------|----------|------|
| **A. 固化计算** | 口径严格，合规/报告场景 | 无 SQL，调 calculator | concentration_monitor |
| **B. 探索式查询** | 灵活统计，LLM 判断 | LLM 生成 SQL | position_query |
| **C. 确定性数据管道** | 用户已定义完整处理逻辑 | LLM 按用户定义执行 | 理财周报、谈参要点 |

### 架构决策（OCP 原则）
- **稳态核心**：loop.py / llm_client.py / tools_spec.py / data_loader.py（改动极低频）
- **单一入口**：`prepare_skill_for_execution()` 函数（loop.py 唯一改动点，未来不再改）
- **敏态功能**：agent/skill_preflight.py（新建，所有 Skill 准备阶段逻辑集中于此）
- **YAGNI**：当前不引入 Pipeline 框架；`prepare_skill_for_execution()` 内部线性分阶段，将来可零成本抽取为 pipeline

### SKILL.md 新增可选 frontmatter 字段（向后兼容）
```yaml
required_files:
  - semantic: "周报数据源"
    file_pattern: "周报*数据源*"    # 模糊匹配已上传文件名
    expected_fields: [统计日期, 组合代码, 产品标签]
optional_files:
  - semantic: "模板参考"
    file_pattern: "周报*模板*"
external_sources:
  - type: groups_yaml
    required: false
```

### 实施计划

**Phase A — 预检模块 ✅ 完成（2026-06-10，commit b3c878a）**
- [x] `agent/skill_preflight.py` 新建（`prepare_skill_for_execution()` 单一入口）
- [x] `agent/skill_loader.py` — SkillInfo 加 `metadata: dict` 字段（一行）
- [x] `agent/loop.py` — Skill 注入替换为 `prepare_skill_for_execution()` 调用
- [x] `tests/test_skill_preflight.py` — 16 个单测，325/325 全通过

**Phase B — Skill Builder 数据感知 ✅ 完成（2026-06-10，commit a1597ab）**
- [x] `tools/skill_builder.py` — `build_skill_generation_prompt(data_context)` 注入已加载 schema
- [x] `SkillDraft` — 新增 required_files / optional_files / external_sources 字段
- [x] `generate_skill_md` — 生成含 required_files 的 frontmatter
- [x] `api/skill_api.py` — generate 端点调用 `build_schema_context()` 传给 LLM

**Phase C — 需求文档直接导入 ✅ 完成（2026-06-10）**
- [x] `tools/skill_builder.py` — `import_from_requirement_doc()` + `build_import_prompt()` 从 .md 解析 required_files
- [x] `api/skill_api.py` — 新增 `POST /api/skill-builder/import` 端点
- [x] `ui/js/skill_builder.js` + `ui/index.html` — 新增"从文档导入"入口（Step 0）
- [x] `tests/test_skill_builder.py` — 7 个新测试（prompt 构建 / 空内容 / 超大 / mock LLM 成功+失败+坏JSON）
- [x] 测试：332/332 通过，2 跳过，无回归

**后续 — 创建两个验收用 Skill ✅ 完成（2026-06-10，commit e390f5a）**
- [x] `skills/weekly_report_generator/SKILL.md` — 理财周报多模板生成器（5 个输出 CSV，Type C）
- [x] 替换 `skills/meeting_report/SKILL.md` — 谈参要点 v3（含集团关系树 + 动态持仓表）

### 测试要求
1. 单测：`pytest tests/test_skill_preflight.py -x -v`
2. 无数据场景：触发 Skill → 明确提示缺什么文件
3. 有数据场景：触发 Skill → 注入真实表名/列名 → LLM 正确执行
4. 未知类型数据（`table_type=unknown`）→ 仍可通过 `file_pattern` 被 Skill 关联
5. 回归：`pytest tests/ -x -q` 全绿

## 文件上传升级 ✅ 完成（2026-06-10）

### 批量上传
- [x] `ui/index.html`：`fileInput` 已有 `multiple` 属性，前端 `handleFiles()` 已支持多文件队列，无需额外改动

### 本地工作目录（选项 B — 配置持久化）
- [x] `tools/workdir_loader.py` — 新建：`get_work_dir()` / `list_workdir_files()` / `scan_for_pattern()`
- [x] `api/data.py` — 新增 3 个端点：`GET /api/workdir/files` / `POST /api/workdir/preview` / `POST /api/workdir/load`
- [x] `api/config_api.py` — GET/POST `/api/config` 支持 `app.work_dir` 字段
- [x] `agent/skill_preflight.py` — 预检缺数据时自动扫描工作目录，提示候选文件（不改 loop.py）
- [x] `ui/js/sidebar.js` — 新增"工作目录"侧边栏区块 + `loadWorkdir()` + `loadWorkdirFile()` 函数
- [x] `ui/js/settings.js` — 加载/保存 `work_dir` 设置
- [x] `ui/js/upload.js` — `confirmUploadFile()` 支持工作目录文件走 `/api/workdir/load` 分支
- [x] `ui/index.html` — 新增工作目录侧边栏区块 + 设置面板工作目录输入框
- [x] `tests/test_workdir_loader.py` — 9 个单测，341/341 全通过

### 未来扩展方向（已评估，本次不实现）
- 远程数据库 / 企业数据中台：引入 `DataSource` 抽象接口（`LocalFileDataSource` / `LocalDirDataSource` / `RemoteDBDataSource`），当前实现以兼容该方向的方式编写

---

## v3.0 演进规划 ✅ 完成（2026-06-14）

### 方案评审
- [x] 对 `docs/v3-architecture-evolution.md`（1318行）进行逐 Track 专家评审
- [x] 产出最终实施计划 `docs/v3-evolution-final-plan.md`（~500行）
- [x] 4 周实施方案（Week 1-4）+ UI 设计优化方案（6类问题7项优化）

### Track 判定汇总
| Track | 判定 | 说明 |
|-------|------|------|
| Track 1 ToolRegistry | ADJUST | 降级为文件拆分（tool_defs + tool_dispatch） |
| Track 2A 快速路径 | APPROVE（P0） | 补充 default_args 参数来源 |
| Track 2B ExecutionTracker | APPROVE（简化版） | 仅做写入端 JSONL |
| Track 2C D-term | DEFER → v3.1 | 需先有 baseline 数据 |
| Track 3 Skill卡片 | APPROVE（P0） | 提升优先级 |
| Track 4 Eval Framework | DEFER → v3.1 | 缺 baseline + 校准数据 |
| 仪表盘 | ADJUST | 消息流内嵌（非独立面板） |
| 置信度标注 | APPROVE | 集中 Week 3 交付 |
| fund_nav_report | P0 修复 | 合规风险：B类场景违规用LLM SQL |

### v3.0 Week 1 — 快速路径 + 执行追踪 ✅ 完成（2026-06-14）
✅ 已测（L1+L2+L3通过，L4待UAT）— 测试：`tests/test_fast_path.py`（11 个测试）

- [x] `agent/fast_path.py` — 确定性快速路径（跳过 LLM，直接调用固化计算）
- [x] `agent/execution_tracker.py` — JSONL 写入端（`data/traces/`）
- [x] `agent/loop.py` — `try_fast_path` 集成入口
- [x] `skills/concentration_monitor/SKILL.md` — 新增 `default_args` 字段
- [x] `tests/test_fast_path.py` — 11 个测试全绿（352/352 通过）

---

## v3.0 Week 2 — Skill 卡片 + fund_nav_report 合规修复 ✅ 已测（L1+L2 通过，L3 部分延期，L4 待 UAT）

### 测试计划
- [x] 迭代测试计划：`data/test_plans/20260614_v3_week2_skill_cards_and_nav_fix.md`（执行结果已填写）

### 功能开发
- [x] `api/skill_api.py` — `GET /api/skills/status`（批量 preflight，30s 缓存）
- [x] `api/skill_api.py` — `POST /api/skills/<name>/execute`（复用 SSE 流）
- [x] `ui/js/sidebar.js` — Skill 卡片（描述+就绪状态+执行按钮）
- [x] `ui/js/chat.js` — `executeSkill()`（复用 SSE 事件流）
- [x] `sidebar.js` 表名点击 → `openProfile(tableName)`
- [x] `skills/fund_nav_report/SKILL.md` — `calc_type` 改 `fixed`，串联 3 个 calculator（P0 合规修复）
- [x] `agent/skill_loader.py` — `fixed_calculators: list[str]` 字段支持
- [x] `agent/fast_path.py` — 多 calculator 串联 + 新格式化函数

### 测试执行
- [x] L1 单元测试：`tests/test_skill_api.py` 17 个测试全绿（含 can_fast_path/preflight/精确触发）
- [x] L2 功能测试：`/api/skills/status` 就绪/缺数据场景；`/api/skills/<name>/execute` 有效/无效名
- [x] L3 集成测试（部分）：缓存命中行为通过；端到端 SSE 流延期至 UAT
- [ ] L4 UAT：见测试计划 U4-01 ~ U4-06（Windows 内测时业务方确认）

### 全量回归
- [x] 369 通过，2 跳过，0 失败（2026-06-14）

---

## v3.0 Week 3 — Skills 修复 + 新工具 + 置信度标注 ✅ 已测（L1+L2+L3 通过，L4 待 UAT）

### 测试计划
- [x] 迭代测试计划：`data/test_plans/20260614_v3_week3_skills_fix_tools_confidence.md`（执行结果已填写）

### 功能开发
- [x] `skills/client_meeting_report/` — 整目录删除（与 meeting_report 重复）
- [x] `skills/meeting_report/SKILL.md` — 合并 client_meeting_report 触发词，新增 Step 5 `request_confirmation`
- [x] `skills/partnership_summary/SKILL.md` — 将非正式确认节点改为正式 Step 4 `request_confirmation`
- [x] `agent/skill_preflight.py` — 新增 `_skill_dir()` + `template_file` 存在性检查（缺失时阻断）
- [x] `agent/tools_spec.py` — 新增 `list_tables` 工具 + `export_data` 工具（直连 DuckDB 绕过 SQLGuard）
- [x] `agent/loop.py` — `_text(text, confidence=None)` 支持置信度字段；LLM 回复 → `confidence="ai_generated"`
- [x] `agent/fast_path.py` — text 事件携带 `confidence="auditable"`
- [x] `ui/js/chat.js` — text 分支追踪 `streamConf`，流结束时追加 `.conf-tag` 标签
- [x] `ui/js/state.js` — 新增 `streamConf` 全局变量
- [x] `ui/index.html` — `.conf-tag` CSS（3种颜色+深色主题）；placeholder 去技术化

### 测试执行
- [x] L1 单元测试：`tests/test_week3.py` 14 个测试全绿（Skills合并/preflight模板检查/新工具/置信度字段）
- [x] L2 功能测试：`/api/skills/status` 反映 Week 3 变更（L2-01~L2-03 全通过）
- [x] L3 集成测试：fast_path confidence="auditable" 已通过（test_fast_path_emits_auditable）
- [ ] L4 UAT：见测试计划 U4-07 ~ U4-11（业务方手动验收）

### 全量回归
- [x] 383 通过，2 跳过，0 失败（2026-06-14）

---

---

## v3.0 Week 4 — tools_spec 拆分 + UI 统一 ✅ 已测（L1+L2 通过，L4 待 UAT）

### 测试计划
- [x] 迭代测试计划：`data/test_plans/20260614_v3_week4_toolspec_split_ui_unify.md`（执行结果已填写）

### 功能开发
- [x] `agent/tool_defs.py` — 新建：TOOL_DEFINITIONS + ToolResult + ToolContext
- [x] `agent/tool_dispatch.py` — 新建：dispatch_tool + 所有 _tool_* 实现 + 校验 + 超时
- [x] `agent/tools_spec.py` — 改为薄转发层（re-export all public symbols，向后兼容）
- [x] `ui/js/main.js` — `buildWelcomePanel(tables)` 统一欢迎面板；`resetChat()` 使用统一面板；`pollHealth()` 改为 AI 就绪/AI 离线；`updateTableCountHeader(n)` 新增
- [x] `ui/js/sidebar.js` — `loadTables()` 成功后调用 `updateWelcomeExamples(tables)`（存入 _lastLoadedTables + 更新 Header 计数）
- [x] `ui/index.html` — Header：移除 RAM/Token chip，改 llmName→llmStatus，新增 tableCountChip；欢迎面板改为 JS 渲染占位；新增 `.wc-skill-btn` CSS
- [x] `docs/user-guide.md` — 更新至 v3.0（界面介绍 / Skill 卡片 / 置信度标签 / 版本记录）

### 测试执行
- [x] L1 单元测试：所有现有测试覆盖拆分后的工具分发逻辑（383 通过）
- [x] L2 功能测试：全量回归验证 re-export 层不破坏现有调用
- [ ] L4 UAT：见测试计划 U4-12 ~ U4-14（业务方手动验收）

### 全量回归
- [x] 383 通过，2 跳过，0 失败（2026-06-14）

---

## Phase 4 — 批量报告（进入条件：C-02/03/04 模板已确认）
- [ ] skills/dept_weekly_report/ + template
- [ ] skills/monthly_bond_summary/ + template
- [ ] skills/partnership_summary/
- [x]意图路由改 LLM 分类
- [ ] Phase 4 验收

## Phase 5 — Windows + 打包（需切换到 Windows 环境）
- [x] 切换到 Windows，安装 requirements-prod.txt
- [x] 验证 PyWebView 原生窗口
- [x] 验证 Windows toast 通知
- [x] 记录 WebView2 内存基线（docs/memory_baseline.md）
- [ ] PyInstaller 打包测试
- [ ] 最终验收

---

## 待办：尚未使用的数据文件

> 以下文件已评估但暂未纳入当前开发范围，后续按业务需求补充对应的数据字典和功能。

### 投资团队 (testdata/) — 已评估、V1 暂不覆盖

| 文件 | 类型 | 后续关联功能 |
|------|------|------------|
| `实时资产头寸查询(2026-05-15).csv` | 资产头寸 | 持仓查询增强（5.2），可按证券账户维度分析 |
| `申赎数据0515.csv` | 申购赎回 | 产品流动性分析（需先有业务需求） |
| `组合资金账户头寸(2026-05-15).csv` | 资金头寸 | 现金流/头寸管理（需先有业务需求） |
| `账户流水(2026-05-15).csv` | 账户流水 | 资金变动分析（需先有业务需求） |
| `现金流缺口分析(2026-05-15).csv` | 现金流缺口 | 流动性风险管理（需先有业务需求） |
| `估值表查询(2026-05-15).csv` | 估值数据 | NAV 分析增强版（字段结构与净值表不同） |
| `债券质押查询(2026-05-15).csv` | 质押管理 | 质押品监控（需先有业务需求） |
| `质押式回购投资交易查询(2026-05-15).csv` | 回购交易 | 回购交易分析（需先有业务需求） |

### 研究员 (yanjiu/) — 已评估、V1 暂不覆盖

| 文件 | 类型 | 后续关联功能 |
|------|------|------------|
| `底层资产持仓及债券信息表260507.csv` | 底层持仓明细(66列,9.6MB) | 穿透分析(5.2/5.3)，C-01 穿透口径决策关键数据 |
| `内网信评AI生成谈参要点-1.docx` | 参谈要点参考 | meeting_report Skill 的格式参考（非结构化数据） |

> **备注**：`底层资产持仓及债券信息表260507.csv` 优先级最高——含`穿透类型`字段，是 C-01 口径确认后必须支持的数据源。建议 Phase 3 或 Phase 4 补充 `holding_dict.yaml` 中该表的完整字段映射。
