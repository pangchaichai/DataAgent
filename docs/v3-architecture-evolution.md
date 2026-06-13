# DataAgent v3.0 架构演进方案 — Agent-as-OS + Closed-Loop Eval

> 版本：v3.0 final（2026-06-13）
> 研究基础：Anthropic《Building Effective Agents》完整内容 + 控制工程理论 + LangSmith/Braintrust/Arize eval 模式 + 四位专家观点
> 状态：已批准，进入实施阶段（2026-06-13）

---

## Context — 五个根本性问题

DataAgent 完成了 v2.0（核心链路 + Skill v3 数据感知 + 工作目录）后，进入推广前的架构审视阶段：

1. **内核与应用耦合** — `tools_spec.py` 硬编码 7 个 calculator 枚举，Skill 匹配逻辑写死在内核循环中
2. **LLM 过度使用** — 确定性任务（固化计算）仍经 LLM tool-calling 路由，浪费 2-5 秒 + token
3. **Skill 不可靠** — 500 行 Markdown 注入 LLM 上下文期望"忠实执行"，超出 LLM 可靠执行边界
4. **开发者思维 UX** — 需选 rating_entity 类型、@mention 语法、YAML frontmatter 编辑
5. **缺乏可观测性与评估闭环** — 执行数据只写入日志，没有读取/分析/改进的闭环机制

**用户确认的三个决策**：
- 内核解耦：**完整解耦**（引入 ToolRegistry，应用层声明式注册）
- 自我进化：**仅追踪**（先建执行追踪数据基础，不做自动学习）
- UI 方向：**对话 + 卡片增强**（保持对话为主，侧边栏 Skill 卡片化 + 一键执行）

---

## 第一章：理论框架 — 控制工程视角下的 Agent 设计

> 这是本次演进的核心新增内容。控制工程为 Agent 设计提供了一套严格的分析语言，帮助我们系统性地识别 DataAgent 的短板和改进方向。

### 1.1 Agent 的闭环控制模型

传统 LLM 调用是**开环系统**（open-loop）：输入进，答案出，无验证。DataAgent 的 Agent Loop 是**闭环系统**（closed-loop）：

| 控制工程概念 | DataAgent 对应元素 |
|------------|------------------|
| **Plant**（被控对象） | 外部环境：DuckDB、Config、用户状态 |
| **Controller**（控制器） | LLM + 系统提示 + 工具分发逻辑 |
| **Sensor / Measurement** | 工具输出结果、用户反馈 |
| **Actuator**（执行器） | 工具调用（SQL 执行、calculator、报告生成） |
| **Reference signal**（设定值） | 用户意图 / 期望输出 |
| **Error signal**（误差信号） | 当前输出与用户意图的差距 |
| **Feedback loop** | Tool result → 下一轮 LLM 推理 |

**OODA Loop 映射**（军事决策模型，适用于 Agent）：
- **Observe**（观察）→ 工具结果、用户消息、数据剖析
- **Orient**（定向）→ 上下文注入、Schema 映射、数据字典注入（这是大多数 Agent 失败的环节）
- **Decide**（决策）→ LLM 推理 + 工具选择
- **Act**（行动）→ 工具执行

### 1.2 PID 控制类比 — Agent 自校正的三个维度

**P（比例，Proportional）= 即时纠错**
- 工具调用失败后立即调整下一动作
- DataAgent 现有实现：`categorize_tool_error()` 区分语法/语义/空结果/异常，差异化重试
- 风险："增益过高"导致振荡——连续修改 SQL 但越改越错
- **改进点（Track 4）**：连续 2 次同类错误后，切换策略而非继续同类重试

**I（积分，Integral）= 跨会话积累学习**
- 纠正历史错误，防止"稳态误差"（系统性偏差）
- DataAgent 现有：BM25+SQLite 口径纠正记忆（默认关闭）
- 风险："积分饱和"（integral windup）——过多历史纠正使 Agent 过度约束
- **改进点（Track 4 ExecutionTracker）**：记录被拒绝的执行模式，有时效性，3 个月自动衰减

**D（微分，Derivative）= 趋势预测**
- 检测误差正在恶化，提前干预而非等崩溃
- DataAgent 现有：**零实现**——这是最大的缺口
- **改进点（Track 2 新增）**：在 Agent Loop 中追踪每轮误差率，`d(error)/d(turn) > threshold` 时提前触发 `ask_user`，而非等到 MAX_TURNS 耗尽

```python
# 新增：D-term 误差趋势检测（agent/loop.py）
class ErrorTrendDetector:
    def __init__(self, window=3, threshold=0.6):
        self.recent_errors = []    # 最近 N 轮的成功/失败
        self.threshold = threshold  # 错误率阈值
    
    def record(self, success: bool):
        self.recent_errors.append(0 if success else 1)
        if len(self.recent_errors) > self.window:
            self.recent_errors.pop(0)
    
    def should_escalate(self) -> bool:
        if len(self.recent_errors) < self.window:
            return False
        error_rate = sum(self.recent_errors) / len(self.recent_errors)
        return error_rate >= self.threshold
```

### 1.3 稳定性 — 防止 Agent 振荡与发散

**振荡模式**（控制论中的 limit cycle）：
- Agent 在两个矛盾动作间来回切换（如反复添加/移除同一 SQL 过滤条件）
- Agent 不断换方式提问但未取得进展

**发散模式**（正反馈失控）：
- 每次纠正引入新错误，误差累积增大
- 上下文无限增长导致 LLM 注意力退化

**DataAgent 现有稳定性机制**（控制论角度的再解释）：

| 机制 | 控制论类比 | 状态 |
|-----|----------|------|
| MAX_TURNS=15 | 迭代次数上界（粗暴但有效） | ✅ 已实现 |
| MAX_TOOL_RETRY=3 | 单工具重试限制 | ✅ 已实现 |
| 三级上下文压缩 | 阻尼函数（减少噪声放大） | ✅ 已实现 |
| Plan-Execute 规划层 | 前馈控制（减少反馈负担） | ✅ 已实现 |
| D-term 误差趋势检测 | 提前降级（预测性稳定） | ❌ 待实现 |

### 1.4 可观测性与可控性

**可观测性**（Observability）— 能否从输出推断内部状态？

DataAgent 现有可观测性：
- ✅ SSE 事件流（thinking/tool_start/tool_end/plan/ask）
- ✅ Hook 系统（pre_tool_use/post_tool_use/on_error）
- ✅ 运行时日志（JSONL 按日滚动）
- ✅ 合规审计日志（Hash Chain）

**缺口**：可观测性是**写入端完整**，但**读取端/分析端缺失**——数据只进不出，没有闭环。Track 4 的 Eval Framework 解决此问题。

**可控性**（Controllability）— 能否将 Agent 引导至期望行为？

DataAgent 现有控制机制：
- ✅ 工具过滤（`calc_type=="fixed"` 时移除 `run_sql`）= **硬约束**（类比机械限位器）
- ✅ SQLGuard 的 LIMIT≤1000 和 BLOCKED_FUNCTIONS = **饱和限制**（类比安全阀）
- ✅ `request_confirmation` = **人工Override**（类比手动切换到手动控制模式）
- ✅ Plan 展示 = 允许用户在执行前修改"轨迹"
- ❌ 缺乏 D-term 触发的自动降级（见 1.2）

---

## 第二章：专家观点综述与设计映射

### 一、Anthropic《Building Effective Agents》(2024.12, Erik Schluntz & Barry Zhang)

**核心原则**：
> "The most successful implementations weren't using complex frameworks. They were building with simple, composable patterns."

**五种 Workflow 模式**（DataAgent 需要全部理解并映射）：

