# DataAgent — Claude Code 主引导文件 v2.2

> 版本历史见文末"改进记录"表格。
> **测试指南**：完整测试策略见 `TESTING.md`。
> **自动化机制**：`scripts/sync_project_state.py` 在每次 git commit 后自动维护管理文档。

---

## ★ 会话协议（Session Protocol）— 每次会话强制执行

> **这是最高优先级指令，高于本文件其他所有章节。**

### 会话开始（必须先做，在写任何代码之前）

```
步骤 1：python scripts/project_check.py        # 获取项目状态快照
步骤 2：读取 HANDOFF.md                        # 了解上次会话做了什么、下一步是什么
步骤 3：读取 PROGRESS.md 当前阶段部分           # 确认阶段和遗留项
步骤 4：向用户输出 3-5 句话的当前状态摘要：
        - 当前阶段是什么
        - 上次做了什么
        - 本次建议从哪里开始
        - 是否有未提交变更或技术债需要先处理
```

### 会话结束（git commit 前必须做，commit 后自动触发）

```
【Claude 负责 — 叙述性内容，需要判断】
步骤 1：写 HANDOFF.md「上次会话完成的工作」段落 + 「立即可执行的下一步」
        （最后更新块的日期/提交/分支 → commit 后自动填写，无需手动）
步骤 2：更新 PROGRESS.md（将完成的 [ ] 改为 [x]，新增遗留项）
步骤 3：若有架构变更，更新 CLAUDE.md 对应章节
步骤 4：git add + commit + push
        ↑ 提交后自动执行（git hooks + Claude PostToolUse）：
          • pre-commit  → pytest -x + ruff（失败则阻断提交）
          • post-commit → sync_project_state.py：
                          更新 HANDOFF.md 最后更新块 / START_HERE.md /
                          latest_summary.json / CHANGELOG.md
步骤 5：告知用户：本次完成了什么，下次从哪里开始（1-2 句话）

【首次克隆时运行一次】
python scripts/install_hooks.py    # 安装 pre-commit / post-commit git 钩子
```

### 自动维护的文档（无需手动更新）
| 文档 | 自动更新时机 | 更新内容 |
|------|------------|---------|
| `HANDOFF.md` "最后更新"块 | 每次 git commit | 日期/提交哈希/分支 |
| `START_HERE.md` 状态行 | 每次 git commit | 分支名/测试结果 |
| `CHANGELOG.md` | 每次 git commit | 追加本次提交（按类型分组）|
| `data/test_reports/latest_summary.json` | 每次 git commit | 时间戳；运行测试时更新数值 |

### 迭代测试关卡（Iteration Testing Gate）— 新功能/阶段迭代时强制执行

【迭代开始前（编码前）— 测试设计关卡】
```
步骤 T1：分析本次迭代的变更范围和影响面
步骤 T2：按四层测试框架（L1单元/L2功能/L3集成/L4 UAT）设计测试用例
步骤 T3：写出迭代测试计划到 data/test_plans/YYYYMMDD_{迭代名}.md
         （模板见 TESTING.md 第十章）
步骤 T4：确认已有测试对变更影响面的覆盖情况，补充缺口
⚠️ 没有测试计划，不得开始写功能代码
```

【迭代完成后（提交前）— 测试执行关卡】
```
步骤 T5：运行全量测试套件（pytest tests/ -v），确认无回归
步骤 T6：对照测试计划逐条确认：L1~L3 用例全部实现并通过
步骤 T7：在 data/test_plans/ 下的迭代测试计划中填写执行结果
步骤 T8：UAT 场景（L4）写入测试计划"待验收"栏，等待业务方/用户确认
步骤 T9：在 PROGRESS.md 迭代条目旁标注测试状态：
         ✅ 已测（L1+L2+L3通过，L4待UAT）或 ⚠️ 部分覆盖（说明原因）
⚠️ 测试未通过或存在P0/P1缺口，不得标记迭代为"完成"
```

【违反规则的后果】
- 跳过测试计划（T1-T4）→ PROGRESS.md 不得标记该迭代完成
- L1/L2/L3 有失败 → 不得提交，先修复
- 使用 `--no-verify` 跳过 pre-commit → 必须在 HANDOFF.md 记录原因且补写测试

### 违反协议的后果
- 跳过 HANDOFF.md 叙述更新 → 下次会话无法定位状态
- 跳过 PROGRESS.md 更新 → 阶段进度断档
- 使用 `--no-verify` 跳过 pre-commit → 必须在 HANDOFF.md 记录原因
- 跳过迭代测试计划（T1-T4）→ 该迭代不得标记完成

---

## 零、开发环境与平台策略（重要，必读）

### 当前环境
- **开发环境**：Linux（Claude Code）/ macOS（本地开发）
- **目标运行环境**：Windows 11
- **已验证平台**：Linux / macOS / Windows（Phase 3 验收通过）

### 解决策略：平台适配层

所有平台差异封装在 `platform_adapter/` 目录，业务代码不感知平台：

```
platform_adapter/
├── ui_driver.py      → 窗口驱动（Linux=浏览器，Windows=PyWebView）
└── notify_driver.py  → 通知推送（Linux=终端/notify-send，Windows=toast）
```

### Linux 可以完整开发和测试的内容（所有业务逻辑）
Flask后端 / Agent Loop / DuckDB / calculators/ / data_dictionary/ / Skills系统 / LLM调用

### 必须等 Windows 的内容（仅UI层，Phase 5 统一处理）
PyWebView 原生窗口 / winotify toast / PyInstaller 打包 / WebView2内存测试

### 启动方式
```bash
# Linux 开发（自动走浏览器模式）
pip install -r requirements-dev.txt
python main.py

# Windows 生产（自动走 PyWebView）
pip install -r requirements-prod.txt
python main.py
```

详细说明见 `docs/dev-environment.md`。

## 一、项目定位与核心设计理念

### 一句话定位
DataAgent 是一个「**自然语言 → 确定性计算 → 受控叙述**」的本地资管分析助手。它要解决的不是「让 AI 算数字」，而是「让业务人员不写 SQL 也能拿到口径正确、可审计、不外泄的数字和报告」。

### 第一性约束（高于一切）
**数字的正确性和可追溯性，高于 Agent 的灵活性。**

准确性 = 算术准确 × 口径准确。本地引擎执行 SQL 只保证算术准确，不保证口径准确。若 SQL 取错字段、漏穿透、集团没合并，结果是「精确的错误」——比 AI 估算更可怕，因为它看起来权威。

### 硬性约束

| 约束 | 具体要求 |
|------|---------|
| 运行环境 | Windows 11，4–8 GB RAM，无独立 GPU |
| 内存目标 | **Python 进程树 < 200MB**（WebView2 渲染进程独立计算，Day 1 实测确认，必要时与业务方重新协商） |
| 数据合规 | 实际数值不出内网；**问题文本和表名含敏感商业信息，SQL 生成优先走内网 LLM**；外部 LLM 仅作兜底且需合规签字 |
| 用户背景 | 投资业务人员，非技术人员，设计不得有技术门槛 |
| 扩展方式 | 新业务场景 = 新增 Skills 文件，不修改核心 Python 代码 |
| 设计原则 | 第一性原理 + 开闭原则 |

