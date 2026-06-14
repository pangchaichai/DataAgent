# DataAgent v3.0 演进方案 — 综合评估与最终实施计划

## 评估背景

基于对以下材料的完整研读和交叉验证：
- 项目全部核心代码（agent/、tools/、calculators/、ui/js/、api/、skills/）
- 现有演进方案 `docs/v3-architecture-evolution.md`（1318行）
- 用户原始思考（re-prompt.md，5个维度）
- 项目状态文件（HANDOFF.md、PROGRESS.md）
- 341个测试用例的覆盖范围

---

## 一、现有方案总体评价

**优点**：理论框架扎实（控制工程PID映射、Anthropic五种workflow模式引用）、问题诊断准确（5个根本性问题）、Track逻辑链清晰。

**核心问题**：
1. **工程师气质过重，用户价值排序有偏差** — ToolRegistry抽象层解决的是"开发者新增calculator不方便"，但当前只有7个calculator且增长极慢；而用户每天面对的"点击即用"体验改进（Skill卡片+快速路径）反而排P1
2. **3.5周时间线严重不现实** — 实际工作量估算36-45个工作日（7-9周），方案标注17.5天，系统性低估了集成、调试、回归测试成本
3. **Eval Framework时机过早** — 没有1000+条真实trace数据，LLM-as-Judge的校准、退化阈值的设定都缺乏依据
4. **缺少关键实操细节** — 迁移策略、回滚计划、内存影响分析、真实数据端到端验证均未涉及

---

## 二、逐Track评审判定（含原方案 vs 推荐方案对比）

### Track 1：内核解耦 — ToolRegistry + ACI加强

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 新建 `agent/tool_registry.py`，所有工具通过 `register_tool()` 声明式注册；tools_spec.py 从 1128 行瘦身至 ~100 行薄转发层 | **降级为文件拆分**：tools_spec.py 拆分为 `tool_defs.py`（工具定义）+ `tool_dispatch.py`（分发逻辑），tools_spec.py 保留为转发层 |
| 工作量 | 5天（方案估计） | 3天（实际可达） |
| 判定 | 架构上正确，但规模不匹配 | **ADJUST** |
| 核心理由 | 当前只有 11 个工具、7 个 calculator，且 calculator 增长极慢。完整 Registry 模式（含 `register_tool/dispatch/list_tools` API 体系）要求 handler 统一签名，导致 ctx 变成上帝对象。80% 的解耦收益只需拆文件即可获得 | 工具数超过 20 个时，或引入第三方工具时，再引入完整 Registry |

---

### Track 2A：快速路径（双通道编排）

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | `agent/fast_path.py`，绕过 LLM 直接执行固化计算，置信度标注 `auditable`；loop.py 入口加 `try_fast_path` 分支 | 保持原方案，但**不依赖 Track 1 完成**，handler 直接从现有 tools_spec.py 调用，不等 ToolRegistry | 
| 工作量 | 3天 | 5天（快速路径本身+SKILL.md新增default_args字段+集成） |
| 判定 | 核心价值正确 | **APPROVE（P0）** |
| 核心理由 | 固化计算从 3-5 秒降到 0.5 秒，是用户感知最强的单项改进。方案未说明 `_build_calculator_args` 如何在没有 LLM 的情况下确定参数——需补充：Skill SKILL.md 新增 `default_args` 字段，由 skill_info 提供默认参数，preflight 确认数据就绪后直接构建 args | 原方案把快速路径与 ToolRegistry 解耦设计成依赖关系，实际不必要 |

---

### Track 2B：ExecutionTracker 执行追踪

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 完整 `ExecutionTracker` 类，含 `start_trace/record_tool_call/record_user_feedback/end_trace/get_stats/get_degradation_signals`，并暴露 `/api/eval/stats` 端点 | **只做写入端**：JSONL 记录 trace_id/用户消息/工具调用链/耗时/outcome。读取端、退化信号检测、API 端点全部推迟 |
| 工作量 | 含 API 约 3天 | 写入端 2天 |
| 判定 | 写入端正确，读取端时机过早 | **APPROVE（简化版）** |
| 核心理由 | 退化告警阈值（完成率 85%、错误率 15%）是拍脑袋数字——没有 baseline 数据，这些数字没有统计意义。应先跑 ExecutionTracker 写入端积累 2-4 周数据，再用实际 p50/p95 确定阈值 | — |