| 模式 | DataAgent 当前对应 | 本次演进 |
|-----|-----------------|---------|
| **Prompt Chaining**（链式调用） | 各 Skill 的步骤执行 | Plan-Execute 已覆盖 |
| **Routing**（路由） | Skill 关键词匹配 → Track 1 ToolRegistry | 升级为声明式路由 |
| **Parallelization**（并行化） | 无 | 未来 Multi-Agent 时考虑 |
| **Orchestrator-Workers** | planner.py + executor.py | 保持现有实现 |
| **Evaluator-Optimizer**（评估-优化循环） | **无** | **Track 4 新增** |

**ACI（Agent-Computer Interface）设计原则**（与 HCI 同等重要）：
- 工具描述必须包含"**何时使用**"，不只是"**做什么**"
- Poka-yoke（防错设计）：让错误更难发生——例如要求绝对路径而非相对路径
- `strict: true` 在工具定义上确保 Schema 一致性
- 用熟悉的格式（Markdown > JSON for output）

**→ DataAgent ACI 改进项**（集成到 Track 1）：
- `profile_table` 工具描述加 "先调用此工具了解表结构，再生成 SQL"
- `run_sql` 工具描述加 "仅用于探索式查询（A 类），合规场景已被系统移除此工具"
- `run_calculator` 工具描述加 "使用时禁止自行传入计算参数，使用 config 中的预设参数"

**Evaluator-Optimizer 模式**（DataAgent Track 4 的核心来源）：
```
用户请求 → Agent 生成结果 → Evaluator 评估 → 不通过则反馈给 Agent 重试（最多 N 次）
```
Anthropic 建议最多 5 次迭代，用于有明确评估标准的场景（如 SQL 正确性、报告格式合规性）。

### 二、Boris Cherny（Claude Code 创建者）

> "You don't trust; you instrument."

- **Loop Engineering**：设计循环来驱动 Agent，而非手工编写 Prompt
- **Verification over trust**：给 Agent 验证工具能提升质量 2-3x
- **Phased rollout**：L1 Report-only → L2 Assisted → L3 Unattended（只有在证明可靠后才升级）
- **CLAUDE.md 作为活约定**：每次错误后加规则，形成增长的约束系统

**→ DataAgent 映射**：
- ExecutionTracker = "instrument" 的体现
- 置信度标注 = L1 阶段（report-only）— 先可审计，再逐步自动化
- Track 4 Eval Framework = 在升级到 L2/L3 前的质量门控

### 三、Addy Osmani（Google VP Engineering）

> "The specification is the critical bottleneck, not the AI itself."

- **Three-tier boundary**：Always（自行执行）/ Ask（标记待审）/ Never（硬性阻断）
- **Self-verification**：Agent 在人工审查前先自我验证
- **Demo vs Production Gap**：可见代码 20%，不可见的（错误处理/审计/重试）占 80%

**→ DataAgent 映射**：
- 固化计算 = Always，探索查询 = Ask（SelfChecker 校验），危险操作 = Never（SQLGuard）
- Track 4 Eval Framework = "invisible 80%"的质量保障

### 四、Peter Steinberger（PSPDFKit 创始人）

> "Skill descriptions should be short and generic; optimize for routing, not documentation."

- Skill 路由阶段只需短描述；执行阶段才加载完整内容（DataAgent 已有渐进式加载）
- 即使最大自主权，不可逆操作仍需人工确认

### 五、Agent 架构研究

- 单 Agent + 技能库 = 多 Agent 的成本 1/4-1/220，准确率相当（Skill < 50 时）
- 当前 DataAgent Skill 数量 < 10，远低于退化阈值 → 单 Agent 正确
- Hierarchical Supervisor-Worker 在金融文档处理中 F1=0.929，成本最优

---

## 第三章：架构决策

### 问题 A：纯客户端 vs 引入服务端

**结论：保持纯客户端，预留服务端接口**

理由：数据合规第一性、用户数 < 50、Anthropic "Start simple" 原则。

预留接口（不实现）：
- `tool_registry.py` 工具定义预留 `source` 字段
- `execution_tracker.py` 日志设计为可匿名化
- Skill 文件保留 `version` + `author` 元数据

触发服务端的条件：活跃用户 > 50 或 跨团队共享需求出现。

### 问题 B：验证与防幻觉 — 五层防护体系

**现有四层（保留）**：

| 层 | 模块 | 状态 |
|----|------|------|
| 输入层 | SQLGuard（SELECT-only + BLOCKED_FUNCTIONS + LIMIT） | ✅ |
| 输入层 | quality.py（空值率/覆盖率/JOIN 兼容性） | ✅ |
| 输出层 | SelfChecker（数值范围校验） | ✅ |
| 审计层 | compliance_audit.py（Hash Chain） | ✅ |

**新增第五层（本次演进）**：

| 层 | 机制 | Track |
|----|------|-------|
| 路由层 | 双通道分流（快速路径绕过 LLM） | Track 2 |
| 语义层 | LLM-as-Judge SQL 语义校验 | Track 4 |
| 追踪层 | ExecutionTracker 完整工具调用链 | Track 2 |
| 展示层 | 置信度标注 `[可审计]`/`[请校验]`/`[AI生成]` | 贯穿 |
| 评估层 | 四级 Eval Framework（闭合观测反馈环） | Track 4 |

---

## 第四章：演进方案 — 四个轨道

### Track 1：内核解耦 — ToolRegistry + ACI 加强

**目标**：tools_spec.py 不再硬编码，应用层声明式注册；同时提升工具的 ACI 质量。

#### 1.1 新建 `agent/tool_registry.py`

```python
class ToolRegistry:
    """内核工具注册中心 — 应用层通过此接口声明式注册"""
    
    def register_tool(self, name, schema, handler, category, metadata=None):
        """
        - name: 工具名（全局唯一）
        - schema: OpenAI function-calling schema（必须含 when_to_use 字段）
        - handler: callable(args, ctx) -> dict
        - category: "calculator"|"query"|"interaction"|"output"|"external"
        - metadata: calc_type, requires_confirmation 等
        """
    
    def get_tool_definitions(self, categories=None, exclude=None) -> list[dict]: ...
    def dispatch(self, name, args, ctx) -> dict: ...
    def list_tools(self, category=None) -> list[str]: ...

_registry = ToolRegistry()
def get_registry() -> ToolRegistry: return _registry
```

#### 1.2 应用层自注册模式

**calculators/ 自注册**（`calculators/__init__.py`）：
```python
def register_all_calculators():
    registry = get_registry()
    registry.register_tool(
        name="entity_concentration",
        schema={"type": "function", "function": {
            "name": "entity_concentration",
            "description": "计算主体/单券集中度。仅在用户询问集中度监控、限额使用情况时使用。合规场景必用此工具，禁止用 run_sql 替代。",
            "parameters": {...}
        }},
        handler=_handle_entity_concentration,
        category="calculator",
        metadata={"requires_config_params": ["threshold_entity", "market_value_field"]}
    )
```

**内置工具注册**（`agent/builtin_tools.py`）：
```python
def register_builtin_tools():
    registry = get_registry()
    # ACI 改进：每个工具描述包含 when_to_use
    registry.register_tool("profile_table", schema={
        "description": "剖析表结构，返回列名/类型/样本/空值率。在生成 SQL 之前必须先调用此工具了解实际列名，避免引用不存在的列。",
        ...
    }, category="query")
    
    registry.register_tool("run_sql", schema={
        "description": "执行 SELECT 查询（A 类探索式查询专用）。仅在 calc_type=exploratory 的场景下可用。合规场景系统会自动移除此工具。",
        ...
    }, category="query")
```

#### 1.3 tools_spec.py 瘦身（1128 行 → ~100 行）

