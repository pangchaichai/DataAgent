# DataAgent 项目评估与演进方案

> 评估日期：2026-06-05
> 评估视角：Agent 架构师 + 金融资管行业业务顾问
> 项目状态：Phase 1-2 基本完成，Phase 3-5 待启动

---

## 第一部分：当前设计的缺陷与不足

### 一、架构层面

#### 1.1 单进程 + 全局状态的可扩展性瓶颈

**问题**：`main.py` 中使用全局 `_session` 字典 + `_session_lock` 管理状态，`data_loader.py` 中 `_global_conn` 和 `_loaded_tables` 也是模块级全局变量。这意味着：

- 只能同时服务一个用户（单会话设计），多标签页打开会互相干扰
- 如果后续想支持多用户协作、团队共享数据，架构需要大改
- DuckDB 连接是单例，长时间持仓数据加载后的 GC 压力无法隔离

**严重程度**：中等。作为单机桌面工具尚可接受，但限制了产品形态的演进（SaaS、团队版）。

#### 1.2 Agent 循环缺少规划层（Planning）

**问题**：当前 `agent/loop.py` 是一个简单的 tool-calling 循环——LLM 决定调哪个工具，执行，把结果塞回 messages，再让 LLM 决定。这种 **ReAct 风格** 适合简单任务，但对资管行业的复杂多步分析力不从心：

- **缺少任务分解**：用户说"帮我准备下周一的参谈要点"，这需要：拉最新持仓 → 计算集中度 → 拉净值 → 计算收益 → 拉评级 → 汇总 → 生成报告。当前架构完全依赖 LLM 临场决定每一步，无法保证步骤完整性
- **缺少执行计划的可视化和可编辑性**：用户看不到 Agent 打算做什么，只能看到它正在做什么
- **缺少回退和重规划**：某一步失败后没有结构化的回退策略，只靠 LLM 自愈

**严重程度**：高。这是从"能用的 demo"到"可靠的生产工具"的核心差距。

#### 1.3 前后端耦合度高，缺少 API 版本化

**问题**：`main.py` 承载了 800+ 行的路由定义，Flask app 既是 API 又是静态文件服务器。所有 API 无版本前缀（直接 `/api/xxx`），随着功能增长将出现：

- 路由逻辑臃肿（已经 40+ 个路由）
- 无法对 API 做向后兼容的演进
- 前端和后端改动高度耦合

**建议**：拆分为 Blueprint 模块，增加 `/api/v1/` 前缀。

#### 1.4 SSE 推送架构的限制

**问题**：当前用 `queue.Queue` 做 SSE 推送，每次 POST `/api/chat` 启动后台线程，GET `/api/stream/<sid>` 消费队列。这种模式：

- 不支持断线重连（EventSource 默认会重连，但队列中的历史事件已丢失）
- 不支持多设备同步查看（同一个 sid 只能被一个客户端消费）
- 超时 120 秒后只发 keep-alive，但浏览器的 EventSource 可能已经超时断开

**严重程度**：低。当前单机场景够用，但制约了移动端、多端协同的可能性。

---

### 二、业务功能层面

#### 2.1 固化计算器（calculators/）覆盖面不足

**现状**：已实现 4 个计算器（concentration, nav_metrics, asset_structure, credit_distribution），但资管行业日常需要的计算远不止这些：

| 缺失的计算场景 | 业务重要性 | 说明 |
|---|---|---|
| **久期/修正久期计算** | P0 | 债券投资组合的利率风险核心指标 |
| **杠杆率计算** | P0 | 合规硬指标，正回购/买断式回购口径 |
| **流动性指标** | P0 | 高流动性资产比例、前十大重仓集中度 |
| **到期分布分析** | P1 | 按到期日桶分组的市值分布 |
| **持仓变动对比** | P1 | 两期持仓的新增/减持/清仓对比 |
| **收益归因分析** | P2 | 行业/久期/信用利差等维度的归因 |
| **估值偏离度** | P1 | 摊余成本法 vs 市价法偏离的合规指标 |

