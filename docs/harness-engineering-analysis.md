# DataAgent Harness Engineering 分析与改进方案

> 基于 Agent Harness Engineering 理论体系（ETCLOVG 七层分类法）、
> Claude Code 架构实践（六层 Harness + 七重安全层）、
> OpenClaw 架构设计（Gateway + Node-Host + Agent Runtime），
> 对 DataAgent 当前架构做逐层对标评估，给出必须改进的内容和实施方案。
>
> 分析日期：2026-06-06

---

## 一、Agent Harness Engineering 理论框架

### 1.1 什么是 Agent Harness

> "Harness engineering is the discipline of designing the scaffolding—context delivery, tool interfaces, planning artifacts, verification loops, memory systems, and sandboxes—that surrounds an AI agent and determines whether it succeeds or fails on real tasks."

**核心洞见**：Agent 的能力 = 模型推理能力 × Harness 工程质量。Harness 是模型和真实世界之间的全部基础设施——它决定模型的文本输出能「触达」什么。Claude Code 的 ~512K 行代码中，98.4% 是确定性基础设施，仅 1.6% 涉及 AI 决策逻辑。

**第一性原理**：Harness 的每个组件之所以存在，是因为模型自身无法完成该功能。随着模型能力提升，某些组件会变得不必要——但工程师必须主动设计这些组件，而非假设模型会自行解决。

### 1.2 ETCLOVG 七层分类法

学术界（2026年 TMLR 综述论文）提出的系统性分层：

| 层 | 名称 | 职责 |
|----|------|------|
| **E** | Execution（执行环境） | 沙箱、文件系统隔离、进程管理、资源限制 |
| **T** | Tools（工具接口） | 工具定义、Schema 校验、注册发现、分发执行 |
| **C** | Context（上下文管理） | Token 预算、分层检索、压缩/裁剪、渐进加载 |
| **L** | Lifecycle/Orchestration（生命周期编排） | Agent 循环、状态机、规划-执行分离、检查点恢复 |
| **O** | Observability（可观测性） | 决策日志、Token 追踪、成本归因、异常检测 |
| **V** | Verification（验证反馈） | 结果校验、自省机制、防幻觉检查、评估基准 |
| **G** | Governance（治理约束） | 权限模型、审批流、合规审计、数据安全策略 |

前四层（E/T/C/L）是结构核心，后三层（O/V/G）是控制平面。

### 1.3 关键设计模式

从 Claude Code 和 OpenClaw 的实践中提炼出的关键模式：

1. **Permission as Architecture**：权限是架构问题（hook pipeline + deny-by-default），不是 prompt 问题
2. **Context as Navigation**：把上下文当作导航问题（索引 + 按需检索），而非压缩问题（全量注入）
3. **Eager Scaffolding**：在第一条消息之前就初始化全部组件（文件系统 + 沙箱 + 内存 + 上下文）
4. **Harness Before Model**：Harness 改进带来的性能提升往往超过模型能力提升
5. **Skills as Trainable Artifacts**：Skill 是可版本化、可优化的工件，不是写一次就不管的文档
6. **Compound Multi-Model**：不同角色用不同模型实例（执行/推理/批判/视觉），而非一个模型承担一切
7. **Memory Decoupling**：三级内存分离——工作内存（活跃上下文）/ 归档内存（长期存储）/ 召回内存（检索增强）

---

## 二、标杆系统架构分析

### 2.1 Claude Code 的六层 Harness

```
┌─ 用户接口层 ─────────────────────────────────────────┐
│  CLI / SDK / IDE Extension                           │
├─ Agent 循环层 ───────────────────────────────────────┤
│  queryLoop (AsyncGenerator)                          │
│  9 步流水线：设置→状态→上下文→5 级压缩→模型→工具→权限→执行→终止检查  │
├─ 权限系统层 ─────────────────────────────────────────┤
│  7 种权限模式：plan→default→acceptEdits→auto(ML)→dontAsk→bypass │
│  7 重安全层：工具预过滤→Hook→Deny 规则→Handler→边界→沙箱→拦截    │
├─ 工具层 ─────────────────────────────────────────────┤
│  54 个内置工具 + MCP 外部工具                         │
│  5 步工具池组装：枚举→模式过滤→Deny 过滤→MCP 集成→去重   │
├─ 状态与持久化层 ──────────────────────────────────────┤
│  JSONL 追加式会话记录 + 文件历史检查点 + Subagent 侧链  │
│  4 级 CLAUDE.md 层次：系统→用户→项目→本地             │
├─ 执行环境层 ─────────────────────────────────────────┤
│  Shell 沙箱 + 文件系统隔离 + 进程恢复                 │
└──────────────────────────────────────────────────────┘
```

