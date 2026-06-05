# DataAgent 战略演进分析：五大核心问题深度评估

> 评估日期：2026-06-05
> 视角：Agent 架构师 + 金融资管行业顾问 + 独立开发者效率专家
> 输入：项目全代码审查 + 前次架构评估 + 创始人五问

---

## 一、工程基建（Harness）补全方案

### 1.1 现状诊断

当前项目在工程基建上处于「原型验证阶段」，具体表现：

| 维度 | 现状 | 风险等级 |
|------|------|---------|
| CI/CD | 无。无 GitHub Actions，无自动测试 | **高** |
| 依赖管理 | `requirements-dev.txt` 不完整（缺 openpyxl/pytest 等），无锁文件 | **高** |
| 代码质量 | 无 linter/formatter（无 ruff/mypy），无类型检查 | **中** |
| 预提交检查 | CLAUDE.md 声称有 PreCommit hook 但 `.claude/` 目录不存在 | **高** |
| 测试覆盖 | 77 用例，17 失败（22% 失败率），无覆盖率门槛 | **高** |
| 密钥管理 | `config.yaml` 明文存储 API Key，无 `.env` 分离 | **中** |
| 版本管理 | 无 CHANGELOG，无语义版本号 | **低** |
| 文档 | CLAUDE.md 详尽但偏「设计意图」，缺少「运行指南」 | **低** |

### 1.2 需要补全的内容（按优先级排序）

#### P0：立即补全（影响日常开发效率和代码质量）

**1. 依赖锁定与环境隔离**

```
# pyproject.toml（推荐迁移方向，替代 requirements.txt）
[project]
name = "dataagent"
version = "0.2.0"
requires-python = ">=3.10"
dependencies = [
    "flask>=3.0",
    "flask-cors",
    "duckdb>=0.10",
    "sqlglot>=20.0",
    "chardet",
    "pyyaml",
    "requests",
    "pandas",
    "openpyxl",
    "rank_bm25",
    "psutil",
    "jinja2",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff", "mypy"]
prod = ["pywebview>=4.4", "winotify", "pyinstaller", "pythonnet"]
```

当前的双 requirements 文件策略（dev/prod）是合理的平台适配设计，但文件内容不完整，导致新环境无法一次装好。改用 `pyproject.toml` 的 optional-dependencies 可以统一管理，且是 Python 生态的现代标准。

**2. CI 流水线（GitHub Actions）**

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: pytest tests/ -x --tb=short -q
```

一人开发更需要 CI，因为没有同事帮你 code review，CI 是你唯一的自动化守门人。

**3. 代码质量工具链**

```toml
# pyproject.toml 追加
[tool.ruff]
line-length = 120
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
ignore = ["E501"]  # 由 line-length 控制

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short -q"
```

ruff 替代 flake8+isort+pyupgrade 三件套，配置简单速度快，一人团队的最佳选择。

**4. 密钥分离**

```bash
# .env（gitignore 中）
DEEPSEEK_API_KEY=sk-xxx

# config.yaml 中改为引用
deepseek:
  api_key: ${DEEPSEEK_API_KEY}
```

当前 `config.example.yaml` 中 `api_key: 你的DeepSeek_API_Key` 是占位符没问题，但生产使用时用户容易直接改 `config.yaml` 导致 key 入库。应该从环境变量读取。

#### P1：一周内补全（提升迭代信心）

**5. 测试修复与覆盖率门槛**

当前 17 个失败用例中：
- 13 个是 `ModuleNotFoundError: pandas` — 环境问题，依赖补齐即修复
- 2 个是 DeepSeek API key 缺失 — 需要 mock，不应依赖外部服务
- 1 个是 `ReportDegradedResult` 缺少 `success` 属性 — 代码 bug
- 1 个是 `AgentMemory` 测试断言 — 代码或测试 bug

修复策略：先修环境依赖 → 再修代码 bug → 最后补 mock 隔离外部依赖。目标：全绿后设 CI 门槛。

**6. 预提交钩子**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: local
    hooks:
      - id: pytest-quick
        name: Quick tests
        entry: pytest tests/ -x -q --timeout=30
        language: system
        pass_filenames: false
```

#### P2：两周内（工程化成熟）

- CHANGELOG.md + 语义版本号
- `make` / `just` 任务编排（`just test`、`just dev`、`just lint`）
- 开发环境一键脚本（`scripts/setup-dev.sh`）

### 1.3 实施节奏

```
Day 1:  修复 requirements + 安装所有依赖 + 修复测试
Day 2:  添加 ruff + pyproject.toml + .env 分离
Day 3:  配置 GitHub Actions CI + pre-commit
Day 4:  修复全部失败测试，设置覆盖率门槛
Day 5:  验收——push 触发 CI 全绿
```

