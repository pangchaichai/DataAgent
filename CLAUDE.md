# DataAgent — Claude Code 主引导文件 v1.3

> **每次开始新会话，必须先完整阅读本文件。**
> 版本历史见文末"改进记录"表格。
> v1.3 融入 op专家 P0/P1/P2 全部评审意见。

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

## 二、架构总览（v1.3 新增语义层）

```
┌──────────────────────────────────────────────────────────────┐
│  交互层  PyWebView 窗口 / 对话 / @mention / 快捷按钮 / 告警横幅  │
├──────────────────────────────────────────────────────────────┤
│  Agent 编排层  意图识别（LLM分类）→ 任务路由 → 工具调用 → 人工确认  │
├──────────────────────────────────────────────────────────────┤
│  业务能力层（两类，严格区分）                                   │
│   A. 探索式分析：LLM 生成 SQL（允许灵活）                       │
│   B. 合规/报告口径：calculators/ 固化计算（禁止 LLM 生成 SQL）   │
├──────────────────────────────────────────────────────────────┤
│  ★语义层  data_dictionary/ 数据字典 / 字段映射 / 主体归一 / Join键│
│            entity_normalizer 主体别名归一                       │
├──────────────────────────────────────────────────────────────┤
│  数据引擎层  DuckDB（只读 SELECT，参数化执行）max_memory=80MB     │
├──────────────────────────────────────────────────────────────┤
│  数据接入层  chardet 编码识别 / 字典映射清洗 / 多期版本 / 时效校验  │
└──────────────────────────────────────────────────────────────┘
```

### 两类业务能力的区分（P0-1，最重要）

| 类型 | 适用场景 | SQL 来源 | 是否允许 LLM 修改 |
|------|---------|---------|---------------|
| **A 探索式** | 临时查询、灵活统计（场景5.2） | LLM 生成 | 允许 |
| **B 固化计算** | 合规监控（场景5.3）、运作报告（5.4.1）、参谈要点（5.4.2） | `calculators/` 中的函数 | **严禁** |

判断规则：只要结果会被用于合规决策或对外报告，必须走 B 类。

---

## 三、技术栈（已锁定）

| 层级 | 选型 | 说明 |
|------|------|------|
| 桌面窗口 | pywebview 4.x | 原生窗口，非浏览器 |
| 后端 | Flask（最小化） | 随机端口，避免冲突 |
| 实时通信 | Flask-SSE | LLM 流式输出 |
| 数据引擎 | DuckDB（内嵌） | max_memory=80MB, threads=2 |
| 数据处理 | Pandas | 清洗辅助 |
| 编码检测 | chardet | 自动识别 GB18030/UTF-8 |
| SQL 解析 | **sqlglot** | 替代正则提取表名（P1-4改进） |
| 定时调度 | schedule 库 | 轻量，无额外依赖 |
| 前端 | 单 HTML 文件 | vanilla JS + Tailwind(CDN) + ECharts |
| 报告模板 | Jinja2 | 渲染引擎 |
| 系统通知 | winotify | Windows toast 通知 |
| 配置 | PyYAML | config.yaml / task_config.yaml |
| 日志 | append-only JSONL | 会话日志 + 独立合规审计日志 |
| LLM（SQL生成）| 内网 LLM（优先）/ DeepSeek V3（兜底）| 见 P0-3 说明 |
| LLM（报告文字）| 企业内网 LLM | **禁止 fallback 到外部** |
| 打包 | PyInstaller --onedir | 单目录绿色版 |

新增依赖（相比v1.2）：`sqlglot`
开发依赖文件：`requirements-dev.txt`（Linux）
生产依赖文件：`requirements-prod.txt`（Windows，含 pywebview/winotify/pyinstaller）

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
│   ├── loop.py
│   ├── context.py
│   ├── skill_loader.py
│   └── llm_client.py          ← report_text 禁止 fallback（P1-3）
│
├── calculators/               ← ★新增：固化计算模块（P0-1）
│   ├── README.md
│   ├── concentration.py       ← 主体/单券集中度固化计算
│   ├── nav_metrics.py         ← 净值指标固化计算
│   ├── asset_structure.py     ← 资产结构固化计算
│   ├── credit_distribution.py ← 信用评级分布固化计算
│   └── _base.py
│
├── data_dictionary/           ← ★新增：语义层（P0-2/P0-4）
│   ├── README.md
│   ├── holding_dict.yaml
│   ├── nav_dict.yaml
│   ├── rating_entity_dict.yaml
│   ├── rating_bond_dict.yaml
│   └── entity_alias.yaml      ← 主体别名归一表
│
├── scheduler/
│   └── task_manager.py        ← 新增补跑机制（P1-1）
│
├── tasks/
│   └── task_config.yaml
│
├── tools/
│   ├── __init__.py
│   ├── data_loader.py         ← 加载后自动字典映射 + 时效校验（P1-1/P0-2）
│   ├── query_runner.py        ← sqlglot 解析 + 增强 SQLGuard（P1-4）
│   ├── entity_manager.py
│   ├── entity_normalizer.py   ← ★新增：主体归一（P0-4）
│   ├── report_builder.py
│   ├── chart_builder.py
│   ├── notify.py
│   ├── error_translator.py    ← ★新增：用户侧错误话术（P2-5）
│   └── compliance_audit.py    ← ★新增：合规级审计日志（P1-6）
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
│   └── compliance_audit/      ← ★新增：合规审计日志目录
├── docs/
├── tests/
│   ├── test_tools.py
│   └── test_calculators.py    ← ★新增：固化计算单测（P0-1要求）
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