**关键设计决策**：
- **上下文压缩 5 级流水线**（从廉到贵依次执行）：Budget Reduction → Snip → Microcompact → Context Collapse → Auto-Compact。100 轮对话实测压缩 84%
- **Hook 系统**：27 个生命周期事件，在 Agent 循环的三个注入点（assemble/model/execute）触发
- **四种扩展机制**（按上下文成本排序）：Hooks（零成本零上下文）→ Skills（低成本注入当前上下文）→ Plugins（中成本注册组件）→ MCP Servers（高成本外部进程）
- **Subagent 隔离**：侧链转录——只有摘要返回父级，保护父级上下文不被子级内容淹没

### 2.2 OpenClaw 的 Gateway-Node 架构

```
┌─ Channel 接入层 ─────────────────────────────────────┐
│  Slack / Discord / Telegram / Web / API              │
├─ Gateway 控制平面 ────────────────────────────────────┤
│  会话生命周期 + 工具分发 + Channel 路由 + Agent 编排     │
│  WebSocket + HTTP 多路复用，单端口                     │
├─ Agent Runtime ──────────────────────────────────────┤
│  多轮推理循环：历史 + 系统提示 → 生成 tool_calls →     │
│  顺序执行 → 更新上下文 → 重复直到纯文本响应终止          │
├─ Plugin & Skills ────────────────────────────────────┤
│  可热加载的能力模块 + 配置驱动的角色定义                 │
├─ Memory & Knowledge ─────────────────────────────────┤
│  持久化本地记忆 + 角色配置 + 行为定义                   │
├─ Node-Host 执行层 ───────────────────────────────────┤
│  设备节点（macOS/iOS/Android）WebSocket 连接            │
│  本地能力暴露为远程可调用工具（相机/屏幕/通知）          │
├─ LLM Provider ───────────────────────────────────────┤
│  统一 Provider 接口，支持任意 LLM 后端                 │
└──────────────────────────────────────────────────────┘
```

**关键设计决策**：
- **多级策略级联**：权限从 global → provider → agent → session → sandbox 五级策略逐级覆盖
- **统一 Provider 接口**：任意 LLM 后端可插拔
- **跨设备工具暴露**：本地设备能力通过 WebSocket 注册为 Agent 可调用工具
- **A2A 协议桥**：Agent-to-Agent 通信通过 Agent Card 服务发现

---

## 三、DataAgent 逐层对标评估

用 ETCLOVG 七层框架逐层评估 DataAgent 当前状态：

### E 层：执行环境 — ⚠️ 基本可用但需加固

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 沙箱隔离 | Shell 沙箱 + 文件系统隔离 | sandbox 策略 + Node-Host 隔离 | DuckDB 只读 SELECT + SQLGuard | SQL 层面隔离足够，但无进程级沙箱 |
| 资源限制 | 进程恢复 + 内存管理 | 容器化 | `max_memory=200MB, threads=2` | ✅ DuckDB 有硬限制 |
| 错误恢复 | 检查点恢复 + 文件历史回滚 | 会话恢复 | 错误分类自愈（syntax/semantic/empty/anomaly） | ❌ 无检查点恢复机制 |

**必须改进**：
1. **Agent 循环检查点**：当前 `agent/loop.py` 的 `ask_user`/`request_confirmation` 暂停机制已初步实现状态持久化，但缺少 Agent 异常中断后的恢复——应支持从最后一个成功步骤续跑
2. **工具执行超时统一化**：`query_runner` 有 30 秒超时，但其他工具（profiler、calculator）没有超时保护