### 1.4 核心判断

**必须补，但要「轻量」补。** 一人团队的工程基建不是为了好看，而是为了两个目的：
1. **防退化**：你今天改了 data_loader，CI 自动告诉你 calculators 是否受影响
2. **降认知负担**：不用记住「提交前要跑 pytest」，CI 替你记

不需要：Docker 化（桌面应用不需要）、复杂的 monorepo 工具、多环境部署流水线。

---

## 二、客户端 vs 客户端-服务端架构决策

### 2.1 核心矛盾分析

这个问题的本质不是「要不要做服务端」，而是：

> **你的目标用户群是「一个人用」还是「一个团队用」？**

当前设计是彻底的单机架构：全局 `_session`、单例 DuckDB 连接、PyWebView 窗口——这些都是「我的电脑上跑我自己的工具」的设计。

但金融资管的现实是：
- 投资经理、研究员、风控、合规 各自需要看不同维度的同一份数据
- 合规监控的结果要多人知晓，不是一个人看完就行
- 报告需要协作（投资经理出数字，部门负责人审）
- 数据源是共享的（同一份持仓导出，不应每人上传一次）

### 2.2 我的判断：采用「厚客户端 + 薄服务端」渐进架构

**不是二选一，而是分层设计，逐步引入服务端能力。**

```
Phase A（当前→3个月）：纯客户端，优化单机体验
  ┌─────────────┐
  │  PyWebView   │
  │  Flask(local)│
  │  DuckDB      │
  │  本地文件     │
  └─────────────┘

Phase B（3→6个月）：可选的轻量服务端
  ┌─────────────┐     ┌──────────────────┐
  │  客户端      │────→│  协作服务端(可选)  │
  │  本地计算    │     │  报告共享         │
  │  本地数据    │     │  消息通知         │
  │  离线可用    │     │  配置同步         │
  └─────────────┘     └──────────────────┘

Phase C（6个月+）：混合架构
  ┌─────────────┐     ┌──────────────────┐
  │  客户端      │────→│  团队服务端       │
  │  敏感数据    │     │  用户认证         │
  │  本地执行    │     │  权限管理         │
  │             │←────│  数据源注册       │
  └─────────────┘     │  审批工作流       │
                      │  共享知识库       │
                      └──────────────────┘
```

### 2.3 服务端要做什么（以及不做什么）

**服务端做的（轻量、高价值）：**

| 能力 | 目的 | 实现方式 |
|------|------|---------|
| 报告共享 | 投资经理生成的报告，负责人/合规可以通过链接查看 | 静态文件服务 + 访问令牌 |
| LLM API 网关 | 集中管理 API Key，避免每台客户端存 key | FastAPI 代理层 |
| 配置同步 | 集团系名单、阈值等团队级配置统一管理 | Git 同步 或 简单 REST API |
| 通知推送 | 超标告警推送到企业微信/钉钉 | Webhook 转发 |
| 用户认证 | 区分谁是投资经理、谁是合规 | 企业 LDAP / 简单 JWT |

**服务端不做的（守住合规底线）：**

| 不做 | 原因 |
|------|------|
| 不传输原始持仓数据 | 合规红线——实际数值不出内网 |
| 不在服务端运行 SQL | 数据留在客户端，算力也在客户端 |
| 不存储完整分析结果 | 服务端只存摘要/元数据，不存行级数据 |

### 2.4 架构上需要做的调整

当前架构调整为服务端友好并不需要推倒重来，核心改动是：

**1. 将 `_session` 全局状态改为 SessionStore**

```python
# 当前（单机单用户）
_session = {"messages": [], "loaded_tables": {}, ...}

# 目标（多会话隔离，为多用户铺路）
class SessionStore:
    def get_session(self, session_id: str) -> Session: ...
    def create_session(self, user_id: str) -> Session: ...
```

这个改动即使不做服务端也有价值——支持多标签页、防止状态混乱。

**2. 将 Flask 路由拆分为 Blueprint**

```python
# 当前：main.py 40+ 路由全部堆在一起
# 目标：
api/
├── chat.py          # /api/chat, /api/stream
├── data.py          # /api/upload, /api/tables, /api/data
├── config.py        # /api/config, /api/groups
├── skill.py         # /api/skill-builder/*
├── report.py        # /api/report/*（新增）
└── system.py        # /api/health, /api/logs
```

**3. 定义清晰的 API 契约**

为将来客户端-服务端通信做准备，当前 API 的请求/响应格式需要标准化：

```python
# 统一响应格式
{
    "ok": true,
    "data": {...},
    "error": null
}
```

### 2.5 核心判断

