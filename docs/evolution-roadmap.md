# DataAgent 演进路线图 v1.0

> **每次 Claude Code 会话开始前，须阅读本文件 + CLAUDE.md + PROGRESS.md。**
> 本文件是可执行的迭代指南，每个迭代包含明确的目标、文件清单和验收标准。
> 编写日期：2026-06-05 | 基于项目全量代码审查 + 创始人五大战略问题

---

## 一、五大战略问题最终判断

### Q1：工程基建 → 必须补，轻量补，第一优先

**现状**：无 CI/CD、无 linter、`.claude/` 目录不存在（CLAUDE.md 声称有 PreCommit hook）、11 个测试失败（修复 pandas 依赖后）、`config.yaml` 不存在仅有 `config.example.yaml`、API key 明文存储。

**判断**：工程基建是所有后续迭代的地基。一人团队更需要 CI 守门——没有同事 review，自动化测试是你唯一的质量保障。

**做什么**：
- `pyproject.toml` 统一依赖管理 + ruff lint 配置
- `.claude/settings.json` PreCommit hook
- `.env` + `.env.example` 密钥分离
- 修复全部 11 个失败测试
- GitHub Actions CI（push/PR 触发 lint + test）

**不做什么**：Docker、复杂 monorepo 工具、多环境部署流水线。

---

### Q2：客户端 vs 服务端 → 近期不做服务端，做架构准备

**现状**：全局 `_session` 字典 + `_session_lock` + 单例 DuckDB 连接，只能单用户单标签页。`main.py` 800+ 行堆了 40+ 路由。

**判断**：服务端运维开销大，用户量 < 5 人前不值得投入。但当前全局状态设计限制了多标签页，也堵死了未来多用户演进。

**做什么**（架构准备，对当前单机无副作用）：
- `_session` 全局字典 → `SessionStore` 类（每个 session_id 独立状态）
- `main.py` 40+ 路由 → Blueprint 模块化拆分
- API 响应格式标准化 `{"ok": bool, "data": ..., "error": ...}`

**不做什么**：不写服务端代码、不加用户认证、不做数据库。

---

### Q3：资源约束 → 两周迭代制 + T 型能力策略

**核心原则**：做乘法不做加法。每新增一个功能就增加一份维护成本。选择不做什么比选择做什么更重要。

**实操策略**：
1. **每个迭代只做一件事**（3-5 个工作日），完成 → 测试全绿 → 提交 → 再开始下一个
2. **Claude Code 最适合做的事**：写测试、做重构、修 bug、补文档
3. **Claude Code 不适合做的事**：架构决策、业务口径确认
4. **用成熟库替代自研**：`python-docx`（Word 导出）、`duckduckgo-search`（联网搜索）、`pypdf2`（PDF 读取）
5. **先完成闭环再打磨细节**：一个粗糙但完整的 `上传→分析→报告→导出` 闭环，比十个精致的半成品有价值十倍

---

### Q4：通用能力 → T 型扩展，数据分析做深，其余做广

```
              数据分析（深 — 核心壁垒）
                │
                │
    ┌───────────┼───────────────────────────────────┐
   联网搜索    │    文件处理    报告编制    日常办公（广 — 够用即可）
    │          │       │          │          │
    浅         深      浅         深         浅
```

**优先级**：报告编制（最大价值缺口，资管人 60% 时间在写报告） → 文件解析（Word/PDF） → 联网搜索（投研辅助） → 日常办公（锦上添花）。

**实施方式**：每个新能力 = 一个 Agent 工具。加入 `TOOL_DEFINITIONS` 列表 + `dispatch_tool` 分发即可。工具数 < 15 时不需要复杂的注册表/插件系统。

**合规注意**：搜索查询可能包含主体名等商业信息，需与 SQL 生成相同的合规处理。

---

### Q5：前端设计 → 四象限分类，先补功能再改架构

将所有功能按「交互方式 × 使用频率」分为四个区域：

