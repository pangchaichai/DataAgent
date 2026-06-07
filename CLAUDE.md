# DataAgent — Claude Code 主引导文件 v1.5

> **每次开始新会话，必须先完整阅读本文件。**
> 版本历史见文末"改进记录"表格。
> v1.5 融入 Phase R 重构（tool-calling Agent / 质量诊断 / UI 重建 / 自适应编码 / 跨会话记忆）。
>
> **测试指南**：完整测试策略见 `TESTING.md`。每次迭代后须按该文件第四章流程执行测试。

---


---

## 零、开发环境与平台策略（重要，必读）

### 当前环境
- **开发环境**：Linux（Claude Code）
- **目标运行环境**：Windows 11

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

## 二、架构总览（v1.5 新增 Agent 工具编排层 + 剖析/质量层）

```
┌──────────────────────────────────────────────────────────────┐
│  交互层  PyWebView 窗口 / 对话 / 设置面板 / 确认卡片 / 告警横幅  │
├──────────────────────────────────────────────────────────────┤
│  ★Agent 工具编排层  LLM function-calling → 5 工具分发          │
│    profile_table(剖析) / run_sql(探索) / run_calculator(固化)  │
│    ask_user(澄清) / request_confirmation(确认)                 │
│    暂停/续跑机制 + 会话 messages 持久化                         │
├──────────────────────────────────────────────────────────────┤
│  业务能力层（两类，严格区分）                                   │
│   A. 探索式分析：LLM 生成 SQL（允许灵活，经 SQLGuard 校验）      │
│   B. 合规/报告口径：calculators/ 固化计算（禁止 LLM 生成 SQL）   │
├──────────────────────────────────────────────────────────────┤
│  ★剖析/质量层  tools/profiler.py(表结构剖析 + 自适应编码)        │
│              tools/quality.py(空值率/覆盖率/JOIN兼容性)         │
├──────────────────────────────────────────────────────────────┤
│  语义层  data_dictionary/ 数据字典 / 字段映射 / 主体归一 / Join键│
│          entity_normalizer 主体别名归一                         │
├──────────────────────────────────────────────────────────────┤
│  数据引擎层  DuckDB（只读 SELECT，参数化执行）max_memory=200MB    │
├──────────────────────────────────────────────────────────────┤
│  数据接入层  多编码竞争评分 + 字典映射清洗 + 多期版本 + 时效校验   │
└──────────────────────────────────────────────────────────────┘
```

### 两类业务能力的区分（P0-1，最重要）

| 类型 | 适用场景 | SQL 来源 | 是否允许 LLM 修改 |
|------|---------|---------|---------------|
| **A 探索式** | 临时查询、灵活统计（场景5.2） | LLM 生成 | 允许 |
| **B 固化计算** | 合规监控（场景5.3）、运作报告（5.4.1）、参谈要点（5.4.2） | `calculators/` 中的函数 | **严禁** |

判断规则：只要结果会被用于合规决策或对外报告，必须走 B 类。

---

## 三、技术栈（v1.5 更新）

| 层级 | 选型 | 说明 |
|------|------|------|
| 桌面窗口 | pywebview 4.4.x | 原生窗口，pythonnet 3.x 兼容 |
| 后端 | Flask（最小化） | 随机端口，避免冲突 |
| 实时通信 | SSE（Server-Sent Events） | LLM 流式输出 + tool_start/tool_end/thinking/ask/confirm 事件 |
| 数据引擎 | DuckDB（内嵌） | max_memory=200MB, threads=2 |
| 数据处理 | Pandas | 清洗辅助 |
| 编码检测 | **多编码竞争评分** | 自适应 UTF-8/GB18030/GBK/GB2312/Latin-1 |
| SQL 解析 | sqlglot | CTE/子查询/别名感知的表名提取 |
| 定时调度 | schedule 库 | 轻量，含补跑检测 + 数据时效校验 |
| 前端 | 单 HTML 文件 | vanilla JS + 本地 CSS + 本地 ECharts（**零 CDN**） |
| 报告模板 | Jinja2 | 渲染引擎 |
| 系统通知 | winotify | Windows toast 通知 |
| 配置 | PyYAML | config.yaml / task_config.yaml / groups.yaml |
| 日志 | append-only JSONL | 会话日志 + 独立合规审计日志 |
| LLM | DeepSeek / Qwen3-32B | OpenAI function-calling 原生支持（tool_mode: native） |
| 记忆检索 | rank_bm25 + SQLite | 跨会话口径纠正（默认关闭，仅本机） |
| 系统监控 | psutil | 内存/进程健康检查 |
| 打包 | PyInstaller --onedir | 单目录绿色版 |