---

## 二、架构总览（v2.0 Evolution I-1~I-10 + ETCLOVG 七层加固）

```
┌──────────────────────────────────────────────────────────────┐
│  交互层  PyWebView 窗口 / 对话 / 设置面板 / 确认卡片 / 告警横幅  │
│         前端 JS 9 模块（ui/js/）+ ECharts 图表 + Word 导出     │
├──────────────────────────────────────────────────────────────┤
│  API 路由层  main.py 40+ 路由（api/ Blueprint 模块待启用）      │
│             session_store.py 集中管理会话/队列/路径             │
├──────────────────────────────────────────────────────────────┤
│  ★Agent 编排层  Plan-Execute 两阶段（planner+executor）        │
│    LLM function-calling → 7 工具分发 + 场景化工具过滤           │
│    profile_table / run_sql / run_calculator / ask_user         │
│    request_confirmation / generate_chart / render_report       │
│    SelfChecker 数值自检 + 工具参数 Schema 校验                  │
│    暂停/续跑机制 + 会话 messages 持久化                         │
├──────────────────────────────────────────────────────────────┤
│  业务能力层（两类，严格区分，均经字段映射）                       │
│   A. 探索式分析：LLM 生成 SQL（apply_field_map + SQLGuard）     │
│   B. 合规/报告口径：calculators/ 固化计算（cols 全参数化映射）    │
├──────────────────────────────────────────────────────────────┤
│  ★可观测性层  Hook 系统(agent/hooks.py) + 成本追踪(cost_tracker)│
│              上下文三级压缩(context.py) + 审计 Hash Chain        │
├──────────────────────────────────────────────────────────────┤
│  ★剖析/质量层  tools/profiler.py(表结构剖析 + 自适应编码)        │
│              tools/quality.py(空值率/覆盖率/JOIN兼容性)         │
├──────────────────────────────────────────────────────────────┤
│  通用工具层  file_reader(文档解析) / web_search(联网搜索)        │
│            chart_builder(图表) / report_builder(报告+Word导出)  │
├──────────────────────────────────────────────────────────────┤
│  语义层  data_dictionary/ 数据字典 / 字段映射 / 主体归一 / Join键│
│          entity_normalizer 主体别名归一                         │
├──────────────────────────────────────────────────────────────┤
│  数据引擎层  DuckDB（只读 SELECT，参数化执行）max_memory=80MB    │
├──────────────────────────────────────────────────────────────┤
│  数据接入层  多编码竞争评分 + 字典映射清洗 + 多期版本 + 时效校验   │
│            两阶段上传确认 + 数据持久化（DuckDB 文件）            │
└──────────────────────────────────────────────────────────────┘
```

### 两类业务能力的区分（P0-1，最重要）

| 类型 | 适用场景 | SQL 来源 | 是否允许 LLM 修改 |
|------|---------|---------|---------------|
| **A 探索式** | 临时查询、灵活统计（场景5.2） | LLM 生成 | 允许 |
| **B 固化计算** | 合规监控（场景5.3）、运作报告（5.4.1）、参谈要点（5.4.2） | `calculators/` 中的函数 | **严禁** |

判断规则：只要结果会被用于合规决策或对外报告，必须走 B 类。

---

## 三、技术栈（v2.0 更新）

| 层级 | 选型 | 说明 |
|------|------|------|
| 桌面窗口 | pywebview 4.4.x | 原生窗口，pythonnet 3.x 兼容 |
| 后端 | Flask（最小化） | 随机端口，避免冲突；40+ 路由内联于 main.py |
| API 拆分 | api/ Blueprint 模块 | 6 个模块已创建（chat/data/config/skill/report/system），待启用注册 |
| 会话管理 | session_store.py | 集中管理 `_session`、`_stream_queues`、`BASE_DIR` |
| 实时通信 | SSE（Server-Sent Events） | LLM 流式输出 + tool_start/tool_end/thinking/ask/confirm/plan 事件 |
| 数据引擎 | DuckDB（内嵌） | max_memory=80MB, threads=2；支持持久化文件 |
| 数据处理 | Pandas | 清洗辅助 |
| 编码检测 | **多编码竞争评分** | 自适应 UTF-8/GB18030/GBK/GB2312/Latin-1 |
| SQL 解析 | sqlglot | CTE/子查询/别名感知的表名提取 |
| 定时调度 | schedule 库 | 轻量，含补跑检测 + 数据时效校验 |
| 前端 | HTML + 9 个 JS 模块 | ui/js/ 模块化，vanilla JS + 本地 CSS + 本地 ECharts（**零 CDN**） |
| 文档解析 | python-docx + pypdf | Word/PDF/TXT 文档读取 + Word 导出 |
| 联网搜索 | duckduckgo-search | 可选依赖，联网搜索工具 |
| 报告模板 | Jinja2 | 模板在 templates/reports/，支持 Word 导出 |
| 图表 | ECharts（客户端） | 柱/折/饼/散点，客户端渲染 + chart_builder.py 配置 |
| 系统通知 | winotify / osascript | Windows toast / macOS Notification Center |
| 配置 | PyYAML | config.example.yaml（.gitignore 排除 config.yaml） |
| 密钥管理 | python-dotenv + .env | .env.example 提供模板，.env 被 .gitignore 排除 |
| 日志 | append-only JSONL | 会话日志 + 合规审计日志（Hash Chain 防篡改） |
| LLM | DeepSeek / LM Studio / 企业内网 | OpenAI 兼容 API，支持本地 LLM（LM Studio） |
| Agent 规划 | planner.py + executor.py | Plan-Execute 两阶段，复杂任务自动分步 |
| 验证层 | self_check.py | 数值合理性校验（集中度/净值/收益率） |
| Hook 系统 | agent/hooks.py | 生命周期扩展点 + 可观测性事件 |
| 成本追踪 | tools/cost_tracker.py | Token 用量 / LLM 调用成本统计 |
| 记忆检索 | rank_bm25 + SQLite | 跨会话口径纠正（默认关闭，仅本机） |
| 系统监控 | psutil | 内存/进程健康检查 |
| 代码质量 | ruff + pyproject.toml | Lint + PreCommit hook（.claude/settings.json） |
| 打包 | PyInstaller --onedir | 单目录绿色版 |

开发依赖文件：`requirements-dev.txt`（Linux/macOS）
生产依赖文件：`requirements-prod.txt`（Windows，含 pywebview/winotify/pyinstaller/pythonnet）

---

## 四、项目目录结构（v2.0 更新）