### T 层：工具接口 — ⚠️ 结构正确但缺少关键设计

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 工具数量 | 54 内置 + MCP 外部 | Plugin 热加载 | 7 个硬编码 | 数量够用，但缺扩展机制 |
| Schema 校验 | 工具输入参数类型校验 | JSON Schema | 无——LLM 返回的 args 直接传给 handler | ❌ **高风险** |
| 工具池组装 | 5 步：枚举→过滤→Deny→MCP→去重 | 策略级联 | 全部工具始终可用 | ❌ 缺少按场景过滤 |
| 结构化返回 | 类型化返回值 | JSON | dict 返回 `{"ok": bool, ...}` | ⚠️ 格式统一但无类型校验 |
| 工具分发 | 注册表 + 安全门 | Gateway 分发 | `dispatch_map` 字典直接映射 | ⚠️ 简单但够用 |

**必须改进**：
1. **工具输入参数校验**：当前 LLM 返回的 `arguments` JSON 直接传给 handler，没有任何 Schema 校验。如果 LLM 返回错误类型或缺少必填字段，会产生不可预期的运行时错误。必须在 `dispatch_tool` 层添加参数校验
2. **场景化工具过滤**：合规场景应只暴露 `run_calculator`（不暴露 `run_sql`）；探索场景应暴露 `run_sql`（不强推 `run_calculator`）。当前全部 7 个工具始终全部暴露给 LLM，浪费 token 且增加误用风险
3. **工具结果标准化**：`ToolResult` dataclass 替代松散 dict，确保每个工具返回一致的结构

### C 层：上下文管理 — ❌ 最大短板

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 上下文压缩 | 5 级流水线（84% 压缩率） | 会话窗口管理 | **无压缩** | ❌ **严重不足** |
| 分层检索 | 按需工具检索 + Subagent 隔离 | 层级记忆 | `build_schema_context()` 全量注入所有表的全部列名 | ❌ 全量注入浪费 token |
| Token 预算管理 | 显式预算分配 + 压缩触发 | 窗口限制 | `context_budget_ratio: 0.75` 配置存在但未实现 | ❌ 配置了但未使用 |
| 指令层次 | 4 级 CLAUDE.md（系统→用户→项目→本地） | 角色配置 | 单一 system_prompt + skill 内容 | ⚠️ 功能够用 |

**必须改进**：
1. **上下文压缩管线**：当前 `agent/context.py` 的 `build_schema_context()` 把所有已加载表的全部列名一次性注入 system prompt。5-10 张表、每张 50+ 列时，仅 schema 就消耗数千 token。必须实现：
   - **渐进式 schema 注入**：只注入当前相关表的 schema，其他表仅显示名称
   - **历史消息压缩**：对话超过 N 轮时，对早期消息做摘要压缩
   - **工具结果截断**：大表查询结果在注入 messages 前截断为关键统计
2. **Token 预算管理**：`config.yaml` 中已有 `context_budget_ratio: 0.75` 但代码中未使用。应在每轮 LLM 调用前估算当前 token 占用，超预算时触发压缩

### L 层：生命周期编排 — ⚠️ 基础完整但缺规划层

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| Agent 循环 | 9 步流水线 AsyncGenerator | 多轮推理循环 | `run_agent_loop` Generator + MAX_TURNS=15 | ✅ 基本完整 |
| 规划层 | Plan 模式 + Subagent 委派 | 无显式规划 | **无规划层** | ❌ 复杂任务完成率低 |
| 暂停/续跑 | Session 持久化 + 恢复 | 会话恢复 | `ask_user`/`request_confirmation` 暂停机制 | ✅ 已实现 |
| 子任务委派 | 6 种 Subagent + 侧链隔离 | Plugin 调度 | 无 Subagent | ⚠️ 当前规模不需要 |
| Skill 路由 | SkillTool（注入上下文）vs AgentTool（隔离上下文） | Plugin 热加载 | `skill_loader` 渐进加载 + 关键词匹配 | ⚠️ 路由精度待提升 |

**必须改进**：
1. **Plan-Execute 双层架构**：详见 evolution-roadmap.md I-8 章节。复杂任务（参谈要点、运作报告）需要先分解为步骤，再逐步执行
2. **Skill 路由精度**：当前用关键词匹配 Skill，应升级为 LLM 意图分类（CLAUDE.md 已设计但未实现）

