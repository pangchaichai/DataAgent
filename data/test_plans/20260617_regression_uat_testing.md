# 回归测试与 UAT 验证 — 2026-06-17

> 覆盖全版本前后端回归 + API-前端字段一致性 UAT
> **执行日期**：2026-06-17
> **最终结果**：575 passed, 2 skipped, 0 failed, 76% 覆盖率；3 个前端 bug 修复

---

## 测试范围

| 维度 | 覆盖内容 |
|------|---------|
| L1 单元测试 | 575 自动化测试（全量回归）|
| L2 前端验证 | 16 个 JS 文件语法 + DOM 引用交叉检查 + CSS 类名 + 静态资源 |
| L2 后端验证 | 14 个 API 端点烟雾 + 9 个 Skills YAML + 7 个字典 YAML + 7 个计算器签名 |
| L3 集成测试 | CSV 上传全流程 + SSE 流 + 设置读写 + 报告导出 + 日志系统 + 集团 CRUD + Skill Builder |
| UAT 验证 | 前端-API 字段一致性 + 路由绑定 + DOM ID 安全性 + 静态文件服务 |

---

## L1 — 单元测试

### L1-01: 全量回归
- [x] `pytest tests/ -v` → 575 passed, 2 skipped, 0 failed (11.17s)
- [x] 覆盖率 76%

---

## L2 — 功能测试

### L2-01: JS 语法检查（16 个文件）
- [x] `node --check` 全部通过（11 核心 + 5 页面模块）

### L2-02: CSS 构建 + 关键类名
- [x] `ui/dist/styles.css` 34,733 bytes
- [x] 10 个关键类名全部存在：stitch-card, bubble-ai, bubble-user, suggestion-pill, status-badge, data-mono, label-caps, btn-primary, btn-secondary, btn-ghost

### L2-03: 静态资源
- [x] styles.css (34,733 bytes), echarts.min.js (1,029,203 bytes), tailwind-local.css (14,753 bytes)
- [x] 3 个字体目录存在（inter, jetbrains-mono, material-symbols）

### L2-04: API 端点烟雾（14 个）
- [x] 全部返回 200，零 500 错误
- 覆盖：/, /api/health, /api/tables, /api/config, /api/skills/status, /api/report/templates, /api/groups, /api/logs/stats, /api/suggestions, /api/cost, /api/workdir/files, /api/sessions, /api/skill-builder/drafts, /api/logs/files

### L2-05: Skills YAML 验证（9 个）
- [x] 全部 frontmatter 解析正确，name + calc_type 字段完整

### L2-06: 数据字典 YAML 验证（7 个）
- [x] 全部解析成功

### L2-07: 计算器函数签名（9 个函数）
- [x] 全部接受 `conn` 参数，签名一致

### L2-08: 旧 RulesPage 引用清理
- [x] 零 `RulesPage.createGroup/addMember/removeMember/deleteGroup` 残留
- [x] 零 `rules-groups` DOM ID 残留
- [x] `sources-groups` DOM ID 正确存在于 sources.js

### L2-09: DOM 引用安全性
- [x] 70 个 HTML 静态 ID
- [x] 所有 JS getElementById 引用均安全（存在于 HTML、动态创建、或有 null guard）

---

## L3 — 集成测试

### L3-01: 应用启动与首页
- [x] Flask app 创建成功，GET / 返回 200（45,554 bytes）
- [x] 关键 DOM 元素存在：navSidebar, pageRoot, topHeader, settingsOverlay, uploadConfirmOverlay
- [x] 12 个静态 JS/CSS 文件全部正确服务（200）

### L3-02: CSV 上传完整流程
- [x] Upload → Confirm → Table exists → Delete → Cleaned up（5 步全通过）

### L3-03: SSE 流合约
- [x] POST /api/chat → stream_id
- [x] GET /api/stream/<sid> → 200 text/event-stream; charset=utf-8

### L3-04: 设置读写循环
- [x] GET → POST(name=UAT_TestUser_2026) → GET 验证持久化 → 恢复

### L3-05: 报告模板与 Word 导出
- [x] GET /api/report/templates → 2 个模板
- [x] POST /api/report/export-word → 200 ok

### L3-06: 日志系统端到端
- [x] mode=basic → switch detailed → verify → restore basic

### L3-07: 集团系 CRUD 完整流程（Sources 页面 API）
- [x] 创建集团 → 添加成员 → 验证成员 → 移除成员 → 删除集团 → 验证清理

### L3-08: Skill Builder 草稿生命周期
- [x] 保存草稿 → 加载草稿 → 校验 → 删除草稿

### L3-09: 数据表剖析
- [x] 上传含 null 的 CSV → profile 返回列名/类型/空值率/样本 → 清理

---

## UAT — 前端-API 字段一致性

### UAT-01: 路由页面绑定
- [x] 5 个页面全部注册：/dashboard, /sources, /rules, /chat, /audit
- [x] index.html 16 个 JS 文件引用完整

### UAT-02: Sources 页面功能完整性
- [x] 上传区 + 数据源列表 + 集团系管理 + 工作目录 + 数据预览

### UAT-03: Rules 页面精简
- [x] 仅包含分析模板 + 自定义参数
- [x] 不包含集团系代码

### UAT-04: Chat SSE + @mention
- [x] EventSource 连接正确
- [x] mentionPopup ID 一致（`mentionPopup`）
- [x] sidebar.js 使用正确的 `chat-suggestions`/`suggestion-pills` 目标

### UAT-05: 深色模式
- [x] index.html 有 `data-theme` 属性
- [x] CSS 有 `[data-theme="dark"]` 规则
- [x] main.js 有 `toggleTheme()` 函数

---

## 发现并修复的 Bug（3 个）

### Bug 1: 数据预览空值率字段不匹配（P1）
- **位置**：`ui/js/pages/sources.js:285`
- **问题**：前端使用 `c.null_pct`，API 返回 `c.null_rate`（小数）→ 空值率列永远显示 `--`
- **修复**：改为 `c.null_rate != null ? (c.null_rate * 100).toFixed(1) + '%' : (c.null_pct != null ? c.null_pct + '%' : '--')`

### Bug 2: 数据预览样本字段不匹配（P1）
- **位置**：`ui/js/pages/sources.js:284`
- **问题**：前端使用 `c.sample`，API 返回 `c.samples`（数组）→ 示例列永远显示 `--`
- **修复**：改为 `Array.isArray(c.samples) ? c.samples[0] : (c.sample || c.example || '--')`

### Bug 3: 仪表盘 LLM 状态字段不匹配（P1）
- **位置**：`ui/js/pages/dashboard.js:82`
- **问题**：前端使用 `health.llm_ok`，API 返回 `health.llm_status`（字符串 'online'）→ LLM 状态永远显示"离线"
- **修复**：改为 `health.llm_ok || health.llm_status === 'online'`

### Bug 4: 数据源列表列数字段不匹配（P2）
- **位置**：`ui/js/pages/sources.js:135`
- **问题**：前端使用 `t.columns || t.col_count`，API 返回 `t.cols` → 列数永远显示 0
- **修复**：改为 `t.cols || t.columns || t.col_count || 0`

---

## 覆盖率

| 指标 | 数值 |
|------|------|
| 自动化测试 | 575 passed, 2 skipped |
| 覆盖率 | 76% |
| L2 功能测试 | 9 项全通过 |
| L3 集成测试 | 9 项全通过 |
| UAT 字段一致性 | 5 项全通过，4 个 bug 已修复 |
