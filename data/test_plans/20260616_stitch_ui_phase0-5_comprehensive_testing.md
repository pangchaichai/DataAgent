# 迭代测试计划 — Stitch UI 重构 Phase 0-5 全面测试

- **日期**：2026-06-16
- **迭代目标**：为 Stitch Design System UI 重构（5 页面 SPA + Material Symbols 图标迁移 + 聊天气泡重写）建立全面测试覆盖，确认前端改动零回归后端，且新前端结构自身完整可用
- **预计完成**：2026-06-16
- **关联 PROGRESS.md 条目**：## Stitch Design System UI 重构 ✅ Phase 0-5 完成（2026-06-16）

---

## 一、变更范围

| 变更文件 / 模块 | 变更类型 | 说明 |
|---------------|---------|------|
| `ui/index.html` | 修改（大改）| 新 5 页面 SPA 容器结构，legacy CSS 保留兼容 |
| `ui/js/router.js` | 新增 | hash 路由（#/dashboard #/sources #/rules #/chat #/audit）|
| `ui/js/pages/*.js`（5个）| 新增 | 5 个页面渲染模块 |
| `ui/js/render.js` | 重写 | 消息渲染全面 Stitch 化（气泡/表格/图表/卡片） |
| `ui/js/chat.js` | 修改 | 流式气泡结构 + 过程包装器图标迁移 |
| `ui/js/main.js` | 修改 | 欢迎面板 Material Symbols 化 |
| `ui/js/dom.js` | 修改 | copyBubble/setSendMode 兼容新旧结构 |
| `ui/js/upload.js` | 修改 | 文档结果气泡图标迁移 |
| `ui/js/settings.js` | 修改 | LLM 状态指示图标迁移 |
| `ui/js/sidebar.js` | 修改 | 分组箭头/复制反馈图标迁移 |
| `ui/js/skill_builder.js` | 修改 | 校验图标迁移 |
| `ui/src/input.css` | 修改 | MD3 token + 流式光标动画，Tailwind v4 编译 |
| `ui/dist/styles.css` | 重新编译 | 构建产物 |
| `ui/fonts/*` | 新增 | Inter/JetBrains Mono/Material Symbols 本地字体 |
| **后端（main.py / api/ / agent/ / calculators/）** | **未改动** | 本次为纯前端重构，零后端代码变更 |

## 二、影响面分析

- **上游依赖**：浏览器加载 `ui/index.html` → 引入 `ui/js/*.js`（含 `ui/js/pages/*.js`）和 `ui/dist/styles.css`；无其他系统依赖前端文件
- **下游依赖**：前端通过 `/api/*` 路由与 Flask 后端交互（`fetch`/SSE `EventSource`），请求/响应格式（JSON 字段名、SSE chunk 类型）**未变更**，因此后端测试应保持 100% 通过率（零回归）
- **共享状态**：`session_store.py`、DuckDB 连接、SSE 队列均未涉及，前端改动不触达
- **前端 SSE 流**：`chat.js` 的 `handleChunk()` 处理的 SSE 事件类型（text/thinking/tool_start/tool_end/plan/plan_step/confirm/ask/error/chart/stream_end）**结构未变**，只是渲染层（图标/HTML结构）变了
- **风险点**：
  1. 新增的 `ui/js/pages/*.js` 和 `router.js` 是全新代码，无任何现有测试覆盖
  2. `render.js` 全面重写，是消息渲染的核心，回归风险最高
  3. DOM ID 引用错配（JS 引用的元素 ID 在 index.html 中不存在）是最常见的重构 bug 来源
  4. 本环境无浏览器/Playwright，无法做真实渲染像素级验证，只能做结构性/契约性验证 + 尽力用 verify 技能跑一次真实交互

## 三、测试用例设计

### L1 — 单元测试（静态正确性）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L1-01 | 全量 pytest 单元测试回归（后端零改动验证） | 388 个测试，0 失败（与基线一致） | P0 | todo |
| L1-02 | 所有 `ui/js/*.js` 及 `ui/js/pages/*.js` 通过 `node --check` 语法校验 | 0 语法错误 | P0 | todo |
| L1-03 | `ui/js/*.js`（除 agent_status.js）中不含残留 emoji 图标（已知 textContent 场景排除）| 仅 textContent 上下文允许残留，HTML 拼接处无 emoji | P1 | todo |
| L1-04 | `ui/dist/styles.css` 编译产物非空、包含关键 Stitch 类（`.bubble-ai` `.stitch-card` `.suggestion-pill`）| 类名存在 | P1 | todo |

### L2 — 功能测试（模块级契约）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L2-01 | `router.js` 注册的路由集合 = {dashboard, sources, rules, chat, audit} | 5 个路由全部注册 | P0 | todo |
| L2-02 | 每个 `ui/js/pages/*.js` 导出的渲染函数被 `router.js` 正确引用 | 无悬空引用 | P0 | todo |
| L2-03 | `ui/js/*.js` 中所有 `$('xxx')` / `getElementById('xxx')` 引用的 DOM ID 均存在于 `ui/index.html` | 0 个悬空 ID 引用 | P0 | todo |
| L2-04 | `index.html` 中所有 `<script src>` 引用的文件均存在于磁盘 | 0 个 404 | P0 | todo |
| L2-05 | 后端 API 路由表（`/api/*`）与本次改动前完全一致（无端点增删）| diff 为空 | P0 | todo |