**Phase A（近3个月）不做服务端，但做好架构准备。** 具体做的事：
- 会话隔离（SessionStore）
- 路由拆分（Blueprint）
- API 响应标准化

这些改动对当前单机体验无害，但为将来加服务端打好地基。一人团队运维服务端的 overhead 很大，在用户量达到 5-10 人之前不值得。

---

## 三、一人团队的资源约束策略

### 3.1 核心原则：做乘法，不做加法

一人研发 + Claude Code 的组合，最大的优势是**迭代速度**，最大的劣势是**维护带宽**。

这意味着：
- **每新增一个功能，未来的维护成本就增加一份**
- **选择不做什么，比选择做什么更重要**
- **用成熟库替代自研，哪怕功能只覆盖 80%**

### 3.2 优先级矩阵（结合前次评估）

用「影响力 × 实现难度」四象限重新排列所有改进项：

```
影响力高 + 难度低（立即做）        影响力高 + 难度高（分阶段做）
┌─────────────────────────┐    ┌─────────────────────────┐
│ ① 工程基建补全            │    │ ⑤ Agent 规划层（Plan-Execute）│
│ ② 测试全修复 + CI         │    │ ⑥ 前端组件化重构           │
│ ③ report_builder 补全     │    │ ⑦ 团队协作/服务端          │
│ ④ 数据持久化              │    │                         │
└─────────────────────────┘    └─────────────────────────┘

影响力低 + 难度低（空闲时做）      影响力低 + 难度高（暂不做）
┌─────────────────────────┐    ┌─────────────────────────┐
│ ⑧ chart_builder 补全     │    │ ⑩ 多 Agent 协作           │
│ ⑨ 智能上传识别           │    │ ⑪ 收益归因分析            │
│                         │    │ ⑫ 移动端适配              │
└─────────────────────────┘    └─────────────────────────┘
```

### 3.3 一人团队的 6 条实操策略

**策略一：两周迭代制**

```
Week 1: 一个聚焦目标（如「补全 report_builder」）
  - Day 1-2: 设计 + 写测试
  - Day 3-4: 实现
  - Day 5: 测试 + 修 bug

Week 2: 同一个目标的收尾 + 下一个目标的调研
  - Day 1-2: 集成测试 + 修边界情况
  - Day 3: 推上去，写简短变更日志
  - Day 4-5: 下个迭代的需求分析 + 技术调研
```

每个迭代只做一件事。不要在一个迭代里同时改 Agent 循环和改 UI。

**策略二：Claude Code 作为开发伙伴的最佳实践**

你已经在用 Claude Code，以下是最大化效率的建议：
- **CLAUDE.md 是你最重要的资产**——保持它准确、最新。你已经做得很好
- **用 Claude Code 写测试**——测试是最适合 AI 写的代码（确定性规则、不需要创意）
- **用 Claude Code 做重构**——把「拆分 main.py 为 Blueprint」这种确定性改动交给它
- **不要用 Claude Code 做架构决策**——架构决策需要业务理解，这是你的专长
- **每次会话开始时让 Claude Code 先跑测试**——建立基线，避免回退

**策略三：用库替代自研**

| 需求 | 当前方案 | 建议方案 | 省时 |
|------|---------|---------|------|
| Word 导出 | 无（report_builder 空壳） | `python-docx` | 3 天 |
| PDF 导出 | 无 | `weasyprint` 或 `fpdf2` | 2 天 |
| 图表生成 | 无（chart_builder 空壳） | ECharts 已引入但未用，后端只需传数据 | 2 天 |
| Web 搜索 | 无 | `duckduckgo-search` 或 `tavily-python` | 1 天 |
| 文件解析 | 仅 CSV/Excel | `unstructured` 或 `pypdf2` + `python-docx` | 2 天 |
| 前端框架 | 单 HTML（1781行） | 暂不迁移，先抽 JS 为独立模块 | — |

**策略四：先完成闭环，再打磨细节**

> 一个粗糙但能跑完全流程的功能，比十个精致但只完成一半的功能，价值高十倍。

具体来说：先让用户能 `上传数据 → 对话分析 → 生成报告 → 导出 Word` 这个完整闭环走通，再去优化每一步的体验。

**策略五：技术债务的管理**

一人团队一定会积累技术债，关键是**主动管理**而非假装没有：

- 用 `TODO(P0)` / `TODO(P1)` / `TODO(P2)` 标记，不用 `FIXME` 或空的 `TODO`
- 每月花半天做一次「技术债清理日」
- 把技术债和功能开发的比例控制在 2:8（每 5 个工作日中 1 天还债）

**策略六：不要过早抽象**