| 区域 | 定位 | 内容 |
|------|------|------|
| **A 对话操作区** | 高频 + 对话驱动 | 数据查询、合规检查、报告生成、图表、联网搜索 |
| **B 快捷操作区** | 高频 + 直接操作 | 拖拽上传、一键日报/周报/合规检查、导出结果、切换会话 |
| **C 状态感知区** | 被动展示 | LLM 连接状态、已加载表摘要、数据时效警告、Agent 执行进度、定时任务状态 |
| **D 配置管理区** | 低频深度操作 | LLM API Key、合规阈值、用户档案、集团系 CRUD、日志模式、主题 |

**优先顺序**：功能补全（报告/图表/导出）→ 可发现性（能力标签/推荐/引导）→ 操作效率（快捷动作/复制/下载）→ 架构升级（JS 模块化）。

**不做什么**：近期不迁移 Vue/React 框架。PyWebView 环境下框架运行时开销不可忽略。先拆 JS 为独立模块文件，能用 vanilla JS 解决就不引入框架。

---

## 二、迭代执行计划

### I-1：工程基建 + 测试修复（3-4 天）

**目标**：建立自动化质量门控 + 全部测试绿灯。这是所有后续迭代的前置条件。

**当前实际问题**（2026-06-05 实测）：
- `config.yaml` 不存在 → 8 个 agent/loop 测试 FileNotFoundError
- `ReportDegradedResult` 缺少 `success` 属性 → 1 个测试失败
- DeepSeek API key 未配置 → 1 个测试依赖外部服务
- AgentMemory 测试断言错误 → 1 个测试失败

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `pyproject.toml` | 统一项目元数据 + ruff 配置 + pytest 配置 |
| 新建 | `.env.example` | API key 占位模板 |
| 新建 | `.claude/settings.json` | PreCommit hook: `pytest tests/ -x -q --timeout=60` |
| 复制 | `config.example.yaml` → `config.yaml` | 测试和开发需要，加入 `.gitignore` |
| 修改 | `.gitignore` | 添加 `.env`、`config.yaml`、`*.duckdb` |
| 修改 | `agent/llm_client.py` | `ReportDegradedResult` 加 `success = False` 属性 |
| 修改 | `tests/test_agent.py` | loop 测试用 fixture 提供 mock config；API key 测试改为 mock 不依赖外部 |
| 修改 | `tests/conftest.py` | 添加 `config_fixture` 提供测试用 config dict（不依赖 config.yaml 文件） |

**验收标准**：
```bash
pytest tests/ -v          # 125/125 通过，0 失败
ruff check .              # 零错误或首次 ignore 已有代码
```

---

### I-2：报告生成管线（4-5 天）

**目标**：实现「数据计算 → 模板渲染 → Word 导出」完整闭环。这是产品最大的价值缺口。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `tools/report_builder.py` | `render_report(template, data) -> str`（Jinja2 → Markdown）; `export_word(md, path) -> Path`（Markdown → python-docx Word）; `ReportResult` dataclass |
| 新建 | `templates/reports/concentration_report.md.j2` | 集中度报告 Jinja2 模板 |
| 新建 | `templates/reports/nav_report.md.j2` | 净值运作报告模板 |
| 新建 | `templates/reports/base_report.md.j2` | 报告公共头部（产品名/日期/制表人） |
| 修改 | `agent/tools_spec.py` | 添加 `generate_report` 工具定义 + handler |
| 修改 | `main.py` | 添加 `/api/report/download/<filename>` 端点 |
| 修改 | `ui/index.html` | 消息流中添加报告预览卡片 + 下载 Word 按钮 |
| 新建 | `tests/test_report_builder.py` | 渲染 + Word 导出 单测 |