```
DataAgent/
├── CLAUDE.md                  ← 主引导文件（本文件）
├── PROGRESS.md                ← 开发进度记录
├── TESTING.md                 ← 测试策略
├── main.py                    ← Flask 应用入口（40+ 路由内联）
├── session_store.py           ← ★I-7: 集中会话/队列/路径管理
├── config.example.yaml        ← 配置模板（config.yaml 在 .gitignore 中）
├── groups.yaml
├── pyproject.toml             ← ★I-1: ruff + pytest 配置
├── .env.example               ← ★I-1: 密钥模板
├── .claude/settings.json      ← ★I-1: PreCommit hook 配置
│
├── api/                       ← ★I-7: Blueprint 模块（已创建，待注册启用）
│   ├── chat.py                ← /api/chat, /api/stream, /api/sessions
│   ├── data.py                ← /api/upload, /api/tables
│   ├── config_api.py          ← /api/config, /api/llm/*
│   ├── skill_api.py           ← /api/skills, /api/skill-builder/*
│   ├── report_api.py          ← /api/report/*
│   └── system_api.py          ← /api/health, /api/groups, /api/logs/*
│
├── agent/
│   ├── loop.py                ← tool-calling 循环 + 场景化工具过滤
│   ├── tools_spec.py          ← 7 工具定义 + dispatch + Schema 校验 + 字段映射解析
│   ├── llm_client.py          ← ChatResult + chat() + LM Studio/多 provider
│   ├── context.py             ← ★I-3b: 三级上下文压缩
│   ├── planner.py             ← ★I-8: Plan-Execute 规划层
│   ├── executor.py            ← ★I-8: Plan-Execute 执行层
│   ├── self_check.py          ← ★I-1b: 数值合理性自检（SelfChecker）
│   ├── hooks.py               ← ★I-5b: 生命周期 Hook 系统
│   ├── skill_loader.py        ← Skills 渐进式加载
│   └── memory.py              ← BM25 + SQLite 跨会话记忆
│
├── calculators/               ← 固化计算模块
│   ├── columns.py             ← ★语义列名常量 + resolve_columns() 字段映射解析
│   ├── concentration.py       ← 主体/单券集中度
│   ├── nav_metrics.py         ← 净值指标
│   ├── asset_structure.py     ← 资产结构
│   ├── credit_distribution.py ← 信用评级分布
│   ├── leverage.py            ← ★I-9: 杠杆率计算
│   ├── liquidity.py           ← ★I-9: 流动性分析
│   └── position_diff.py       ← ★I-9: 持仓变动对比
│
├── data_dictionary/           ← 语义层
│   ├── holding_dict.yaml
│   ├── nav_dict.yaml
│   ├── rating_entity_dict.yaml
│   ├── rating_bond_dict.yaml
│   ├── monitoring_dict.yaml
│   ├── weekly_report_dict.yaml
│   ├── entity_alias.yaml      ← 主体别名归一表
│   └── drafts/                ← 内联推断草稿目录
│
├── scheduler/
│   └── task_manager.py        ← 补跑机制 + 数据时效校验
│
├── tools/
│   ├── data_loader.py         ← 多编码竞争评分 + 两阶段上传确认
│   ├── query_runner.py        ← sqlglot + SQLGuard
│   ├── profiler.py            ← 表结构剖析
│   ├── quality.py             ← 数据质量诊断
│   ├── entity_manager.py      ← 集团系 CRUD
│   ├── entity_normalizer.py   ← 主体归一
│   ├── report_builder.py      ← ★I-2: Jinja2 渲染 + Word 导出
│   ├── chart_builder.py       ← ★I-3: 图表配置生成
│   ├── file_reader.py         ← ★I-6: 文档解析（Word/PDF/TXT）
│   ├── web_search.py          ← ★I-6: 联网搜索（DuckDuckGo）
│   ├── cost_tracker.py        ← ★I-3b: LLM 成本追踪
│   ├── notify.py              ← 通知（Windows/macOS/Linux）
│   ├── error_translator.py    ← 用户侧错误话术
│   ├── compliance_audit.py    ← 合规审计日志（Hash Chain）
│   ├── skill_builder.py       ← Skill 自助创建/校验/发布
│   └── runtime_logger.py      ← 两级运行日志系统
│
├── templates/
│   └── reports/               ← ★I-2: Jinja2 报告模板
│       ├── base_report.md.j2
│       ├── concentration_report.md.j2
│       └── nav_report.md.j2
│
├── skills/                    ← 业务 Skill 目录
│   ├── concentration_monitor/
│   ├── partnership_summary/
│   ├── dept_weekly_report/    ← 模板待确认，Phase 4 进入条件
│   ├── monthly_bond_summary/  ← 模板待确认，Phase 4 进入条件
│   ├── flexible_stats/
│   ├── fund_nav_report/
│   ├── meeting_report/
│   └── position_query/
│
├── platform_adapter/
│   ├── ui_driver.py           ← Linux/macOS/Windows 窗口驱动
│   └── notify_driver.py       ← 通知驱动（macOS osascript / Linux / Windows toast）
│
├── ui/
│   ├── index.html             ← 主 HTML（设置按钮在侧栏底部）
│   ├── echarts.min.js         ← ECharts 本地文件
│   └── js/                    ← ★I-10: 前端 JS 模块化（9 文件）
│       ├── state.js           ← 全局状态
│       ├── dom.js             ← DOM 工具（$, esc, toast）
│       ├── render.js          ← 消息渲染（Markdown, ECharts, 确认卡片）
│       ├── chat.js            ← 发送消息 + SSE 流式接收
│       ├── upload.js          ← 文件上传（两阶段确认）
│       ├── sidebar.js         ← 侧边栏（会话/表/Skills/@mention）
│       ├── settings.js        ← 设置面板
│       ├── skill_builder.js   ← Skill 创建向导
│       └── main.js            ← 入口 + 键盘事件 + 轮询
│
├── data/
│   ├── uploads/               ← 上传文件（含 documents/ 子目录）
│   ├── outputs/               ← 报告输出（Markdown + Word）
│   ├── sessions/              ← 会话日志
│   ├── compliance_audit/      ← 合规审计日志
│   ├── logs/                  ← 运行日志（JSONL 按日滚动）
│   ├── skill_drafts/          ← Skill 草稿暂存
│   └── test_reports/          ← 测试报告
│
├── docs/
│   ├── architecture.md        ← 架构设计文档 v2.0
│   ├── evolution-master-plan.md ← 演进总体方案（I-1~I-10）
│   ├── dev-environment.md
│   └── ...
│
├── tests/
│   ├── test_agent.py
│   ├── test_calculators.py
│   ├── test_report_builder.py ← ★I-2: 报告生成单测
│   ├── test_file_reader.py    ← ★I-6: 文档解析单测
│   ├── test_chart_builder.py  ← ★I-3: 图表生成单测
│   ├── test_self_check.py     ← ★I-1b: SelfChecker 单测
│   ├── test_platform.py       ← 平台适配层单测
│   ├── test_context.py
│   ├── test_executor.py
│   └── ...
│
├── prompts/                   ← LLM Prompt 模板
├── schemas/                   ← 兼容保留，指向 data_dictionary/
└── requirements.txt
```

---

## 五、数据字典与语义层（P0-2，新增）

### 5.1 作用

解决三个根本问题：
1. 各系统 CSV 列名不统一 → 字段语义映射
2. 同一主体在不同表写法不同 → 实体归一
3. 跨表 JOIN 键对不齐 → 归一后校验

### 5.2 字段映射机制