```python
# ❌ 一人团队不需要这种过度设计
class ToolRegistry:
    def register(self, name, definition, handler): ...
    def get_definitions(self, context) -> list: ...

# ✅ 直接在 tools_spec.py 里加一个工具定义就行
# 等工具超过 15 个再考虑注册表机制
```

### 3.4 推荐的 12 周路线图（一人团队版）

```
Week 1-2:  工程基建 + 测试全修复 + CI 绿灯
Week 3-4:  report_builder 完整实现（Jinja2 模板 → Word 导出）
Week 5-6:  数据持久化（DuckDB 文件模式 + 启动自动加载上次数据）
Week 7-8:  通用能力扩展——联网搜索工具 + 文件解析工具
Week 9-10: chart_builder 补全 + ECharts 数据联动
Week 11-12: main.py 拆分 Blueprint + SessionStore + API 标准化
```

12 周后你将拥有：一个测试完备、能生成 Word 报告、数据持久化、支持联网搜索的资管 Agent。

---

## 四、通用 Agent 能力扩展评估

### 4.1 我的判断：方向正确，但策略必须是「T 型」而非「一字型」

```
         数据分析（深）
           │
           │
   ┌───────┼───────────────────────────────┐
   搜索    │    文件处理    报告编制    日常办公（广）
   │       │       │          │          │
   浅      深      浅         深         浅
```

**「T 型」策略**：数据分析做到行业最深（这是你的壁垒），其他能力做到「够用」即可。

不要试图在每个方向都做到极致——联网搜索你不可能比 Perplexity 好，文件处理你不可能比 WPS 好。但是：
- 当用户在分析持仓数据时顺手问「最近有没有关于这个发行人的新闻」，能直接搜出来，就是巨大的价值
- 当分析完成后能自动填入 Word 模板导出报告，而不是用户手动复制粘贴，就解决了真实痛点

### 4.2 各能力的评估与实施策略

#### A. 数据分析（持续深化，核心竞争力）

**保持当前的固化计算器 + 探索式 SQL 双轨制**，这个设计是正确的。深化方向：

| 能力 | 优先级 | 实施 |
|------|--------|------|
| 补齐合规计算器（杠杆率、久期、流动性） | P0 | 每个 2-3 天，是固化 SQL 不需要 LLM |
| 持仓变动对比（两期 diff） | P0 | 1 个 calculator，复用现有 DuckDB |
| 多期时间序列趋势 | P1 | 在现有数据表上增加日期维度查询 |
| 数据质量自动修复建议 | P2 | 基于 tools/quality.py 输出推荐清洗动作 |

#### B. 联网搜索（新增，中等优先级）

**定位**：不是通用搜索引擎，而是「投研辅助搜索」——搜主体新闻、搜行业政策、搜债券公告。

**实施方案**：

```python
# 新增 tools/web_search.py
# 工具定义加入 TOOL_DEFINITIONS
{
    "name": "web_search",
    "description": "搜索互联网信息（新闻、公告、政策等）。当用户问到某个主体的最新动态、市场新闻、监管政策时使用。",
    "parameters": {
        "query": {"type": "string", "description": "搜索关键词"},
        "search_type": {"type": "string", "enum": ["news", "policy", "bond_notice", "general"]}
    }
}
```

技术选型：
- `duckduckgo-search`（无需 API key，免费，适合原型）
- 或 `tavily-python`（质量更好，有 API key 免费额度）
- 长期可接入 Wind/Bloomberg API（金融专业数据源）

**合规注意**：搜索查询可能包含主体名等商业信息。需要与 SQL 生成相同的合规处理——优先内网搜索代理，外部搜索需脱敏或合规签字。

#### C. 文件处理（新增，高优先级）

**定位**：不只是「读文件」，而是「从各种格式的业务文档中提取结构化信息」。

资管人员日常处理的文件类型：

| 文件类型 | 场景 | 处理方式 |
|---------|------|---------|
| Excel (.xlsx) | 已支持 | 当前 data_loader.py |
| CSV | 已支持 | 当前 data_loader.py |
| Word (.docx) | 评级报告、会议纪要、投委会决议 | `python-docx` 读取 |
| PDF | 债券募集说明书、评级报告 | `pypdf2` / `pdfplumber` |
| 图片 | 截图中的数据表 | OCR（后期，需要依赖较重） |

**实施方案**：

```python
# 扩展 tools/data_loader.py 或新增 tools/file_reader.py
# 将「文件解析」作为 Agent 工具
{
    "name": "read_document",
    "description": "读取并解析 Word/PDF 文档内容，提取文本和表格。当用户上传非表格数据文件，或要求分析文档内容时使用。",
    "parameters": {
        "file_path": {"type": "string"},
        "extract_tables": {"type": "boolean", "default": true}
    }
}
```