---

### Track 2C：D-term 误差趋势检测

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | `ErrorTrendDetector(window=3, threshold=0.67)`，连续 2 次失败后第 3 次触发 ask_user | **推迟到 v3.1** |
| 工作量 | 1天 | 0 |
| 判定 | — | **DEFER** |
| 核心理由 | "什么算工具调用失败"的定义不精确。多步任务（如周报生成）前几轮连续调用 profile_table/run_sql，工具本身成功但 SQL 结果为空——算失败吗？window=3 且 threshold=0.67 在正常多步任务中很容易误报。需要先从 ExecutionTracker 数据中分析实际的失败模式，再反推合理的检测参数 | — |

---

### Track 3：Skill 卡片化 + 一键执行

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 侧边栏 Skill 从文字列表变为交互卡片，显示数据就绪/缺失状态，支持一键执行；新增 `/api/skills/status`（批量 preflight）+ `/api/skills/<name>/execute`（复用 SSE 流） | 保持原方案完整实现，**提升优先级为 P0**（原方案为 P1） |
| 工作量 | 2天（方案估计） | 4天（含 preflight 批量调用性能优化） |
| 判定 | 方向和实现均正确，只是优先级低估 | **APPROVE，提升为 P0** |
| 核心理由 | 对非技术用户，这是每天打开应用后最先接触的界面元素。"记住触发词" → "看到绿灯就按"是质的体验变化，直接决定推广期的第一印象。注意：批量 preflight 检查所有 Skill 可能有性能问题，status API 需要加轻量缓存（30秒内同一 Skill 不重复做文件检查） | — |

---

### Track 4：Eval Framework 评估框架

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 四级评估架构（单元/组件/端到端/生产监控）+ LLM-as-Judge SQL 语义质量评估 + 预置 YAML 评估用例 + 退化告警阈值 | **推迟到 v3.1** |
| 工作量 | 5天（方案估计） | 0 |
| 判定 | — | **DEFER** |
| 核心理由 | （1）数据不足：LLM-as-Judge 需要 human-judge vs LLM-judge 一致性校准（至少 50 个样本），没有这个校准步骤，judge 分数不可信。（2）阈值无依据：退化告警的 85%/15%/5 等阈值需要 baseline 数据支撑。（3）成本不明：judge 每次调用注入完整数据字典，对 Windows 本地部署用户的 token 开销需要实测确认。正确顺序：ExecutionTracker 积累数据 → 用数据确定 baseline → 建 Eval Framework | — |

---

### 仪表盘（Task Dashboard）

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 右侧滑出独立面板（260px），含进度条、步骤脉冲动画、数据源发光效果、冻结态回顾；`ui/js/dashboard.js`（~150行）新建 | **简化为消息流内嵌**：复用现有 Process Wrapper 位置，步骤列表+当前步骤高亮+数据源列表，不做独立面板和动画 |
| 工作量 | 4-5天 | 2天 |
| 判定 | 方向正确，首版过度设计 | **ADJUST** |
| 核心理由 | （1）独立 260px 面板在 1366x768 分辨率（金融行业常见）压缩聊天区 19%，表格数据展示受影响。（2）CSS 脉冲动画在 Windows WebView2 中有兼容性风险，调试成本被低估。（3）"冻结态"多任务堆叠的 DOM 管理引入新复杂度。消息流内嵌版天然支持历史回顾，无需额外设计 | 用户反馈消息流内嵌不满足需求时，再升级为独立面板 |

---

### 置信度标注

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | SSE 事件新增 `confidence` 字段（auditable/verify/ai_generated），前端渲染对应颜色标签+溯源卡片 | 保持原方案，但**首版只做后端 SSE 字段**，前端渲染简化为纯文字标签（不做溯源卡片折叠展开） |
| 工作量 | 分散在各 Track | 2天集中交付 |
| 判定 | 设计合理 | **APPROVE** |
| 核心理由 | 注意：这是横切关注点，所有 SSE helper 函数签名需要改（`_text(text)` → `_text(text, confidence=None)`），chat.js 的 handleChunk 需识别新字段。影响面比原方案估计的大，建议集中在 Week 3 一次性改完，而非分散在各 Track | — |