### L3 — 集成测试（前后端契约 + 端到端）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L3-01 | 启动 Flask（`python main.py` 浏览器模式），GET `/` 返回 200，HTML 含 `nav-sidebar` `pageRoot` 等新结构关键字 | 200 + 关键字存在 | P0 | todo |
| L3-02 | GET 所有静态 JS/CSS/字体文件 → 200，Content-Type 正确 | 全部 200 | P0 | todo |
| L3-03 | 真实上传 CSV → `/api/upload` 两阶段确认 → `/api/tables` 返回新表 | 流程不报错，与改动前行为一致 | P0 | todo |
| L3-04 | 真实发送聊天消息 → SSE 流 → 收到 text/tool_start/tool_end/stream_end 等事件，事件 JSON 结构不变 | SSE 事件可被旧版 handleChunk 逻辑解析（即结构未破坏）| P0 | todo |
| L3-05 | 全量 pytest 回归套件（与 L1-01 同一次运行，确认无新增失败）| 0 回归 | P0 | todo |

### L4 — UAT 验收场景（人工/`verify` 技能浏览器执行）

| 场景 ID | 用户角色 | 操作步骤 | 预期结果 | 验收标准 | 状态 |
|--------|---------|---------|---------|---------|------|
| U4-01 | 投资经理 | 打开应用，依次点击 5 个侧边栏导航项 | 5 个页面均正确渲染，无白屏/控制台报错 | 路由切换无报错 | 待验收 |
| U4-02 | 投资经理 | 切换深色模式 | 颜色 token 正确切换，无样式断裂 | 视觉一致 | 待验收 |
| U4-03 | 投资经理 | 在 Chat 页面发送一条消息 | 流式气泡出现 neurology 图标，过程包装器显示 Material Symbols（非方块乱码）| 图标正确渲染，无 tofu 方块 | 待验收 |
| U4-04 | 投资经理 | 打开设置面板，测试 LLM 连接 | 状态点颜色正确（绿/红），无 emoji | 视觉正确 | 待验收 |
| U4-05 | 投资经理 | 上传文档，查看文档解析结果气泡 | description 图标正确渲染 | 无 emoji 残留 | 待验收 |
| U4-06 | 投资经理 | 打开 Skill Builder，触发校验错误 | 错误/警告图标使用 Material Symbols | 视觉正确 | 待验收 |

---

## 四、执行结果

### L1 — 单元测试

| 测试 ID | 结果 | 说明 |
|--------|------|------|
| L1-01 | ✅ 通过 | `python -m pytest tests/` → 392 passed, 2 skipped, 0 failed（环境缺 `python-docx`/`duckduckgo-search` 依赖，补装后转绿，与本次 UI 改动无关）|
| L1-02 | ✅ 通过 | `ui/js/*.js`（12个）+ `ui/js/pages/*.js`（5个）全部 `node --check` 0 错误 |
| L1-03 | ✅ 通过 | 扫描到 4 处残留 Unicode/emoji，均为 `textContent` 赋值或纯文本分隔符场景（`settings.js:38` 阈值提示、`dom.js:32` 复制按钮文案、`chat.js:191` 溯源标签、`sidebar.js:412` 字段映射箭头），HTML 拼接处无残留 |
| L1-04 | ✅ 通过 | `ui/dist/styles.css` 34733 字节，含 `.bubble-ai` `.bubble-user` `.stitch-card` `.stitch-table` `.suggestion-pill` `@keyframes blink`；`./scripts/build-css.sh` 重新编译后 `diff -q` 确认字节级一致（可复现构建）|

### L2 — 功能测试

| 测试 ID | 结果 | 说明 |
|--------|------|------|
| L2-01 | ✅ 通过 | `router.js` 注册 5 路由 `/dashboard /sources /rules /chat /audit`，`main.js` 中 `Router.init('pageRoot','#/chat')` |
| L2-02 | ✅ 通过 | 5 个 `pages/*.js` 渲染函数均被 `router.js` 正确引用，无悬空引用 |
| L2-03 | ⚠️ 发现并修复 2 个真实 bug，另确认 2 项为范围外缺口 | 详见下方"L2-03 详情" |
| L2-04 | ✅ 通过 | `index.html` 全部 `<script src>` / `<link href>`（18 个）经 Flask test_client 验证均返回 200；编译后 CSS 内引用的 4 个本地字体文件解析路径后均 200 |
| L2-05 | ✅ 通过 | `git diff HEAD~2 -- main.py api/ agent/ calculators/` 为空，两次 Stitch UI 提交均零后端代码变更 |

#### L2-03 详情（DOM ID 引用交叉校验，最高风险项）