#### D. 报告编制（最高优先级，最大价值增量）

这是当前项目最大的价值缺口。`report_builder.py` 和 `chart_builder.py` 都是空文件，但 CLAUDE.md 中详细设计了报告模板系统、Jinja2 渲染、Word 导出。

**完整的报告生成管线**：

```
数据查询/计算（已有）
    ↓
模板选择（Skill.md 中 calc_type: fixed 的场景）
    ↓
Jinja2 渲染 Markdown → HTML 预览（前端显示）
    ↓
用户确认/编辑（request_confirmation 工具已有）
    ↓
导出 Word/PDF（python-docx / weasyprint）
    ↓
保存到 data/outputs/ + 合规审计日志
```

**分步实施**：

```
Step 1（3天）：report_builder 核心——Jinja2 模板渲染 → Markdown 输出
Step 2（2天）：python-docx 导出——模板 + 数据 → Word 文件
Step 3（2天）：前端「报告预览」面板——在对话中内嵌 HTML 预览
Step 4（2天）：chart_builder——ECharts 配置生成器，输出 option JSON
Step 5（1天）：集成——报告中嵌入图表（ECharts 截图 或 SVG）
```

#### E. 日常办公辅助（低优先级，渐进增加）

| 能力 | 价值 | 实现难度 | 建议 |
|------|------|---------|------|
| 日程提醒 | 低（系统自带） | 低 | 不做 |
| 邮件草稿 | 中 | 低 | 可做，LLM 生成邮件文本 |
| 会议纪要生成 | 高 | 中 | 基于已有数据生成要点 |
| 公文模板填充 | 中 | 低 | Jinja2 模板，复用报告管线 |

### 4.3 工具扩展的架构设计

当前 7 个工具硬编码在 `tools_spec.py` 的 `TOOL_DEFINITIONS` 列表中。随着能力扩展，建议改为按模块自动发现：

```python
# tools_spec.py 改造方案（不需要复杂注册表）
# 每个工具文件导出自己的定义和处理函数

# tools/web_search.py
TOOL_DEF = { "type": "function", "function": { "name": "web_search", ... } }
def handle(args, ctx): ...

# tools_spec.py 自动收集
import importlib
TOOL_MODULES = ["profile_table", "run_sql", "run_calculator",
                "ask_user", "request_confirmation",
                "web_search", "read_document"]  # 新增的直接加名字

TOOL_DEFINITIONS = []
_handlers = {}
for mod_name in TOOL_MODULES:
    mod = importlib.import_module(f"tools.{mod_name}")
    TOOL_DEFINITIONS.append(mod.TOOL_DEF)
    _handlers[mod.TOOL_DEF["function"]["name"]] = mod.handle
```

这种方式在工具数 < 20 时足够简洁，不需要抽象类/注册表/插件系统。

### 4.4 核心判断

**扩展路径：报告编制 → 文件解析 → 联网搜索 → 日常办公。**

理由：
1. 报告编制是资管人员每天必做的事，且当前完全缺失，ROI 最高
2. 文件解析让用户不只上传表格，还能喂入 Word/PDF 文档做分析
3. 联网搜索提供「投研助手」的体验升级
4. 日常办公是锦上添花，优先级最低

---

## 五、前端界面设计：功能分类与交互架构

### 5.1 核心设计理念

> **Agent 产品的前端不是「功能菜单」，而是「能力展厅 + 对话画布」。**

用户不应该需要翻菜单找功能。最好的 Agent UI 是：用户说出需求，Agent 自动调动正确的能力。UI 的作用是让用户**看到 Agent 能做什么**和**看到 Agent 正在做什么**。

### 5.2 功能四象限分类

将 DataAgent 的所有功能按「交互方式」和「使用频率」分为四个区域：

```
                        高频使用
                          ↑
              ┌───────────┼───────────┐
              │ A 对话操作区 │ B 快捷操作区│
     对话驱动 ←│           │           │→ 直接操作
              │ C 状态感知区│ D 配置管理区│
              └───────────┼───────────┘
                          ↓
                        低频使用
```

#### A 区：对话操作区（Chat-Driven，主交互区）

用户通过自然语言触发的所有能力：

| 能力 | 触发方式 | 结果展示 |
|------|---------|---------|
| 数据查询 | 对话 | 表格 + 文字 |
| 合规检查 | 对话 | 结论卡片 + 确认按钮 |
| 报告生成 | 对话 | 报告预览 + 导出按钮 |
| 图表分析 | 对话 | 内嵌 ECharts |
| 联网搜索 | 对话 | 搜索结果摘要 |
| 持仓变动 | 对话 | 对比表格 + 瀑布图 |