**影响**：业务人员的核心需求未覆盖，会被迫回到 Excel 手算，削弱产品价值。

#### 2.2 报告生成能力是空壳

**现状**：
- `tools/report_builder.py` = 1 行（空文件）
- `tools/chart_builder.py` = 1 行（空文件）
- Skills 目录下有 `template.md.j2` 模板但无渲染管线
- 无 Word/PDF 导出能力

**影响**：这是资管人员最痛的刚需之一——每周/每月要出大量格式固定的报告。当前 DataAgent 只能对话式回答问题，不能生成可交付的报告文档。这极大降低了产品的实用价值。

#### 2.3 数据接入太被动

**现状**：只支持用户手动上传 CSV/Excel。每次启动都是空数据库，需要重新上传。

**实际痛点**：
- 资管人员每天要从估值系统、Wind/Bloomberg、内部OA等多个系统导出数据
- 手动上传+选表类型+选日期 的交互链条太长
- 没有数据持久化——昨天上传的数据今天开机就没了
- 不支持自动化的数据刷新（如每日定时从指定目录读取最新文件）

#### 2.4 缺少多期数据的时间序列分析

**问题**：当前设计中每张表是独立的快照（如 `holding_20260515`），但没有：
- 跨日期的持仓变动追踪
- 净值时间序列的趋势分析
- 数据版本管理（同日多次导出哪个为准）

这些是资管日常最频繁的分析需求。

#### 2.5 集团系管理过于简单

**现状**：`groups.yaml` 手动维护集团-成员映射，`EntityManager` 只支持简单的 CRUD。

**实际需求**：
- 集团关系是动态的（股权变更、重组、更名）
- 需要支持多层级（母公司→子公司→孙公司）穿透
- 实际业务中集团系可能有几十个关联主体，手动维护不现实
- 应支持从外部评级系统批量导入集团关系

#### 2.6 协同与审批流缺失

**问题**：合规场景的真实流程是：投资经理发现超标 → 通知风控 → 风控确认/豁免 → 记录。当前的 `request_confirmation` 只是前端弹窗让当前用户点确认，不支持：
- 多角色协作（投资经理 vs 风控 vs 合规）
- 审批链（谁发起、谁审批、审批意见）
- 超标事件的持续跟踪（从发现到化解的全生命周期）

---

### 三、技术实现层面

#### 3.1 测试基础设施不稳定

**事实**：运行测试发现 110 个用例中 45 个失败 + 18 个报错，主要原因是 `openpyxl` 模块依赖缺失导致大量 `ModuleNotFoundError`。这说明：
- `requirements-dev.txt` 不完整或未与测试环境同步
- CI/CD 未配置，测试未自动运行
- 对 CLAUDE.md 声称的"每次迭代后须按 TESTING.md 流程执行测试"执行不到位

#### 3.2 UI 是单一巨型 HTML 文件（1781 行）

**问题**：`ui/index.html` 包含了全部 HTML + CSS + JavaScript，没有组件化、没有构建流程。随着功能增长（Skill 创建面板、报告编辑器、图表配置等），这个文件会变得无法维护。

**当前状态**：UI 功能基本够用（对话、上传、侧边栏），但：
- 无法做复杂交互（如拖拽排序、表格内编辑）
- 无法做响应式适配（移动端完全不可用）
- 前端状态管理全靠 DOM 操作，容易出 bug

#### 3.3 LLM 调用缺少成本和质量监控

**问题**：`llm_client.py` 虽然记录了 `elapsed_ms` 和 `token_count`，但：
- 没有 token 用量的累计统计和预算控制
- 没有 LLM 响应质量的监控（幻觉率、SQL 正确率）
- 没有 prompt 版本管理（`prompts/system_prompt.txt` 改了就改了，无法回溯哪个版本效果好）
- 不支持 A/B 测试不同 prompt 或不同模型

#### 3.4 安全性有提升空间