---

### Skills 编排修复

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 方向 | 识别 5 个编排问题（重复Skill/A-B类违规/模板缺失/缺确认节点/缺预览）；将 `fund_nav_report` 改为 fixed，合并 meeting_report，模板检查加 preflight | 保持原方案所有修复，**将 fund_nav_report 提升为 P0**（原方案列为 P1 Skill 修复的一部分） |
| 工作量 | 1天（方案估计） | 3天（实际：calculator串联+测试） |
| 判定 | 问题诊断准确 | **APPROVE，fund_nav_report 提升为 P0** |
| 核心理由 | fund_nav_report 是合规风险而非技术债。运作报告数据若来自 LLM 生成的 SQL，一旦 LLM 选错列名，报告数字是"精确的错误"——比估算更危险，因为它看起来权威。需串联 nav_metrics + asset_structure + credit_distribution 三个已有 calculator，不需要写新代码 | 原方案遗漏了 flexible_stats 的 @mention 语法对非技术用户的门槛问题，与"开发者思维 UX"问题诊断矛盾 |

---

### 3 个新工具

| | 原方案 | 推荐方案 |
|--|--------|---------|
| 工具 | export_data（P1）、list_tables（P1）、dispatch_alert（P2） | export_data **P1必做**（weekly_report_generator Skill明确依赖）、list_tables **P1**（减少上下文压缩后的Agent幻觉）、dispatch_alert **P2推迟** |
| 工作量 | 1天（方案估计） | 2天 |
| 判定 | 基本正确 | **ADJUST（dispatch_alert 推迟）** |
| 核心理由 | dispatch_alert 依赖 `tools/notify.py` 的 Windows toast 集成，在 Linux 开发环境无法完整测试，推迟到 Phase 5 Windows 测试环境中一并验证 | — |

---

### 3 个新 Skill

| | 原方案 | 推荐方案 |
|--|--------|---------|
| Skill | risk_dashboard（P2）、maturity_alert（P2）、product_comparison（P3） | **全部推迟到 v3.1** |
| 工作量 | Week 4 最后0.5天（方案估计，明显低估） | 0 |
| 判定 | — | **DEFER** |
| 核心理由 | 现有 10 个 Skill 中有 2 个无法运行（模板缺失）、1 个合规违规（fund_nav_report）、2 个重复（meeting_report）、1 个无导出功能（position_query）。在修好现有 Skill 之前新增 Skill 只是扩大了问题面。product_comparison 与 flexible_stats 的差异化价值也不够清晰，建议先观察用户真实请求再决定 | — |

---

## 三、发现的额外问题（方案未覆盖）

1. **fund_nav_report合规风险** — 运作报告（B类场景）使用LLM生成SQL，违反CLAUDE.md核心约束。若LLM选错列名，报告数据将是"精确的错误"。必须立即修复
2. **快速路径参数来源** — `_build_calculator_args`如何从skill_info+config确定calculator完整参数？需要Skill SKILL.md新增`default_args`字段
3. **ToolRegistry handler签名问题** — 不同工具的handler依赖完全不同（duckdb_conn vs calculation_config vs 文件系统），统一为`callable(args, ctx)`要求ctx变成上帝对象
4. **置信度标注影响面** — 所有SSE helper函数签名需改、chat.js handleChunk需识别新字段，是横切关注点
5. **迁移策略缺失** — tools_spec.py重构后无向后兼容期或feature flag
6. **内存预算未分析** — 新增ExecutionTracker、仪表盘DOM是否突破200MB目标

---

## 四、最终实施方案（4周，现实版）

### 核心原则
**先让用户用起来（快速路径+Skill卡片），再让系统自我改进（Eval+自进化）。**

### Week 1: 快速路径 + ExecutionTracker写入端
- Day 1-2: `agent/fast_path.py` + SkillInfo新增`fixed_calculator`一级字段 + Skill SKILL.md增加`default_args`
- Day 3: `loop.py`集成fast_path入口（try_fast_path分支，在Skill匹配+preflight后、agent loop前）
- Day 4: `agent/execution_tracker.py`（仅JSONL写入）+ loop.py/fast_path.py埋点
- Day 5: 回归测试（pytest tests/ -x -q全绿）