**设计原则**：这些能力不需要菜单入口，用户说了就有。但需要：
- **提示气泡**：当用户加载了数据但没说话，显示 3-5 个推荐问题
- **能力标签**：在输入框上方显示「可用能力」标签（数据分析、合规检查、报告生成...）
- **@mention 增强**：`@持仓表` 指定数据源，`@集中度` 指定 Skill

#### B 区：快捷操作区（Direct Action，高频但非对话）

用户直接点击触发的操作，不需要打字：

| 操作 | UI 元素 | 位置 |
|------|---------|------|
| 上传数据文件 | 拖拽区 + 文件选择器 | 侧边栏顶部 |
| 刷新数据（重新加载指定目录） | 刷新按钮 | 每个数据表旁 |
| 一键生成日报/周报 | 快捷按钮 | 工作台区域 |
| 导出上次分析结果 | 导出按钮 | 每条分析结果旁 |
| 切换会话 | 会话列表 | 侧边栏 |
| 复制表格数据 | 复制按钮 | 每个表格右上角 |

**设计原则**：高频操作要一键触达，不要埋在对话流中。上传文件这种操作，对话不是最佳交互方式。

#### C 区：状态感知区（System Awareness，被动展示）

系统状态信息，用户需要知晓但不需要操作：

```
┌─ 顶栏状态条 ─────────────────────────────────────────────┐
│ 🟢 LLM 在线  │  📊 3 张表已加载  │  ⏱ 数据截至 06-05  │  📝 2 报告待导出  │
└─────────────────────────────────────────────────────────┘
```

| 信息 | 展示方式 | 位置 |
|------|---------|------|
| LLM 连接状态 | 绿/红/黄点 | 顶栏 |
| 已加载数据表摘要 | 列表 + 行数 + 时效 | 侧边栏 |
| 数据时效警告 | 橙色横幅 | 顶栏/数据表旁 |
| Agent 执行状态 | 进度条 + 步骤指示 | 对话区内嵌 |
| 内存使用 | 小型仪表盘 | 设置面板或状态栏 |
| 定时任务状态 | 下次执行时间 | 侧边栏 |
| 合规超标计数 | 红色角标 | 侧边栏 |

**设计原则**：状态信息不应抢占注意力，但异常状态必须醒目。用「颜色语义」区分：绿=正常，黄=注意，红=异常。

#### D 区：配置管理区（Settings，低频深度操作）

用户偶尔需要修改的配置项：

| 配置项 | 交互方式 | 频率 |
|--------|---------|------|
| LLM 端点/API Key | 表单 | 首次 + 变更时 |
| 合规阈值（集中度/杠杆率） | 数值输入 + 确认 | 极低频（监管要求变更） |
| 用户档案（姓名/部门/产品） | 表单 | 首次设置 |
| 集团系管理（增删改） | CRUD 列表 | 中频（关系变动） |
| 数据源目录配置 | 路径选择器 | 首次设置 |
| 定时任务配置 | 时间选择 + 开关 | 低频 |
| 记忆库开关 | 开关 | 一次性 |
| 主题（明/暗） | 切换按钮 | 一次性 |
| Skill 管理（创建/编辑/删除） | 专用面板 | 低频 |

**设计原则**：配置项收纳在侧边栏的「设置」面板中，不污染主工作区。合规阈值等敏感配置需要二次确认。

### 5.3 推荐的界面布局（演进版）

```
┌──────────────────────────────────────────────────────┐
│ 顶栏：Logo │ 状态条（C区）  │ 搜索 │ 设置 │ 主题 │     │
├────────────┬─────────────────────────────────────────┤
│            │                                         │
│  侧边栏     │        主工作区                          │
│  (240px)   │                                         │
│            │  ┌──────────────────────────────────┐    │
│  ▼ 数据表   │  │  能力推荐标签 [分析] [报告] [搜索]  │    │
│    表1 ●新  │  └──────────────────────────────────┘    │
│    表2     │                                         │
│    表3 ⚠旧  │  ┌──────────────────────────────────┐    │
│            │  │                                  │    │
│  ▼ 快捷动作  │  │     对话消息流（A区）              │    │
│    📊 日报  │  │                                  │    │
│    📋 周报  │  │     [文字][表格][图表][报告预览]    │    │
│    ⚡ 合规  │  │                                  │    │
│            │  │     [确认卡片][选择卡片]           │    │
│  ▼ 会话历史  │  │                                  │    │
│    今天      │  └──────────────────────────────────┘    │
│    昨天     │                                         │
│            │  ┌──────────────────────────────────┐    │
│  ▼ 技能     │  │ 输入框 [📎上传] [@mention] [发送]  │    │
│  ▼ 集团系   │  │ 能力标签: 数据分析 报告 搜索 文件   │    │
│  ⚙ 设置    │  └──────────────────────────────────┘    │
│            │                                         │
├────────────┴─────────────────────────────────────────┤
│ 底栏(可选)：内存 45MB │ 3个待办 │ 下次任务 09:00      │
└──────────────────────────────────────────────────────┘
```