- `config.yaml` 中 API Key 明文存储，虽然 API 返回时脱敏了，但文件本身不安全
- `data_loader.py` 的 `load_file` 虽然用 `safe_table` 做了简单清洗，但 DuckDB 的 `CREATE OR REPLACE TABLE "{safe_table}" AS SELECT ... FROM df` 中 `safe_table` 只替换了 `-` 和 `.`，未做 SQL 注入防护（虽然表名来自用户输入）
- SSE 流的 `sid` 是随机 UUID，但没有鉴权——知道 sid 就能消费流

#### 3.5 Context 管理粗糙

**问题**：`agent/context.py` 的 `build_schema_context()` 会把所有已加载表的完整列名列表注入 system prompt。当加载 5-10 张表、每张 50+ 列时，仅 schema 就会消耗数千 token，对有限上下文窗口造成浪费。

**影响**：
- 留给对话历史和工具结果的空间被压缩
- 每轮 LLM 调用的成本上升
- CLAUDE.md 提到了"Token 压缩"但从未实现

---

### 四、用户体验层面

#### 4.1 上传交互链条过长

当前流程：选文件 → 选表类型（下拉框）→ 选日期 → 点上传 → 等待 → 看质量报告。

理想流程：拖入文件 → 自动识别表类型和日期 → 一键确认。

#### 4.2 缺少上下文感知的引导

- 新用户不知道能问什么、该怎么开始
- 没有 onboarding 流程
- 没有基于当前加载数据的智能推荐（"你刚上传了持仓数据，要不要看看集中度？"）

#### 4.3 结果展示能力单一

- 只有文本和表格，没有图表
- `chart_builder.py` 是空文件
- 没有结果的导出功能（复制表格、下载 CSV、导出图表）
- 对比分析没有可视化对照

#### 4.4 错误恢复体验差

- LLM 调用失败时只显示"Agent 处理异常"，用户不知道该怎么办
- 没有"重试"按钮
- 合规计算失败时没有告诉用户哪些前置条件未满足

---

## 第二部分：演进方案与实施路线

### 演进总纲：从"对话式查询工具"到"资管智能工作台"

```
Phase A（当前）          Phase B（3个月）             Phase C（6个月）
━━━━━━━━━━━━━        ━━━━━━━━━━━━━━━━          ━━━━━━━━━━━━━━━
对话式数据查询    →    业务流程自动化引擎    →    资管智能工作台
                                                  
- 上传 CSV           - 数据自动刷新             - 多用户协作
- 问答式分析         - 报告一键生成             - 审批工作流
- 单次查询           - 定时监控告警             - 知识库积累
                     - 多步任务编排             - 投研助手
```

---

### 路线一：Agent 内核升级（优先级最高）

#### R1-1: 引入 Plan-Execute 双层架构

```
当前：
  User → LLM(选工具) → 执行 → LLM(选工具) → 执行 → ... → 回答

目标：
  User → Planner(任务分解) → Plan[step1, step2, ...] → 用户确认/编辑
       → Executor(按计划执行) → 中间结果 → Planner(评估/重规划)
       → ... → 汇总回答
```

**实施方案**：
1. 新增 `agent/planner.py`：接收用户意图，输出结构化执行计划
2. Plan 格式：`[{step, tool, args_template, depends_on, description}]`
3. 前端增加"执行计划卡片"——展示计划步骤、允许用户勾选/调整/重排
4. `agent/executor.py`：按 DAG 执行计划（支持并行无依赖的步骤）
5. 失败时回到 Planner 重规划，而非简单重试

**收益**：
- 复杂任务（如"准备参谈要点"）的完成率从 ~30% 提升到 ~80%
- 用户有控制感，知道 Agent 要做什么
- 可审计——每步计划和执行结果都有记录

#### R1-2: Agent 自省与质量闭环

```python
# 新增 agent/self_check.py
class SelfChecker:
    def check_result(self, query, result, context) -> CheckVerdict:
        """
        对 Agent 产出的结果做自检：
        - 数值合理性（集中度不应超 100%、收益率不应超 ±50%）
        - 数据完整性（是否漏了某些产品）
        - 口径一致性（本次计算口径是否与历史一致）
        """
```

**收益**：减少"精确的错误"交付给用户的概率。