**验收**：触发concentration_monitor → 响应<1s → data/traces/有JSONL记录 → 无LLM调用

### Week 2: Skill卡片 + 一键执行 + fund_nav_report修复 + 侧边栏UI
- Day 1-2: `/api/skills/status` API（批量preflight检查）+ `/api/skills/<name>/execute`端点
- Day 3-4: 前端Skill卡片渲染（sidebar.js改造，含描述/数据就绪/执行按钮）+ executeSkill()复用SSE流
- Day 4 追加: **[UI] 数据表侧边栏增强**（点击表名 → openProfile，显示表类型+日期副信息）+ **智能快捷按钮**（根据已加载表动态切换按钮组）
- Day 5: fund_nav_report改为`calc_type: fixed`，串联nav_metrics+asset_structure+credit_distribution三个calculator

**验收**：侧边栏显示Skill卡片 → 数据就绪时蓝色"执行"按钮 → 点击出结果 → fund_nav_report全程无LLM SQL → 数据表点击可打开结构弹窗 → 快捷按钮随数据状态变化

### Week 3: Skills修复 + 新工具 + 置信度标注 + 交互体验
- Day 1: 合并meeting_report与client_meeting_report、partnership_summary加request_confirmation节点
- Day 2: skill_preflight.py增加模板文件存在性检查（dept_weekly_report/monthly_bond_summary标记不可用）
- Day 3: `export_data`工具（CSV导出+下载链接）+ `list_tables`工具（返回已加载表元数据）
- Day 4: 置信度标注（SSE事件新增confidence字段 + 前端标签渲染）
- Day 4 追加: **[UI] 输入体验优化**（placeholder去技术化 + suggestionsBar主动显示）+ **消息体验增强**（Agent消息hover增加"导出Word"按钮 + 错误消息增加"重试"按钮）
- Day 5: 回归测试 + 联调

### Week 4: 简化仪表盘 + tools_spec拆分 + 全局UI统一 + 文档
- Day 1-2: 仪表盘（消息流内嵌版，复用Process Wrapper位置，步骤列表+当前步骤高亮+数据源列表）
- Day 3: tools_spec.py拆分为`agent/tool_defs.py`(工具定义) + `agent/tool_dispatch.py`(分发逻辑)，tools_spec.py保留为薄转发层
- Day 3 追加: **[UI] 欢迎面板统一**（合并index.html和resetChat()两份欢迎面板为一个buildWelcomePanel()函数，有数据时显示可执行Skill推荐）+ **Header信息重组**（LLM状态改为"AI就绪/离线"、移除RAM/Token、新增"N张表"计数）+ **上传确认弹窗**（inline style改为统一CSS class）
- Day 4: 端到端联调 + 真实数据测试（持仓表+净值表完整流程）
- Day 5: 文档更新（CLAUDE.md/PROGRESS.md/HANDOFF.md）+ 推送

---

## 五、UI 设计优化方案（补充章节）

> 基于对 index.html（940行）、9 个 JS 模块的完整代码审读，识别出当前 UI 的 6 类体验问题，提出具体优化方案。

### 5.0 当前 UI 问题诊断

| 问题 | 具体表现 | 影响 |
|------|---------|------|
| **侧边栏 Skills 是死文字** | Skills 区域只显示 name + fixed/exp 标签，无描述、无数据就绪状态、不可点击执行 | 用户不知道每个 Skill 能做什么、能不能用 |
| **快捷按钮不感知上下文** | 4 个固定按钮（上传/合规/报告/持仓），未加载数据时"合规检查""持仓"按钮点击必失败 | 用户首次使用就遭遇失败体验 |
| **欢迎面板与重置面板不一致** | index.html 的 welcomePanel 是 4 卡片布局，main.js 的 resetChat() 重建的是另一个版本（4 个 wq-btn 按钮），两者内容、样式都不同 | 产品感缺失 |
| **数据表侧边栏无直达操作** | 表名只能看不能点（没有绑定 openProfile），只有 hover 后的 x 删除按钮 | 用户上传数据后无法快速探查表结构 |
| **Header 状态对非技术用户无意义** | 显示 RAM MB、Token 用量（如 "Tok 0/64K"），非技术金融从业者看不懂也不关心 | 浪费珍贵 Header 空间 |
| **输入框提示语技术化** | placeholder 写着"@表名 指定数据表"，@mention 是开发者术语 | 增加非技术用户认知负担 |