**`generate_report` 工具定义**：
```python
{
    "name": "generate_report",
    "description": "基于计算结果生成格式化报告并导出 Word。先调用 run_calculator 获取数据，再调用本工具生成报告。",
    "parameters": {
        "report_type": {"type": "string", "enum": ["concentration", "nav", "asset_structure", "custom"]},
        "data": {"type": "object", "description": "来自 run_calculator 的计算结果"},
        "title": {"type": "string", "description": "报告标题（可选，默认自动生成）"}
    },
    "required": ["report_type", "data"]
}
```

**验收标准**：
- 对话 "生成集中度报告" → Agent 调 `run_calculator` → 调 `generate_report` → 前端显示 Markdown 预览 + Word 下载按钮
- 下载的 Word 文件可用 WPS/Office 正常打开，包含表格和数据
- `pytest tests/test_report_builder.py` 全绿

---

### I-3：图表生成 + ECharts 联动（3-4 天）

**目标**：让分析结果可视化。ECharts 已在前端引入但未使用。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `tools/chart_builder.py` | `build_chart(chart_type, data, options) -> dict` 生成 ECharts option JSON；支持 pie/bar/line/waterfall |
| 修改 | `agent/tools_spec.py` | 添加 `render_chart` 工具定义 + handler |
| 修改 | `agent/loop.py` | 添加 `chart` SSE 事件 yield |
| 修改 | `ui/index.html` | SSE `chart` 事件 → 创建 ECharts 容器 → `echarts.init().setOption()`；支持全屏、下载 PNG |
| 新建 | `tests/test_chart_builder.py` | chart option 生成单测 |

**`render_chart` 工具定义**：
```python
{
    "name": "render_chart",
    "description": "将数据渲染为图表。支持饼图(pie)、柱状图(bar)、折线图(line)。当用户要求可视化或图表时使用。",
    "parameters": {
        "chart_type": {"type": "string", "enum": ["pie", "bar", "line", "waterfall"]},
        "title": {"type": "string"},
        "data": {"type": "object", "description": "图表数据，来自 run_sql 或 run_calculator 的结果"}
    },
    "required": ["chart_type", "data"]
}
```

**验收标准**：
- 对话 "画一个资产结构饼图" → Agent 调 `run_calculator(asset_structure)` → 调 `render_chart(pie, ...)` → 前端渲染 ECharts 饼图
- 图表可全屏查看、可下载 PNG

---

### I-4：数据持久化 + 智能上传（4-5 天）

**目标**：解决 "每次启动都是空数据库" + "上传交互链条过长" 两大痛点。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `tools/data_loader.py` | DuckDB 改为文件模式 `data/dataagent.duckdb`；启动时从文件恢复已有表的元信息到 `_loaded_tables`；新增 `auto_detect_table_type(df)` 基于列名特征匹配表类型；新增 `extract_date_from_filename(filename)` 正则提取日期 |
| 修改 | `main.py` 的 `/api/upload` | 返回智能识别结果（表类型+日期+预览），用户确认后才入库 |
| 修改 | `ui/index.html` | 上传后显示"智能识别卡片"：识别出的表类型、日期、行数、列数预览；用户可修正后确认 |
| 修改 | `.gitignore` | 添加 `data/*.duckdb` |
| 修改 | `tests/test_tools.py` | auto_detect 和 date_extract 单测 |

**auto_detect_table_type 识别规则**：
```python
# 列名中包含以下关键词 → 对应表类型
HOLDING_KEYWORDS = ["持仓", "市值", "穿透", "资产代码", "持有量"]
NAV_KEYWORDS = ["净值", "累计净值", "万份收益", "七日年化"]
RATING_KEYWORDS = ["评级", "主体评级", "债项评级", "外部评级"]
```

**验收标准**：
- 上传 CSV → 自动识别为"持仓表 / 2026-05-15" → 用户确认 → 入库
- 关闭程序 → 重启 → `GET /api/tables` 返回上次加载的表
- 对话查询上次数据正常工作

---

### I-5：前端增量改进（3-4 天）

**目标**：降低用户学习成本 + 提升操作效率。不迁移框架，在现有 HTML 增量改进。