```python
# tools_spec.py 只做两件事：
from agent.tool_registry import get_registry

def get_tool_definitions(skill_info=None):
    exclude = []
    if skill_info and skill_info.calc_type == "fixed":
        exclude.append("run_sql")
    return get_registry().get_tool_definitions(exclude=exclude)

def dispatch_tool(name, args, ctx):
    return get_registry().dispatch(name, args, ctx)
```

#### 1.4 涉及文件

| 文件 | 变更 |
|------|------|
| `agent/tool_registry.py` | **新建** — ToolRegistry 核心类 |
| `agent/builtin_tools.py` | **新建** — 内置工具注册（含 ACI 加强的工具描述） |
| `calculators/__init__.py` | **新建/改** — register_all_calculators() |
| `tools/output_tools.py` | **新建** — 输出工具注册 |
| `agent/tools_spec.py` | **重构** — 瘦身到 ~100 行薄转发层 |
| `main.py` | **改** — 启动时调用注册函数 |
| `agent/loop.py` | **改** — 从 tools_spec 导入改为 registry 接口 |

---

### Track 2：双通道编排 + 执行追踪 + D-term 趋势检测

**目标**：确定性任务跳过 LLM（0.5s 响应），建立执行追踪数据基础，加入误差趋势检测。

#### 2.1 快速路径 — `agent/fast_path.py`

```python
def try_fast_path(user_message, skill_info, preflight_result, ctx) -> Generator | None:
    """
    快速路径条件（全部满足）：
    1. skill_info.calc_type == "fixed"
    2. preflight_result.can_execute == True
    3. 工具参数可从 skill_info + config 确定（无需 LLM 推断）
    """
    if not _can_fast_path(skill_info, preflight_result):
        return None
    
    calculator_name = skill_info.fixed_calculator
    args = _build_calculator_args(skill_info, preflight_result, ctx)
    
    yield _tool_start(calculator_name, "执行固化计算")
    result = get_registry().dispatch(calculator_name, args, ctx)
    yield _tool_end(calculator_name, result)
    
    if result.get("ok"):
        yield from _render_fast_result(result, skill_info, confidence="auditable")
        # 可选 LLM 一句话解读（token 极少，价值高）
        summary = _llm_one_line_summary(result, ctx)
        if summary:
            yield _text(summary, confidence="ai_generated")
    else:
        yield _error(result.get("error", "计算失败"))
    
    yield _stream_end()
```

#### 2.2 loop.py 集成点（含 D-term）

```python
def run_agent_loop(user_message, ...):
    # ... schema context, skill matching, preflight (不变) ...
    
    # === 新增：尝试快速路径 ===
    fast = try_fast_path(user_message, matched_skill_info, preflight_result, ctx)
    if fast is not None:
        yield from fast
        return
    
    # === 原有 Agent Loop（开放路径），新增 D-term 检测 ===
    error_detector = ErrorTrendDetector(window=3, threshold=0.67)
    
    while turn < MAX_TURNS:
        result = llm.call(...)
        tool_success = _execute_tool(result)
        error_detector.record(tool_success)
        
        # D-term：误差趋势恶化，提前升级
        if error_detector.should_escalate():
            yield _ask_user("我连续遇到了一些问题，请问您是否可以提供更多信息？")
            return
        
        # ... 现有逻辑 ...
```

#### 2.3 执行追踪 — `agent/execution_tracker.py`

```python
@dataclass
class ExecutionTrace:
    trace_id: str
    timestamp: str
    user_message: str            # 前 200 字符
    matched_skill: str | None
    execution_path: str          # "fast_path" | "agent_loop" | "direct_answer"
    tool_calls: list[dict]       # [{tool, args_summary, success, duration_ms}]
    total_duration_ms: int
    token_usage: dict
    user_feedback: str | None    # "confirmed"|"rejected"|"corrected"|None
    outcome: str                 # "success"|"partial"|"error"
    error_summary: str | None

class ExecutionTracker:
    def start_trace(self, user_message, skill_name=None) -> str: ...
    def record_tool_call(self, trace_id, tool, args, result, duration_ms): ...
    def record_user_feedback(self, trace_id, feedback_type, details=None): ...
    def end_trace(self, trace_id, outcome): ...
    def get_stats(self) -> dict:
        """返回：成功率、平均耗时、最常用Skill、最常见错误、快速路径占比"""
    def get_degradation_signals(self) -> dict:
        """检测退化信号：近7天 vs 近1天对比"""
```

存储：`data/traces/traces_YYYYMMDD.jsonl`

#### 2.4 涉及文件

| 文件 | 变更 |
|------|------|
| `agent/fast_path.py` | **新建** — 确定性快速路径 |
| `agent/execution_tracker.py` | **新建** — 执行追踪 + 退化信号检测 |
| `agent/loop.py` | **改** — fast_path 集成 + D-term 趋势检测 + 追踪埋点 |
| `agent/skill_loader.py` | **改** — SkillInfo 新增 `fixed_calculator` 一级字段 |

---

### Track 3：Skill 卡片化 + 一键执行

**目标**：侧边栏 Skill 从文字列表变为交互卡片，显示数据就绪状态，支持一键执行。

#### 3.1 新增 API

```python
# api/skill_api.py 新增

@skill_bp.route('/api/skills/status', methods=['GET'])
def api_skills_status():
    """返回所有 Skill 的运行状态（含数据就绪检查）"""
    # 返回：name, description, calc_type, data_ready, missing_data,
    #        can_fast_execute, last_executed, last_result_summary

@skill_bp.route('/api/skills/<name>/execute', methods=['POST'])
def api_skill_execute(name):
    """一键执行 Skill（走快速路径或 Agent Loop）"""
    # 复用现有 /api/chat 的 SSE 流式输出
```

#### 3.2 前端 Skill 卡片

```javascript
// ui/js/sidebar.js 改造
function renderSkillCard(skill) {
    return `
    <div class="skill-card ${skill.can_fast_execute ? 'ready' : ''}">
        <div class="skill-card-header">
            <span class="skill-card-name">${esc(skill.name)}</span>
            <span class="skill-badge ${skill.calc_type}">
                ${skill.calc_type === 'fixed' ? '固化' : '探索'}
            </span>
        </div>
        <div class="skill-card-desc">${esc(skill.description)}</div>
        <div class="skill-card-status">
            ${skill.data_ready 
                ? '<span class="status-ok">数据就绪</span>'
                : '<span class="status-warn">缺: ' + esc(skill.missing_data.join(', ')) + '</span>'}
        </div>
        ${skill.last_executed 
            ? '<div class="skill-last-run">上次: ' + esc(skill.last_executed) + '</div>'
            : ''}
        <div class="skill-card-actions">
            ${skill.can_fast_execute 
                ? '<button class="btn-primary-sm" onclick="executeSkill(\'' + esc(skill.name) + '\')">执行</button>'
                : skill.data_ready
                    ? '<button class="btn-ghost-sm" onclick="triggerSkill(\'' + esc(skill.name) + '\')">对话执行</button>'
                    : '<button class="btn-ghost-sm disabled" disabled>需要数据</button>'}
        </div>
    </div>`;
}
```

#### 3.3 涉及文件

| 文件 | 变更 |
|------|------|
| `api/skill_api.py` | **改** — 新增 status + execute 端点 |
| `ui/js/sidebar.js` | **改** — Skill 卡片渲染 + executeSkill() |
| `ui/index.html` | **改** — .skill-card CSS 样式 |
| `ui/js/chat.js` | **改** — executeSkill 复用 SSE 流处理 |

---

### Track 4：Agent 评估框架 — 闭合可观测性反馈环（本次核心新增）