### 5.4 关键交互设计

#### 5.4.1 新用户引导（Onboarding）

```
首次启动 → 欢迎面板：
┌──────────────────────────────────────┐
│  👋 欢迎使用 DataAgent               │
│                                      │
│  先完成简单设置：                      │
│  [1] 设置您的姓名和部门  ✓            │
│  [2] 配置 LLM 连接                   │
│  [3] 上传第一份数据文件               │
│                                      │
│  或者，试试这些：                      │
│  💬 "帮我看看这份持仓的集中度"         │
│  💬 "生成本周运作报告"                 │
│  💬 "最近有没有关于XX主体的新闻"       │
└──────────────────────────────────────┘
```

#### 5.4.2 上下文感知推荐

```python
# 推荐逻辑（嵌入 agent/recommender.py）
def get_suggestions(loaded_tables, recent_queries, current_time):
    suggestions = []
    
    # 基于已加载数据
    if has_holding_table():
        suggestions.append("查看主体集中度")
        suggestions.append("查看资产结构分布")
    if has_nav_table():
        suggestions.append("查看净值变动趋势")
    if has_holding_table() and has_previous_holding():
        suggestions.append("对比持仓变动")
    
    # 基于时间
    if is_friday():
        suggestions.append("生成本周运作报告")
    if is_month_end():
        suggestions.append("生成月度总结")
    
    # 基于最近查询
    if last_query_about("集中度") and found_breach:
        suggestions.append("查看超标主体详情")
        suggestions.append("生成超标预警报告")
    
    return suggestions[:5]
```

#### 5.4.3 Agent 执行过程可视化

当前 Agent 执行时用户只能看到流式文字输出。升级为：

```
用户：帮我准备参谈要点

Agent 执行计划（可编辑）：
┌──────────────────────────────────────┐
│ ☑ Step 1: 剖析持仓表结构             │
│ ☑ Step 2: 计算主体集中度（固化计算）    │
│ ☐ Step 3: 计算资产结构分布            │  ← 当前执行
│ ☐ Step 4: 获取净值数据               │
│ ☐ Step 5: 生成参谈要点报告            │
│                                      │
│ [编辑计划] [跳过 Step 4] [停止]       │
└──────────────────────────────────────┘
```

这需要前面讨论的 Plan-Execute 架构配合，但 UI 部分可以先搭好框架。

#### 5.4.4 结果操作菜单

每个分析结果后增加操作按钮：

```
[表格结果]
  产品名称 | 集中度 | 阈值 | 状态
  ...

  [📋 复制] [📥 下载CSV] [📊 生成图表] [📝 加入报告]
```

### 5.5 前端实施策略

**近期（1-2 个月）：不迁移框架，在现有 index.html 上增量改进**

| 改进 | 工作量 | 效果 |
|------|--------|------|
| 添加快捷操作区（侧边栏） | 1 天 | 高频操作一键触达 |
| 添加能力推荐标签（输入框上方） | 0.5 天 | 用户知道能问什么 |
| 表格结果增加操作按钮（复制/下载） | 1 天 | 结果可导出 |
| 状态条（顶栏） | 0.5 天 | 系统状态可见 |
| 新用户引导面板 | 1 天 | 降低上手成本 |

**中期（3-4 个月）：JS 模块化，为组件化铺路**

将 index.html 中的 JS 按功能拆分为独立文件：
```
ui/
├── index.html          # 只保留 HTML 结构
├── css/
│   └── main.css        # 样式抽出
├── js/
│   ├── app.js          # 入口 + 状态管理
│   ├── chat.js         # 对话逻辑
│   ├── upload.js       # 上传逻辑
│   ├── sidebar.js      # 侧边栏
│   ├── sse.js          # SSE 事件处理
│   ├── charts.js       # ECharts 渲染
│   └── report.js       # 报告预览/导出
```

**远期（5-6 个月）：如需更复杂的交互再考虑 Vue/React**

但要注意：PyWebView 环境下，前端框架的运行时开销不能忽略。如果能用 vanilla JS + 模块化解决问题，不要为了「技术先进性」引入框架。

### 5.6 核心判断