```python
# data_loader.py 加载 CSV 后自动执行
def apply_dictionary_mapping(df, table_type):
    """
    读取 data_dictionary/{table_type}_dict.yaml
    遍历 physical_candidates，找到实际列名
    建立「语义名 → 实际列名」映射，存入 session.field_map
    找不到则显式提示用户，而非静默跳过
    """
```

### 5.3 实体归一机制（P0-4）

```python
# 加载持仓/评级表后，对「限额占用主体」字段自动归一
normalizer = EntityNormalizer("data_dictionary/entity_alias.yaml")
df["限额占用主体_标准"] = df["限额占用方主体"].apply(normalizer.normalize)

# JOIN 前校验
clean, unmatched = normalizer.validate_join_keys(
    left_values=holding_entities,
    right_values=rating_entities,
    join_semantic="限额占用主体"
)
if not clean:
    # 提示用户而非静默漏数据
    yield WarningMessage(
        error_translator.translate("join_key_mismatch", details=str(unmatched))
    )
```

### 5.3b B 类固化计算的字段映射（Path B 全参数化）

A 类探索式查询通过 `apply_field_map()` + sqlglot AST 自动翻译列名。
B 类固化计算（calculators/）通过全参数化方案解决同一问题：

```python
# calculators/columns.py — 语义列名常量 + 解析函数
from calculators.columns import resolve_columns, COL_PRODUCT_NAME, COL_ENTITY

# 每个计算器函数接受 cols=None 参数
def calc_entity_concentration(conn, holding_table, ..., cols=None):
    c_product = (cols or {}).get(COL_PRODUCT_NAME, "产品名称")
    c_entity = (cols or {}).get(COL_ENTITY, "限额占用方主体")
    # SQL 使用 SELECT "物理列" AS 语义别名 保证下游 DataFrame 列名不变
    sql = f'SELECT "{c_product}" AS 产品名称, ...'

# agent/tool_dispatch.py — 调用前解析字段映射
cols = _resolve_cols_for_table(table_name, [COL_PRODUCT_NAME, COL_ENTITY])
results = calc_entity_concentration(conn, table, ..., cols=cols)
```

向后兼容：`cols=None` 时使用语义名本身，与修改前行为一致。

### 5.4 LLM 的语义注入

LLM 生成 SQL（探索式 A 类）时，system prompt 中注入的是**字典映射后的信息**：
```
已加载数据表：
  holding_20260515（持仓表，283行）
  字段映射：穿透后市值 → "资产市值_穿透后"，产品名称 → "产品名称"，...
  JOIN键：限额占用主体（已归一）→ rating_entity.主体名称
```

---

## 六、Skills 系统（v3 数据感知版，2026-06-10 更新）

### 6.1 渐进式加载（不变）

### 6.2 Skill 三类型划分（v3 扩展）

| 类型 | `calc_type` | 特征 | SQL 角色 | 示例 |
|------|-------------|------|----------|------|
| **A. 固化计算** | `fixed` | 口径严格，合规/报告场景 | 无 SQL，调 `calculators/` 函数 | concentration_monitor |
| **B. 探索式查询** | `exploratory` | 灵活统计，LLM 自主判断 | LLM 根据 schema 生成 SQL | position_query |
| **C. 确定性数据管道** | `exploratory` | 用户已定义完整处理逻辑，Agent 忠实执行 | LLM 按用户步骤执行，不自由发挥 | 理财周报、谈参要点 |

**SQL 在 Skill 中的地位**：SQL 示例是"参考提示"，不是必须项，也不直接执行。LLM 根据实际加载的 schema 自行生成最终 SQL。Skill 中没有 SQL 也能正常运行（`concentration_monitor` 即为例证）。

SKILL.md frontmatter `calc_type` 字段：
```yaml
---
name: concentration_monitor
calc_type: fixed          # fixed=固化计算，exploratory=探索式/数据管道
fixed_calculator: calculators.concentration.calc_entity_concentration
---
```

### 6.3 SKILL.md 数据依赖声明（v3 新增，可选字段，向后兼容）

**用途**：Skill 执行前预检数据是否就绪，执行时注入真实表名/列名映射。无此字段的旧 Skill 行为不变。

```yaml
# 可选字段，所有旧 Skill 无需修改
required_files:               # 必需数据文件
  - semantic: "周报数据源"      # 用户可理解的语义名称
    file_pattern: "周报*数据源*" # 模糊匹配已上传文件名（fnmatch 格式）
    expected_fields:           # 期望存在的关键列（用于校验，非全量）
      - 统计日期
      - 组合代码
      - 产品标签
optional_files:               # 可选数据文件（缺失时警告，不阻断）
  - semantic: "模板参考"
    file_pattern: "周报*模板*"
external_sources:             # 非数据库依赖（groups.yaml / web_search 等）
  - type: groups_yaml
    purpose: "集团成员列表"
    required: false           # false=可选，true=必须
```

**无预定义数据的处理**：`file_pattern` 基于文件名模糊匹配，不依赖 `table_type` 分类。用户上传任何 CSV，表名匹配 `file_pattern` 即可关联，无需在代码中预定义表类型。

### 6.4 Skill 执行架构（v3，OCP 分层）

**稳态核心**（极低频改动）：`loop.py` / `tools_spec.py` / `data_loader.py`

**单一入口**（敏态与稳态的分界线）：
```python
# agent/loop.py 唯一改动点，之后不再为 Skill 功能改 loop.py
from agent.skill_preflight import prepare_skill_for_execution
result = prepare_skill_for_execution(skill_content, skill_info, schema_ctx)
if result.blocked:
    yield _text(result.block_message); return
session_messages[-1]["content"] += result.skill_note
```

**敏态模块**（高频迭代，新增需求改这里）：`agent/skill_preflight.py`
- `run_preflight()` — 校验数据依赖
- `build_data_aware_skill_context()` — 构建注入内容
- `prepare_skill_for_execution()` — 对外唯一接口

**扩展原则（YAGNI）**：不引入 Pipeline 框架。`prepare_skill_for_execution()` 内部线性分阶段，未来阶段 ≥3 时可零成本抽取为 pipeline。

### 6.5 数据源绑定（不变）

### 6.6 @mention 边界定义（P2-6，不变）

```
规则1：@mention 可指定多张表（@表A @表B）
规则2：若 @mention 多张同类型表（如 @持仓_0515 @持仓_0501），
        系统提示「您指定了2张持仓表，是否进行跨期对比分析？」
        而非静默选一张或合并
规则3：@(\S+) 中 \S+ 匹配到最近一个空格或标点前的内容
        例：「@持仓_0515，帮我查」→ 提取「持仓_0515」，逗号不计入表名
规则4：@mention 的表不存在于已加载列表时，立即提示「表名不存在，已加载的表有：...」
```

---

---

## 七、Agent 核心循环（v2.0 Plan-Execute + ETCLOVG 加固）

MAX_TURNS = 15，MAX_TOOL_RETRY = 3。

### 7.1 架构演进（v1.0 → v1.5 → v2.0）