## 七、Agent 核心循环（P1-5 改进）

MAX_TURNS = 15，MAX_TOOL_RETRY = 3。

### 新增：意图路由改 LLM 分类（P2-2）

```python
# 不使用纯关键词子串匹配，改为轻量 LLM 分类
# 8个 Skill 关键词高度重叠（报告/周报/月报/简报），子串匹配必误判

def detect_relevant_skill(user_input, registry, llm_client):
    """
    使用 LLM（code_gen端点）对用户意图分类：
    输入：用户问题 + 所有 Skill 的 name + description（已加载的注册表）
    输出：最匹配的 Skill name（或 None 表示探索式查询）

    若多个 Skill 评分接近，显示歧义确认：
    「您的需求可能是 A（运作报告）或 B（部门周报），请选择」
    """
```

### 新增：错误类型区分自愈（P1-5）

```python
# 区分「语法类失败」和「结果异常」
def categorize_tool_error(error: ToolError) -> str:
    """
    返回：
    'syntax'  → SQL 语法错误，可自动重试（LLM 修正语法）
    'semantic' → 字段/语义错，浮现给用户确认而非自动改写
    'empty'    → 结果为空，询问用户是否口径有误
    'anomaly'  → 结果异常（集中度>100%、总市值=0），强制人工介入
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
  sql_gen:                          # SQL生成（原 code_gen，改名更准确）
    primary: enterprise_internal    # 优先走内网（P0-3：问题文本含敏感信息）
    fallback: deepseek              # 兜底外部（需合规签字）
    external_allowed: false         # true=已获合规签字，可外发问题文本

  report_text:
    provider: enterprise
    url: http://[内网LLM地址]/v1
    model: [企业模型名称]
    fallback: none                  # ★ 显式禁止 fallback（P1-3）
    degraded_mode: template_only    # 不可用时降级为纯模板输出

  enterprise_internal:
    url: http://[内网LLM地址]/v1
    model: [企业模型名称]

  deepseek:
    url: https://api.deepseek.com/v1
    model: deepseek-chat
    api_key: ${DEEPSEEK_API_KEY}
    # 注意：发送的是字段语义名（非原始列名），不含真实数值

calculation_config:                 # ★ 新增：固化计算口径配置（P0-1/C-01）
  concentration:
    market_value_field: "穿透后市值"  # C-01 确认后修改此处
    use_group_merge: true             # true=集团合并口径
    exclude_asset_types: []           # 排除的资产大类
    threshold_entity: 10.0            # 主体集中度阈值(%)
    threshold_single_bond: 10.0       # 单券集中度阈值(%)
  nav:
    return_annualization_days: 365
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

## 十三、编码规范（v1.3 新增）

```python
# ✅ 固化计算（合规/报告场景）
from calculators.concentration import calc_entity_concentration
results = calc_entity_concentration(conn, table_name, ...)  # 直接调用函数

# ❌ 禁止在合规/报告场景让 LLM 生成 SQL
sql = llm_client.generate_sql("计算象屿系集中度")  # 禁止用于合规计算

# ✅ SQLGuard 使用 sqlglot 解析
import sqlglot
tables = {t.name for t in sqlglot.parse_one(sql).find_all(sqlglot.exp.Table)}

# ✅ report_text 端点无 fallback
try:
    text = llm_client.generate_report_text(prompt)
except LLMUnavailable:
    text = ReportDegradedResult(...)  # 降级，不调用外部

# ✅ 所有用户侧错误使用翻译层
except Exception as e:
    yield ErrorMessage(error_translator.translate(e))
# ❌ 禁止把技术报错直接展示给用户
yield ErrorMessage(str(e))  # 禁止

# ✅ 合规/报告事件写审计日志
compliance_audit.log_compliance_event(event_type='monitoring', ...)

# ✅ 加载后验证用户档案产品名
data_loader.validate_user_profile_products(loaded_products, config)
```

---

## 十四、已知数据特征（同 v1.2，新增归一提醒）

持仓GB18030、Sam系列UTF-8、千分位逗号、括号列名——处理方式不变。
**新增**：主体名称在不同表中写法可能不同，必须经过 entity_normalizer 归一后再 JOIN。

---

## 十五、改进历史记录

| 版本 | 改进内容 | 来源 |
|------|---------|------|
| v1.0 | 初始方案 | CC设计 |
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