---

### 5.1 侧边栏重构 — Skill 卡片化 + 数据表直达

**与 Track 3（Skill 卡片）合并实施。**

#### Skills 区域改造

```
当前:
  concentration_monitor   [固化]
  position_query          [探索]

改造后:
  +------------------------------+
  | 主体集中度监控         [固化] |
  | 检查主体/单券集中度是否超标   |
  | * 数据就绪              执行  |
  +------------------------------+
  +------------------------------+
  | 持仓查询               [探索] |
  | 自然语言查询持仓明细         |
  | * 数据就绪          对话执行  |
  +------------------------------+
  +------------------------------+
  | 运作报告               [固化] |
  | 生成产品运作报告             |
  | o 缺: 净值表       需要数据  |
  +------------------------------+
```

**实现要点**：
- Skill 卡片高度控制在 3 行以内，避免侧边栏滚动过多
- "执行" 按钮仅在 `can_fast_execute == true` 时显示为主色蓝色
- "对话执行" 按钮（exploratory 类型）点击后在输入框填入触发语
- 缺数据时灰色禁用态，显示缺什么数据（如"缺: 净值表"）
- 复用 `/api/skills/status` API（Track 3 新增）

#### 数据表区域增强

```
当前:
  * holding_20260515    283行  x

改造后:
  * holding_20260515   283行  [i]  x
    持仓表 . 2026-05-15
```

**变更**：
- 点击表名 → 调用 `openProfile(tableName)`（当前只有 hover 显示 x 删除按钮，无法点击探查）
- 新增 [i] 图标按钮 → 直接打开结构/质量弹窗
- 表名下方增加一行副信息：表类型中文名 + 数据日期

**涉及文件**：`ui/js/sidebar.js` loadTables() 和 loadSkills() 函数

---

### 5.2 智能快捷按钮 — 上下文感知

**当前问题**：4 个快捷按钮固定不变，没有数据时 3 个按钮都无意义。

**改造方案**：快捷按钮根据当前状态动态生成。

```javascript
// 规则：
// 无数据时 -> 只显示「上传」「创建 Skill」
// 有持仓表时 -> 显示「合规检查」「持仓查询」「上传更多」
// 有净值表时 -> 追加「运作报告」
// 有多张同类型表时 -> 追加「跨期对比」
```

**具体逻辑**：
```
状态 A（无数据）:
  上传数据 | 创建Skill | 开始提问

状态 B（有持仓表）:
  合规检查 | 持仓分析 | 上传更多 | 报告

状态 C（有持仓 + 净值）:
  合规检查 | 净值分析 | 运作报告 | 持仓分析
```

**涉及文件**：
- `ui/js/main.js` — 新增 `updateQuickButtons()` 函数
- `ui/js/sidebar.js` — loadTables() 成功后调用 `updateQuickButtons(tables)`

---

### 5.3 欢迎面板统一 + 状态感知

**当前问题**：index.html 和 main.js resetChat() 各自维护一份欢迎面板，内容不同。

**改造方案**：
1. 统一欢迎面板为一个 `buildWelcomePanel()` 函数，index.html 和 resetChat() 共用
2. 欢迎面板感知数据状态：
   - 无数据 → 引导上传（当前行为，保持）
   - 有数据 → 直接显示可执行的 Skill 推荐 + 示例查询

```
无数据时:
  +----------------------------------------+
  |         DataAgent                      |
  |   专业的金融资管数据分析助手            |
  |                                        |
  |  [上传数据分析] [合规监控]             |
  |  [创建 Skill]  [通用问答]              |
  +----------------------------------------+

有数据时:
  +----------------------------------------+
  |         DataAgent                      |
  |   已加载 3 张表，可以开始分析           |
  |                                        |
  |  可直接执行：                           |
  |  [主体集中度监控] [持仓查询]           |
  |                                        |
  |  试试问我：                             |
  |  "查看持仓市值前10" "检查集中度超标"   |
  +----------------------------------------+
```