#### R1-3: 多 Agent 协作（长期）

将 DataAgent 从单 Agent 拆分为协作 Agent 团队：
- **Analyst Agent**：数据分析、SQL 生成
- **Compliance Agent**：合规校验、阈值判断
- **Report Agent**：报告撰写、格式化
- **Orchestrator**：任务分配、结果汇聚

---

### 路线二：业务能力深化（优先级高）

#### R2-1: 补齐核心计算器

| 计算器 | 优先级 | 估时 | 说明 |
|---|---|---|---|
| `leverage.py` | P0 | 2天 | 杠杆率（正回购/买断式） |
| `duration.py` | P0 | 3天 | 组合久期/修正久期 |
| `liquidity.py` | P0 | 2天 | 高流动性资产比例 |
| `maturity_profile.py` | P1 | 2天 | 到期分布桶 |
| `position_diff.py` | P1 | 2天 | 两期持仓变动 |
| `valuation_deviation.py` | P1 | 2天 | 估值偏离度 |
| `yield_attribution.py` | P2 | 5天 | 收益归因 |

#### R2-2: 报告生成管线

```
数据计算 → 模板渲染(Jinja2) → 格式化(Markdown/HTML) → 导出(Word/PDF)
                                                          ↓
                                                    可编辑的富文本
                                                    用户校对→定稿
```

**实施方案**：
1. 补全 `tools/report_builder.py`：基于 Jinja2 模板渲染 + python-docx 导出 Word
2. 报告模板标准化：每种报告类型一个 `.md.j2` + 一个 `.docx` 模板
3. 前端增加"报告预览面板"：支持在线编辑、批注、导出
4. LLM 负责文字段落的润色，不负责数值计算

#### R2-3: 数据持久化与自动刷新

```yaml
# 新增 data_sources.yaml
sources:
  - name: daily_holding
    type: csv_directory
    path: "D:/资管系统导出/持仓/"
    pattern: "持仓明细_*.csv"
    table_type: holding
    date_pattern: "持仓明细_{date}.csv"  # 自动提取日期
    auto_refresh: true
    schedule: "08:30"  # 每日 8:30 自动扫描
```

**实施方案**：
1. 新增 `tools/data_source_manager.py`：管理数据源配置、目录监控、自动加载
2. 启动时自动检测指定目录的新文件并加载
3. 支持历史数据保留（自动命名 `holding_20260515`、`holding_20260516` ...）
4. 前端增加"数据源管理"面板

#### R2-4: 持仓变动追踪

```python
# 新增 calculators/position_diff.py
def calc_position_diff(conn, table_old, table_new, ...) -> list[PositionChange]:
    """
    对比两期持仓：
    - 新增持仓（新表有、旧表无）
    - 减持（市值下降）
    - 增持（市值上升）
    - 清仓（旧表有、新表无）
    - 不变
    """
```

#### R2-5: 投研辅助（中长期）

- 债券基本面查询（集成 Wind/Bloomberg 数据）
- 行业新闻与舆情关联（结合 RAG）
- 类似持仓的同业对比

---

### 路线三：用户体验重塑（优先级中高）

#### R3-1: 智能上传与数据识别

```
拖入文件 → 自动识别编码 → 自动匹配表类型 → 自动提取日期
         → 显示预览卡片 → 用户一键确认
```

**实施方案**：
1. `data_loader.py` 增加 `auto_detect_table_type(df)` 函数：基于列名特征自动判断类型
2. 增加 `extract_date_from_filename(filename)` 函数：正则匹配常见日期格式
3. 前端拖拽上传 → 后端返回识别结果 → 用户确认或修正

#### R3-2: 上下文感知推荐

```python
# 新增 agent/recommender.py
def suggest_next_actions(loaded_tables, recent_queries) -> list[Suggestion]:
    """
    基于当前数据和历史操作，推荐下一步分析：
    - 刚上传持仓表 → "查看主体集中度" "对比上期持仓变动"
    - 发现集中度超标 → "查看超标主体详情" "生成预警报告"
    - 临近月末 → "生成月度运作报告" "统计本月收益"
    """
```

