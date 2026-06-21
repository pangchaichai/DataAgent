# DataAgent — 会话交接文件（HANDOFF.md）

> **每次会话结束前，Claude Code 必须更新此文件。**
> 下次会话开始时，优先读取本文件（在 CLAUDE.md 之前）。
>
> 本文件回答三个问题：上次做了什么？现在的状态是什么？下次从哪里开始？

---

## 最后更新
- **日期**：2026-06-21
- **提交**：f9018f5 feat(ui): Phase 4 — Rules page + Home quick-nav, all pages functional
- **分支**：`claude/happy-euler-awvv3j`

---

## 上次会话完成的工作（2026-06-21，第十八轮）

### 多页面导航 UI 重构（Phase 0–4 全部完成）

**背景**：现有 DataAgent 所有功能塞在单页面中，目标是引入可折叠主导航侧边栏，将功能拆分到 6 个独立页面（首页/数据/规则/会话/审计/设置），以平稳过渡为首要原则，不破坏任何现有功能。

**Phase 0 — 基础设施（提交 `1ba8531`）**
- 新建 `ui/css/main.css`：将 index.html 609 行内联 CSS 原封迁出
- 新建 `ui/css/nav.css`：主导航栏专属样式（折叠 52px / 展开 200px + localStorage 持久化）
- 新建 `ui/css/pages.css`：各页面专属样式（随 Phase 逐步填入）
- 新建 `ui/js/router.js`：Hash-based SPA 路由器（navigateTo / register / onHashChange / back）
- 新建 `ui/js/nav.js`：导航折叠/展开/激活状态管理（initNav / toggleNav / setNavActive / navClick）
- 修改 `ui/index.html`：body 结构重组为 `app-shell`（nav-rail + 6 个 page 容器）；header 引入外部 CSS
- 修改 `ui/js/state.js`：新增 `currentPage:'/chat'` 属性
- 修改 `ui/js/dom.js`：`scrollBottom()` 加 `.page.active` 可见性守卫，防 SSE 跨页滚动

**Phase 1 — sidebar.js 拆分 + Chat 页面隔离（提交 `3719c51`）**
- `sidebar.js`（453行 → ~150行）：保留 sessions / compact tables / compact skills / refreshSidebar（加页面感知）
- 新建 `ui/js/data_tables.js`（~190行）：loadTables / deleteTable / loadWorkdir / openProfile / closeProfile / switchProfileTab / loadQualityTab / sortTbl / exportCSV / copyTable / chartFromTable
- 新建 `ui/js/groups.js`（~80行）：loadGroups / toggleGrp / addMember / removeMember / confirmDeleteGroup / showCreateGroup / createGroup
- `main.js`：Router 初始化 + 6 个页面路由注册（含 chat onEnter scrollBottom + focus，settings onEnter loadSettings）

**Phase 2 — Settings 独立页面（提交 `9576a87`）**
- 设置表单 HTML 从弹层（`#settingsPanel`）迁移到 `#page-settings` 容器
- `#settingsPanel` / `#settingsOverlay` 保留为空 shell，防既有 JS 引用报错
- `settings.js`：openSettings() → `Router.navigateTo('/settings')`；closeSettings() → `Router.navigateTo('/chat')`
- `pages.css` 新增设置页布局样式（`.settings-page-*`）

**Phase 3 — 数据源管理页（提交 `b51d6d8`）**
- 新建 `ui/js/pages/data_page.js`：DataPage 对象（onEnter / \_renderTableList / \_loadWorkdir）+ dpTriggerUpload / dpRefreshTableList / dpRefreshWorkdir
- `index.html`：`#page-data` 增加页头（上传按钮）+ 已加载数据区块（`#dataPageTableList`）+ 工作目录区块（`#dataPageWorkdirList`）
- `upload.js`：confirmUploadFile() 加页面感知：Chat 页用 addSysMsg，其他页用 toast；`ST.currentPage==='/data'` 时刷新数据页表格
- `pages.css` 新增数据页样式（`.data-page-*`, `.dp-*`）

**Phase 4 — 分析规则页 + 首页（提交 `f9018f5`）**
- 新建 `ui/js/pages/rules_page.js`：RulesPage 对象（onEnter / \_renderSkills / \_renderGroups），技能列表从 `/api/skills/status` 加载，集团列表从 `/api/groups` 加载
- `index.html`：`#page-rules` 增加技能列表区块（`#rulesPageSkillList`）+ 集团列表区块（`#rulesPageGroupList`）；`#page-home` 增加 4 个快捷导航卡片（数据管理/合规检查/分析技能/开始对话）；`#page-audit` 增加占位内容
- `pages.css` 新增规则页样式（`.rp-skill-card / .rp-group-card / .rp-member-tag`）+ 首页快捷卡片样式（`.rp-quick-card`）

**全程验证**：后端 622 passed, 2 skipped, 0 failed。所有前端页面路由正常，Escape 键支持跨页返回 Chat，导航栏折叠/展开/localStorage 持久化正常。

---

## 上次会话完成的工作（2026-06-18，第十七轮）

### Windows v3.0-beta3 EXE 打包支持

`scripts/package_windows.py` 新增 PyInstaller EXE 打包流程：
- 新增 `BUILD_EXE_BAT` — Windows 批处理脚本，检查虚拟环境 → 安装 PyInstaller → 使用 spec 文件打包 → 复制配置文件到输出目录
- 新增 `PYINSTALLER_SPEC` — 完整的 PyInstaller spec 文件，包含所有 datas（ui/data_dictionary/templates/skills/prompts）、hiddenimports（全部项目模块）、excludes（pytest/matplotlib/scipy）、console=False、UPX 启用
- `write_scripts()` 更新：额外输出 `build_exe.bat` 和 `DataAgent/dataagent.spec`
- `README_TXT` 重写：两种安装方式（run.bat 脚本运行 vs build_exe.bat 打包 EXE）、LLM 配置指南、beta3 变更日志
- 版本号升级为 `v3.0-beta3`
- 生成包：`dist/DataAgent-v3.0-beta3.zip`（88.1 MB）

### 立即可执行的下一步（多页面导航完成后）