```
v1.0（直线流水线）：
  关键词匹配 → 单条 SQL → 执行 → 表格

v1.5（tool-calling Agent）：
  messages 驱动 → LLM 自主选择工具 → 工具分发 → 结果回流 → 下一轮

v2.0（Plan-Execute + ETCLOVG 加固）：
  用户消息 → should_plan() 判断
    ├→ 简单任务 → 单步 Agent Loop（同 v1.5）
    └→ 复杂任务 → build_plan() → 按步骤执行 → SSE plan/plan_step 事件
  工具调用前：Schema 校验 + 场景化工具过滤
  工具调用后：SelfChecker 数值合理性自检
  全程：Hook 事件 + 成本追踪 + 三级上下文压缩
```

### 7.2 工具集（`agent/tools_spec.py`）

| 工具 | 类型 | 说明 |
|------|------|------|
| `profile_table` | 数据剖析 | 返回列名/类型/样本/空值率 |
| `run_sql` | A 类探索 | 经 SQLGuard 校验的只读 SELECT，合规场景自动过滤 |
| `run_calculator` | B 类固化 | 调用 calculators/，**禁止 LLM 传值** |
| `ask_user` | 人机交互 | 存在歧义时提一个关键选择题 |
| `request_confirmation` | 人机交互 | 合规/报告结论前确认 |
| `generate_chart` | 图表 | ★I-3: 生成 ECharts 图表配置 |
| `render_report` | 报告 | ★I-2: Jinja2 模板渲染 + Word 导出 |

场景化工具过滤：当 `skill.calc_type == "fixed"` 时，`run_sql` 从工具列表中移除。

### 7.3 Plan-Execute 两阶段（`agent/planner.py` + `agent/executor.py`）

```python
# should_plan(message) — 判断是否需要规划（含"分析""报告""对比"等关键词）
# build_plan(messages) — LLM 生成步骤列表
# run_with_plan(plan, ...) — 按步骤调用 run_agent_loop()
# 降级：should_plan()==False 或 build_plan() 失败时，走单步循环
```

### 7.4 ETCLOVG 加固层

```python
# T 层：工具参数 Schema 校验（tools_spec._validate_tool_args）
# V 层：SelfChecker 数值自检（self_check.py）
#   - 集中度 0-100%，市值非负，净值 0.5-3.0，收益率 ±20%
# C 层：三级上下文压缩（context.py）
#   - 全量 → 相关表 → 核心字段，历史消息摘要压缩
# O 层：Hook 系统（hooks.py）+ 成本追踪（cost_tracker.py）
# G 层：审计 Hash Chain（compliance_audit.py）
```

### 7.5 LLM 多 Provider 支持（`agent/llm_client.py`）

支持三个 Provider：LM Studio（本地）、DeepSeek（外部）、企业内网。
`list_providers()` 返回可用列表，`test_connection()` 校验连通性。

### 7.6 暂停/续跑机制

`ask_user` 或 `request_confirmation` 触发暂停 → `_session["pending"]` 保存状态 → 用户回应后续跑。

### 7.7 错误分类自愈

```python
def categorize_tool_error(error: ToolError) -> str:
    # 'syntax'  → SQL 语法错，自动重试
    # 'semantic' → 字段/语义错，浮现给用户
    # 'empty'    → 结果为空，询问用户
    # 'anomaly'  → 强制人工介入
```

---

## 八、工具规格（v1.3 更新）

### 8.1 data_loader（新增字典映射 + 时效校验）

```python
def load_file(file_path, table_name, date_tag=None):
    """
    在 v1.2 基础上新增：
    1. 加载后自动应用 data_dictionary/ 字段映射
    2. 对「限额占用主体」字段自动调用 entity_normalizer 归一
    3. 时效标注：在 session 中记录数据日期，供定时任务校验使用
    4. 用户档案校验：若 table_type=holding，校验 config.yaml 中
       managed_products 列表与实际产品名是否对齐（P2-4）
       不一致则提示，而非静默
    """
```

### 8.2 query_runner（P1-4 SQLGuard 加强）

```python
class SQLGuard:
    # 新增：使用 sqlglot 解析提取表名（替代正则，支持 CTE/子查询/别名）
    # 新增：显式拦截 DuckDB 特有危险函数
    BLOCKED_FUNCTIONS = {
        'read_csv_auto', 'read_parquet', 'read_json',
        'copy', 'attach', 'install', 'load',
        'pragma', 'export_database',
    }

    def validate(self, sql: str, conn) -> tuple[bool, str]:
        """
        规则1：只允许 SELECT
        规则2：LIMIT 必须存在且 <= 1000（日常查询）
        规则3：sqlglot 解析提取所有引用的表名，与 SHOW TABLES 动态校验
        规则4：显式拦截 BLOCKED_FUNCTIONS 中的所有函数调用
        规则5：禁止 information_schema 等系统表
        规则6：执行超时 30 秒
        """
```

### 8.3 llm_client（P1-3 禁止 fallback）

```python
def generate_report_text(self, prompt: str) -> str:
    """
    ★ report_text 端点严禁 fallback 到任何外部模型 ★
    若内网 LLM 不可用，降级为「模板+数值+占位说明」，绝不外发。

    实现：
    try:
        return self._call('report_text', prompt)
    except LLMUnavailable:
        # 降级：返回纯数值结构，不调用外部
        return ReportDegradedResult(
            message="内网 AI 服务暂不可用，已生成数值报告，文字说明请稍后补充"
        )
    # 不调用 fallback，不调用外部任何 LLM
    """

def generate_sql(self, prompt: str) -> str:
    """
    code_gen 端点（SQL生成）的 fallback 规则：
    优先：内网 LLM（若有，且合规签字已确认问题文本外发）
    兜底：DeepSeek V3（外部，仅传 Schema + 映射后的语义字段名）

    ★ 注意：用户问题文本（如「查象屿系持仓」）含敏感商业信息
    外发前须经合规签字确认（P0-3）
    """
```

### 8.4 compliance_audit（P1-6，新增）

```python
# tools/compliance_audit.py

def log_compliance_event(
    event_type: str,         # 'monitoring' / 'report' / 'query'
    skill_name: str,
    data_files: list[dict],  # [{name, date, fingerprint(md5)}]
    sql_or_formula: str,     # 实际执行的 SQL 或固化公式版本号
    thresholds: dict,        # 使用的阈值参数
    result_summary: dict,    # 结果摘要（不含完整数据行）
    confirmed_by: str,       # 用户名（来自 config.yaml user_profile.name）
):
    """
    写入 data/compliance_audit/ 目录的结构化 JSONL 文件。
    合规场景必须记录，保证事后可复现：
    - 用的是哪个数据文件的哪个版本（日期+指纹）
    - 用的是哪段 SQL 或哪个版本的固化公式
    - 阈值是多少
    - 谁确认的
    """
```

### 8.5 task_manager（P1-1 补跑机制）

```python
class TaskManager:
    def on_startup(self):
        """
        启动时调用，检测并补跑错过的任务。
        同时校验数据时效：持仓数据是否为今日/最新。
        """
        missed = self._detect_missed_tasks()
        for task in missed:
            # 推送提示，不自动执行，由用户决定是否补跑
            self.notify_fn('chat',
                f"⚠️ 今日 {task['scheduled_time']} 的「{task['name']}」未执行"
                f"（软件当时未运行），是否立即执行？[执行] [跳过]"
            )

    def _validate_data_freshness(self, required_types: list[str]) -> bool:
        """
        执行定时任务前强制校验：
        所需数据文件的日期是否为今日（或设定的最大允许时差）
        过期则不执行并告警，而非用旧数据算出假合规结果
        """
```