### O 层：可观测性 — ⚠️ 有基础但不完整

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 决策日志 | 27 个 Hook 事件 + 审计追踪 | Gateway 日志 | `runtime_logger.py` basic/detailed 两级 | ✅ 结构正确 |
| Token 追踪 | 每次调用记录 token_count | Provider 层统计 | `llm_client.py` 记录 `elapsed_ms` + `token_count` | ⚠️ 有记录但无累计统计和预算控制 |
| 成本归因 | 按操作类型归因 | 无 | **无** | ❌ 无 LLM 成本追踪 |
| 异常检测 | 结构化异常分类 + 恢复 | 错误上报 | `error_translator.py` 用户侧翻译 | ⚠️ 有翻译但无趋势监控 |
| Hook 事件 | 27 种生命周期事件 | Channel 事件 | 无 Hook 系统 | ❌ 缺少可编程扩展点 |

**必须改进**：
1. **LLM 成本追踪**：在 `runtime_logger` 中增加 token 累计统计、每日/每会话成本概算
2. **生命周期 Hook 系统**：不需要 Claude Code 级别的 27 种事件，但至少需要：
   - `on_session_start` / `on_session_end`
   - `pre_tool_use` / `post_tool_use`
   - `on_error`
   - `on_data_load` / `on_data_unload`
   
   Hook 使得用户可以在不修改核心代码的情况下添加自定义行为（如：加载数据后自动运行质量检查）

### V 层：验证反馈 — ❌ 严重不足

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 结果校验 | Subagent Verifier + 评估循环 | 无显式验证 | **无** | ❌ Agent 结果无自检 |
| 防幻觉 | 上下文验证 + 工具约束 | 无 | SQLGuard 防 SQL 幻觉 | ⚠️ SQL 层有，计算层无 |
| 数值合理性检查 | 无内置 | 无 | **无** | ❌ 合规场景高风险 |
| 自省机制 | Extended Thinking + 多轮修正 | 无 | `MAX_TOOL_RETRY=3`（仅 SQL 语法错自愈） | ⚠️ 仅覆盖语法错误 |

**必须改进**：
1. **Agent 结果自检（SelfChecker）**：对 `run_calculator` 返回的合规计算结果做数值合理性校验：
   - 集中度不应超过 100%
   - 收益率不应超过 ±50%（日度）
   - 市值不应为负数
   - 产品数量应与 `config.yaml` 中 `managed_products` 列表对齐
2. **计算口径一致性校验**：与历史计算结果对比，发现异常偏差时告警

### G 层：治理约束 — ⚠️ 领域特色但需结构化

| 维度 | Claude Code | OpenClaw | DataAgent 现状 | 差距 |
|------|------------|----------|---------------|------|
| 权限模型 | 7 种模式 + ML 分类器 | 5 级策略级联 | A/B 类分离（探索式/固化计算） | ✅ 领域适配设计 |
| 审批流 | 人工确认 + deny-and-continue | Session 级策略 | `request_confirmation` 暂停机制 | ✅ 已实现 |
| 合规审计 | 加密签名审计记录 | 无 | `compliance_audit.py` JSONL 记录 | ⚠️ 有但无完整性保护 |
| 数据安全 | 沙箱 + 权限门 | sandbox 策略 | report_text 禁 fallback + SQL 只读 | ✅ 合规约束到位 |
| 工具级权限 | deny-first + 预过滤 | 策略级联 | 无工具级权限 | ❌ 全部工具始终可用 |

**必须改进**：
1. **场景化工具权限**：当 Skill 的 `calc_type=fixed` 时，应自动隐藏 `run_sql` 工具——从 LLM 的工具列表中移除，而非依赖 prompt 告诉它"不要用"
2. **审计日志完整性**：当前 JSONL 追加写入，无防篡改机制。建议添加简单的 hash chain（每条日志包含前一条的 hash），确保可追溯

---

## 四、必须改进清单（按优先级排序）

综合七层评估，DataAgent **必须改进的 10 个项目**：

### P0：立即改进（影响 Agent 可靠性和安全性）

#### 1. 工具输入参数校验 [T 层]
**问题**：LLM 返回的 `arguments` JSON 直接传给 handler，无 Schema 校验。
**改进**：在 `dispatch_tool()` 中添加参数校验层。