前端改进的优先顺序：
1. **功能补全**（报告预览、图表渲染、结果导出）——这些是业务阻塞项
2. **可发现性**（能力标签、推荐系统、onboarding）——降低学习成本
3. **操作效率**（快捷动作、复制/下载按钮）——提升日常使用效率
4. **架构升级**（JS 模块化、组件化）——只在前三项做完后才有意义

---

## 六、综合路线图：一人团队 24 周演进计划

将上述五个维度的建议整合为统一的执行计划：

### Phase 1：地基加固（Week 1-4）

```
目标：工程基建完备，核心缺陷修复，测试全绿

Week 1: 工程基建
  - 修复所有依赖 + pyproject.toml
  - 配置 ruff + GitHub Actions CI
  - 修复全部 17 个失败测试
  - .env 密钥分离

Week 2: 代码缺陷修复
  - ReportDegradedResult 补全 success 属性
  - AgentMemory 测试修复
  - LLM 调用 mock 化（测试不依赖外部服务）

Week 3-4: report_builder 实现
  - Jinja2 模板渲染 → Markdown/HTML
  - python-docx Word 导出
  - 基础报告模板（运作报告、集中度报告）
  - 前端报告预览面板

交付物：CI 全绿 + 能生成 Word 报告
```

### Phase 2：核心体验闭环（Week 5-8）

```
目标：完整的「上传 → 分析 → 报告 → 导出」闭环

Week 5-6: 数据持久化 + chart_builder
  - DuckDB 文件模式（启动恢复上次数据）
  - chart_builder 核心实现（饼图、柱状图、折线图）
  - ECharts 数据联动

Week 7-8: 前端增量改进
  - 快捷操作区（一键生成日报/周报）
  - 结果操作按钮（复制/下载/加入报告）
  - 能力推荐标签 + 新用户引导
  - 状态条（LLM状态/数据时效/任务状态）

交付物：用户日常工作闭环可用
```

### Phase 3：能力扩展（Week 9-14）

```
目标：从数据分析工具升级为资管助手

Week 9-10: 通用能力扩展
  - tools/web_search.py（联网搜索工具）
  - tools/file_reader.py（Word/PDF 解析工具）
  - 工具注册到 Agent 工具链

Week 11-12: 计算器补齐 + main.py 重构
  - leverage.py / duration.py / liquidity.py
  - main.py 拆分为 Blueprint 模块
  - SessionStore 会话隔离

Week 13-14: 上下文推荐 + Agent 执行可视化
  - agent/recommender.py 上下文感知推荐
  - 前端执行计划展示（为 Plan-Execute 铺路）
  - JS 模块化拆分

交付物：支持搜索和文件解析的多能力 Agent
```

### Phase 4：智能化升级（Week 15-20）

```
目标：Agent 从「工具执行者」升级为「工作规划者」

Week 15-16: Plan-Execute 架构
  - agent/planner.py 任务分解
  - 执行计划的生成、展示、编辑
  - 失败重规划

Week 17-18: 数据自动化
  - 数据源目录监控（自动加载新文件）
  - 时间序列分析（持仓变动追踪）
  - 前端数据源管理面板

Week 19-20: 质量保障
  - Agent 自检机制（结果合理性校验）
  - LLM 成本监控 + token 预算
  - 安全审计增强
  - 综合集成测试

交付物：具备规划能力的智能 Agent
```

### Phase 5：产品化打磨（Week 21-24）

```
目标：可交付给团队试用的产品

Week 21-22: API 标准化 + 协作准备
  - API 版本化 (/api/v1/)
  - 报告共享（可分享链接）
  - 通知推送（企业微信 webhook）

Week 23-24: 打包与发布
  - Windows PyInstaller 打包
  - WebView2 检测和引导
  - 用户手册（简版）
  - 灰度测试

交付物：可安装分发的 Windows 桌面应用
```

---

## 七、最终建议摘要

| 问题 | 核心判断 |
|------|---------|
| 1. 工程基建 | **必须补，轻量补。** CI + ruff + 依赖锁定，5 天内完成。不需要 Docker/K8s |
| 2. 客户端 vs 服务端 | **近期不做服务端，但做架构准备。** SessionStore + Blueprint 拆分，为将来铺路 |
| 3. 资源约束 | **两周迭代制 + T型能力策略。** 每个迭代只做一件事，Claude Code 负责测试和重构 |
| 4. 通用能力扩展 | **报告编制 > 文件解析 > 联网搜索 > 日常办公。** 数据分析深耕为核心壁垒 |
| 5. 前端设计 | **四象限分类：对话操作 / 快捷动作 / 状态感知 / 配置管理。** 先补功能再改架构 |

**一句话总结**：先让产品在单个用户的日常工作中不可替代（完整闭环 + 报告导出），再逐步扩展能力边界和用户范围。