**涉及文件**：`ui/js/main.js` 的 resetChat() + `ui/index.html` 的 welcomePanel

---

### 5.4 Header 信息重组 — 面向业务用户

**当前 Header**：
```
=  DA DataAgent  | * deepseek | RAM 45MB | Tok 0/64K | theme +
```

**改造后**：
```
=  DA DataAgent  | * AI 就绪 | 3张表 | 最近: holding_20260515 | theme +
```

**变更说明**：
- **LLM 状态**：从显示 provider 名称（如 "deepseek"）改为状态描述（"AI 就绪" / "AI 离线"），非技术用户不需要知道用的是什么模型
- **RAM/Token**：移除。非技术用户完全不关心。开发者可通过 `/api/health` 或设置面板查看
- **新增**：显示已加载表数量（"3张表"），让用户一眼知道数据状态
- **新增**：显示最近加载的表名，提供上下文提示

**涉及文件**：`ui/index.html` header 区域 + `ui/js/main.js` pollHealth()

---

### 5.5 输入体验优化

#### 5.5.1 Placeholder 去技术化

```
当前: "输入分析需求... @表名 指定数据表，Enter 发送，Shift+Enter 换行"
改后: "输入分析需求，如「查看持仓前10」「检查集中度」... Enter 发送"
```

当有表加载后，placeholder 动态变为：
```
"输入问题，如「@holding_20260515 市值排名前10」... Enter 发送"
```

#### 5.5.2 空输入提示

当用户在输入框为空时按 Enter，不是静默不响应，而是短暂显示 placeholder 闪烁提示。

#### 5.5.3 输入建议条增强

当前 suggestionsBar 仅在 API 返回 suggestions 时显示。改为：
- 加载数据后自动显示 2-3 个上下文推荐
- 用户输入时实时匹配 Skill 触发词，显示"可能想用的 Skill"
- 复用 `/api/suggestions` 现有接口

**涉及文件**：`ui/js/main.js`、`ui/js/chat.js`

---

### 5.6 消息体验增强

#### 5.6.1 Agent 消息操作按钮扩展

```
当前:  [复制]
改后:  [复制] [导出Word]
```

- 在每条 Agent 回复的 hover 操作栏中增加"导出 Word"按钮
- 复用现有 `exportWordFromBubble()` 函数（render.js 已实现但未绑定）

#### 5.6.2 错误消息增加重试

当前错误消息只是红色文字。改为：
```
+-- x 查询失败：表名不存在 ------------------+
|                                              |
|    [重试] [修改问题]                         |
+----------------------------------------------+
```

- "重试" → 重新发送上一条用户消息
- "修改问题" → 将上一条消息填入输入框供编辑

#### 5.6.3 上传确认弹窗样式统一

当前 uploadConfirmPanel 使用大量 inline style（约 30 处），与全局 CSS 体系脱节。改为使用统一的 CSS class（复用 settings-panel 的样式模式）。

**涉及文件**：`ui/index.html`（上传确认弹窗 HTML/CSS）、`ui/js/render.js`（消息操作按钮）

---

### 5.7 UI 优化实施排期（融入主计划）

| 优化项 | 所属 Week | 与 Track 的关系 | 工作量 |
|--------|----------|----------------|--------|
| 5.1 Skill 卡片 | Week 2 | **与 Track 3 合并**，一起实现 | 含在 Track 3 工作量中 |
| 5.1 数据表直达 | Week 2 | 与 Skill 卡片同步改 sidebar.js | 0.5天 |
| 5.2 智能快捷按钮 | Week 2 | 复用 loadTables 的数据 | 0.5天 |
| 5.3 欢迎面板统一 | Week 4 | 仪表盘联调时统一处理 | 0.5天 |
| 5.4 Header 信息重组 | Week 4 | 与仪表盘/全局联调一起 | 0.5天 |
| 5.5 输入体验优化 | Week 3 | 与置信度标注同步改 chat.js | 0.5天 |
| 5.6 消息体验增强 | Week 3 | 改 render.js | 0.5天 |