#### R3-3: 可视化升级

1. 补全 `tools/chart_builder.py`：
   - 集中度饼图/柱状图
   - 资产结构 Treemap
   - 净值走势折线图
   - 到期分布堆叠柱状图
   - 持仓变动瀑布图

2. 前端 ECharts 渲染（已引入但未使用）

3. 图表支持交互：点击柱子下钻到明细

#### R3-4: 前端架构升级（中期）

从单 HTML 文件迁移到轻量前端框架：

**推荐方案**：Vue 3 + Vite（轻量、易学、生态好）
- 组件化：ChatPanel, UploadCard, ReportPreview, ChartView, Sidebar 等
- 状态管理：Pinia（替代全局 DOM 操作）
- 构建产物仍是静态文件，不影响 PyWebView 集成

**迁移策略**：渐进式迁移，先把 JS 逻辑抽出为独立模块，再逐步组件化

#### R3-5: 移动端适配（长期）

- 响应式 UI 适配手机/平板
- 关键场景移动端覆盖：集中度超标推送通知 → 手机查看详情 → 确认/豁免
- PWA 或小程序形态

---

### 路线四：数据与安全治理（优先级中）

#### R4-1: 数据血缘追踪

```python
# 每个计算结果标记完整血缘
@dataclass
class DataLineage:
    source_files: list[str]        # 来自哪些文件
    source_dates: list[str]        # 数据日期
    calculation: str               # 使用的计算器和版本
    thresholds: dict               # 使用的阈值
    intermediate_sql: list[str]    # 中间执行的 SQL
    operator: str                  # 操作人
    timestamp: str                 # 执行时间
```

**收益**：监管检查时可快速追溯任何数字的来源和计算过程。

#### R4-2: 权限与角色模型

```
角色层级：
  管理员 → 可修改 config、管理数据源
  合规 → 可查看审计日志、审批确认
  投资经理 → 可上传数据、执行查询、生成报告
  研究员 → 可查询、不可修改阈值
```

#### R4-3: 审计日志增强

当前 `compliance_audit.py` 只记录合规事件。应扩展为全操作审计：
- 谁在什么时间上传了什么数据
- 谁执行了什么查询
- 谁修改了什么配置
- 所有操作可回溯、可导出

#### R4-4: 敏感数据分级

```python
# 字段级敏感度标记
sensitivity_levels = {
    "产品名称": "internal",      # 内部可见
    "持仓明细": "confidential",  # 机密
    "客户信息": "restricted",    # 受限
    "收益数据": "internal",
}
```

根据敏感度控制：是否可导出、是否可发送给外部 LLM、是否记录在日志中。

---

### 路线五：技术架构现代化（优先级中低）

#### R5-1: 会话隔离与多用户支持

将全局 `_session` 改为 session store：

```python
# 新增 session_store.py
class SessionStore:
    def __init__(self):
        self._sessions: dict[str, Session] = {}
    
    def create_session(self, user_id: str) -> Session:
        """每个会话有独立的 DuckDB 连接、消息历史、加载数据"""
```

#### R5-2: 插件化工具注册

当前工具硬编码在 `TOOL_DEFINITIONS` 列表中。应改为注册机制：

```python
# tools/registry.py
class ToolRegistry:
    def register(self, name, definition, handler):
        """动态注册工具，支持热加载"""
    
    def get_definitions(self, context) -> list:
        """根据上下文返回可用工具（如合规场景只暴露固化工具）"""
```

**收益**：新增工具不需要修改 `tools_spec.py`，符合开闭原则。

#### R5-3: LLM 网关层

在 `llm_client.py` 之上增加网关：

```python
# agent/llm_gateway.py
class LLMGateway:
    def __init__(self):
        self.providers = []       # 多个 LLM 提供方
        self.cost_tracker = CostTracker()
        self.quality_monitor = QualityMonitor()
        self.prompt_registry = PromptRegistry()
    
    def route(self, request) -> LLMResponse:
        """
        智能路由：
        - 简单意图分类 → 小模型（省成本）
        - SQL 生成 → 代码专长模型
        - 报告文字 → 中文写作模型
        - token 预算超限 → 降级或提示
        """
```