> **为什么这是本次最重要的新增**：控制工程告诉我们，一个没有 Sensor 读取反馈的系统是开环系统——无论它的执行机制多精密，都缺乏自我修正能力。DataAgent 现有的日志、审计、Hook 系统是完整的写入端（传感器），但缺乏读取端（反馈分析）和改进端（控制器调整）。Track 4 闭合这个环。

这映射到 Anthropic 的 **Evaluator-Optimizer 模式**：生成 → 评估 → 反馈 → 优化的完整闭环。

#### 4.1 四级评估架构

```
Level 1: 单元测试（已有）
  ├── calculators/ 正确性测试
  ├── SQLGuard 安全测试
  └── SelfChecker 数值校验测试

Level 2: 组件测试（本次新增）
  ├── 工具选择准确性：给定上下文，LLM 是否选择正确工具？
  ├── SQL 语义质量：生成的 SQL 是否与数据字典语义一致？
  └── 上下文压缩保真度：压缩后是否保留关键信息？

Level 3: 端到端 Agent 测试（本次新增）
  ├── 任务完成率：用户请求 → Agent → 正确最终答案？
  ├── 轨迹效率：实际步骤数 vs 最优步骤数
  └── 错误恢复率：注入工具失败 → Agent 恢复率

Level 4: 生产监控（本次新增，读取 ExecutionTracker 数据）
  ├── 实时指标追踪
  ├── 退化信号告警
  └── 周期性离线评估
```

#### 4.2 新建 `agent/eval_framework.py`

```python
"""
DataAgent Agent 评估框架
实现 Anthropic Evaluator-Optimizer 模式的 Evaluator 端
"""

@dataclass
class EvalCase:
    """单个评估用例"""
    case_id: str
    user_query: str
    expected_skill: str | None       # 期望匹配的 Skill
    expected_tool_sequence: list[str] # 期望工具调用序列（可部分匹配）
    expected_outcome: str            # "success"|"ask_user"|"error"
    tags: list[str]                  # ["sql", "calculator", "compliance"]

@dataclass  
class EvalResult:
    case_id: str
    actual_skill: str | None
    actual_tool_sequence: list[str]
    actual_outcome: str
    skill_match: bool
    tool_sequence_accuracy: float    # 0.0-1.0
    task_complete: bool
    duration_ms: int
    token_usage: dict
    judge_score: float | None        # LLM-as-judge 评分（0-1）
    judge_reasoning: str | None

class AgentEvaluator:
    """Agent 评估器 — Evaluator-Optimizer 模式中的 Evaluator"""
    
    def __init__(self, llm_client, tracker: ExecutionTracker):
        self.llm = llm_client
        self.tracker = tracker
        self.cases: list[EvalCase] = []
    
    def add_case(self, case: EvalCase): ...
    def load_cases_from_file(self, path: str): ...
    
    def run_eval(self, case: EvalCase, agent_fn: Callable) -> EvalResult:
        """运行单个评估用例"""
        result = agent_fn(case.user_query)
        
        # 工具序列对比
        tool_accuracy = self._compare_tool_sequences(
            case.expected_tool_sequence, 
            result.tool_calls
        )
        
        # LLM-as-judge（仅用于探索式查询，固化计算用规则校验）
        if "sql" in case.tags:
            judge_score, reasoning = self._llm_judge_sql_quality(
                case.user_query, result.generated_sql, result.final_output
            )
        else:
            judge_score, reasoning = None, None
        
        return EvalResult(...)
    
    def run_suite(self, suite_name: str) -> dict:
        """运行完整评估套件，返回汇总报告"""
        results = [self.run_eval(c, ...) for c in self.cases]
        return {
            "suite": suite_name,
            "timestamp": now_iso(),
            "total": len(results),
            "skill_match_rate": mean(r.skill_match for r in results),
            "task_completion_rate": mean(r.task_complete for r in results),
            "avg_tool_accuracy": mean(r.tool_sequence_accuracy for r in results),
            "avg_duration_ms": mean(r.duration_ms for r in results),
            "avg_judge_score": mean(r.judge_score for r in results if r.judge_score),
            "failures": [r for r in results if not r.task_complete],
        }
    
    def _llm_judge_sql_quality(self, query, sql, output) -> tuple[float, str]:
        """
        LLM-as-Judge：评估生成 SQL 的语义质量
        使用内网 LLM（不外发数据内容，只发 schema + SQL）
        
        评估维度：
        1. 表名/列名是否与数据字典一致（不使用物理列名作为语义名）
        2. 聚合逻辑是否符合查询意图
        3. WHERE 条件是否合理（不过滤掉应该包含的数据）
        4. 是否有 LIMIT 限制
        """
        prompt = f"""
你是 DataAgent 的 SQL 质量评估员。评估以下 SQL 是否正确回答了用户的问题。

数据字典（语义字段映射）:
{self._get_relevant_dict_context(sql)}

用户问题: {query}
生成的 SQL: {sql}

请评分（0-1）并说明理由，重点检查：
1. 是否正确使用了数据字典中的物理列名
2. 聚合函数和 GROUP BY 是否匹配问题意图
3. 结果样本是否符合预期

返回 JSON: {{"score": 0.0-1.0, "reasoning": "..."}}
"""
        # 注意：只发送 schema 和 SQL，不发送数据内容
        return self.llm.call_judge(prompt)
```

#### 4.3 预置评估用例集 — `tests/eval_cases/`

```yaml
# tests/eval_cases/basic_sql.yaml
cases:
  - case_id: "sql_001"
    user_query: "查询所有持仓的总市值"
    expected_skill: null
    expected_tool_sequence: ["profile_table", "run_sql"]
    expected_outcome: "success"
    tags: ["sql", "aggregation"]
  
  - case_id: "concentration_001"  
    user_query: "查看今日主体集中度"
    expected_skill: "concentration_monitor"
    expected_tool_sequence: ["entity_concentration"]
    expected_outcome: "success"
    tags: ["calculator", "compliance"]

  - case_id: "recovery_001"
    user_query: "查询不存在表的数据"
    expected_skill: null
    expected_tool_sequence: ["profile_table"]
    expected_outcome: "ask_user"  # 应该向用户确认，而非崩溃
    tags: ["error_recovery"]
```

#### 4.4 生产监控端点 — `api/system_api.py` 新增

```python
@system_bp.route('/api/eval/stats', methods=['GET'])
def api_eval_stats():
    """
    返回执行质量统计（读取 ExecutionTracker 数据）
    控制工程意义：这是"反馈回路的读取端"
    """
    tracker = get_tracker()
    days = int(request.args.get('days', 7))
    stats = tracker.get_stats(days=days)
    signals = tracker.get_degradation_signals()
    
    return jsonify({
        "period_days": days,
        "task_completion_rate": stats["completion_rate"],
        "avg_turns_per_task": stats["avg_turns"],
        "fast_path_rate": stats["fast_path_pct"],
        "tool_error_rate": stats["tool_error_rate"],
        "most_used_skills": stats["top_skills"],
        "most_common_errors": stats["top_errors"],
        "degradation_signals": signals,  # 近7天 vs 近1天对比
        "alert_level": _compute_alert_level(signals),  # "ok"|"warn"|"alert"
    })

@system_bp.route('/api/eval/run', methods=['POST'])
def api_eval_run():
    """手动触发评估套件（开发/测试用）"""
    suite = request.json.get('suite', 'basic')
    evaluator = get_evaluator()
    results = evaluator.run_suite(suite)
    return jsonify(results)
```

#### 4.5 退化信号告警阈值

基于控制工程稳定性分析，以下阈值触发告警：