Phase R 新增依赖：`psutil` `rank_bm25`
开发依赖文件：`requirements-dev.txt`（Linux）
生产依赖文件：`requirements-prod.txt`（Windows，含 pywebview/winotify/pyinstaller/pythonnet）

---

## 四、项目目录结构

```
DataAgent/
├── CLAUDE.md
├── main.py
├── config.yaml
├── groups.yaml
│
├── agent/
│   ├── loop.py                ← ★R1: tool-calling 循环
│   ├── tools_spec.py          ← ★R1: 5 工具定义 + dispatch
│   ├── llm_client.py          ← ★R1: ChatResult + chat() (function-calling)
│   ├── context.py             ← ★R2: 注入质量诊断摘要
│   ├── skill_loader.py
│   └── memory.py              ← ★R5: BM25 + SQLite 收窄记忆
│
├── calculators/               ← ★新增：固化计算模块（P0-1）
│   ├── README.md
│   ├── concentration.py       ← 主体/单券集中度固化计算
│   ├── nav_metrics.py         ← 净值指标固化计算
│   ├── asset_structure.py     ← 资产结构固化计算
│   ├── credit_distribution.py ← 信用评级分布固化计算
│   └── _base.py
│
├── data_dictionary/           ← 语义层（P0-2/P0-4）
│   ├── README.md
│   ├── holding_dict.yaml
│   ├── nav_dict.yaml
│   ├── rating_entity_dict.yaml
│   ├── rating_bond_dict.yaml
│   ├── monitoring_dict.yaml
│   ├── weekly_report_dict.yaml
│   ├── entity_alias.yaml      ← 主体别名归一表
│   └── drafts/                ← ★R4: 内联推断草稿目录
│
├── scheduler/
│   └── task_manager.py        ← 新增补跑机制（P1-1）
│
├── tasks/
│   └── task_config.yaml
│
├── tools/
│   ├── __init__.py
│   ├── data_loader.py         ← ★R2-fix: 多编码竞争评分 + drop_table
│   ├── query_runner.py        ← sqlglot 解析 + 增强 SQLGuard（P1-4）
│   ├── profiler.py            ← ★R1: Agent 自行剖析表结构
│   ├── quality.py             ← ★R2: 数据质量诊断报告
│   ├── entity_manager.py
│   ├── entity_normalizer.py   ← 主体归一（P0-4）
│   ├── report_builder.py
│   ├── chart_builder.py
│   ├── notify.py
│   ├── error_translator.py    ← 用户侧错误话术（P2-5）
│   ├── compliance_audit.py    ← 合规级审计日志（P1-6）
│   ├── skill_builder.py       ← ★v1.6: Skill 自助创建/校验/发布
│   └── runtime_logger.py      ← ★v1.6: 两级运行日志系统
│
├── skills/
│   ├── concentration_monitor/ ← 已改：引用 calculators，不让 LLM 生成 SQL
│   ├── partnership_summary/
│   ├── dept_weekly_report/    ← 模板待确认，Phase 4 进入条件
│   ├── monthly_bond_summary/  ← 模板待确认，Phase 4 进入条件
│   ├── flexible_stats/
│   ├── fund_nav_report/
│   ├── meeting_report/
│   └── position_query/
│
├── schemas/                   ← 仍保留（兼容），内容指向 data_dictionary/
├── prompts/
├── ui/
│   └── index.html             ← @mention 含边界定义（P2-6）
├── data/
│   ├── uploads/
│   ├── outputs/
│   ├── sessions/              ← 会话日志
│   ├── compliance_audit/      ← ★新增：合规审计日志目录
│   ├── logs/                  ← ★v1.6: 运行日志（JSONL按日滚动）
│   └── skill_drafts/          ← ★v1.6: Skill 草稿暂存
├── docs/
├── tests/
│   ├── test_agent.py          ← 含 R1 tool-calling / R4/R5 记忆 测试
│   ├── test_tools.py           ← 含 R2 质量诊断 测试
│   ├── test_calculators.py    ← 固化计算单测（P0-1要求）
│   ├── test_profiler.py       ← ★R1: profiler 单测
│   └── test_platform.py       ← 平台适配层单测
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

### 5.4 LLM 的语义注入

LLM 生成 SQL（探索式 A 类）时，system prompt 中注入的是**字典映射后的信息**：
```
已加载数据表：
  holding_20260515（持仓表，283行）
  字段映射：穿透后市值 → "资产市值_穿透后"，产品名称 → "产品名称"，...
  JOIN键：限额占用主体（已归一）→ rating_entity.主体名称