```python
# agent/tools_spec.py 修改

def _validate_tool_args(name: str, args: dict) -> tuple[bool, str]:
    """校验工具参数是否符合 Schema"""
    schema = _get_tool_schema(name)
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    
    for field in required:
        if field not in args:
            return False, f"缺少必填参数：{field}"
    
    for field, value in args.items():
        if field in properties:
            expected_type = properties[field].get("type")
            if expected_type == "string" and not isinstance(value, str):
                return False, f"参数 {field} 应为字符串，实际为 {type(value).__name__}"
            if expected_type == "array" and not isinstance(value, list):
                return False, f"参数 {field} 应为数组，实际为 {type(value).__name__}"
            if "enum" in properties[field] and value not in properties[field]["enum"]:
                return False, f"参数 {field} 的值 '{value}' 不在允许范围内"
    
    return True, ""

def dispatch_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    valid, error = _validate_tool_args(name, args)
    if not valid:
        return {"ok": False, "error": f"参数校验失败：{error}"}
    # ... 原有逻辑
```

**影响文件**：`agent/tools_spec.py`
**工作量**：0.5 天

#### 2. 上下文压缩管线 [C 层]
**问题**：`build_schema_context()` 全量注入所有表所有列名，5-10 张表时消耗数千 token。
**改进**：三级压缩策略。

```python
# agent/context.py 修改

def build_schema_context(relevant_tables: list[str] = None) -> str:
    """
    三级压缩：
    Level 1: 相关表 → 完整列名 + 类型 + 映射
    Level 2: 其他已加载表 → 仅名称 + 行数 + 表类型
    Level 3: 使用 profile_table 工具按需获取详情（不注入 system prompt）
    """

def compress_messages(messages: list, max_tokens: int) -> list:
    """
    历史消息压缩：
    - 保留最近 N 轮完整消息
    - 早期消息压缩为摘要（保留 tool_calls 结构，压缩内容）
    - 工具结果超过 500 字符的截断为统计摘要
    """
```

**影响文件**：`agent/context.py`、`agent/loop.py`
**工作量**：2 天

#### 3. Agent 结果自检 [V 层]
**问题**：`run_calculator` 结果直接展示给用户，无数值合理性校验。
**改进**：添加 `SelfChecker` 后置校验。

```python
# agent/self_check.py 新建

class SelfChecker:
    RULES = {
        "entity_concentration": [
            ("concentration_pct", 0, 100, "集中度应在 0-100% 之间"),
            ("market_value", 0, None, "市值不应为负数"),
        ],
        "nav_metrics": [
            ("return_7d", -20, 20, "7日收益率异常（超出±20%）"),
            ("unit_nav", 0.5, 3.0, "单位净值异常（超出0.5-3.0范围）"),
        ],
    }
    
    def check(self, calculator: str, results: list[dict]) -> list[str]:
        """返回告警列表，空列表表示通过"""
        warnings = []
        rules = self.RULES.get(calculator, [])
        for r in results:
            for field, min_val, max_val, msg in rules:
                val = r.get(field)
                if val is not None:
                    if min_val is not None and val < min_val:
                        warnings.append(f"⚠️ {msg}：{field}={val}")
                    if max_val is not None and val > max_val:
                        warnings.append(f"⚠️ {msg}：{field}={val}")
        return warnings
```

**影响文件**：新建 `agent/self_check.py`，修改 `agent/tools_spec.py` 的 `_tool_run_calculator`
**工作量**：1 天

#### 4. 场景化工具过滤 [T+G 层]
**问题**：全部 7 个工具始终暴露给 LLM，合规场景下 `run_sql` 不应出现。
**改进**：根据匹配到的 Skill 的 `calc_type` 动态过滤工具列表。

```python
# agent/loop.py 修改

def _filter_tools_for_context(tools: list, matched_skill: SkillInfo | None) -> list:
    """根据场景过滤工具列表"""
    if matched_skill and matched_skill.calc_type == "fixed":
        # 合规场景：隐藏 run_sql，只保留 run_calculator + ask_user + request_confirmation
        return [t for t in tools if t["function"]["name"] != "run_sql"]
    return tools
```