| 指标 | 正常范围 | 警告阈值 | 告警阈值 |
|-----|---------|---------|---------|
| 任务完成率 | > 85% | 70-85% | < 70% |
| 平均轮次数 | < 5 | 5-8 | > 8（可能振荡） |
| 工具错误率 | < 15% | 15-25% | > 25% |
| p95 延迟 | < 30s | 30-60s | > 60s |
| 单任务 Token | < avg×2 | avg×2-5 | > avg×5（可能无限循环） |

#### 4.6 涉及文件

| 文件 | 变更 |
|------|------|
| `agent/eval_framework.py` | **新建** — AgentEvaluator + EvalCase + EvalResult |
| `tests/eval_cases/` | **新建** — YAML 评估用例目录（basic_sql.yaml, compliance.yaml, error_recovery.yaml） |
| `tests/test_eval_framework.py` | **新建** — 评估框架单测 |
| `api/system_api.py` | **改** — 新增 /api/eval/stats + /api/eval/run |

---

## 第五章：置信度标注机制（贯穿四个 Track）

在 SSE 事件中新增 `confidence` 字段（由 Boris Cherny 的 L1→L2→L3 阶段和 Addy Osmani 的 Three-tier boundary 共同启发）：

```python
# 固化计算结果 — 可审计（来自 calculators/，有 Hash Chain）
yield _text(summary, confidence="auditable")

# LLM SQL 查询结果 — 请校验（经过 SelfChecker，但 LLM 可能误解意图）
yield _text(data, confidence="verify")

# LLM 生成的文字说明 — AI 生成（无法独立核实）
yield _text(narrative, confidence="ai_generated")
```

前端渲染：
- `auditable` → 绿色标签 `[可审计]` + 溯源卡片（数据文件+日期+公式版本）
- `verify` → 黄色标签 `[请校验]` + "数据来源: SQL" 折叠展示
- `ai_generated` → 灰色标签 `[AI生成]`

---

## 第六章：实施顺序（三周计划）

```
Week 1: Track 1 — 内核解耦（基础，其他 Track 依赖此）
  Day 1-2: tool_registry.py + builtin_tools.py（含 ACI 加强）
  Day 3:   calculators/__init__.py 自注册 + output_tools.py
  Day 4:   tools_spec.py 瘦身 + loop.py 适配 + main.py 启动流
  Day 5:   全量测试 + 回归验证（pytest tests/ -x -q）

Week 2: Track 2 + Track 3 并行
  Day 1-2: fast_path.py（快速路径）+ loop.py D-term 集成
  Day 3:   execution_tracker.py + loop.py/fast_path.py 埋点
  Day 4-5: Skill 卡片 UI + status API + execute API
  Day 6:   置信度标注端到端联调

Week 3: Track 4 — Eval Framework（闭合反馈环）
  Day 1-2: eval_framework.py + EvalCase 数据结构 + LLM-as-judge
  Day 3:   预置评估用例（basic_sql.yaml, compliance.yaml, error_recovery.yaml）
  Day 4:   /api/eval/stats + 退化告警 + ExecutionTracker 集成
  Day 5:   运行完整评估套件 + 验证基线指标
  Day 6:   文档 + PROGRESS.md 更新 + 推送
```

---

## 第七章：验收标准

1. **Track 1 验收**：新增 calculator 只需写代码 + 注册，不改 tools_spec.py → `pytest tests/ -x` 全绿
2. **Track 2 验收（快速路径）**：触发固化计算 Skill → 响应 <1s → data/traces/ 有轨迹 JSONL → 无 LLM 调用
3. **Track 2 验收（D-term）**：模拟连续工具失败 → 第 3 次失败后触发 ask_user，而非等 MAX_TURNS 耗尽
4. **Track 3 验收**：侧边栏显示 Skill 卡片 → 数据就绪时绿色"执行"按钮 → 点击出结果
5. **Track 4 验收**：`pytest tests/test_eval_framework.py` 通过 → `/api/eval/stats` 返回有意义统计 → 运行 basic_sql 套件输出完成率指标
6. **全局回归**：`pytest tests/ -x -q` 全绿，现有对话式交互行为不变

---

## 附录 A：设计决策对照表

| 设计决策 | 支持来源 | 关键引用/理由 |
|---------|---------|-------------|
| **ToolRegistry** | Anthropic ACI | "Invest as much effort in ACI as in HCI" |
| | 工具数量研究 | "> 10-20 tools 准确率显著下降" |
| **快速路径（Workflow）** | Anthropic 5 模式 | "Use workflows for predictable, deterministic tasks" |
| | Salesforce Guided Determinism | "FSM 防止 LLM 幻觉破坏工作流" |
| **ExecutionTracker** | Boris Cherny | "You don't trust; you instrument" |
| **D-term 趋势检测** | 控制工程 PID | "导数项预测趋势，提前干预" |
| **Evaluator-Optimizer (Track 4)** | Anthropic 5 模式 | "Evaluator-optimizer: 有明确标准时的迭代改进" |
| **LLM-as-Judge** | LangSmith + Braintrust | "用强 LLM 评估弱 LLM 输出，替代昂贵人工评估" |
| **置信度标注** | Addy Osmani | "Always/Ask/Never boundary → 可审计/请校验/AI生成" |
| **Skill 卡片化** | Peter Steinberger | "优化 Skill 描述用于路由，不用于文档" |
| **四级 Eval 架构** | 控制工程可观测性 | "传感器读取反馈是闭环的必要条件" |
| **退化告警阈值** | 控制工程稳定性 | "检测 limit cycle（振荡）和 divergence（发散）" |
| **保持纯客户端** | Anthropic + Boris | "Start simple; general + real tools > narrow" |

---

## 附录 B：未采纳方向

| 方向 | 为什么现在不做 | 触发条件 |
|------|--------------|---------|
| Multi-Agent 架构 | Skill < 10，单 Agent 够用，4-220x token 代价 | Skill > 30 或单 Agent 完成率 < 45% |
| Reflexion 自动学习 | 需 1000+ trace 数据积累才有意义 | ExecutionTracker 积累足够后 |
| LLM-as-Judge 内联校验 | 每次查询增加 LLM 调用，成本高 | 探索式查询准确率 < 80% |
| 服务端 Skill 市场 | 用户 < 50，ROI 不足 | 活跃用户 > 50 + 跨团队共享需求 |
| Parallelization 模式 | 当前无并行任务需求 | 批量报告生成场景出现时 |

---

## 附录 C：控制工程 ↔ DataAgent 完整映射

| 控制工程概念 | DataAgent 实现 | 状态 |
|------------|--------------|------|
| 闭环控制 | Agent Loop（tool result → 下一轮推理） | ✅ 已实现 |
| P-term（即时纠错） | categorize_tool_error + MAX_TOOL_RETRY | ✅ 已实现 |
| I-term（跨会话积累） | BM25+SQLite 口径纠正记忆 | ⚠️ 默认关闭 |
| D-term（趋势预测） | ErrorTrendDetector | ❌ Track 2 新增 |
| 前馈控制 | Plan-Execute 规划层 | ✅ 已实现 |
| 稳定性上界 | MAX_TURNS=15, MAX_TOOL_RETRY=3 | ✅ 已实现 |
| 阻尼函数 | 三级上下文压缩 | ✅ 已实现 |
| 硬约束（限位器） | 工具过滤（fixed → 移除 run_sql） | ✅ 已实现 |
| 饱和限制 | SQLGuard LIMIT + BLOCKED_FUNCTIONS | ✅ 已实现 |
| 人工Override | ask_user + request_confirmation | ✅ 已实现 |
| 传感器（写入） | Hook系统 + SSE事件 + 运行时日志 | ✅ 已实现 |
| 传感器（读取） | ExecutionTracker + /api/eval/stats | ❌ Track 2+4 新增 |
| 控制器调整 | Eval Framework → 发现问题 → 改进 | ❌ Track 4 新增 |
| 观测器 | AgentEvaluator（4级评估） | ❌ Track 4 新增 |