1. **浏览器 UAT 验收**（必须）：`python main.py` → 浏览器打开，验证：
   - 左侧 6 个导航项均可点击切换
   - 数据页：上传 CSV → 表格出现在数据页 + Chat 侧栏
   - 规则页：Skills 列表和集团列表正确加载
   - 设置页：保存配置正常，LLM 连接测试正常
   - Chat 页：流式输出中切换到其他页再返回，消息完整
   - 导航栏折叠/展开持久化（刷新后保持状态）
2. **将 `claude/happy-euler-awvv3j` 合入主线**（用户确认 UAT 通过后）
3. **Windows 内测包重建**：在 Windows 机器上重建 beta 包（包含新 UI）
4. 等待 Phase 4 模板确认（C-02/03/04）

---

## 上次会话完成的工作（2026-06-17，第十六轮）

### 企业网关 LLM 适配 + 日志增强

**问题 1 — 企业 LLM 调用失败**：Windows 内测配置企业内网 LLM 后，测试连通成功，但实际发送消息时报"操作遇到异常：'choices'"。

**根因**：企业网关代理（`openai_gateway_proxy.py`）将 OpenAI 标准格式包装为 `{txHeader, txBody: {txEntity: body}}`。代理虽在返回时提取 `txEntity`，但 DataAgent 的 `llm_client.py` 直接用 `data['choices'][0]` 裸访问，任何格式偏差都触发 `KeyError`。

**修复 — 企业网关响应适配器**：
- 新增 `_extract_openai_response()` 静态方法，自动检测并解包网关格式
- `_call()`、`_call_with_messages()`、`_call_streaming()` 三个方法全部适配
- 所有 `data['choices']` 改为 `.get()` 安全访问
- `test_connection()` 增加 choices 字段校验，提前报告格式异常

**问题 2 — 日志不足**：basic 模式下 LLM 请求/响应细节完全不记录，无法排查。

**修复 — 日志增强**：
- `BASIC_CATEGORIES` 新增 `CAT_LLM`：LLM 日志在 basic 模式也始终记录
- 新增 `log_llm_request()`、`log_llm_response()`、`log_agent_error()`、`log_config_change()` 便捷方法
- 失败时自动捕获原始响应预览到 JSONL 日志
- `main.py` 集成 Python `logging.basicConfig`，LLM 模块 debug 日志可输出到控制台
- `loop.py` 失败日志增加上下文（turn、message_count、tool_count）

**测试**：新增 12 个测试（615 总计），覆盖网关格式提取、安全解析、tool_calls 透传、连接校验。

---

## 上次会话完成的工作（2026-06-17，第十五轮）

### LLM 反幻觉两层压缩架构

**问题**：Windows 内测中发现 agent 编造产品名称（用户查询"持仓情况按市值排列"，返回结果中包含上传文件中不存在的产品名）。

**根因分析**：
1. run_sql 返回 200 行完整数据全部写入 session_messages → LLM 上下文膨胀
2. 对话增长后 compress_messages() 将早期工具结果压缩为"[已压缩]"纯文本 → LLM 丢失所有真实数据
3. LLM 用训练知识"补全"缺失数据，产生看似合理但完全虚构的产品名

**解决方案（两层架构）**：

**Layer 1 — 源头精简（`agent/loop.py`）**：
- 新增 `_slim_tool_result_for_llm()` 函数
- run_sql 结果写入 session_messages 前截取前 20 行（`_LLM_MAX_ROWS = 20`）
- 完整数据仍通过 SSE `_table()` 事件推送给前端
- 附带反幻觉提示："请基于这些真实数据回答，不要编造不在此列表中的内容"

**Layer 2 — 历史压缩（`agent/context.py`）**：
- 压缩阈值从 2000 降至 1500 字符
- 保留行数从 10 降至 5（`_COMPRESS_KEEP_ROWS = 5`）
- 智能压缩保留列名 + 前 5 行 + SQL + 反编造注释

**Prompt 加固（`prompts/system_prompt.txt`，上一轮已提交）**：
- 规则 2 从"数字必须精确"扩展为覆盖所有数据值（产品名称、主体名称、资产代码、评级）
- 新增"如果工具返回了 N 条数据，只能展示这 N 条"约束

**Token 预算**：200 行×10 列 ≈ 6,938 tokens → 20 行 ≈ 744 tokens → 5 行 ≈ 200 tokens

**测试**：603 passed, 2 skipped, 0 failed（含更新的 test_context.py 阈值匹配测试）

---

## 上次会话完成的工作（2026-06-17，第十四轮）

### UI Stitch 设计系统回退 + 项目文档同步 + Windows beta2 包

**回退原因**：Stitch UI 重构（Phase 0-5）效果不理想，用户决定回退到原版 UI。

**回退操作**：
1. `git checkout eefaa55 -- ui/` 将 `ui/` 目录恢复到 Stitch 前的状态
2. 删除 Stitch 新增的文件：`ui/dist/` / `ui/fonts/` / `ui/js/pages/` / `ui/js/router.js` / `ui/src/input.css`
3. 保留 `scripts/build-css.sh`（无害备用）

**影响范围**：仅 `ui/` 目录。后端代码（calculators / agent / tools / tests）完全不受影响。
全量测试 601 passed, 0 failed 确认无回归。

**文档同步**：
- PROGRESS.md：Stitch 条目标记为"已回退"，当前阶段描述移除 Stitch 引用
- HANDOFF.md：新增回退记录，更新"立即可执行的下一步"（移除 Stitch 相关项）
- START_HERE.md：移除 Stitch 阶段引用，更新测试数据
- CLAUDE.md：版本历史新增回退条目

---

## 上次会话完成的工作（2026-06-17，第十三轮）

### 计算器字段映射参数化（Path B 方案实施）

**问题**：所有 7 个固化计算器（B 类）SQL 中硬编码了语义列名（如 `产品名称`、`限额占用方主体`），
当用户上传的数据源物理列名不同时（如 `产品简称`、`限额占用方`），计算器直接报列名不存在错误。
而 A 类 run_sql 通过 `apply_field_map()` 已正确处理了这个问题——B 类计算器完全绕过了翻译层。