**影响文件**：`agent/loop.py`
**工作量**：0.5 天

### P1：近期改进（提升 Agent 能力和工程质量）

#### 5. 生命周期 Hook 系统 [O 层]
**问题**：无可编程扩展点，用户无法在不修改核心代码的情况下添加行为。
**改进**：轻量 Hook 系统（不需要 Claude Code 级别的 27 种事件）。

```python
# agent/hooks.py 新建

class HookManager:
    """轻量生命周期 Hook 管理器"""
    
    EVENTS = [
        "on_session_start",    # 会话开始
        "on_session_end",      # 会话结束
        "pre_tool_use",        # 工具执行前（可拦截）
        "post_tool_use",       # 工具执行后
        "on_data_load",        # 数据加载完成
        "on_error",            # 错误发生
        "on_agent_turn_end",   # Agent 单轮结束
    ]
    
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {e: [] for e in self.EVENTS}
    
    def register(self, event: str, callback: Callable):
        self._hooks[event].append(callback)
    
    async def emit(self, event: str, context: dict) -> dict:
        """触发事件，返回合并后的结果"""
        results = {}
        for cb in self._hooks.get(event, []):
            result = cb(context)
            if result:
                results.update(result)
        return results
```

**影响文件**：新建 `agent/hooks.py`，修改 `agent/loop.py`、`tools/data_loader.py`
**工作量**：2 天

#### 6. LLM 成本追踪与预算控制 [O 层]
**问题**：有 token_count 记录但无累计统计和预算控制。
**改进**：在 `runtime_logger` 基础上添加成本追踪。

```python
# tools/cost_tracker.py 新建

class CostTracker:
    """LLM 调用成本追踪"""
    
    PRICING = {
        "deepseek-chat": {"input": 0.27, "output": 1.10},  # 每百万 token
    }
    
    def __init__(self):
        self._session_tokens = {"input": 0, "output": 0}
        self._session_calls = 0
    
    def record(self, model: str, input_tokens: int, output_tokens: int):
        self._session_tokens["input"] += input_tokens
        self._session_tokens["output"] += output_tokens
        self._session_calls += 1
    
    def get_session_cost(self) -> dict:
        return {
            "total_calls": self._session_calls,
            "total_input_tokens": self._session_tokens["input"],
            "total_output_tokens": self._session_tokens["output"],
            "estimated_cost_usd": self._estimate_cost(),
        }
    
    def check_budget(self, budget_usd: float) -> bool:
        return self._estimate_cost() < budget_usd
```

**影响文件**：新建 `tools/cost_tracker.py`，修改 `agent/llm_client.py`、`agent/loop.py`
**工作量**：1 天

#### 7. 工具结果标准化 [T 层]
**问题**：工具返回松散 dict，缺少类型保证。
**改进**：定义 `ToolResult` dataclass。

```python
# agent/tools_spec.py 添加

@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # duration_ms, token_count 等
    
    def to_dict(self) -> dict:
        d = {"ok": self.ok, **self.data}
        if self.error:
            d["error"] = self.error
        if self.warnings:
            d["warnings"] = self.warnings
        return d
```

**影响文件**：`agent/tools_spec.py`
**工作量**：1 天

### P2：中期改进（架构升级）

#### 8. 历史消息压缩 [C 层]
**改进**：超过 8 轮对话时，早期消息压缩为摘要。

**影响文件**：`agent/context.py`、`agent/loop.py`
**工作量**：2 天

#### 9. 审计日志 Hash Chain [G 层]
**改进**：每条合规审计日志包含前一条的 SHA256 hash，形成不可篡改的链式记录。

**影响文件**：`tools/compliance_audit.py`
**工作量**：0.5 天

#### 10. 工具执行超时统一化 [E 层]
**改进**：为所有工具添加统一的超时装饰器。

**影响文件**：`agent/tools_spec.py`
**工作量**：0.5 天

---

## 五、Harness 改进融入迭代计划

将上述 10 项改进融入 `evolution-roadmap.md` 的迭代计划：

### 调整后的迭代顺序