**总增量工作量：约 3 天**（大部分与已有 Track 工作重叠在同一文件中，边际成本低）。

---

### 5.8 不做的 UI 改动（及理由）

| 不做 | 理由 |
|------|------|
| 完全重写 CSS 主题系统 | 当前 CSS 变量体系完整，dark/light 切换正常，不影响用户体验 |
| 引入 CSS 框架（Tailwind 等） | 当前 940 行内联 CSS 虽然多，但高度定制且无外部依赖（零 CDN 约束） |
| 重写 Markdown 渲染器 | 当前 renderMd() 虽然简单，但覆盖了表格/代码/列表/链接，够用 |
| 侧边栏改为可拖拽宽度 | 240px 固定宽度对大多数屏幕合理，拖拽增加交互复杂度 |
| 消息气泡改为左右布局以外的样式 | 对话式布局是用户最熟悉的范式，不需要改 |

---

## 六、推迟到v3.1的内容（需ExecutionTracker积累2-4周数据后）

- D-term误差趋势检测（需先定义"什么算工具调用失败"的精确规则）
- 完整ToolRegistry抽象层（等工具数>20时再考虑）
- Eval Framework四级评估架构 + LLM-as-Judge
- ExecutionTracker读取端（/api/eval/stats + 退化信号检测）
- 3个新Skill（risk_dashboard/maturity_alert/product_comparison）
- dispatch_alert工具
- 独立仪表盘面板（如用户反馈消息流内嵌不够用再升级）
- 自我进化机制（从"追踪"到"学习"的触发条件：1000+条trace、同类错误30天内10+次、Skill rejection率>30%）

---

## 七、涉及文件清单

### 新建文件
| 文件 | 用途 | Week |
|------|------|------|
| `agent/fast_path.py` | 确定性快速路径（绕过LLM） | W1 |
| `agent/execution_tracker.py` | 执行追踪JSONL写入 | W1 |
| `agent/tool_defs.py` | 工具定义（从tools_spec.py拆出） | W4 |
| `agent/tool_dispatch.py` | 工具分发（从tools_spec.py拆出） | W4 |
| `ui/js/dashboard.js` | 简化版任务仪表盘 | W4 |

### 修改文件
| 文件 | 变更 | Week |
|------|------|------|
| `agent/loop.py` | fast_path集成入口 + 追踪埋点 + 置信度字段 | W1,W3 |
| `agent/skill_loader.py` | SkillInfo新增fixed_calculator + default_args | W1 |
| `agent/skill_preflight.py` | 模板文件存在性检查 | W2 |
| `agent/tools_spec.py` | 新增export_data/list_tables + 拆分转发 | W3,W4 |
| `api/skill_api.py` | /api/skills/status + /api/skills/<name>/execute | W2 |
| `ui/js/sidebar.js` | Skill卡片渲染 + executeSkill() + 数据表点击openProfile + 表类型/日期副信息 | W2 |
| `ui/js/chat.js` | executeSkill复用SSE + 置信度标签 + 仪表盘事件转发 | W2,W3,W4 |
| `ui/js/render.js` | 置信度标签渲染 + Agent消息hover增加"导出Word" + 错误消息增加"重试" | W3 |
| `ui/js/main.js` | 智能快捷按钮updateQuickButtons() + 欢迎面板统一buildWelcomePanel() + Header信息重组 + placeholder动态化 | W2,W4 |
| `ui/index.html` | Skill卡片CSS + 仪表盘内嵌样式 + Header改造 + 上传确认弹窗CSS统一（移除~30处inline style） | W2,W3,W4 |
| `skills/fund_nav_report/SKILL.md` | calc_type改fixed + 串联3个calculator | W2 |
| `skills/meeting_report/SKILL.md` | 合并client_meeting_report内容 | W3 |
| `skills/partnership_summary/SKILL.md` | 加request_confirmation步骤 | W3 |

---

## 八、验证策略

1. **每周结束**：pytest tests/ -x -q全绿
2. **Week 1结束**：快速路径端到端验证（concentration_monitor <1s响应）
3. **Week 2结束**：Skill卡片UI验证 + fund_nav_report合规验证（零LLM SQL）
4. **Week 4结束**：真实持仓/净值数据端到端测试 + 内存<200MB确认