#### R5-4: 离线 LLM 支持

资管行业的合规要求可能完全禁止外发。应支持本地小模型：

- 集成 ollama / llama.cpp 后端
- 支持 Qwen-2.5-Coder-7B 等本地模型
- 本地模型用于 SQL 生成和意图分类
- 报告文字可以使用模板填充完全离线

---

### 路线六：产品化与商业化（长期）

#### R6-1: 团队版

- 中央数据仓库（团队共享的 DuckDB/PostgreSQL）
- 权限管理（RBAC）
- 报告协作编辑
- 合规审批工作流

#### R6-2: 知识库与最佳实践

- 跨会话的分析知识积累（不仅是口径纠正，还包括分析思路）
- 团队内分析模板分享
- 行业基准数据集成

#### R6-3: 合规监管集成

- 自动生成监管报表（PBOC/CBIRC 格式）
- 与合规系统双向对接
- 实时预警推送（企业微信/钉钉）

---

## 第三部分：实施路线图

### 近期（1-2 个月）：补齐短板，提升可用性

```
Week 1-2:  修复测试基础设施 + 补齐依赖 + CI/CD 配置
Week 3-4:  补齐核心计算器（leverage, duration, liquidity）
Week 5-6:  实现报告生成管线（report_builder + Word 导出）
Week 7-8:  数据持久化 + 自动刷新 + 智能上传识别
```

**里程碑**：用户可以上传数据后一键生成运作报告 Word 文档。

### 中期（3-4 个月）：Agent 内核升级 + 体验重塑

```
Month 3:   Plan-Execute 双层架构 + 执行计划可视化
Month 4:   可视化升级（chart_builder 补全 + ECharts 联动）
           持仓变动追踪 + 多期时间序列分析
           数据血缘追踪 + 审计日志增强
```

**里程碑**：用户说"帮我准备参谈要点"，Agent 展示执行计划 → 用户确认 → 自动完成全流程。

### 远期（5-6 个月）：产品化

```
Month 5:   前端架构升级（Vue 3 迁移）
           多用户会话隔离
           移动端适配
Month 6:   团队协作 + 权限模型
           知识库积累
           Windows 打包 + 灰度发布
```

**里程碑**：团队版上线，多角色协作，合规审批流程完整。

---

## 第四部分：关键技术决策建议

| 决策点 | 建议 | 理由 |
|---|---|---|
| 前端框架 | Vue 3 + Vite | 轻量、学习曲线低、与 PyWebView 兼容好 |
| 报告导出 | python-docx + WeasyPrint | 原生 Word + PDF，不依赖 Office |
| 本地 LLM | ollama + Qwen3-8B | 合规安全、零外发、SQL 生成够用 |
| 数据持久化 | DuckDB 文件模式 | 性能好、零运维、可导出 |
| 图表库 | ECharts（已引入） | 中文生态好、金融图表丰富 |
| CI/CD | GitHub Actions | 配合现有仓库，自动测试 |
| 多用户 | SQLite session + DuckDB per-user | 最小改动实现隔离 |

---

## 总结

DataAgent 当前完成了一个扎实的技术基座——tool-calling Agent 循环、安全的 SQL 执行、固化计算器、编码自适应、SSE 流式推送。这些是正确的技术选择。

但从**资管业务人员的真实工作流**来看，产品距离"用起来"还有三个核心差距：

1. **报告生成能力为零**——资管人 60% 的时间在写报告，这是最大的价值缺口
2. **数据接入太被动**——每次手动上传是不可接受的日常使用体验
3. **Agent 缺少规划能力**——复杂多步任务（参谈要点、运作报告）完成率不够

建议优先级：**报告生成 > 数据自动化 > Agent 规划升级 > 可视化 > 前端重构**。

先让用户能用 DataAgent 完成一个完整的工作闭环（上传数据 → 分析 → 生成报告 → 导出 Word），再逐步提升 Agent 的智能化水平。