**修改 `ui/index.html`**：

| 功能 | 区域 | 说明 |
|------|------|------|
| 能力推荐标签 | A 区 | 输入框上方显示 [数据分析] [合规检查] [报告生成] [图表]，点击填入示例问题 |
| 状态条 | C 区 | 顶栏显示：LLM 连接状态（绿/红点）+ 已加载表数量 + 数据时效提示 |
| 结果操作按钮 | A 区 | 每个表格结果后：[复制] [下载CSV] [生成图表] |
| 快捷操作 | B 区 | 侧边栏添加快捷按钮：日报、周报、合规检查（点击直接发消息） |
| 新用户引导 | A 区 | 首次启动（无历史会话）显示欢迎面板 + 3 个示例问题 |
| 上下文推荐 | A 区 | 加载数据后自动推荐：已加载持仓表 → "查看集中度"、"资产结构分布" |

**新增 API**：
```
GET /api/suggestions → 基于已加载表 + 最近查询返回推荐操作列表
GET /api/status → 返回 LLM 连接状态 + 数据时效 + 系统健康信息
```

**验收标准**：
- 无数据时看到欢迎面板 + 能力标签
- 上传持仓表后推荐区显示相关分析
- 表格结果的复制/下载按钮正常工作

---

### I-6：通用能力——文件解析 + 联网搜索（4-5 天）

**目标**：从数据分析工具升级为资管助手，支持读 Word/PDF + 搜索市场新闻。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `tools/file_reader.py` | `read_document(path) -> DocumentResult`，用 `python-docx` 读 Word、`pypdf2` 读 PDF，提取文本 + 表格 |
| 新建 | `tools/web_search.py` | `search(query, type) -> list[SearchResult]`，用 `duckduckgo-search` 搜索，支持 news/policy/general |
| 修改 | `agent/tools_spec.py` | 添加 `read_document` 和 `web_search` 工具定义 + dispatch handler |
| 修改 | `requirements-dev.txt` | 添加 `duckduckgo-search>=6.0`、`pypdf2>=3.0` |
| 修改 | `main.py` 的 `/api/upload` | 支持 .docx/.pdf 上传 → 调 file_reader 解析后返回内容预览 |
| 新建 | `tests/test_file_reader.py` | Word/PDF 解析单测 |
| 新建 | `tests/test_web_search.py` | 搜索结果结构单测（mock HTTP） |

**工具定义**：
```python
# read_document
{
    "name": "read_document",
    "description": "读取并解析 Word/PDF 文档内容。提取文本和表格。当用户上传非表格数据文件或要求分析文档时使用。",
    "parameters": {
        "file_path": {"type": "string"},
        "extract_tables": {"type": "boolean", "default": true}
    },
    "required": ["file_path"]
}

# web_search
{
    "name": "web_search",
    "description": "搜索互联网信息。当用户问某个主体的最新动态、市场新闻、监管政策时使用。",
    "parameters": {
        "query": {"type": "string", "description": "搜索关键词"},
        "search_type": {"type": "string", "enum": ["news", "policy", "general"], "default": "general"}
    },
    "required": ["query"]
}
```

**验收标准**：
- 上传 Word → Agent 读取内容 → 对话 "总结这份文档要点"
- 对话 "搜索 XX 集团最近新闻" → 返回搜索结果摘要

---

### I-7：main.py 拆分 + 会话隔离（4-5 天）