---

## 第八章：现有工具链评估与补充建议

> 问题 1 的回答：当前 Agent 工具能力是否受限？哪里有缺口？

### 8.1 现有 11 个工具的全量评估

| 工具名 | 类别 | 质量评分 | 主要问题 |
|--------|------|---------|---------|
| `profile_table` | 数据剖析 | ★★★★ | 良好，是 SQL 生成前的必要前置 |
| `run_sql` | 探索查询 | ★★★★ | SQLGuard 覆盖完整，场景化过滤 |
| `run_calculator` | 固化计算 | ★★★★ | 7个计算器，口径护栏扎实 |
| `ask_user` | 人机交互 | ★★★★ | 设计合理，暂停机制完备 |
| `request_confirmation` | 人机交互 | ★★★★ | 合规场景确认节点完整 |
| `render_chart` | 可视化 | ★★★ | 支持4种图表，但无法导出CSV |
| `generate_report` | 报告生成 | ★★★ | Jinja2模板，Word导出，但报告类型枚举硬编码 |
| `read_document` | 文档解析 | ★★★ | Word/PDF/TXT 已支持，但大文件无分页读取 |
| `web_search` | 联网搜索 | ★★★ | DuckDuckGo，有合规限制，功能基础 |
| `propose_dict_entry` | 字典管理 | ★★★ | 推断流程完整，但使用频率低 |
| `confirm_dict` | 字典管理 | ★★★ | 合并逻辑清晰 |

### 8.2 确定性工具缺口（影响当前已有 Skill 的正常运行）

**缺口 1：无数据导出工具（export_data）**

现状：`position_query` Skill 的输出格式明确写有"如需完整数据请导出 Excel"，`weekly_report_generator` 需要输出 5 个 CSV 文件——但 Agent 没有任何导出工具。用户只能靠浏览器截图或手工复制表格。

建议新增工具：
```python
# 工具名：export_data
# 功能：将查询结果或计算结果导出为 CSV 文件，供用户下载
{
    "name": "export_data",
    "description": "将查询结果导出为 CSV 文件并提供下载链接。用于：用户要求导出数据、生成周报 CSV 文件、行数超过 50 行需完整数据时。",
    "parameters": {
        "table_name_or_sql": str,   # 表名或 SELECT 语句
        "filename": str,             # 输出文件名（不含扩展名）
        "encoding": str              # "utf-8-sig"（Excel兼容）| "utf-8"
    }
}
```

**缺口 2：无已加载表元数据查询工具（list_tables）**

现状：Agent 依赖系统提示中注入的 schema context 来感知已加载的表，但当会话历史较长或上下文压缩后，Agent 经常对"当前有哪些表"产生错误判断，导致 SQL 引用不存在的表名。

建议新增工具：
```python
# 工具名：list_tables  
# 功能：返回当前会话所有已加载表的元数据
{
    "name": "list_tables",
    "description": "查询当前会话已加载的所有数据表。当不确定哪些表可用、或表名记不清时，先调用此工具，再生成 SQL。",
    "parameters": {}  # 无参数
}
# 返回：[{name, type, row_count, date_tag, columns_count, loaded_at}]
```

**缺口 3：无合规告警派发工具（dispatch_alert）**

现状：`concentration_monitor` Skill 计算超标后，只在聊天窗口显示结果——没有工具将告警推送给相关人员。`tools/notify.py` 已实现 Windows toast 推送，但未暴露为 Agent 工具。

建议新增工具：
```python
# 工具名：dispatch_alert
# 功能：将合规告警通过系统通知派发
{
    "name": "dispatch_alert",
    "description": "将超标告警通过系统通知发送。仅用于集中度超标、杠杆率超标等合规监控结果经用户确认后的正式派发。",
    "parameters": {
        "alert_type": "concentration"|"leverage"|"liquidity",
        "title": str,
        "content": str,
        "severity": "warning"|"alert"
    }
}
```

### 8.3 工具能力边界评估

**Agent 现在被工具限制的具体场景**：
1. 大规模数据导出 → 无法 → 建议加 `export_data`
2. 合规告警闭环 → 无法 → 建议加 `dispatch_alert`
3. 跨会话表状态确认 → 不稳定 → 建议加 `list_tables`
4. 大文档分页读取 → `read_document` 单次 10000 字符上限 → 近期可增加 `page` 参数
5. 多维度数据透视 → 当前 SQL 工具可处理，但无 pivot 专用工具 → 暂不需要

**不应新增工具的场景**（Anthropic "避免工具膨胀"原则）：
- 日期格式转换 → 在 SQL 中处理
- 数值格式化 → 在前端渲染时处理
- 邮件发送 → 超出产品定位（不出内网）
- 数据库写入 → 严禁（只读原则）

---

## 第九章：Skills 质量评估与编排优化建议

> 问题 2 的回答：已发布 Skill 的质量如何？存在哪些编排问题？是否需要新增？

### 9.1 10 个 Skill 逐一评估

| Skill | 类型 | 质量 | 主要问题 |
|-------|------|------|---------|
| `concentration_monitor` | fixed | ★★★★★ | 设计最规范。缺：未集成 `dispatch_alert` |
| `position_query` | exploratory | ★★★★ | SQL 清晰，触发词准确。缺：导出功能缺失 |
| `flexible_stats` | exploratory | ★★★★ | @mention 集成好，SQL 模板合理 |
| `weekly_report_generator` | exploratory(C型) | ★★★★ | 5模板设计完整，字段映射详细。缺：无数据预览确认 |
| `fund_nav_report` | exploratory | ★★★ | **问题**：B类合规报告用 LLM SQL，违反固化原则 |
| `meeting_report` | exploratory | ★★★ | v3 设计丰富，动态表格复杂，LLM 执行成功率存疑 |
| `client_meeting_report` | exploratory | ★★★ | 与 `meeting_report` 高度重复，差异不明确 |
| `partnership_summary` | exploratory | ★★★ | SQL 逻辑合理，缺：合规数据无 `request_confirmation` |
| `dept_weekly_report` | exploratory | ★ | `template.md.j2` 未创建，**当前无法执行** |
| `monthly_bond_summary` | exploratory | ★ | `template.md.j2` 未创建，**当前无法执行** |

### 9.2 五个关键编排问题

**编排问题 1（严重）：两个 Skill 功能重复，路由混乱**

`meeting_report` 和 `client_meeting_report` 都生成"谈参要点"，触发词几乎相同，区别仅在于 `client_meeting_report` 的 6 步骤更结构化，`meeting_report` v3 更有集团关系树。用户触发后 Agent 可能任意选其中一个。

**建议**：合并为一个 Skill `meeting_report`，保留 v3 的完整设计，删除 `client_meeting_report`。

**编排问题 2（严重）：fund_nav_report 违反 A/B 类分离原则**

`fund_nav_report` 生成的是"运作报告"——这是 B 类合规场景，但 SKILL.md 里的执行步骤全部是 LLM 生成 SQL（包括净值指标、资产结构、评级分布）。这违反了 CLAUDE.md 的核心约束："凡结果用于合规决策或对外报告，必须走 B 类"。

**建议**：将 `fund_nav_report` 改为 `calc_type: fixed`，Steps 1-4 改为调用 `calculators/nav_metrics.py`、`calculators/asset_structure.py`、`calculators/credit_distribution.py`。

**编排问题 3（中等）：两个 Skill 无法运行（模板缺失）**

