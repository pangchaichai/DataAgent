# 迭代测试计划 — v3.0 Week 4：tools_spec 拆分 + 全局 UI 统一

- **日期**：2026-06-14
- **迭代目标**：tools_spec.py 拆分为 tool_defs/tool_dispatch 两模块 + Header 重组 + 欢迎面板统一
- **关联 PROGRESS.md 条目**：`## v3.0 Week 4`

---

## 一、变更范围

| 变更文件 / 模块 | 变更类型 | 说明 |
|---------------|---------|------|
| `agent/tool_defs.py` | 新建 | 从 tools_spec.py 提取 TOOL_DEFINITIONS 列表 + ToolContext + SkillPrepareResult |
| `agent/tool_dispatch.py` | 新建 | 从 tools_spec.py 提取 dispatch_tool + 所有 _tool_* 实现函数 |
| `agent/tools_spec.py` | 修改 | 保留为薄转发层：从 tool_defs/tool_dispatch re-export 所有公开符号 |
| `ui/index.html` | 修改 | Header：移除 RAM/Token chip，新增 AI 状态 + 表计数 chip；欢迎面板改为由 JS 渲染 |
| `ui/js/main.js` | 修改 | 新增 `buildWelcomePanel(tables)` 函数；`resetChat()` 用 buildWelcomePanel；`pollHealth()` 更新 AI 状态显示；`updateTableCountHeader()` |
| `ui/js/sidebar.js` | 修改 | loadTables 成功后调用 `updateTableCountHeader(n)` |

---

## 二、影响面分析

- **tools_spec.py 拆分**：纯代码组织变更，公开 API 不变（`dispatch_tool`, `TOOL_DEFINITIONS`, `ToolContext` 可继续从 tools_spec 导入）
  - 影响：所有从 `agent.tools_spec` 导入的代码无需修改；新代码可从 `agent.tool_defs` 或 `agent.tool_dispatch` 直接导入
- **Header 重组**：`ramMb`、`tokenUsed`、`tokenLimit` 元素不存在后，`pollHealth()` 不应报错（需 null-check 或移除更新逻辑）
- **欢迎面板统一**：`welcomePanel` div 由静态 HTML 改为 JS 渲染，初始化时需立即调用 `buildWelcomePanel([])`

---

## 三、测试用例设计

### L1 — 单元测试（自动化）

| 测试 ID | 测试场景 | 预期结果 | 优先级 |
|--------|---------|---------|-------|
| L1-01 | `from agent.tools_spec import dispatch_tool, TOOL_DEFINITIONS, ToolContext` | 导入成功，无 ImportError | P0 |
| L1-02 | `from agent.tool_defs import TOOL_DEFINITIONS, ToolContext` | 导入成功，定义完整 | P0 |
| L1-03 | `from agent.tool_dispatch import dispatch_tool` | 导入成功，函数可调用 | P0 |
| L1-04 | 全量回归：`pytest tests/ -x -q` | 全绿，无回归 | P0 |
| L1-05 | `len(TOOL_DEFINITIONS)` 从 tool_defs 和 tools_spec 导入结果相同 | 同一个对象或相同长度 | P1 |

### L2 — 功能测试（集成）

| 测试 ID | 测试场景 | 预期结果 | 优先级 |
|--------|---------|---------|-------|
| L2-01 | Flask 启动后 `GET /api/health` → 含 AI 状态字段 | ok=True，有 llm_name | P0 |
| L2-02 | 全量 pytest（回归） | 所有 383 个测试仍通过 | P0 |

### L3 — UI 验证（手动/可选自动化）

| 测试 ID | 测试场景 | 预期结果 | 优先级 |
|--------|---------|---------|-------|
| L3-01 | Header 显示 "AI 就绪 / AI 离线" 而非 LLM 技术名称 | 非技术用户可理解 | P1 |
| L3-02 | Header 不再显示 RAM MB 和 Token 用量 | RAM/Token 不可见 | P1 |
| L3-03 | 加载 2 张表后 Header 显示 "▣ 2张表" | 表计数正确 | P1 |
| L3-04 | `resetChat()` 和初始欢迎面板 HTML 内容一致 | 视觉统一 | P1 |

### L4 — UAT（业务方手动验收）

| 场景 ID | 操作 | 预期 | 状态 |
|--------|------|------|------|
| U4-12 | 首次打开应用，查看顶部 header | 看到"AI 就绪"状态，不显示技术参数 | 待验收 |
| U4-13 | 上传 2 张表后查看 header | 显示"▣ 2张表"计数 | 待验收 |
| U4-14 | 点击"＋ 新对话"，查看欢迎面板 | 与初始欢迎面板样式/内容一致 | 待验收 |

---

## 四、执行结果

- **测试运行日期**：2026-06-14
- **pytest 结果**：383 passed, 2 skipped（全量回归，无新增测试文件，通过现有测试验证）

### L1~L3 执行摘要

| 测试 ID | 实际结果 | 备注 |
|--------|---------|------|
| L1-01 | ✅ 通过 | `from agent.tools_spec import dispatch_tool, TOOL_DEFINITIONS, ToolContext` 正常 |
| L1-02 | ✅ 通过 | `from agent.tool_defs import TOOL_DEFINITIONS, ToolContext` 正常，13个工具定义 |
| L1-03 | ✅ 通过 | `from agent.tool_dispatch import dispatch_tool` 正常 |
| L1-04 | ✅ 通过 | 383 passed, 2 skipped，无回归 |
| L1-05 | ✅ 通过 | TOOL_DEFINITIONS 对象唯一，两处导入结果一致 |
| L2-01 | ✅ 通过 | /api/health 正常返回 llm_name 字段 |
| L2-02 | ✅ 通过 | 383 passed |

### UAT 状态

- [ ] U4-12 — 待业务方验收（Header AI 状态）
- [ ] U4-13 — 待业务方验收（表计数）
- [ ] U4-14 — 待业务方验收（欢迎面板一致性）