交叉比对 JS 中所有 `$()`/`getElementById()` 引用与（静态 HTML + 全部 JS 动态注入模板）中的 `id="..."` 定义，初筛 39 处疑似悬空引用，逐一排查后：
- **12 处为误报/无害死代码**：`bodyWrap`/`toggleSidebar()`（零调用方）、`chatTitle`（被静态 `pageTitle` 有意替代）、`hint`/`inputbar`/`input`/`inrow`（均有 `||` 防御性回退）、`sessionList`/`skillList`/`tableList`/`tablesCount`（新页面模块已有独立替代实现）、`kpi-llm`/`kpi-rows`/`kpi-tables`（经 `dashboard.js` 的 `_kpiCard()` 辅助函数确认实际已创建，正则初筛未识别该模式）
- **2 处真实 bug，已修复并验证**：
  1. `mentionPopup` vs `mention-popup` 大小写不一致 → @mention 自动补全弹窗从未显示，且 `checkMention()` 在无 `popup` 元素时对 `null.classList` 调用会在每次按键时抛异常。已将 `pages/chat.js` 中 ID 改为 `mentionPopup`，并将 `sidebar.js` 中 `checkMention`/`mentionNav`/`mentionSelect` 的显隐逻辑由失效的 `.classList.add/remove('show')`（legacy CSS 类未挂载在新结构上）改为与本次重构其余下拉/提示框一致的 `style.display` 直接赋值。
  2. `/api/suggestions` 推荐问题功能在新 SPA 中永久不可见 → `pages/chat.js` 创建了占位 `chat-suggestions`/`suggestion-pills`，但旧 `loadSuggestions()` 仍写入已不存在的 `suggestionsBar`。已将 `sidebar.js` 的 `loadSuggestions()` 改为渲染到新占位 ID，按钮样式改用 Stitch `.suggestion-pill` + Material Symbol 图标，与本次重构其余建议按钮风格统一。
  两处修复后 `node --check` 均通过，相关 ID 在新结构下交叉引用关系自洽。
- **2 处确认为真实缺口，但范围超出本次"图标迁移+5页面路由"重构、且涉及信息架构归属决策，未在本次迭代内处理**：
  1. 集团系（entity group）CRUD 功能（`loadGroups`/`createGroup`/`addMember`/`removeMember`/`confirmDeleteGroup` 等）在新 5 页面 IA 中无归属页面，`rules.js` 仅有只读的"集团合并计算开关"展示，原 CRUD 入口已悬空。
  2. 本地工作目录批量上传（`loadWorkdir`/`refreshWorkdir`/`loadWorkdirFile`）在新 IA 中无归属页面，`sources.js` 中无任何相关引用。
  这两项需要业务方/用户确认应归入 Dashboard/Sources/Rules/Audit 中的哪个页面，已征询用户意见（见对话记录），将作为独立后续迭代处理，不阻塞本次 Stitch UI 重构的测试关卡通过。

### L3 — 集成测试

| 测试 ID | 结果 | 说明 |
|--------|------|------|
| L3-01 | ✅ 通过 | Flask `test_client().get('/')` → 200，HTML 含 `nav-sidebar` `pageRoot` `navSidebar` `topHeader` |
| L3-02 | ✅ 通过 | 18 个脚本/样式静态资源 200；CSS 内 4 个本地字体文件相对路径解析后 200 |
| L3-03 | ✅ 通过 | 真实 CSV 上传 → `/api/upload`（编码探测+类型识别）→ `/api/upload/confirm`（质量诊断+主体归一）→ `/api/tables` 含新表，全流程与改动前一致 |
| L3-04 | ✅ 通过（结构验证） | 真实发送聊天消息 → SSE 流返回 `{"type":...,"data":...}` 结构化事件，`stream_end` 正确终止；因本环境无 LLM 网络出口/API Key，收到的是 `error` 事件而非 `text`，但事件 JSON 结构与 `error_translator` 话术均符合既定契约（非代码缺陷，为环境限制）|
| L3-05 | ✅ 通过 | 与 L1-01 同一次运行，392 passed / 2 skipped / 0 failed，确认无新增回归 |

**附带发现（非本次迭代范围，记录供参考）**：`tests/conftest.py` 的 `pytest_runtest_makereport` 钩子仅在 `call.when=="call"` 时记录 `_report`，导致 `skipped` 状态的测试项无 `_report` 属性，被 `pytest_sessionfinish` 汇总逻辑静默漏计入 `passed`/`skipped` 任一桶，使 `latest_summary.json` 长期显示 `skipped:0` 而非实际的 2。不影响测试结果正确性，仅影响自动摘要的统计准确性，建议后续迭代修复。

### L4 — UAT（待业务方验收）

本环境无 Playwright/浏览器渲染能力，6 个 U4 场景维持"待验收"状态，按 TESTING.md 既定流程留待 Windows 内测包发布后由业务方人工确认。结构性前置条件（路由注册、DOM ID 自洽、图标类引用、CSS 编译产物）均已通过 L1-L3 验证。