---

## 九、LLM 集成规格（P0-3 更新）

### 9.1 config.yaml 结构（新增合规配置）

```yaml
llm:
  sql_gen:
    primary: enterprise_internal    # 优先走内网
    fallback: deepseek              # 兜底外部（需合规签字）
    external_allowed: false
    tool_mode: native               # ★R1: native = OpenAI function-calling
    timeout: 30
    max_tokens: 2000

  report_text:
    provider: enterprise
    fallback: none                  # ★ 显式禁止 fallback（P1-3）
    degraded_mode: template_only

  enterprise_internal:
    url: http://[内网LLM地址]/v1
    model: [企业模型名称]

  deepseek:
    url: https://api.deepseek.com/v1
    model: deepseek-chat
    api_key: ${DEEPSEEK_API_KEY}

calculation_config:                 # 固化计算口径配置
  concentration:
    market_value_field: "穿透后市值"
    use_group_merge: true
    threshold_entity: 10.0
    threshold_single_bond: 10.0
    data_max_age_days: 1
  nav:
    return_annualization_days: 365

memory:                             # ★R5: 跨会话记忆（默认关闭）
  enabled: false
  max_db_mb: 5
```

### 9.2 LLM 调用规则（P0-3 更新）

| 操作 | 使用端点 | 发送内容 | 敏感性说明 |
|------|---------|---------|----------|
| 意图分类 | sql_gen.primary | Skill注册表 + 用户问题 | ⚠️ 问题文本含主体名等商业信息 |
| SQL生成（探索式） | sql_gen.primary | 字典映射后的语义字段名 + 用户问题 | ⚠️ 同上 |
| 固化计算（合规/报告） | 本地calculators函数 | **不调用 LLM** | ✅ 无外发 |
| 报告文字生成 | report_text | 精确计算结果数值 | ✅ 只走内网 |

---

## 十、前端 UI 规格（@mention 边界更新）

### 10.1 布局（同 v1.2）

### 10.2 @mention 交互（P2-6 边界定义）

同类型多表时的处理规则见第六章 6.4 节。

### 10.3 ECharts 后置渲染（不变）

### 10.4 人工确认节点（不变）

---

## 十一、main.py 启动规格（新增内存测试 + 补跑）

```python
def main():
    # Day 1 验证项：
    # import tracemalloc; tracemalloc.start()
    # 启动后执行 tracemalloc.get_traced_memory() 打印 Python 进程内存
    # 同时在 Windows 任务管理器确认 WebView2 进程内存（独立记录）
    # 将两者数据记录在 docs/ 作为内存基准

    port = find_free_port()
    app = create_app()

    flask_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=port,
                               threaded=True, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    time.sleep(0.5)

    # 定时任务：启动 + 补跑检测
    config = load_yaml('config.yaml')
    if config.get('scheduler', {}).get('enabled', False):
        task_mgr = TaskManager(...)
        task_mgr.load_and_register()
        task_mgr.on_startup()       # ★ 补跑检测
        task_mgr.start_background()

    webview.create_window('DataAgent', f'http://127.0.0.1:{port}',
                          width=1280, height=800, resizable=True)
    webview.start()
```

---

## 十二、开发阶段计划（P2-3 MVP 收窄）

### Phase 0（Day 1）：Linux 环境搭建
- [ ] 安装开发依赖：`pip install -r requirements-dev.txt`
- [ ] 验证核心依赖：duckdb / flask / chardet / sqlglot / pandas
- [ ] 启动冒烟测试：`python main.py` → 浏览器自动打开，页面显示正常
- [ ] 确认平台适配层正常：终端出现通知打印（ConsoleFallback）
- [ ] **注意**：WebView2 内存基线、PyInstaller 打包推迟到 Phase 5（Windows 环境）

### Phase 1（Day 2-6）：核心数据链路
- [ ] main.py 随机端口 + PyWebView
- [ ] data_loader.py（chardet + DuckDB + **字典映射** + 时效校验）
- [ ] entity_normalizer.py（主体归一）
- [ ] query_runner.py（sqlglot + 增强 SQLGuard）
- [ ] llm_client.py（report_text 禁 fallback + 外部 LLM 合规判断）
- [ ] error_translator.py
- [ ] agent/loop.py（最简版，含错误类型区分）

**验收**：上传持仓 CSV → 自然语言查询 → 表格展示，内存 < Python进程目标

### Phase 2（Day 7-11）：语义层 + 报告生成
- [ ] data_dictionary/ 完整填写（四张表 + entity_alias）
- [ ] calculators/concentration.py 单测通过（C-01口径确认后固化）
- [ ] calculators/nav_metrics.py
- [ ] calculators/asset_structure.py
- [ ] calculators/credit_distribution.py
- [ ] tests/test_calculators.py 完整覆盖
- [ ] skills/fund_nav_report/ 改为调用 calculators
- [ ] compliance_audit.py

**验收**：运作报告全程数值来自 calculators，无 LLM 生成 SQL

### Phase 3（Day 12-16）：合规监控 + 参谈要点
- [ ] concentration_monitor Skill 改为调用 calculators（非 LLM SQL）
- [ ] task_manager.py（含补跑机制 + 数据时效校验）
- [ ] entity_manager.py（集团系 + 集中度打通，P2-1）
- [ ] meeting_report Skill
- [ ] notify.py（Windows toast）
- [ ] 合规审计日志验收

**验收**：主体集中度监控 → 固化计算 → 正确超标告警 → 审计日志可复现

### Phase 4（Day 17-21）：批量报告（进入条件：C-02/03/04 模板已确认）
- [ ] dept_weekly_report Skill + template.md.j2
- [ ] monthly_bond_summary Skill + template.md.j2
- [ ] 部门维度用户档案校验（P2-4）
- [ ] LLM 意图分类路由（替代关键词匹配，P2-2）
- [ ] partnership_summary Skill

**★ 进入条件**：C-02（周报模板）、C-03（月报模板）、C-04（Word格式确认）已由业务方确认

### Phase 5（Day 22-25）：稳健化 + 打包
- [ ] 上下文 Token 压缩
- [ ] LLM Fallback（sql_gen，非 report_text）
- [ ] /health 命令
- [ ] @mention UI 完整交互
- [ ] PyInstaller 打包 + **WebView2 Runtime 检测/引导安装**（P1-2）
- [ ] Windows 10/11 完整测试

---

## 十三、编码规范（v1.5 更新）