`dept_weekly_report` 和 `monthly_bond_summary` 都声明了 `template_file: template.md.j2`，但该文件未创建（等待业务方 C-02/C-03 确认）。这两个 Skill 在 Skill 卡片上会显示"可执行"，但实际触发会失败。

**建议**：在 `skill_preflight.py` 中增加模板文件存在性检查；或将这两个 Skill 的 `data_ready` 标记为 False 直到模板就绪。

**编排问题 4（中等）：partnership_summary 缺少确认节点**

`partnership_summary` 步骤 3 查询内部评级和限额数据（含"理财限额"、"已占用限额"等敏感信息），没有 `request_confirmation` 步骤。用户可能无意间让 Agent 直接输出了合规敏感数据。

**建议**：在输出"二、主体评级及限额情况"前增加 `request_confirmation` 步骤。

**编排问题 5（轻微）：weekly_report_generator 无预览确认**

生成 5 个 CSV 文件的操作是批量写入，但没有预览/确认步骤。用户无法在生成前验证数据是否正确。

**建议**：生成前用 `request_confirmation` 展示：数据行数、产品分布、5个模板的行数预览。

### 9.3 建议新增的 Skills

**新 Skill 1：`risk_dashboard`（综合风险仪表盘）**

理由：当前用户要全貌风险需依次触发 concentration_monitor + leverage + liquidity 三次，没有一键综合视图。

```yaml
name: risk_dashboard
description: 一键生成全量产品风险仪表盘：主体集中度 + 杠杆率 + 流动性风险，汇总超标情况。
触发词: 风险仪表盘、综合风险、风险全貌、整体风险、风控报告
calc_type: fixed
required_files:
  - semantic: "持仓表"
    file_pattern: "*持仓*"
optional_files:
  - semantic: "净值表"
    file_pattern: "*净值*"
执行步骤:
  1. 数据时效检查
  2. 并行调用三个计算器（entity_concentration + leverage + liquidity）
  3. 汇总超标清单，按严重程度排序
  4. 生成"风险仪表盘"报告（三合一视图）
  5. 如有超标，询问是否派发告警（dispatch_alert）
```

**新 Skill 2：`maturity_alert`（近期到期预警）**

理由：现有工具链可以查持仓，但没有"X天内到期"的预警视角。固定收益管理中这是高频需求。

```yaml
name: maturity_alert
description: 查询指定天数内（默认30天）到期的债券持仓，按产品和到期日排序展示。
触发词: 到期预警、近期到期、即将到期、到期安排、债券到期
calc_type: exploratory
required_files:
  - semantic: "持仓表"
    file_pattern: "*持仓*"
```

**新 Skill 3：`product_comparison`（产品横向对比）**

理由：`flexible_stats` 适合单维度统计，但用户常需"A产品 vs B产品的净值/规模/持仓对比"，需要跨表的横向比较视图。

```yaml
name: product_comparison
description: 横向对比多个产品的净值表现、资产结构、集中度等核心指标。
触发词: 产品对比、横向比较、对比分析、比较XX和XX
calc_type: exploratory
optional_files:
  - semantic: "持仓表"
  - semantic: "净值表"
```

---

## 第十章：任务执行仪表盘 — Agent 状态透明化

> 问题 3 的回答：如何实现"汽车仪表盘"式的实时任务流程可视化

### 10.1 设计理念与定位

用户需求：**在任务等待和完成后，随时可以看到任务执行的完整步骤推进情况，像汽车仪表盘一样透明且有体验感。**

核心差异点（与现有 Process Wrapper 对比）：

| 维度 | 现有 Process Wrapper | 任务仪表盘（新） |
|------|---------------------|----------------|
| 生命周期 | 流式期间存在，完成后消失 | **持久存在**，完成后仍可回顾 |
| 视图范围 | 步骤级别（逐行追加） | **全局任务级别**（完整流程鸟瞰） |
| 数据源可视化 | 无 | **数据源点亮**（使用时高亮） |
| 动画效果 | 简单图标切换 | **流程动画**（步骤推进动效） |
| 位置 | 嵌入聊天消息流内 | **独立悬浮面板**，不影响对话区 |

### 10.2 视觉设计方案

**布局**：右侧滑出面板（默认收起，任务开始时自动展开）

```
┌──────────────────────────────────┐
│ ⚙ 任务执行仪表盘          ↘ 收起 │
├──────────────────────────────────┤
│  Skill: concentration_monitor    │
│  ▓▓▓▓▓▓▓▓░░░░  66% · 用时 2.1s  │
├──────────────────────────────────┤
│ 执行步骤                          │
│ ✓ 数据时效验证          0.3s     │
│ ◉ 计算主体集中度...   ←(动画)    │  ← 当前步：脉冲蓝色边框
│ ○ 生成监控报告                   │
│ ○ 写入审计日志                   │
├──────────────────────────────────┤
│ 数据源                            │
│ 💡 holding_20260515  ← (高亮)   │  ← 正在使用，蓝色发光
│ ○  groups.yaml                   │
├──────────────────────────────────┤
│ 工具调用  ⚡run_calculator       │
│ [可审计] entity_concentration    │
│ 触发: 13:42:07 | 耗时: 1.8s     │
└──────────────────────────────────┘
```

**动画规格**：
- 当前步骤：CSS `box-shadow` 脉冲动画（0.8s 循环）
- 步骤完成：绿色 checkmark 淡入 + 耗时数字滚动出现
- 数据源点亮：蓝色 `glow` 动画 1s 后渐消（表示已访问但非持续占用）
- 进度条：线性 transition，按完成步骤数 / 总步骤数推进
- 面板滑入：从右侧 transform: translateX(100%) → 0，0.25s ease-out

### 10.3 技术实现方案

**核心设计原则**：**复用现有 SSE 事件，零后端改动（Task 1），后端增强可选（Task 2）**。

**Task 1（纯前端，无需改后端）**：
- 消费现有 `plan` / `plan_step` / `tool_start` / `tool_end` 事件
- 从 `plan` 事件中提取步骤列表
- 从 `tool_start` args 中推断使用的数据源（e.g., `holding_table` 字段）
- 面板随 `plan` 事件自动滑入，随 `stream_end` 进入"已完成"冻结态

**Task 2（可选后端增强，效果更好）**：
- 增强 `plan` SSE 事件，增加 `data_sources` 字段（预告将用到哪些数据源）
- 修改 `agent/planner.py` 的 `build_plan()` 返回中加入已加载表名列表

**新增文件**：
```
ui/js/dashboard.js     ← 仪表盘模块（~150行）
```

**修改文件**：
```
ui/index.html          ← 仪表盘面板 HTML + CSS（~60行，右侧抽屉）
ui/js/main.js          ← import dashboard + 初始化
ui/js/chat.js          ← handleChunk 中将 plan/plan_step/tool_start/tool_end 转发给 dashboard
agent/planner.py       ← build_plan() 返回增加 data_sources 字段（可选）
```