**解决方案（Path B 全参数化）**：
1. **新建 `calculators/columns.py`**：语义列名常量（20+）+ `resolve_columns()` 函数 + `ColumnResolutionError` 异常
2. **修改全部 7 个计算器**：新增 `cols=None` 参数，SQL 中用 `cols` 字典获取物理列名，通过 `SELECT "物理列" AS 语义别名` 保证下游 DataFrame 列名不变
3. **修改 `agent/tool_dispatch.py`**：新增 `_resolve_cols_for_table()` 和 `_resolve_mv_field()` 辅助函数，在调用计算器前自动解析字段映射
4. **修改 `tools/data_loader.py`**：新增 `get_field_map_for_table()` 接口（按表名获取单表字段映射）
5. **新建 `tests/test_column_resolution.py`**：26 个回归测试（基础功能 7 + 计算器映射 10 + dispatch 层 5 + 端到端 4）

**向后兼容**：`cols=None` 默认值使所有既有测试无需修改即可通过。

**测试结果**：601 passed, 2 skipped, 0 failed（77% 覆盖率，含 26 个新增测试）

---

## 上次会话完成的工作（2026-06-17，第十二轮）

### 回归测试 + UAT 验证 + 前端-API 字段不一致 Bug 修复

**测试执行**：
- L1 全量回归：575 passed, 2 skipped, 0 failed (76% 覆盖率)
- L2 功能测试：16 个 JS 文件语法 + 14 个 API 端点 + 9 个 Skills + 7 个字典 + 7 个计算器 + DOM 安全性 — 全通过
- L3 集成测试：CSV 上传流程 + SSE 流 + 设置读写 + 报告导出 + 日志系统 + 集团 CRUD + Skill Builder + 数据表剖析 — 全通过
- UAT 字段一致性检查：路由绑定 + @mention + 深色模式 — 全通过

**修复 4 个前端-API 字段不一致 Bug**：
1. `sources.js` 数据预览空值率：`c.null_pct` → `c.null_rate`（API 返回小数，需 ×100 转百分比）
2. `sources.js` 数据预览示例值：`c.sample` → `c.samples`（API 返回数组）
3. `dashboard.js` LLM 状态：`health.llm_ok` → `health.llm_status === 'online'`（永远显示"离线"）
4. `sources.js` 数据源列数：`t.columns || t.col_count` → `t.cols ||`（API 返回 `cols` 字段）

**SPA 功能归属**：集团系 CRUD 从 Rules 页面迁移至 Sources 页面完成（上一轮操作）

### 前一轮（第十一轮）：全版本综合测试 — 前后端全覆盖

**测试范围**：66 个后端模块 + 17 个 JS 文件 + 54 个 API 端点 + 9 个 Skills + 7 个数据字典 + 7 个计算器

**新增 183 个自动化测试**（3 个新测试文件）：

**`tests/test_query_runner.py`（90 个测试）**
- SQLGuard 安全边界：DDL 拒绝（8）+ 危险函数拒绝（5）+ 系统命令拒绝（7）+ 系统表拒绝（4）+ LIMIT 校验（5）
- 合法查询接受：基本/WHERE/聚合/CTE/JOIN/子查询等（10）
- 表名动态校验（2）+ 注释处理（3）+ 边界情况（4）
- apply_field_map 字段映射（8）+ execute_query 完整执行（11）
- 参数化全覆盖：BLOCKED_COMMANDS（18）+ BLOCKED_FUNCTIONS（5）

**`tests/test_api_endpoints.py`（45 个测试）**
- AppCreation（3）+ ChatAPI（10）+ DataAPI（8）+ ConfigAPI（6）+ SystemAPI（12）+ ReportAPI（6）
- 覆盖全部 6 个 Blueprint 共 54 个端点

**`tests/test_core_modules.py`（48 个测试）**
- SessionStore（6）+ EntityNormalizer（10）+ QualityAuditor（8）+ ComplianceAudit（9）+ EntityManager（15）

**L2 功能测试**（手动验证脚本）：
- DOM ID 交叉引用：101 个引用 vs 126 个定义，15 个缺失全部有 null 保护
- 静态资源：23 个文件全部 200
- Blueprint 注册：6/6
- Skill 预检：9/9 类型正确
- 计算器签名：7/7 一致

**L3 集成测试**（手动验证脚本）：
- 应用启动与首页（HTML 结构验证）
- CSV 上传完整流程（upload → confirm → tables → delete）
- SSE 流合约（stream_id → text/event-stream → stream_end）
- 设置读写循环（读 → 写 → 验证持久化）
- 报告模板与 Word 导出
- 日志系统端到端

**最终结果**：575 passed, 2 skipped, 0 failed, 76% 覆盖率
**Bug 发现**：0 个新 bug（前一轮修复的 2 个 DOM ID bug 已确认有效）

**SPA 功能归属修复**（测试中发现的问题，已修复）：
- `ui/js/pages/sources.js`：新增集团系 CRUD 区块（创建/删除集团、添加/移除成员、可展开详情、Material Symbols 图标）+ 工作目录区块（文件列表、hover 加载按钮、未配置/空目录状态处理）
- `ui/js/pages/rules.js`：精简为仅分析模板 + 自定义参数（集团系移至 Sources 页面）
- 两者后端 API + sidebar.js 函数均完好，仅 SPA 迁移时缺少入口调用

---

## 上次会话完成的工作（2026-06-16，第十轮）⏪ 已回退

### Stitch Design System — Phase 2-5 图标迁移 + 聊天气泡重构（已回退，见第十四轮）

**UI 全面从 emoji/Unicode 图标迁移到 Material Symbols Outlined**，涉及 11 个文件：