**目标**：解决 main.py 800+ 行臃肿问题 + 支持多标签页独立会话。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `api/__init__.py` | Blueprint 注册函数 `register_blueprints(app)` |
| 新建 | `api/chat.py` | `/api/chat`、`/api/stream/<sid>`、`/api/confirm` |
| 新建 | `api/data.py` | `/api/upload`、`/api/tables`、`/api/data/*` |
| 新建 | `api/config.py` | `/api/config`、`/api/groups` |
| 新建 | `api/skill.py` | `/api/skill-builder/*`、`/api/skills` |
| 新建 | `api/report.py` | `/api/report/*` |
| 新建 | `api/system.py` | `/api/health`、`/api/logs`、`/api/suggestions`、`/api/status` |
| 新建 | `session_store.py` | `SessionStore` 类：管理多个独立会话，每个 Session 有独立 messages、pending、turn_count |
| 修改 | `main.py` | 精简为 app 创建 + Blueprint 注册 + 启动逻辑（目标 < 120 行） |

**SessionStore 核心设计**：
```python
class Session:
    session_id: str
    messages: list
    pending: dict | None
    turn_count: int
    created_at: str

class SessionStore:
    def get_or_create(self, session_id: str) -> Session: ...
    def list_sessions(self) -> list[dict]: ...  # 返回摘要
    def delete(self, session_id: str): ...
```

**验收标准**：
- 现有全部 API 功能不变（回归测试 `pytest tests/`）
- 两个浏览器标签页各自独立会话
- `main.py` < 120 行

---

### I-8：Agent 规划层 Plan-Execute（5 天）

**目标**：让 Agent 能处理复杂多步任务（如"准备参谈要点"），从 ReAct 逐步循环升级为计划-执行模式。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agent/planner.py` | `create_plan(intent, tools, tables) -> ExecutionPlan`；LLM 分解用户意图为步骤列表 `[{step_id, tool, args_template, depends_on, description, status}]` |
| 新建 | `agent/executor.py` | `execute_plan(plan, tool_ctx) -> Generator[SSEEvent]`；按 DAG 顺序执行步骤；某步失败回 planner 重规划 |
| 修改 | `agent/loop.py` | 入口判断任务复杂度（> 2 步或匹配特定 Skill）→ 走 Plan-Execute；简单查询保持直接 tool-calling |
| 修改 | `ui/index.html` | 执行计划卡片：步骤列表 + 当前执行位置 + 用户可勾选/跳过步骤 |
| 新建 | `tests/test_planner.py` | 计划分解 + 执行顺序单测 |

**复杂度判断规则**：
```python
def should_plan(user_input: str, matched_skill: SkillInfo | None) -> bool:
    # 匹配到 meeting_report / dept_weekly_report 等多步 Skill → True
    # 用户意图包含 "报告" "要点" "汇总" 等 → True
    # 简单查询（"查XX" "看XX" "算XX"）→ False