**dashboard.js 核心逻辑**：
```javascript
// ui/js/dashboard.js
const Dashboard = {
    panel: null,    // DOM: #task-dashboard
    steps: [],      // {id, name, objective, status, duration_ms}
    dataSources: [], // {name, type, lit: false}
    startTime: null,
    
    init() {
        this.panel = document.getElementById('task-dashboard');
    },
    
    // 收到 plan 事件时初始化仪表盘
    onPlan(data) {
        this.steps = data.steps.map(s => ({...s, status: 'pending'}));
        this.dataSources = (data.data_sources || []).map(n => ({name: n, lit: false}));
        this.startTime = Date.now();
        this._render();
        this._slideIn();  // 自动弹出
    },
    
    // 收到 plan_step 时更新步骤状态
    onPlanStep(data) {
        const step = this.steps.find(s => s.id === data.step_id);
        if (step) {
            step.status = data.status;  // running/done/failed
            step.duration_ms = data.duration_ms;
        }
        this._renderSteps();
        this._updateProgress();
    },
    
    // 收到 tool_start 时点亮数据源
    onToolStart(data) {
        // 从 tool 参数中提取表名
        const tableName = data.args?.holding_table || data.args?.table_name;
        if (tableName) this._lightUpSource(tableName);
        this._renderToolIndicator(data);
    },
    
    // 收到 stream_end 时冻结面板
    onStreamEnd() {
        this._freeze();  // 停止动画，保留结果
        this._showReviewHint();  // 显示"点击可回顾"提示
    },
    
    _slideIn() { this.panel.classList.add('visible'); },
    _slideOut() { this.panel.classList.remove('visible'); },
    _freeze() { this.panel.classList.add('frozen'); },
    _lightUpSource(name) {
        const src = this.dataSources.find(s => s.name === name);
        if (src) { src.lit = true; this._renderSources(); }
    },
    
    // ...渲染函数
};
```

**CSS 关键样式**：
```css
/* 右侧抽屉式仪表盘 */
#task-dashboard {
    position: fixed;
    right: 0; top: 48px; bottom: 0;
    width: 260px;
    background: var(--bg-secondary);
    border-left: 1px solid var(--border);
    transform: translateX(100%);
    transition: transform 0.25s ease-out;
    z-index: 200;
    overflow-y: auto;
}
#task-dashboard.visible { transform: translateX(0); }

/* 当前步骤脉冲动画 */
.dash-step.running {
    border: 1px solid #3b82f6;
    animation: pulse-step 0.8s ease-in-out infinite;
}
@keyframes pulse-step {
    0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
    50% { box-shadow: 0 0 0 6px rgba(59, 130, 246, 0); }
}

/* 数据源点亮效果 */
.data-source.lit {
    color: #3b82f6;
    animation: glow-source 1s ease-out forwards;
}
@keyframes glow-source {
    0% { text-shadow: 0 0 8px rgba(59, 130, 246, 0.8); }
    100% { text-shadow: none; }
}
```

### 10.4 触发逻辑（无 Plan 时的降级）

对于不经过 Plan-Execute 的简单任务：
- 仪表盘显示轻量版：仅工具调用列表（复用现有 Process Wrapper 数据）
- 不自动弹出，用户可通过 Header 按钮手动打开
- 对话完成后面板显示"此次任务未生成执行计划（直接回答）"

### 10.5 涉及文件

| 文件 | 变更 | 工作量 |
|------|------|--------|
| `ui/js/dashboard.js` | **新建** — 仪表盘模块 ~150行 | 2天 |
| `ui/index.html` | **改** — 右侧面板HTML + CSS + Header切换按钮 | 0.5天 |
| `ui/js/main.js` | **改** — import Dashboard + 初始化 | 0.5天 |
| `ui/js/chat.js` | **改** — handleChunk 转发事件给 Dashboard | 0.5天 |
| `agent/planner.py` | **改（可选）** — plan事件增加data_sources字段 | 0.5天 |

---

## 第十一章：实施顺序更新（综合四个新增章节后）

### 整体时间线（3.5 周）

```
Week 1: Track 1 (ToolRegistry + ACI 加强)
  Day 1-2: tool_registry.py + builtin_tools.py（含 ACI 加强描述）
  Day 3:   calculators/__init__.py + output_tools.py（含 export_data, list_tables, dispatch_alert 新工具）
  Day 4:   tools_spec.py 瘦身 → loop.py 适配 → main.py 启动注册流
  Day 5:   全量测试 pytest tests/ -x -q

Week 2: Track 2+3（双通道 + Skill 卡片 + Skills 修复）
  Day 1-2: fast_path.py + D-term 趋势检测集成
  Day 3:   execution_tracker.py + 埋点
  Day 4:   Skill 卡片 UI + status/execute API
  Day 5:   Skills 编排问题修复（合并 meeting_report + fund_nav_report 改固化）
  Day 6:   置信度标注 + 端到端联调

Week 3: Track 4 + Track 5（Eval Framework + 任务仪表盘）
  Day 1-2: eval_framework.py + 预置评估用例（basic_sql/compliance/error_recovery）
  Day 3:   /api/eval/stats + 退化告警 + ExecutionTracker 集成
  Day 4-5: dashboard.js + index.html 面板 + chat.js 事件转发
  Day 6:   planner.py 增强（data_sources）+ 仪表盘完整联调

Week 4 (0.5天): Skills 新增 + 文档
  risk_dashboard Skill + maturity_alert Skill
  更新 PROGRESS.md / HANDOFF.md / CLAUDE.md
  git push to claude/sleepy-cori-5b5xow
```

### 优先级矩阵

| 项目 | 价值 | 工作量 | 优先级 |
|------|------|--------|--------|
| Track 1 (ToolRegistry) | ★★★★★ 架构基础 | 中 | P0 必做 |
| Track 2 (快速路径) | ★★★★★ 性能+安全 | 中 | P0 必做 |
| Track 3 (Skill卡片) | ★★★★ UX提升 | 小 | P1 优先 |
| Track 4 (Eval) | ★★★★ 质量闭环 | 中 | P1 优先 |
| **Track 5 (仪表盘)** | **★★★★ 体验差异化** | **中** | **P1 优先** |
| export_data 工具 | ★★★★ 补齐功能缺口 | 小 | P1 优先 |
| list_tables 工具 | ★★★ 减少Agent幻觉 | 小 | P1 优先 |
| dispatch_alert 工具 | ★★★ 合规闭环 | 小 | P2 |
| Skills 编排修复 | ★★★★ 合规正确性 | 中 | P1 优先 |
| risk_dashboard Skill | ★★★ 高频需求 | 小 | P2 |
| maturity_alert Skill | ★★★ 高频需求 | 小 | P2 |
| product_comparison Skill | ★★ 扩展需求 | 中 | P3 |

---

## GitHub 文档推送计划

本方案将在 ExitPlanMode 批准后，将以下文档推送至 `docs/` 目录（branch: `claude/sleepy-cori-5b5xow`）：

**文件**：`docs/v3-architecture-evolution.md`

**内容**：本计划文件的完整内容，格式化为独立可读的架构演进文档，包含：
- 五个根本性问题的背景
- 控制工程视角分析（PID映射、稳定性、可观测性）
- 四个演进轨道（ToolRegistry/双通道/Skill卡片/Eval框架）
- 工具链评估与三个新工具
- 10个Skill质量评估与编排问题
- 任务仪表盘设计方案
- 实施时间线与优先级矩阵

---

## 附录 D：Anthropic 五种 Workflow 模式完整参考

（来源：Erik Schluntz & Barry Zhang, Anthropic, 2024.12）

| 模式 | 何时使用 | DataAgent 中的体现 |
|-----|---------|-----------------|
| **Prompt Chaining** | 固定步骤的顺序执行，有 pass/fail 门控 | 各 Skill 的多步执行 |
| **Routing** | 不同类别输入需差异化处理 | Skill 匹配 → Track 1 ToolRegistry |
| **Parallelization（Sectioning）** | 独立子任务并行 | 未来批量报告 |
| **Parallelization（Voting）** | 相同任务多次运行取共识 | 未来高置信度合规决策 |
| **Orchestrator-Workers** | 子任务在运行时才能确定 | Plan-Execute（planner + executor） |
| **Evaluator-Optimizer** | 有明确评估标准的迭代优化 | **Track 4 Eval Framework** |

Anthropic 关键提醒：
> "Start by using LLM APIs directly. Many patterns can be implemented in a few lines of code. Only use frameworks if they demonstrably improve outcomes — they add abstraction that makes debugging harder."