```

---

## 六、Skills 系统（含数据源绑定，P0-1更新）

### 6.1 渐进式加载（不变）

### 6.2 Skill 类型标注（新增）

SKILL.md frontmatter 新增 `calc_type` 字段，区分探索式/固化：

```yaml
---
name: concentration_monitor
calc_type: fixed          # fixed=固化计算，exploratory=探索式
fixed_calculator: calculators.concentration.calc_entity_concentration
# calc_type=fixed 时：Agent 调用 fixed_calculator 指定的函数，禁止 LLM 生成 SQL
# calc_type=exploratory 时：允许 LLM 生成 SQL（临时查询场景）
---
```

### 6.3 数据源绑定（不变）

### 6.4 @mention 边界定义（P2-6，新增）

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

## 七、Agent 核心循环（v1.5 tool-calling 重构）

MAX_TURNS = 15，MAX_TOOL_RETRY = 3。

### 7.1 架构变化（v1.0 → v1.5）

```
v1.0（直线流水线）：
  关键词匹配 → 单条 SQL → 执行 → 表格

v1.5（tool-calling Agent）：
  messages 驱动 → LLM 自主选择工具 → 工具分发 → 结果回流 → 下一轮
                                            ↑
                              暂停/续跑 ← ask_user / request_confirmation
```

### 7.2 五个工具（`agent/tools_spec.py`）

| 工具 | 类型 | 说明 |
|------|------|------|
| `profile_table` | 数据剖析 | 返回列名/类型/样本/空值率，Agent 自行读懂数据 |
| `run_sql` | A 类探索 | 经 SQLGuard 校验的只读 SELECT，禁止用于合规 |
| `run_calculator` | B 类固化 | 调用 calculators/，口径来自 config，**禁止 LLM 传值** |
| `ask_user` | 人机交互 | 存在影响正确性的歧义时，提一个关键选择题 |
| `request_confirmation` | 人机交互 | 合规/报告结论前确认，未决时输入框禁用 |

### 7.3 LLM function-calling（`agent/llm_client.py`）

```python
# chat() 方法：发送 messages + tools，解析 tool_calls
result = llm_client.chat(messages, tools=TOOL_DEFINITIONS)
# → ChatResult(text, tool_calls=[{id, name, arguments}], ...)

# tool_mode: native — OpenAI function-calling（默认）
#            react  — 文本 JSON 协议（仅作兜底，可后置）
```

### 7.4 暂停/续跑机制

`ask_user` 或 `request_confirmation` 触发暂停 → `_session["pending"]` 保存状态 → `_session["messages"]` 持久化 → 用户回应后 `/api/chat` 带 pending 续跑。

### 7.5 错误分类自愈（保留 v1.0）

```python
def categorize_tool_error(error: ToolError) -> str:
    """
    'syntax'  → SQL 语法错，自动重试
    'semantic' → 字段/语义错，浮现给用户
    'empty'    → 结果为空，询问用户
    'anomaly'  → 强制人工介入
    """
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
# ✅ 固化计算（合规/报告场景）
from calculators.concentration import calc_entity_concentration
results = calc_entity_concentration(conn, table_name, ...)

# ❌ 禁止在合规/报告场景让 LLM 生成 SQL
sql = llm_client.generate_sql("计算象屿系集中度")  # 禁止

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