```python
# ✅ 固化计算（合规/报告场景）— 带字段映射
from calculators.concentration import calc_entity_concentration
from calculators.columns import COL_PRODUCT_NAME, COL_ENTITY
cols = _resolve_cols_for_table(table_name, [COL_PRODUCT_NAME, COL_ENTITY])
results = calc_entity_concentration(conn, table_name, ..., cols=cols)

# ✅ 固化计算向后兼容（无映射时）
results = calc_entity_concentration(conn, table_name, ...)  # cols=None 使用语义名

# ❌ 禁止在合规/报告场景让 LLM 生成 SQL
sql = llm_client.generate_sql("计算象屿系集中度")  # 禁止

# ✅ 新增/修改计算器时使用 cols 参数模式
# SQL 中使用 SELECT "物理列" AS 语义别名，保证下游代码不受影响

# ✅ Tool-calling Agent 模式
from agent.tools_spec import dispatch_tool, ToolContext
result = dispatch_tool("run_calculator", args, ctx)

# ✅ 编码自适应：多编码竞争评分
encoding = detect_encoding(file_path)  # 自动选 UTF-8/GB18030/GBK 最优

# ✅ report_text 端点无 fallback
try:
    text = llm_client.generate_report_text(prompt)
except LLMUnavailable:
    text = ReportDegradedResult(...)  # 降级，不调用外部

# ✅ 所有用户侧错误使用翻译层
yield ErrorMessage(error_translator.translate(e))
# ❌ 禁止把技术报错直接展示给用户

# ✅ 合规/报告事件写审计日志
compliance_audit.log_compliance_event(event_type='monitoring', ...)

# ✅ 每个 .py 文件 ≤ 300 行，超了就拆模块
# ✅ 每个新函数配单测，旧单测全绿后再提交
# ✅ 提交前运行 pytest tests/ -x，全绿才提交
# ✅ 迭代后按 TESTING.md 第四章流程执行变更分析→测试→记录
```

---

## 十三-A、Skill 自助创建与发布（v1.6 新增）

### 功能定位
让非技术业务人员通过对话描述或模板化表单创建自定义 Skill，无需编写代码。
发布前自动执行质量和安全校验。

### 核心模块
`tools/skill_builder.py`，不修改 `agent/skill_loader.py`（职责分离）。

### 创建流程

```
用户描述场景 → POST /api/skill-builder/generate → LLM 生成结构化 SkillDraft
  → generate_skill_md() 渲染为 SKILL.md → save_draft() 存入 data/skill_drafts/
  → 用户预览 + 编辑 → POST /api/skill-builder/validate → 校验反馈
  → POST /api/skill-builder/publish → validate + 写入 skills/{name}/SKILL.md
```

### 校验维度（`validate_skill_md()`）

| 维度 | 规则 |
|------|------|
| 格式 | YAML frontmatter 可解析，name + description 必填 |
| 命名 | 3-40 位小写字母/数字/下划线，字母开头，不与已有 Skill 冲突 |
| 安全 | SQL 示例中禁止 DROP/DELETE/INSERT/CREATE 等危险操作 |
| 质量 | 建议含触发词、执行步骤、输出格式、LIMIT 子句 |
| 大小 | SKILL.md ≤ 10000 字符 |

### 安全约束
- 用户创建的 Skill 只能是 `calc_type: exploratory`（不能创建固化计算类）
- SQL 示例仅供 LLM 参考，实际执行仍经 SQLGuard 拦截
- 草稿存在 `data/skill_drafts/`，未发布前对 Agent 不可见

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skill-builder/drafts` | 草稿列表 |
| POST | `/api/skill-builder/generate` | LLM 辅助从自然语言生成 Skill |
| POST | `/api/skill-builder/validate` | 校验 SKILL.md 内容 |
| POST | `/api/skill-builder/save-draft` | 保存草稿 |
| GET | `/api/skill-builder/draft/<name>` | 加载草稿 |
| DELETE | `/api/skill-builder/draft/<name>` | 删除草稿 |
| POST | `/api/skill-builder/publish` | 校验并发布到 skills/ |

---

## 十三-B、运行时日志系统（v1.6 新增）

### 功能定位
结构化运行日志，用于 Windows 生产环境中异常排查和问题定位。
两种模式，默认仅开启基本记录。

### 两种模式

| 模式 | 记录内容 | 默认 |
|------|---------|------|
| **basic** | ERROR/WARNING + 生命周期事件（启动/关闭/异常） | ✅ 是 |
| **detailed** | 上述 + 用户操作 + Agent 轮次 + 工具调用 + LLM 请求 + 内存快照 | 否 |

### 核心模块
`tools/runtime_logger.py`（全局单例 `RuntimeLogger`，线程安全）。

### 日志存储
- 路径：`data/logs/dataagent_YYYYMMDD.jsonl`
- 按日滚动，追加写入
- 超过 `max_days`（默认 30 天）自动清理
- 单文件超过 50MB 自动截断保留尾部

### 日志条目格式
```json
{"timestamp":"2026-06-04T10:23:45.123","level":"ERROR","category":"error",
 "event":"DuckDB 查询失败","detail":{"sql_preview":"SELECT...","error":"..."},
 "duration_ms":null,"session_id":"abc123"}
```

### 隐私安全
- 不记录用户数据内容，仅记录元信息（表名、行数、耗时）
- 用户消息仅记录前 50 字符预览
- SQL 仅记录前 100 字符

### config.yaml 配置

```yaml
logging:
  mode: basic         # basic | detailed
  max_days: 30        # 日志保留天数
```

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs` | 查看日志（支持 ?date=&level=&category= 过滤） |
| GET | `/api/logs/files` | 日志文件列表 |
| GET | `/api/logs/stats` | 日志统计（模式、文件数、总大小） |
| POST | `/api/logs/mode` | 切换日志模式（即时生效，同步写入 config.yaml） |
| POST | `/api/logs/cleanup` | 手动清理旧日志 |

### 已埋点位置
- `main.py`：应用启动、文件上传、发送消息、Agent 异常
- `agent/loop.py`：LLM 调用（含耗时）、工具调用（含耗时和成败）

### 编码规范
```python
# ✅ 记录运行日志
from tools.runtime_logger import get_logger
logger = get_logger()
logger.error('error', 'DuckDB 连接失败', {'detail': str(e)[:200]})
logger.log_tool_call('run_sql', args, ok=True, duration_ms=120)

# ✅ 记录异常（始终记录，含 traceback）
logger.log_exception('agent', 'Agent 循环异常', e)
```
---

## 十三-C、测试策略（v1.6 新增）

完整测试策略见 **`TESTING.md`**。此处列出必须遵守的硬性规则：

1. **合规计算（calculators/）变更**：必须先改测试再改代码，覆盖率 ≥ 95%
2. **每次迭代后**：运行全量 `pytest tests/`，生成覆盖率报告
3. **测试记录留存**：每次迭代在 `data/test_reports/` 生成迭代测试记录
4. **PreCommit Hook**：`.claude/settings.json` 配置了 PreCommit 钩子，提交前自动运行测试
5. **失败阻断**：安全关键测试（SQLGuard / calculators）失败时不得继续开发


---

## 十四、已知数据特征（同 v1.2，新增归一提醒）

持仓GB18030、Sam系列UTF-8、千分位逗号、括号列名——处理方式不变。
**新增**：主体名称在不同表中写法可能不同，必须经过 entity_normalizer 归一后再 JOIN。

---

## 十五、改进历史记录