```
I-1  工程基建 + 测试修复（不变）
I-1b ★Harness 加固（新增，紧跟 I-1 之后）
     ├── P0-1 工具输入参数校验
     ├── P0-3 Agent 结果自检（SelfChecker）
     ├── P0-4 场景化工具过滤
     ├── P1-7 工具结果标准化（ToolResult）
     └── P2-10 工具执行超时统一化
     
I-2  报告生成管线（不变）
I-3  图表生成（不变）

I-3b ★上下文与可观测性（新增）
     ├── P0-2 上下文压缩管线（三级压缩）
     ├── P1-6 LLM 成本追踪
     └── P2-8 历史消息压缩

I-4  数据持久化（不变）
I-5  前端改进（不变）

I-5b ★Hook 系统 + 审计加固（新增）
     ├── P1-5 生命周期 Hook 系统
     └── P2-9 审计日志 Hash Chain

I-6  文件解析 + 搜索（不变）
I-7  main.py 拆分（不变）
I-8  Plan-Execute（不变）
I-9  计算器补齐（不变）
I-10 JS 模块化（不变）
```

### 总工作量估算

| 迭代 | 天数 | 内容 |
|------|------|------|
| I-1 | 3-4 | 工程基建 + 测试修复 |
| **I-1b** | **3** | **Harness 加固：参数校验 + 自检 + 工具过滤 + ToolResult + 超时** |
| I-2 | 4-5 | 报告生成 |
| I-3 | 3-4 | 图表生成 |
| **I-3b** | **3-4** | **上下文压缩 + LLM 成本追踪 + 历史压缩** |
| I-4 | 4-5 | 数据持久化 |
| I-5 | 3-4 | 前端改进 |
| **I-5b** | **2-3** | **Hook 系统 + 审计加固** |
| I-6 | 4-5 | 能力扩展 |
| I-7 | 4-5 | main.py 拆分 |
| I-8 | 5 | Plan-Execute |
| I-9 | 4 | 计算器补齐 |
| I-10 | 4-5 | JS 模块化 |

新增 3 个 Harness 专项迭代，共 ~9 个工作日。

---

## 六、DataAgent vs 标杆系统的最终对标

| ETCLOVG 层 | Claude Code | OpenClaw | DataAgent（改进后） |
|------------|------------|----------|-------------------|
| E 执行环境 | ★★★★★ | ★★★★ | ★★★ DuckDB 沙箱 + 超时 + 检查点 |
| T 工具接口 | ★★★★★ | ★★★★ | ★★★★ Schema 校验 + 场景过滤 + ToolResult |
| C 上下文 | ★★★★★ | ★★★ | ★★★ 三级压缩 + 历史摘要 + Token 预算 |
| L 生命周期 | ★★★★★ | ★★★ | ★★★★ Agent 循环 + Plan-Execute + 暂停续跑 |
| O 可观测性 | ★★★★★ | ★★★ | ★★★ 两级日志 + 成本追踪 + Hook 事件 |
| V 验证 | ★★★★ | ★★ | ★★★ SelfChecker + SQLGuard + 数值校验 |
| G 治理 | ★★★★★ | ★★★★ | ★★★★ A/B 类分离 + 审计链 + 工具权限 |

**评估结论**：DataAgent 不需要达到 Claude Code 的五星标准（那是一个 512K 行代码的通用开发 Agent），但必须在每一层都达到三星以上。当前 C 层（上下文）和 V 层（验证）是最大短板，改进后可全面达到 ★★★~★★★★ 水平，作为垂直领域 Agent 完全合格。

---

## 参考资料

- [Awesome Harness Engineering](https://github.com/ai-boost/awesome-harness-engineering) — 200+ 资源的系统性汇编
- [Dive into Claude Code (VILA-Lab)](https://github.com/VILA-Lab/Dive-into-Claude-Code) — Claude Code 架构系统性分析
- [Agent Harness Engineering: A Survey (TMLR)](https://openreview.net/forum?id=3hXEPbG0dh) — ETCLOVG 七层分类法学术论文
- [OpenClaw Architecture Diagram](https://vallettasoftware.com/blog/post/openclaw-architecture-diagram-2026) — OpenClaw 架构解析
- [OpenClaw Security Analysis](https://arxiv.org/html/2603.27517v2) — OpenClaw 安全性系统评估