**`ui/js/render.js` — 完整重写（Stitch 设计系统）**
- 所有渲染函数使用 Stitch 类名：`.bubble-ai`、`.bubble-user`、`.stitch-card`、`.stitch-table`
- Material Symbols 图标：`neurology`（AI 头像）、`person`（用户头像）、`check_circle`、`bar_chart` 等
- AI 气泡：非对称圆角（左上 0）+ 白色背景 + 蓝色标签
- 用户气泡：非对称圆角（右上 0）+ 蓝色背景 (#316bf3)
- 表格、图表、确认卡片、计划卡片等全部使用 Tailwind 工具类

**`ui/js/chat.js` — 流式气泡 + 过程包装器图标**
- 流式气泡结构匹配 `addAgentHTML()` — neurology 图标 + DataAgent AI 标签 + 状态徽章 + 复制/导出按钮
- 过程包装器：`↻`→`sync`、`▸`→`expand_more`、`✓`→`check_circle`
- SSE 事件图标：`💭`→`psychology`、`⚡`→`bolt`
- `breakStream()` 状态徽章从"生成中"更新为"就绪"

**`ui/js/main.js` — 欢迎面板 Material Symbols**
- 📊→`bar_chart`、✅→`check_circle`、⚡→`bolt`、💬→`chat_bubble`、📈→`trending_up`
- Stitch 卡片布局 + `suggestion-pill` 快捷按钮

**`ui/js/dom.js` — 兼容性更新**
- `copyBubble()` 支持新旧两种 DOM 结构（`.bubble-ai` 和 `.bubble`）
- `setSendMode()` 使用 Material Symbols HTML

**`ui/js/upload.js`** — 文档结果气泡：`📄`→`description` Material Symbol

**`ui/js/settings.js`** — LLM 状态：emoji 彩色圆点→Tailwind 圆点（`bg-success`/`bg-error`），`✓`/`✗`→Material Symbols

**`ui/js/sidebar.js`** — 分组箭头 `▸`→`chevron_right`，复制反馈 `✓`→`check`，质量图标更新

**`ui/js/skill_builder.js`** — 校验图标：`✕`→`cancel`、`✓`→`check_circle`、`⚠`→`warning`

**`ui/index.html`** — LLM 状态点从 HTML 实体改为 Tailwind 圆点

**`ui/src/input.css`** — 新增 `.bubble-ai.streaming::after` 闪烁光标动画 + `@keyframes blink`

**`ui/dist/styles.css`** — 重新编译（34733 字节）

---

## 上次会话完成的工作（2026-06-15，第九轮）

### v3.0 内测 Bug 修复 + UX 优化（全量交付）

**Bug 1 修复：`agent/loop.py`**
- `MAX_TURNS`: 15 → 25，复杂任务不再触发超限错误
- 会话级/循环级错误提示改写，去掉误导性"输入继续"，改为引导"新对话"

**Bug 2 修复：列名映射自动替换**
- `tools/query_runner.py`: 新增 `apply_field_map(sql, field_map)` 函数（sqlglot transformer）
- `tools/data_loader.py`: 新增 `get_all_field_maps()` 合并所有已加载表的字段映射
- `agent/tool_dispatch.py`: `_tool_run_sql()` 在 SQLGuard 校验前调用 `apply_field_map`
- `agent/skill_preflight.py`: 字段映射提示改为强制语气

**Bug 3 修复：Skill 注入不再污染用户消息**
- `agent/loop.py`: skill_note 改为独立 system 消息（含 `skip_display=True`），原用户消息保存 `_display_content`
- `session_store.py`: 保存 `display_content` / `skip_display` 字段；标题使用 `_display_content`
- `api/chat.py`: session detail 端点传递 `display_content` / `skip_display`
- `ui/js/sidebar.js`: `loadSes()` 跳过 skip_display 消息，使用 display_content 渲染用户气泡

**UX 改善**
- `ui/js/sidebar.js`: DOM ID `tablesCount` → `tableCountH`（功能性修复）；"卸载" → "移除"
- `ui/js/chat.js`: `doConfirm(true)` 改为静默续跑（不显示"确认继续"气泡）；confirm/ask 卡片出现后自动滚动定位
- `ui/js/upload.js`: "入库" → "加载"
- `ui/js/render.js`: "查看公式/SQL" → "查看计算过程"
- `ui/js/settings.js`: DeepSeek 选项新增橙色警告框 + 首次选择二次确认弹窗
- `ui/js/main.js`: 欢迎面板"创建 Skill" → "创建分析"
- `ui/index.html`: "Skills" → "分析功能"；"确认入库" → "确认导入"；"Skill 创建向导" → "创建自定义分析"；"编辑 SKILL.md 内容" → "编辑分析配置"；表类型下拉去掉英文括号；textarea 绑定 checkMention

**新增测试**
- `tests/test_tools.py`: `TestApplyFieldMap` 6 个单测（基本替换/字面量保护/多列/空映射/未知列/解析失败）
- `tests/test_agent.py`: `TestSkillInjectionDisplay` 3 个单测（system 消息注入/标题提取/历史过滤）
- `test_loop_max_turns` 改用 `MAX_TURNS` 常量，不硬编码 15

---

## 上次会话完成的工作（2026-06-14，第八轮）

### v3.0 Week 4 — tools_spec 拆分 + 欢迎面板统一 + Header 重组

**新建 `agent/tool_defs.py`（483 行）**：
- 从 tools_spec.py 提取 `TOOL_DEFINITIONS`（13 个工具定义，OpenAI function-calling 格式）
- 提取 `ToolResult` / `ToolContext` dataclass 定义
- 纯数据层，无副作用导入

**新建 `agent/tool_dispatch.py`（830 行）**：
- 从 tools_spec.py 提取 `dispatch_tool` + 所有 `_tool_*` 实现函数（13 个）
- 提取 `_get_tool_schema` / `_validate_tool_args` / `_with_timeout`
- 顶部从 `agent.tool_defs` 导入 `ToolContext`（不重复定义）

**改造 `agent/tools_spec.py` 为薄转发层（~30 行）**：
- 从 `agent.tool_defs` re-export `TOOL_DEFINITIONS / ToolContext / ToolResult`
- 从 `agent.tool_dispatch` re-export 所有公开符号
- 所有从 `agent.tools_spec` 导入的现有代码无需修改（向后兼容）

**改造 `ui/index.html` Header（移除技术参数）**：
- 移除 `ramMb`、`tokenUsed`、`tokenLimit` 三个 chip
- 新增 `llmStatus` span：显示"AI 就绪" / "AI 离线"（非技术术语）
- 新增 `tableCountChip`：格式"▣ N张表"，点击展开侧边栏数据表区，初始隐藏
- 新增 `.wc-skill-btn` CSS（欢迎面板 Skill 快捷按钮样式）
- 欢迎面板静态 HTML 替换为注释占位，改由 JS 渲染

**改造 `ui/js/main.js`（欢迎面板统一 + 状态更新）**：
- 新增 `buildWelcomePanel(tables)` 函数：无数据时 4 卡片布局（上传/合规/创建Skill/对话）；有数据时显示表数量 + 可执行 Skill 快捷按钮 + 示例查询
- 改造 `resetChat()`：用 `buildWelcomePanel(window._lastLoadedTables||[])` 替换内联 HTML
- 新增 `updateTableCountHeader(n)`：更新 Header 中的表数量 chip
- 改造 `pollHealth()` → 使用内部 `_applyHealth(d)` 更新 `llmStatus` / `llmDot`，移除旧 RAM/Token 更新逻辑
- 改造 `updateWelcomeExamples(tables)`：存入 `window._lastLoadedTables`，调用 `updateTableCountHeader`，整体重渲染欢迎面板
- 初始化：`buildWelcomePanel([])` 渲染初始欢迎面板，`AgentStatus.init()`

**改造 `ui/js/sidebar.js`（loadTables 联动 Header）**：
- `loadTables()` 成功后调用 `updateWelcomeExamples(tables)` 同步 Header 表数量和欢迎面板

**更新 `docs/user-guide.md`（v3.0 用户手册）**：
- 版本号更新至 v3.0，最后更新日期 2026-06-14
- 界面介绍章节重写：反映新 Header（AI 就绪/张数）、Skill 卡片、置信度标签
- Skills 章节重写：说明卡片化操作方式（就绪状态、一键执行、缺数据提示）
- 版本更新记录表：补充 v3.0 所有新功能

**新建 `data/test_plans/20260614_v3_week4_toolspec_split_ui_unify.md`**：
- L1~L3 测试用例设计（5 个 L1，2 个 L2，4 个 L3）
- 执行结果全部填写：383 通过，2 跳过

**测试结果**：383 通过，2 跳过，0 失败（tools_spec 拆分无回归）

---

## 立即可执行的下一步

### 1. UAT 验收（L4）
- 需浏览器/Windows 环境手动验收：聊天流程、中文上传、Skill 执行、@mention、深色模式、表剖析、Skill Builder、Word 导出

### 2. UI 优化（待用户确认方向）
- Stitch 设计已回退，如需重新设计 UI 需先确认设计方向
- agent_status.js 猫头鹰状态栏保持现状

### 3. Phase 5（Windows 打包测试）
- PyInstaller 打包，WebView2 Runtime 检测
- Windows 10/11 完整功能验收
- 内存基准测试（目标 Python 进程 < 200MB）

### 4. v3.1 推迟功能（待 ExecutionTracker 积累 2-4 周数据后）
- ExecutionTracker 读取端（`/api/eval/stats`，退化信号检测）
- Eval Framework 四级评估（需 1000+ trace 数据和 baseline）
- 3 个新 Skill（risk_dashboard / maturity_alert / product_comparison）

### 5. 近期待确认的外部阻塞项
- C-02（周报模板）、C-03（月报模板）、C-04（Word 格式）待业务方确认
- Phase 4（批量报告）进入条件

---

## 上次会话完成的工作（2026-06-14，第七轮）

### v3.0 Week 3 — Skills 修复 + 新工具 + 置信度标注

**删除 `skills/client_meeting_report/`**：与 `meeting_report` 完全重复，整目录移除

**更新 `skills/meeting_report/SKILL.md`**：
- 吸收 client_meeting_report 触发词：`客户合作情况、准入投放、业务合作报告` + `拜访材料`
- 新增 Step 5 `request_confirmation`（在汇总后要求用户确认再输出完整报告）

**更新 `skills/partnership_summary/SKILL.md`**：
- 将非正式"人工确认节点"改为正式 Step 4 `request_confirmation` 工具调用步骤

**扩展 `agent/skill_preflight.py`**：
- 新增 `_skill_dir(skill_name)` 工具函数：返回 skills/{name} 目录 Path
- 新增 `template_file` 存在性检查：frontmatter 有 `template_file` 字段时，若文件不存在则返回 `blocked=True`
- 影响：`monthly_bond_summary`（缺模板）将正确阻断；`dept_weekly_report`（有模板）不受影响

**扩展 `agent/tools_spec.py`**：
- 新增 `list_tables` 工具：调用 `tools.data_loader.get_loaded_tables()` 返回已加载表元数据
- 新增 `export_data` 工具：直接用 `ctx.duckdb_conn.execute()` 绕过 SQLGuard，写 CSV 到 `data/outputs/`
- dispatch_map 新增两个入口

**更新 `agent/loop.py`**：
- `_text(text, confidence=None)` 新增可选参数；有值时在 SSE 事件中附加 `confidence` 字段
- LLM 文本回复设 `confidence="ai_generated"`

**更新 `agent/fast_path.py`**：
- `run_fast_path` yield 的 text 事件携带 `confidence="auditable"`

**更新 `ui/js/chat.js`**：
- `handleChunk` text 分支：第一个文本块初始化 `streamConf = chunk.confidence`，后续块累积
- `breakStream()` 结束时若有 `streamConf`，在气泡末尾追加 `.conf-tag` span

**更新 `ui/js/state.js`**：
- 新增模块级变量 `streamConf`（置信度追踪）

**更新 `ui/index.html`**：
- 新增 `.conf-tag.conf-auditable / .conf-verify / .conf-ai_generated` CSS（含深色主题）
- placeholder 去技术化：移除 `@表名` 技术术语，改为自然语言示例

**新建 `tests/test_week3.py`（14 个测试，全绿）**：
- L1-01~L1-08：Skills 合并/preflight 模板检查/新工具/置信度字段
- L2-01~L2-03：`/api/skills/status` 反映 Week 3 变更

**测试结果**：383 通过，2 跳过，0 失败（新增 14 个）

---

## 立即可执行的下一步（Week 4）

### 优先级排序
1. **tools_spec.py 拆分**（Day 3）：拆为 `agent/tool_defs.py` + `agent/tool_dispatch.py`，保留转发层
2. **简化仪表盘**（Day 1-2）：消息流内嵌版，复用 Process Wrapper 位置，步骤列表+高亮+数据源
3. **欢迎面板统一**（Day 3 追加）：合并 index.html 和 resetChat() 两份面板为 `buildWelcomePanel()`
4. **Header 重组**（Day 3 追加）：移除 RAM/Token，新增"AI 就绪/N 张表"显示
5. **端到端联调**（Day 4）：持仓+净值真实数据完整流程
6. **文档更新**（Day 5）：CLAUDE.md / PROGRESS.md / HANDOFF.md

### 参考资料
- 演进方案：`docs/v3-evolution-final-plan.md` Week 4 章节
- 测试计划：需在 Day 1 写 `data/test_plans/20260614_v3_week4_*.md`（T1-T4 关卡）

---

## 上次会话完成的工作（2026-06-14，第六轮）

### v3.0 Week 2 — Skill 卡片 + fund_nav_report 合规修复

**新增 `GET /api/skills/status` 端点**（`api/skill_api.py`）：
- 批量运行所有 Skill 的 preflight 检查
- 返回 `{skills: [{name, description, calc_type, ready, missing_files}]}`
- 30s TTL 缓存（`_skill_status_cache`），避免重复 preflight

**新增 `POST /api/skills/<name>/execute` 端点**（`api/skill_api.py`）：
- 验证 Skill 存在，否则返回 404
- 构造 `message = "__skill__:{name}"` 精确触发，复用 SSE queue/thread 机制
- 返回 `{ok: true, stream_id: "..."}`，前端用 `/api/stream/<sid>` 读取事件

**更新 `ui/js/sidebar.js`**：
- `loadSkills()` 改为调用 `/api/skills/status`，渲染 Skill 卡片（标题+描述+就绪状态+执行按钮）
- 表名新增点击事件：`onclick="openProfile('{name}')"` → 直接打开表结构剖析

**新增 `executeSkill(skillName)` 函数**（`ui/js/chat.js`）：
- POST 到 `/api/skills/{name}/execute`，获取 stream_id
- 用 `EventSource` 读取 SSE 流，复用 `handleChunk()` 处理所有事件

**修复 `skills/fund_nav_report/SKILL.md`（P0 合规问题）**：
- 原：`calc_type: exploratory`，LLM 生成 SQL → 严重违反 B 类合规约束
- 改：`calc_type: fixed`，新增 `fixed_calculators: [nav_metrics, asset_structure, credit_distribution]`
- 新增 `required_table_types: [nav, holding]`

**扩展 `agent/skill_loader.py`**：
- `SkillInfo` 新增 `fixed_calculators: list[str]` 字段
- `_score_skill()` 新增 `__skill__:{name}` 精确触发（返回分数 100）

**扩展 `agent/fast_path.py`**：
- `can_fast_path()` 支持 `fixed_calculators` 列表（全部在映射表中才返回 True）
- `run_fast_path()` 支持多 calculator 顺序调用，合并结果
- 新增 `_fmt_nav_metrics()`, `_fmt_asset_structure()`, `_fmt_credit_distribution()` 格式化函数

**新建 `tests/test_skill_api.py`（17 个测试，全绿）**：
- L1：can_fast_path 判断（4 变体）、__skill__ 精确触发（3）、preflight 场景（3）
- L2：skills/status 端点（4）、skills/execute 端点（3）

**修复 `tests/test_agent.py`**：
- `test_fixed_skill_has_calculator`：接受 `fixed_calculator` 或 `fixed_calculators` 任一字段

**测试结果**：369 通过，2 跳过，0 失败（新增 17 个）

---

## 立即可执行的下一步（Week 3）

### 优先级排序
1. **Skills 修复**（Day 1）：合并 meeting_report + client_meeting_report；partnership_summary 加 request_confirmation
2. **模板检查**（Day 2）：skill_preflight 增加模板文件存在性检查（dept_weekly_report/monthly_bond_summary）
3. **新工具**（Day 3）：`export_data`（CSV 导出+下载链接）+ `list_tables`（返回已加载表元数据）
4. **置信度标注**（Day 4）：SSE 事件新增 `confidence` 字段 + 前端标签渲染
5. **UX 细节**（Day 4 追加）：placeholder 去技术化 + 错误消息增加"重试"按钮

### 参考资料
- 测试计划：`data/test_plans/20260614_v3_week2_skill_cards_and_nav_fix.md`（执行结果已填写）
- 演进方案：`docs/v3-evolution-final-plan.md`（Week 3 详细内容）
- 现有 Skills：`skills/` 目录，重点看 meeting_report、partnership_summary、dept_weekly_report

### Week 3 开始时必须先做

```
python scripts/project_check.py
# 然后：设计 Week 3 测试计划（T1-T4 关卡，写入 data/test_plans/）
# 再：开始编码
```

---

## 上次会话完成的工作（2026-06-14，第五轮）

### v3.0 Week 1 — 快速路径 + 执行追踪

**新建 `agent/fast_path.py`**：
- `can_fast_path(skill_info)` — 判断是否满足快速路径条件（calc_type=fixed + 已知 calculator）
- `run_fast_path(...)` — 直接调用 `dispatch_tool("run_calculator", ...)` 跳过 LLM，yield SSE 事件
- `_CALC_NAME_MAP` — 7 种 fixed_calculator 路径 → calculator 短名映射
- `_fmt_entity_concentration()` — 按 SKILL.md 定义输出格式化超标提示（含 ✅ 无超标场景）
- 末尾调用 execution_tracker 写追踪日志

**新建 `agent/execution_tracker.py`**：
- JSONL 写入端，线程安全，写入 `data/traces/traces_YYYY-MM-DD.jsonl`
- 读取端/stats API/退化信号推迟到 v3.1（积累 2-4 周数据后实现）

**更新 `agent/loop.py`**：
- preflight 之后、Tool-calling 循环之前插入 `try_fast_path` 分支
- `can_fast_path()` 为 True 时 `yield from run_fast_path(...)` 并直接 `return`

**更新 `skills/concentration_monitor/SKILL.md`**：
- 新增 `default_args` 字段（向后兼容，已在 SkillInfo.metadata 中自动可读）

**新建 `tests/test_fast_path.py`（11 个测试全绿）**：
- can_fast_path 4 种判断场景、SSE 事件顺序、breach/no-breach 格式化
- loop.py 集成：concentration_monitor 触发词 → LLM call_count == 0
- ExecutionTracker JSONL 写入 + 截断验证

**测试结果**：352 通过，2 跳过，0 失败（新增 11 个）

---

## 上次会话完成的工作（2026-06-14，第四轮）

### 自动状态同步机制

**新建 `scripts/sync_project_state.py`**：
- 自动运行 `pytest`，写入 `data/test_reports/latest_summary.json`
- 自动更新 `START_HERE.md` 分支/测试状态行
- 自动更新 `HANDOFF.md` "最后更新"块（日期/提交/分支）
- 明确列出仍需 Claude 手动完成的叙述性内容

**更新 `.claude/settings.json`**：
- `Stop` hook：改为直接运行 `sync_project_state.py`（而非仅提示）
- 新增 `PostToolUse` hook on `Bash`：git commit 后自动触发 `--no-test` 快速同步

---

## 上次会话完成的工作（2026-06-14，第三轮）

### 项目管理完整性审计与修复

**问题发现与修复**：

1. **依赖版本过时（requirements-dev.txt）**
   - `sqlglot==23.12.2` → `>=23.0.0`（已验证 30.11.0 可用）
   - `duckdb==0.10.3` → `>=1.0.0`（已验证 1.5.3）
   - `pandas==2.2.2` → `>=2.2.0`（已验证 3.0.3）
   - 其余过旧固定版本均改为 `>=` 兼容约束

2. **project_check.py 陈旧技术债清除**
   - 移除已解决的 KNOWN_GAPS（I-7/I-9/I-10 早于 2026-06-08 修复）
   - 替换为 v3.0 演进下一步行动列表

3. **START_HERE.md 大幅更新**
   - 更新至当前分支和正确测试结果
   - 补充 v3.0 演进状态和 Skill v3 完成状态

4. **新建 docs/user-guide.md**
   - 面向投资业务人员的完整使用说明（约 300 行）
   - 涵盖：启动、上传、查询、Skills 详解、图表、导出、设置、FAQ、数据安全

5. **测试全绿**
   - 修复缺失依赖（sqlglot / duckduckgo-search / rank_bm25）
   - 最终结果：341 通过，2 跳过，0 失败

---

## 上次会话完成的工作（2026-06-14，第二轮）

### DA 小猫头鹰任务进度动画组件（已完整实现）

新增 Agent 任务状态栏，位于输入框上方，随任务进度动态展示卡通猫头鹰（DA）角色。

**实现内容**：

1. **`ui/js/agent_status.js`（新建，~230行）**
   - IIFE 模块，公开 API：`init / onNewMessage / onThinking / onPlan / onPlanStep / onToolStart / onToolEnd / onError / onConfirm / onAsk / onStreamEnd / onStop / onResume / dismiss`
   - 内联 SVG 猫头鹰：耳羽/头/身/腹/眼白/瞳孔高光/金属眼镜框+鼻桥/橙色喙/蓝色领结/翅膀
   - 5 种展示模态：thinking（漂浮+dots）/ planned（时间轴）/ executing（猫头鹰跳至当前步骤）/ simple（单工具）/ done（彩色完成状态）
   - 6 种完成状态：success（绿✓）/ hard（橙≈）/ partial（黄?）/ failed（红✗）/ stopped（灰⏸）/ waiting（蓝脉冲）
   - CSS transition 驱动猫头鹰在时间轴上平滑移动，每步触发 owlJump 动画

2. **`ui/index.html`（修改）**
   - 新增 CSS：`--owl-body/belly/wing/glasses` 变量 + 深色主题适配
   - 新增 7 个 @keyframes：owlFloat / owlWork / owlJump / owlCelebrate / owlShake / owlPulseGlow / asbDot
   - 新增时间轴/状态栏全部 CSS 类（`.asb-*`, `.da-owl.*`）
   - 在 chat-outer 与 inputbar 之间插入 `<div id="agentStatusBar" class="agent-status-bar asb-hidden"></div>`
   - 在 main.js 之后插入 `<script src="/static/js/agent_status.js"></script>`

3. **`ui/js/chat.js`（修改）**
   - `sendMessage()` → `AgentStatus.onNewMessage()`
   - `stopStream()` → `AgentStatus.onStop()`
   - `handleChunk()` 所有事件分支末尾追加对应 AgentStatus 调用
   - `doConfirm()` / `doAsk()` → `AgentStatus.onResume()`

4. **`ui/js/main.js`（修改）**
   - Init 块中加 `AgentStatus.init()`

---

## 上次会话完成的工作（2026-06-13 ~ 2026-06-14，第一轮）

### v3.0 演进方案综合评估与最终实施计划

对现有 `docs/v3-architecture-evolution.md`（1318行）进行了完整的专家级评审，产出最终可执行方案：

1. **逐 Track 评审判定**（原方案 vs 推荐方案对比表）：
   - Track 1 ToolRegistry → **ADJUST**（降级为文件拆分，80%收益20%成本）
   - Track 2A 快速路径 → **APPROVE（P0）**（补充 default_args 参数来源方案）
   - Track 2B ExecutionTracker → **APPROVE（简化版，仅写入端）**
   - Track 2C D-term → **DEFER**（误报风险高，需先有数据）
   - Track 3 Skill卡片 → **APPROVE，提升为 P0**
   - Track 4 Eval Framework → **DEFER**（缺 baseline 数据）
   - 仪表盘 → **ADJUST**（简化为消息流内嵌）
   - 置信度标注 → **APPROVE**（集中交付）
   - fund_nav_report → **P0 合规修复**（B类场景违规使用LLM SQL）

2. **发现 6 个原方案未覆盖的问题**（合规风险、参数来源、handler签名、影响面、迁移策略、内存预算）

3. **制定 4 周现实版实施方案**：
   - Week 1: 快速路径 + ExecutionTracker 写入端
   - Week 2: Skill 卡片 + 一键执行 + fund_nav_report 修复 + 侧边栏 UI
   - Week 3: Skills 修复 + 新工具 + 置信度标注 + 交互体验
   - Week 4: 简化仪表盘 + tools_spec 拆分 + 全局 UI 统一 + 文档

4. **补充 UI 设计优化方案**（第五章，6 类问题 + 7 项具体优化）：
   - 5.1 侧边栏 Skill 卡片化 + 数据表直达
   - 5.2 智能快捷按钮（上下文感知）
   - 5.3 欢迎面板统一 + 状态感知
   - 5.4 Header 信息重组（面向业务用户）
   - 5.5 输入体验优化（去技术化）
   - 5.6 消息体验增强（导出Word + 错误重试）

### 产出文件
- `docs/v3-evolution-final-plan.md` — 最终实施计划（约 500 行），作为下一步升级的主要输入材料

---

## 当前项目状态

### 阶段
```
v2.0 全部完成 + Skill v3 已合并主线 + 计算器字段映射参数化完成
Stitch UI 重构已回退（效果不理想）
v3.0 Week 1-4 已完成
下一步：UAT 验收 / UI 重新设计（待确认方向）/ Phase 5 Windows 打包
```

### 关键文档关系
```
docs/v3-architecture-evolution.md  ← 原始方案（1318行，供参考）
docs/v3-evolution-final-plan.md    ← ★最终实施计划（执行依据）
```

### v3.0 Week 1 完成情况
- [x] `agent/fast_path.py` — 快速路径（跳过 LLM）
- [x] `agent/execution_tracker.py` — JSONL 写入端
- [x] `agent/loop.py` — try_fast_path 集成
- [x] `skills/concentration_monitor/SKILL.md` — default_args 字段
- [x] `tests/test_fast_path.py` — 11 个测试全绿

### 测试
- **结果**：601/601 通过，2 跳过，0 失败（77% 覆盖率）
- **最后运行**：2026-06-17

### 已知外部阻塞项
- Phase 4 进入条件：C-02（周报模板）、C-03（月报模板）、C-04（Word 格式）待业务方确认
- Phase 5 PyInstaller 打包：需 Windows 11 环境执行

---

## 立即可执行的下一步（按优先级排序）

### 1. v3.0 Week 2 — Skill 卡片 + 一键执行（P0）

**Day 1-2: API**
- `api/skill_api.py` 新增 `GET /api/skills/status`（批量 preflight，30s 缓存）
- `api/skill_api.py` 新增 `POST /api/skills/<name>/execute`（复用 SSE 流）

**Day 3-4: 前端**
- `ui/js/sidebar.js` 改造：`loadSkills()` 渲染卡片（描述+就绪状态+执行按钮）
- `ui/js/chat.js` 新增 `executeSkill()` 复用 SSE 事件流

**Day 4 追加: 数据表直达**
- `sidebar.js` 表名点击 → `openProfile(tableName)`（目前只有 × 按钮无点击）

### 2. fund_nav_report 合规修复（P0，Week 2 Day 5）
- `skills/fund_nav_report/SKILL.md` calc_type 改 fixed
- 串联 nav_metrics + asset_structure + credit_distribution 三个已有 calculator

### 3. Windows 内测包重建（可并行）
- 从主线重新构建，验证 Skill v3 + 工作目录功能

---

## 关键设计决策记录

| 决策 | 原因 | 影响 |
|------|------|------|
| OCP 分层：loop.py 稳态 / skill_preflight.py 敏态 | 新增 Skill 准备逻辑不改核心循环 | 所有 Skill 相关改进集中在 skill_preflight.py |
| 工作目录文件不复制到 uploads/ | 避免大文件重复占用磁盘 | load_file() 直接从 workdir 路径入库 |
| ToolRegistry 降级为文件拆分 | 当前仅 11 工具 7 calculator，完整 Registry 收益不足 | Week 4 拆分 tools_spec.py 为 tool_defs + tool_dispatch |
| Eval Framework 推迟到 v3.1 | 缺 baseline 数据，阈值无统计依据 | 先跑 ExecutionTracker 积累 2-4 周数据 |
| 仪表盘简化为消息流内嵌 | 1366x768 分辨率下独立面板压缩聊天区 19% | 用户反馈不足再升级为独立面板 |
| fund_nav_report 提升为 P0 修复 | B 类合规场景违规使用 LLM SQL，"精确的错误"风险 | Week 2 串联 3 个已有 calculator |

---

## 本次会话修改的文件清单

```
# 本轮（第十四轮）— UI Stitch 回退 + 文档同步：
ui/                                # 整目录回退到 Stitch 前版本（eefaa55）
  ↑ 删除：ui/dist/ / ui/fonts/ / ui/js/pages/ / ui/js/router.js / ui/src/input.css
  ↑ 还原：ui/index.html / ui/js/*.js（9 文件恢复原版）
HANDOFF.md                         # 新增第十四轮记录，更新下一步（移除 Stitch 项）
PROGRESS.md                        # Stitch 条目标记"已回退"，当前阶段描述更新
START_HERE.md                      # 更新分支/测试/阶段状态
CLAUDE.md                          # 版本历史新增回退条目

# 上轮（第十三轮）— Path B 字段映射参数化：
calculators/columns.py             # 新建：语义列名常量 + resolve_columns()
calculators/*.py（7 个）            # 修改：新增 cols=None 参数
agent/tool_dispatch.py             # 修改：新增字段映射解析层
tools/data_loader.py               # 修改：新增 get_field_map_for_table()
tests/test_column_resolution.py    # 新建：26 个回归测试
data/test_plans/20260617_calculator_field_mapping.md  # 新建：测试计划
```

---

## 会话交接模板（下次会话结束时复制此模板填写）

```markdown
## 最后更新
- **日期**：2026-06-16
- **提交**：451ed47 chore: sync auto-generated test report and traces
- **分支**：`claude/clever-meitner-fqsa3v`

## 上次会话完成的工作
1. <具体做了什么>

## 当前项目状态
### 阶段
<当前阶段描述>

### 测试
- **结果**：<X/Y 通过，Z 失败>
- **最后运行**：<date>

## 立即可执行的下一步
1. <具体可操作的步骤>

## 本次会话修改的文件清单
- <文件路径>  # <一句话说明变更>
```