| 版本 | 改进内容 | 来源 |
|------|---------|------|
| v1.0 | 初始方案 | CC设计 |
| v1.5 | Agent 内核重构为 tool-calling（5 工具 + function-calling + 暂停续跑） | Phase R1 |
| v1.5 | 数据质量诊断（空值率/覆盖率/JOIN 兼容性 + 自适应编码） | Phase R2 |
| v1.5 | UI 重建（全本地零 CDN / 设置面板 / 集团 CRUD / 确认卡片） | Phase R3 |
| v1.5 | 未知表内联推断（sanitize + 字典草稿→正式） | Phase R4 |
| v1.5 | 收窄版跨会话记忆（BM25+SQLite，仅口径纠正，默认关闭） | Phase R5 |
| v1.5 | 内测反馈修复（PyWebView 4.4.1 / 一键启动 / 记忆开关即时保存） | 内测 |
| v1.1 | 随机端口/DuckDB内存限制/动态SQLGuard/ECharts钩子/Skills共享 | GG审查 |
| v1.2 | 定时任务/用户档案/数据源绑定/@mention/5个新Skill | 业务需求补充 |
| v1.3 | 新增语义层/数据字典（P0-2） | op专家评审 |
| v1.3 | 合规计算改为固化函数calculators/（P0-1） | op专家评审 |
| v1.3 | 明确问题文本/表名外发合规风险（P0-3） | op专家评审 |
| v1.3 | 主体归一entity_normalizer（P0-4） | op专家评审 |
| v1.3 | 定时任务补跑+数据时效校验（P1-1） | op专家评审 |
| v1.3 | 内存KPI口径明确+Day1实测（P1-2） | op专家评审 |
| v1.3 | report_text禁fallback（P1-3） | op专家评审 |
| v1.3 | SQLGuard改sqlglot+拦截危险函数（P1-4） | op专家评审 |
| v1.3 | 自愈重试区分语法/语义错误（P1-5） | op专家评审 |
| v1.3 | 合规级审计日志compliance_audit（P1-6） | op专家评审 |
| v1.3 | 集团系与集中度监控打通（P2-1） | op专家评审 |
| v1.3 | 意图路由改LLM分类（P2-2） | op专家评审 |
| v1.3 | Phase4进入条件：模板先确认（P2-3） | op专家评审 |
| v1.3 | 加载时校验用户档案产品名（P2-4） | op专家评审 |
| v1.3 | 用户侧错误话术层error_translator（P2-5） | op专家评审 |
| v1.3 | @mention边界规则定义（P2-6） | op专家评审 |
| v1.6 | Skill 自助创建与发布（LLM辅助生成+校验+草稿+发布） | 用户体验需求 |
| v1.6 | 运行时两级日志系统（basic/detailed + 自动清理 + API 查询） | 用户体验需求 |
| v1.6 | claude测试策略新增 | 用户体验需求 |
| v1.6.1 | SSE 流挂起修复（线程存活检测+心跳30s）、Skill Builder 发布修复、文档上传（Word/PDF/TXT）、图表客户端渲染（柱/饼/折/散）、Word 导出（report_builder.py）、设置按钮移至侧栏底部 | 内测反馈修复 |
| v2.0 I-1 | 工程基建（pyproject.toml+ruff+.claude/ PreCommit）+ macOS 支持 + 本地 LLM（LM Studio）+ 测试修复 | Evolution |
| v2.0 I-1b | ETCLOVG Harness 加固：工具参数 Schema 校验 + SelfChecker 数值自检 + 场景化工具过滤 + 统一超时 | Evolution |
| v2.0 I-2 | 报告生成管线：Jinja2 模板渲染 + Word 导出 + templates/reports/ + render_report 工具 | Evolution |
| v2.0 I-3 | 图表生成：chart_builder.py 重构 + ECharts 配置 + generate_chart 工具 | Evolution |
| v2.0 I-3b | 上下文三级压缩（context.py）+ LLM 成本追踪（cost_tracker.py）| Evolution |
| v2.0 I-4 | 数据持久化（DuckDB 文件模式）+ 智能上传两阶段确认 + 自动表类型/日期检测 | Evolution |
| v2.0 I-5 | 前端增量改进：状态推荐 API + 欢迎面板 + 能力标签 | Evolution |
| v2.0 I-5b | Hook 系统（agent/hooks.py）+ 审计 Hash Chain 防篡改 | Evolution |
| v2.0 I-6 | 文档解析（file_reader.py: Word/PDF/TXT）+ 联网搜索（web_search.py: DuckDuckGo）| Evolution |
| v2.0 I-7 | main.py Blueprint 拆分准备：api/ 6 模块 + session_store.py（路由仍内联于 main.py）| Evolution |
| v2.0 I-8 | Plan-Execute 两阶段 Agent：planner.py + executor.py（复杂任务自动分步）| Evolution |
| v2.0 I-9 | 计算器补齐：position_diff（持仓变动）+ leverage（杠杆率）+ liquidity（流动性）| Evolution |
| v2.0 I-10 | 前端 JS 模块化：ui/js/ 9 个文件（state/dom/render/chat/upload/sidebar/settings/skill_builder/main）| Evolution |
| v2.0 UX | 综合 UX 优化：LLM 设置面板 + @mention 自动补全 + 数据质量弹窗 + 表结构剖析 | UX 优化 |
| v2.0 UAT | UAT 修复 7 项：macOS 客户端 + Skill Builder + 文档上传 + LLM 错误处理 + UI 改进 | UAT 修复 |
| v2.1 UAT | Windows 内测修复：联网搜索拒绝/文档上下文丢失/上传后表不可见/错误提示优化/自定义 Skill 不生效 | Windows 内测 |
| v3.0 Skill | Skill 数据感知重构：三类 Skill 划分 / required_files 声明 / 预检模块 / 数据映射注入 / OCP 分层架构 | 架构改进 |
| v3.0 Skill-C | Skill Builder 需求文档导入：import_from_requirement_doc() / POST /api/skill-builder/import / 从文档导入 UI | 功能完善 |
| v3.0 Skills | 验收用 Skill 创建：weekly_report_generator（理财周报 5 模板）/ meeting_report v3（谈参要点含集团关系树）| Skills 库 |
| v2.2 Upload | 文件上传升级：批量上传 + 本地工作目录（workdir_loader / 侧边栏区块 / Skill 预检自动扫描）| 功能升级 |
| v2.3 FieldMap | 计算器字段映射全参数化（Path B）：columns.py 语义常量 + resolve_columns() + 7 个计算器 cols 参数 + tool_dispatch 解析层 + 26 个新测试（含端到端）| 字段映射 |
| v2.3 Revert | Stitch UI 回退：Phase 0-5 全部回退到原版 UI（效果不理想），仅 ui/ 目录，后端不受影响 | UI 回退 |
| v3.1 NavUI | 多页面导航 UI 重构（Phase 0-4）：Hash SPA 路由器 + 可折叠主导航侧栏（6页面）+ sidebar.js 拆分为 data_tables.js/groups.js + 数据源管理页/分析规则页/设置独立页/首页快捷卡片 + SSE 跨页保活 + 零后端改动，622 tests 通过 | 前端多页面 |