```

**验收标准**：
- 对话 "准备参谈要点" → Agent 展示 5-6 步计划 → 用户确认 → 按计划执行 → 汇总报告
- 简单查询仍走直接 tool-calling（不显示计划卡片）
- 某步失败 → 重规划或跳过 → 最终结果仍完整

---

### I-9：计算器补齐 + 上下文推荐（4 天）

**目标**：补齐资管行业核心计算指标 + 智能推荐。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `calculators/position_diff.py` | 两期持仓变动对比：新增/减持/清仓/不变 |
| 新建 | `calculators/leverage.py` | 杠杆率（正回购口径） |
| 新建 | `calculators/liquidity.py` | 高流动性资产比例 |
| 新建 | `agent/recommender.py` | `get_suggestions(tables, queries, time) -> list[str]`；基于已加载数据+时间+查询历史推荐 |
| 修改 | `agent/tools_spec.py` | `run_calculator` enum 添加 position_diff / leverage / liquidity |
| 新建 | `tests/test_calculators_extended.py` | 新计算器单测，覆盖率 >= 95% |

**推荐规则**：
```python
# 基于已加载数据
if has_type("holding"): suggest("查看主体集中度", "查看资产结构")
if has_type("holding") and count_type("holding") >= 2: suggest("对比持仓变动")
if has_type("nav"): suggest("查看净值变动")
# 基于时间
if is_friday(): suggest("生成本周运作报告")
# 基于最近查询
if last_query_about("集中度") and found_breach: suggest("查看超标主体详情")
```

**验收标准**：
- 对话 "对比两期持仓" → `run_calculator(position_diff)` → 表格展示变动
- 新计算器单测全绿，覆盖率 >= 95%
- `/api/suggestions` 返回上下文相关的推荐列表

---

### I-10：前端 JS 模块化 + 整体打磨（4-5 天）

**目标**：`ui/index.html` 从 1800 行单文件拆分为可维护的模块结构；整体质量收尾。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 拆分 | `ui/js/app.js` | 入口 + 全局状态管理 |
| 拆分 | `ui/js/chat.js` | 对话逻辑 + 消息渲染 |
| 拆分 | `ui/js/sse.js` | SSE EventSource 事件处理 |
| 拆分 | `ui/js/upload.js` | 文件上传交互 |
| 拆分 | `ui/js/sidebar.js` | 侧边栏（会话/数据表/技能/集团系） |
| 拆分 | `ui/js/charts.js` | ECharts 渲染封装 |
| 拆分 | `ui/js/report.js` | 报告预览 + 导出 |
| 修改 | `ui/index.html` | 只保留 HTML 结构 + CSS + `<script src>` 引用 |
| 修改 | `main.py` | 静态文件服务支持 `ui/js/` 目录 |
| 更新 | `CLAUDE.md` | 更新为 v2.0，反映实际架构 |
| 更新 | `PROGRESS.md` | 记录全部完成迭代 |

**验收标准**：
- 前端功能完全不变
- `pytest tests/` 全绿 + 覆盖率 >= 70%
- `ruff check .` 零错误
- 手动冒烟：上传 → 分析 → 图表 → 报告 → 导出 Word 完整闭环

---

## 三、迭代依赖图

```
I-1 工程基建+测试修复
 │
 ├─→ I-2 报告生成管线 ─→ I-3 图表生成
 │                          │
 │                          ↓
 ├─→ I-4 数据持久化  ─→  I-5 前端改进
 │
 ├─→ I-6 文件解析+搜索 ─→ I-7 main.py拆分 ─→ I-8 Plan-Execute
 │
 └─→ I-9 计算器补齐（可与 I-2~I-6 并行）
                                                    │
                                                    ↓
                                               I-10 JS模块化
```

**强依赖**：I-1 是所有后续迭代的前置条件。
**可并行**：I-2 和 I-4 可以并行；I-9 可以在任何时间插入。
**建议顺序**：I-1 → I-2 → I-3 → I-4 → I-5 → I-6 → I-7 → I-8 → I-9 → I-10

---

## 四、每个迭代的标准流程

每个迭代开始前：
1. 阅读 `CLAUDE.md` + `PROGRESS.md` + 本文件中对应迭代章节
2. `pytest tests/ -x` 确认基线全绿
3. `git checkout -b I-N/描述` 创建迭代分支

每个迭代结束时：
1. `ruff check .` 零错误
2. `pytest tests/ -x --cov` 全绿 + 覆盖率不降
3. 手动冒烟：`python main.py` → 浏览器打开 → 验收功能
4. 更新 `PROGRESS.md` 记录完成状态
5. `git commit` + `git push`

---

## 五、成功 Agent 产品的核心指标

从原型到产品，需要关注以下指标：

| 维度 | 指标 | 目标 |
|------|------|------|
| **功能闭环** | 上传→分析→报告→导出 全流程可用 | I-2 后达成 |
| **Agent 可靠性** | 复杂任务（参谈要点等）完成率 | I-8 后 > 80% |
| **用户体验** | 新用户 5 分钟内完成首次分析 | I-5 后达成 |
| **工程质量** | 测试通过率 100%，覆盖率 > 70% | I-1 后持续保持 |
| **T 型能力** | 数据分析深度 + 搜索/文件/报告广度 | I-6 后达成 |
| **可维护性** | 单文件 < 300 行，模块职责清晰 | I-7/I-10 后达成 |
