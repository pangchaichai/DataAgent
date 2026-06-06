# DataAgent 演进总体方案 v1.0

> **每次 Claude Code 会话开始前，须阅读 CLAUDE.md + PROGRESS.md + 本文件。**
> 本文件是项目唯一权威的演进指南，合并了战略决策、Harness 工程改进和可执行迭代计划。
>
> 编写日期：2026-06-06
> 输入来源：项目全量代码审查 + 创始人五大战略问题 + ETCLOVG Harness 工程对标分析
>
> 替代文件：本文件替代 `docs/evolution-roadmap.md` 和 `docs/harness-engineering-analysis.md`

---

## 第一章：五大战略决策

### Q1：工程基建 → 必须补，轻量补，第一优先

**现状**：无 CI/CD、无 linter、`.claude/` 目录不存在、11 个测试失败、`config.yaml` 不存在（仅 `config.example.yaml`）、API key 明文存储。

**判断**：一人团队更需要 CI——没有同事 review，自动化测试是唯一的质量守门人。

**做**：pyproject.toml + ruff + `.claude/settings.json` PreCommit hook + `.env` 密钥分离 + GitHub Actions CI + 修复全部失败测试。
**不做**：Docker、monorepo 工具、多环境部署流水线。

### Q2：客户端 vs 服务端 → 近期不做服务端，做架构准备

**现状**：全局 `_session` 字典 + 单例 DuckDB，只能单用户单标签页。main.py 800+ 行堆了 40+ 路由。

**判断**：服务端运维开销大，用户量 < 5 人前不值得。但全局状态限制了多标签页使用。

**做**（对单机无副作用的架构准备）：`_session` → `SessionStore` 类、main.py → Blueprint 拆分、API 响应格式标准化。
**不做**：服务端代码、用户认证、数据库。

### Q3：资源约束 → 两周迭代制 + T 型能力策略

- 每个迭代只做一件事（3-5 工作日），完成 → 测试全绿 → 提交 → 再开下一个
- Claude Code 负责测试、重构、bug 修复；架构决策和业务口径由人决定
- 用成熟库替代自研：`python-docx`、`duckduckgo-search`、`pypdf2`
- 先完成一个粗糙但完整的「上传→分析→报告→导出」闭环，再逐步打磨

### Q4：通用能力 → T 型扩展，分析做深，其余做广

**优先级**：报告编制（最大价值缺口）→ 文件解析 → 联网搜索 → 日常办公。

每个新能力 = 一个 Agent 工具，加入 `TOOL_DEFINITIONS` + `dispatch_tool` 即可。工具数 < 15 时不需要插件注册系统。

### Q5：前端设计 → 四象限分类，先补功能再改架构

| 区域 | 定位 | 内容 |
|------|------|------|
| **A 对话操作区** | 高频 + 对话驱动 | 数据查询、合规检查、报告生成、图表 |
| **B 快捷操作区** | 高频 + 直接操作 | 拖拽上传、一键报告、导出结果 |
| **C 状态感知区** | 被动展示 | LLM 状态、数据时效、Agent 进度 |
| **D 配置管理区** | 低频深度 | API Key、阈值、集团系、主题 |

优先顺序：功能补全 → 可发现性 → 操作效率 → 架构升级。近期不迁移 Vue/React。

---

## 第二章：Harness 工程评估（ETCLOVG 七层对标）

### 2.1 理论框架

Agent Harness 是模型和真实世界之间的全部基础设施。ETCLOVG 七层分类法：

| 层 | 名称 | 职责 |
|----|------|------|
| **E** | Execution 执行环境 | 沙箱、资源限制、错误恢复 |
| **T** | Tools 工具接口 | 定义、Schema 校验、分发、场景过滤 |
| **C** | Context 上下文 | Token 预算、压缩裁剪、渐进加载 |
| **L** | Lifecycle 生命周期 | Agent 循环、规划-执行、暂停续跑 |
| **O** | Observability 可观测性 | 决策日志、Token/成本追踪、Hook 事件 |
| **V** | Verification 验证 | 结果自检、数值合理性、防幻觉 |
| **G** | Governance 治理 | 权限模型、合规审计、数据安全 |

### 2.2 DataAgent 逐层评估与改进项

#### E 层：执行环境 — ★★★ 应用层沙箱已足够

DataAgent 采用**应用层沙箱**（SQLGuard + 封闭工具集）而非进程级沙箱。这是正确的设计——LLM 没有 Shell/Bash 工具，无法执行任意代码。7 个工具全部是预定义 Python 函数，不存在不可信代码执行路径。

- ✅ SQLGuard（SELECT-only + 函数黑名单 + 动态表名白名单 + 30s 超时）
- ✅ DuckDB 资源硬限制（max_memory=200MB, threads=2）
- ⚠️ 需要改进：其他工具（profiler、calculator）缺统一超时保护

**结论：不需要进程级沙箱。** 如果未来添加 Shell 工具或插件热加载，需重新评估。

#### T 层：工具接口 — 需要 3 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **工具输入参数校验** | P0 | LLM 返回的 arguments 直接传给 handler，无 Schema 校验 |
| **场景化工具过滤** | P0 | 全部 7 个工具始终暴露，合规场景下 run_sql 不应出现 |
| **工具结果标准化** | P1 | 工具返回松散 dict，缺类型保证 |

#### C 层：上下文管理 — ❌ 最大短板，需要 2 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **上下文压缩管线** | P0 | `build_schema_context()` 全量注入所有表所有列名，5-10 张表时消耗数千 token，无任何压缩 |
| **历史消息压缩** | P2 | 对话超过 8 轮时无摘要压缩 |

#### L 层：生命周期编排 — 需要 1 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **Plan-Execute 双层架构** | 中期 | 复杂多步任务（参谈要点）完成率低，缺任务分解 |

#### O 层：可观测性 — 需要 2 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **LLM 成本追踪** | P1 | 有 token_count 记录但无累计统计和预算控制 |
| **生命周期 Hook 系统** | P1 | 无可编程扩展点 |

#### V 层：验证反馈 — ❌ 严重不足，需要 1 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **Agent 结果自检** | P0 | run_calculator 结果直接展示，无数值合理性校验（集中度超 100%、市值为负等不会被拦截） |

#### G 层：治理约束 — 需要 1 项改进

| 改进项 | 优先级 | 问题 |
|--------|--------|------|
| **审计日志 Hash Chain** | P2 | 合规审计 JSONL 追加写入，无防篡改机制 |

### 2.3 改进后目标评级

| ETCLOVG 层 | 当前 | 改进后 | 说明 |
|------------|------|--------|------|
| E 执行环境 | ★★★ | ★★★ | 应用层沙箱已足够 + 统一超时 |
| T 工具接口 | ★★ | ★★★★ | Schema 校验 + 场景过滤 + ToolResult |
| C 上下文 | ★ | ★★★ | 三级压缩 + 历史摘要 |
| L 生命周期 | ★★★ | ★★★★ | Agent 循环 + Plan-Execute + 暂停续跑 |
| O 可观测性 | ★★ | ★★★ | 两级日志 + 成本追踪 + Hook |
| V 验证 | ★ | ★★★ | SelfChecker + SQLGuard + 数值校验 |
| G 治理 | ★★★ | ★★★★ | A/B 类分离 + 审计链 + 工具权限 |

---

## 第三章：迭代执行计划（13 个迭代）

### 迭代依赖图

```
I-1  工程基建+测试修复
 │
 └─→ I-1b Harness 加固
      │
      ├─→ I-2 报告生成 ─→ I-3 图表生成
      │                      │
      │                      └─→ I-3b 上下文+可观测性
      │
      ├─→ I-4 数据持久化 ─→ I-5 前端改进 ─→ I-5b Hook+审计
      │
      ├─→ I-6 文件解析+搜索 ─→ I-7 main.py 拆分 ─→ I-8 Plan-Execute
      │
      └─→ I-9 计算器补齐（可与 I-2~I-6 并行）
                                                        │
                                                        └─→ I-10 JS 模块化
```

**强依赖**：I-1 是所有后续迭代的前置条件。I-1b 紧跟 I-1。
**建议顺序**：I-1 → I-1b → I-2 → I-3 → I-3b → I-4 → I-5 → I-5b → I-6 → I-7 → I-8 → I-9 → I-10

---

### I-1：工程基建 + 测试修复（3-4 天）

**目标**：建立自动化质量门控 + 全部测试绿灯。

**当前问题**：
- `config.yaml` 不存在 → 8 个 agent/loop 测试 FileNotFoundError
- `ReportDegradedResult` 缺少 `success` 属性 → 1 个测试失败
- DeepSeek API key 未配置 → 1 个测试依赖外部服务
- AgentMemory 测试断言错误 → 1 个测试失败

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `pyproject.toml` | 项目元数据 + ruff 配置（line-length=120, select=E,F,W,I,UP,B）+ pytest 配置 |
| 新建 | `.env.example` | `DEEPSEEK_API_KEY=your_key_here` |
| 新建 | `.claude/settings.json` | PreCommit hook: `pytest tests/ -x -q --timeout=60` |
| 复制 | `config.example.yaml` → `config.yaml` | 开发和测试需要，加入 .gitignore |
| 修改 | `.gitignore` | 添加 `.env`、`config.yaml`、`data/*.duckdb` |
| 修改 | `agent/llm_client.py` | `ReportDegradedResult` 添加 `success = False` 属性 |
| 修改 | `tests/test_agent.py` | loop 测试用 fixture 提供 mock config；API key 测试改 mock |
| 修改 | `tests/conftest.py` | 添加 `config_fixture` 提供测试用 config dict |

**验收**：
```bash
pytest tests/ -v          # 全通过，0 失败
ruff check .              # 零错误或首次 ignore 已有代码
```

---

### I-1b：Harness 加固（3 天） ★ 新增

**目标**：修补 ETCLOVG 评估中的 T 层、V 层、E 层短板——工具参数校验、结果自检、场景过滤、统一超时。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `agent/tools_spec.py` | ① 添加 `_validate_tool_args(name, args)` 函数——从 TOOL_DEFINITIONS 提取 schema，校验 required 字段和类型；② `dispatch_tool()` 入口处调用校验，失败返回 `{"ok": False, "error": "参数校验失败: ..."}`；③ 添加 `ToolResult` dataclass（ok, data, error, warnings, metadata）；④ 添加 `_timeout_wrapper(func, timeout_sec)` 装饰所有 handler |
| 新建 | `agent/self_check.py` | `SelfChecker` 类——对 run_calculator 结果做数值合理性校验（集中度 0-100%，市值非负，净值 0.5-3.0，收益率 ±20%），返回 warnings 列表 |
| 修改 | `agent/tools_spec.py` | `_tool_run_calculator` 末尾调用 `SelfChecker.check()`，将 warnings 合入返回结果 |
| 修改 | `agent/loop.py` | 添加 `_filter_tools_for_context(tools, matched_skill)` 函数——当 skill.calc_type=="fixed" 时从工具列表中移除 run_sql |
| 新建 | `tests/test_self_check.py` | SelfChecker 单测：正常值通过、异常值告警 |
| 修改 | `tests/test_agent.py` | 添加参数校验和工具过滤的单测 |

**参数校验核心逻辑**（`agent/tools_spec.py`）：
```python
def _validate_tool_args(name: str, args: dict) -> tuple[bool, str]:
    schema = _get_tool_schema(name)  # 从 TOOL_DEFINITIONS 中按 name 查找
    if schema is None:
        return True, ""  # 未知工具交给 dispatch_map 处理
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for field in required:
        if field not in args:
            return False, f"缺少必填参数：{field}"
    for field, value in args.items():
        if field in properties:
            expected = properties[field].get("type")
            if expected == "string" and not isinstance(value, str):
                return False, f"参数 {field} 应为 string"
            if expected == "array" and not isinstance(value, list):
                return False, f"参数 {field} 应为 array"
            if "enum" in properties[field] and value not in properties[field]["enum"]:
                return False, f"参数 {field}='{value}' 不在允许范围"
    return True, ""
```

**SelfChecker 核心逻辑**（`agent/self_check.py`）：
```python
@dataclass
class CheckRule:
    field: str
    min_val: float | None
    max_val: float | None
    message: str

class SelfChecker:
    RULES: dict[str, list[CheckRule]] = {
        "entity_concentration": [
            CheckRule("concentration_pct", 0, 100, "集中度应在 0-100%"),
            CheckRule("market_value", 0, None, "市值不应为负"),
        ],
        "nav_metrics": [
            CheckRule("return_7d", -20, 20, "7日收益率超出 ±20%"),
            CheckRule("unit_nav", 0.5, 3.0, "单位净值超出 0.5-3.0"),
        ],
    }

    def check(self, calculator: str, results: list[dict]) -> list[str]:
        warnings = []
        for r in results:
            for rule in self.RULES.get(calculator, []):
                val = r.get(rule.field)
                if val is None:
                    continue
                if rule.min_val is not None and val < rule.min_val:
                    warnings.append(f"⚠️ {rule.message}：{rule.field}={val}")
                if rule.max_val is not None and val > rule.max_val:
                    warnings.append(f"⚠️ {rule.message}：{rule.field}={val}")
        return warnings
```

**场景化工具过滤**（`agent/loop.py`）：
```python
def _filter_tools_for_context(tools: list, matched_skill) -> list:
    if matched_skill and getattr(matched_skill, 'calc_type', '') == "fixed":
        return [t for t in tools if t["function"]["name"] != "run_sql"]
    return tools
```

**验收**：
```bash
pytest tests/ -v                        # 全绿
# 手动验证：合规 Skill 触发时，LLM 工具列表中不含 run_sql
# 手动验证：集中度计算结果包含 warnings 字段（如果有异常值）
```

---

### I-2：报告生成管线（4-5 天）

**目标**：实现「数据计算 → 模板渲染 → Word 导出」完整闭环。资管人 60% 时间在写报告，这是最大价值缺口。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `tools/report_builder.py` | `render_report(template_name, data) -> str` Jinja2→Markdown；`export_word(markdown, output_path) -> Path` Markdown→python-docx；`list_templates() -> list`；`ReportResult` dataclass |
| 新建 | `templates/reports/concentration_report.md.j2` | 集中度报告模板 |
| 新建 | `templates/reports/nav_report.md.j2` | 净值运作报告模板 |
| 新建 | `templates/reports/base_report.md.j2` | 报告公共头部（产品名/日期/制表人） |
| 修改 | `agent/tools_spec.py` | 添加 `generate_report` 工具定义（report_type: enum[concentration, nav, asset_structure, custom]，data: object，title: string）+ dispatch handler |
| 修改 | `main.py` | 添加 `GET /api/report/download/<filename>` 端点 |
| 修改 | `ui/index.html` | 消息流中添加报告预览卡片 + 下载 Word 按钮 |
| 新建 | `tests/test_report_builder.py` | 渲染 + Word 导出 单测 |

**验收**：
- 对话 "生成集中度报告" → Agent 调 run_calculator → 调 generate_report → 前端预览 + Word 下载
- Word 文件可用 WPS/Office 正常打开
- `pytest tests/test_report_builder.py` 全绿

---

### I-3：图表生成 + ECharts 联动（3-4 天）

**目标**：分析结果可视化。ECharts 已在前端引入但未使用。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 重写 | `tools/chart_builder.py` | `build_chart(chart_type, data, options) -> dict` 生成 ECharts option JSON；支持 pie/bar/line/waterfall |
| 修改 | `agent/tools_spec.py` | 添加 `render_chart` 工具（chart_type: enum，title: string，data: object） |
| 修改 | `agent/loop.py` | 添加 `chart` SSE 事件 yield |
| 修改 | `ui/index.html` | SSE chart 事件 → echarts.init().setOption()；支持全屏、下载 PNG |
| 新建 | `tests/test_chart_builder.py` | chart option 生成单测 |

**验收**：
- 对话 "画资产结构饼图" → ECharts 饼图渲染在前端
- 图表可全屏、可下载 PNG

---

### I-3b：上下文压缩 + 可观测性（3-4 天） ★ 新增

**目标**：修补 ETCLOVG 的 C 层（最大短板）和 O 层——实现上下文压缩、LLM 成本追踪。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `agent/context.py` | ① `build_schema_context(relevant_tables=None)` 改为三级压缩：相关表→完整 schema，其他表→仅名称+行数+类型，详细信息→profile_table 按需获取；② 新增 `compress_messages(messages, max_tokens)` 保留最近 N 轮完整消息，早期消息压缩为摘要，工具结果超 500 字符截断为统计摘要 |
| 修改 | `agent/loop.py` | 每轮 LLM 调用前调用 compress_messages；schema 注入时传入 relevant_tables（从用户消息中 @mention 提取） |
| 新建 | `tools/cost_tracker.py` | `CostTracker` 类——记录每次 LLM 调用的 input/output tokens，累计统计，估算成本（按 DeepSeek 定价），check_budget() 预算控制 |
| 修改 | `agent/llm_client.py` | chat() 返回后调用 CostTracker.record() |
| 修改 | `main.py` | `GET /api/cost` 端点返回当前会话成本统计 |
| 新建 | `tests/test_context.py` | 压缩逻辑单测：验证三级 schema 输出、消息压缩后保留关键结构 |

**三级 Schema 压缩逻辑**（`agent/context.py`）：
```python
def build_schema_context(relevant_tables: list[str] = None) -> str:
    all_tables = get_loaded_tables()
    lines = ["已加载数据表：\n"]
    for t in all_tables:
        if relevant_tables and t["name"] in relevant_tables:
            # Level 1: 完整 schema
            cols = _get_columns_from_duckdb(t["name"])
            lines.append(f"  ■ {t['name']}（{t.get('type','未知')}，{t.get('row_count',0)}行）")
            for c in cols[:30]:
                lines.append(f"    - {c['name']}（{c['type']}）")
            if len(cols) > 30:
                lines.append(f"    ... 共 {len(cols)} 列")
        else:
            # Level 2: 仅摘要
            lines.append(f"  □ {t['name']}（{t.get('type','未知')}，{t.get('row_count',0)}行）— 需要详情请用 profile_table")
    return "\n".join(lines)
```

**验收**：
- 加载 5 张表时，system prompt 中非相关表仅显示一行摘要
- `/api/cost` 返回有效的 token 统计和成本估算
- `pytest tests/test_context.py` 全绿

---

### I-4：数据持久化 + 智能上传（4-5 天）

**目标**：解决「每次启动空数据库」和「上传链条过长」两大痛点。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `tools/data_loader.py` | DuckDB 改文件模式 `data/dataagent.duckdb`；启动时恢复已有表元信息到 `_loaded_tables`；新增 `auto_detect_table_type(df)` 基于列名特征匹配；新增 `extract_date_from_filename(filename)` 正则提取日期 |
| 修改 | `main.py` `/api/upload` | 返回智能识别结果（表类型+日期+预览），用户确认后入库 |
| 修改 | `ui/index.html` | 上传后显示识别卡片：表类型、日期、行数、列数预览；确认或修正后入库 |
| 修改 | `.gitignore` | 添加 `data/*.duckdb` |
| 修改 | `tests/test_tools.py` | auto_detect 和 date_extract 单测 |

**识别规则**：
```python
HOLDING_KEYWORDS = ["持仓", "市值", "穿透", "资产代码", "持有量"]
NAV_KEYWORDS = ["净值", "累计净值", "万份收益", "七日年化"]
RATING_KEYWORDS = ["评级", "主体评级", "债项评级", "外部评级"]
```

**验收**：
- 上传 CSV → 自动识别 "持仓表 / 2026-05-15" → 确认 → 入库
- 关闭 → 重启 → 数据仍在可查询

---

### I-5：前端增量改进（3-4 天）

**目标**：降低学习成本 + 提升操作效率。不迁移框架。

**修改 `ui/index.html`**：

| 功能 | 区域 | 说明 |
|------|------|------|
| 能力推荐标签 | A | 输入框上方 [数据分析] [合规检查] [报告生成] [图表]，点击填入示例 |
| 状态条 | C | 顶栏：LLM 状态（绿/红点）+ 已加载表数 + 数据时效 |
| 结果操作按钮 | A | 表格后 [复制] [下载CSV] [生成图表] |
| 快捷操作 | B | 侧边栏快捷按钮：日报、周报、合规检查 |
| 新用户引导 | A | 无历史会话时显示欢迎面板 + 3 个示例问题 |
| 上下文推荐 | A | 加载数据后推荐相关分析 |

**新增 API**：
- `GET /api/suggestions` → 基于已加载表 + 最近查询返回推荐列表
- `GET /api/status` → LLM 连接状态 + 数据时效 + 系统健康

**验收**：
- 无数据时看到欢迎面板 + 能力标签
- 上传持仓表后推荐区显示相关分析
- 复制/下载按钮正常工作

---

### I-5b：Hook 系统 + 审计加固（2-3 天） ★ 新增

**目标**：修补 O 层（可编程扩展点）和 G 层（审计完整性）。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agent/hooks.py` | `HookManager` 类，7 种事件：on_session_start, on_session_end, pre_tool_use, post_tool_use, on_data_load, on_error, on_agent_turn_end。register(event, callback) + emit(event, context)。同步调用，失败不阻塞主流程 |
| 修改 | `agent/loop.py` | 在工具调用前后 emit pre_tool_use / post_tool_use |
| 修改 | `tools/data_loader.py` | 数据加载完成后 emit on_data_load |
| 修改 | `main.py` | 会话开始/结束 emit 对应事件 |
| 修改 | `tools/compliance_audit.py` | 每条日志包含前一条的 SHA256 hash（hash chain），首条 hash 为固定种子 |
| 新建 | `tests/test_hooks.py` | Hook 注册、触发、异常隔离 单测 |

**Hook 核心设计**（`agent/hooks.py`）：
```python
class HookManager:
    EVENTS = [
        "on_session_start", "on_session_end",
        "pre_tool_use", "post_tool_use",
        "on_data_load", "on_error", "on_agent_turn_end",
    ]

    def __init__(self):
        self._hooks = {e: [] for e in self.EVENTS}

    def register(self, event: str, callback):
        if event in self._hooks:
            self._hooks[event].append(callback)

    def emit(self, event: str, context: dict = None) -> list:
        results = []
        for cb in self._hooks.get(event, []):
            try:
                r = cb(context or {})
                if r is not None:
                    results.append(r)
            except Exception:
                pass  # Hook 异常不阻塞主流程
        return results
```

**验收**：
- 注册 post_tool_use hook → 工具调用后 hook 被触发
- 合规审计日志含 prev_hash 字段，可验证链式完整性

---

### I-6：文件解析 + 联网搜索（4-5 天）

**目标**：支持 Word/PDF 文档读取 + 投研搜索。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `tools/file_reader.py` | `read_document(path) -> DocumentResult`（python-docx + pypdf2），提取文本+表格 |
| 新建 | `tools/web_search.py` | `search(query, type) -> list[SearchResult]`（duckduckgo-search），支持 news/policy/general |
| 修改 | `agent/tools_spec.py` | 添加 read_document + web_search 工具定义和 dispatch handler |
| 修改 | `requirements-dev.txt` | 添加 `duckduckgo-search>=6.0`、`pypdf2>=3.0` |
| 修改 | `main.py` `/api/upload` | 支持 .docx/.pdf 上传 → file_reader 解析 → 内容预览 |
| 新建 | `tests/test_file_reader.py` | 单测 |
| 新建 | `tests/test_web_search.py` | 单测（mock HTTP） |

**验收**：
- 上传 Word → Agent 读取 → 对话 "总结文档要点"
- 对话 "搜索 XX 集团最近新闻" → 搜索结果摘要

---

### I-7：main.py 拆分 + 会话隔离（4-5 天）

**目标**：main.py 800+ 行 → <120 行 + Blueprint 模块 + SessionStore。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `api/__init__.py` | `register_blueprints(app)` |
| 新建 | `api/chat.py` | /api/chat, /api/stream, /api/confirm |
| 新建 | `api/data.py` | /api/upload, /api/tables |
| 新建 | `api/config.py` | /api/config, /api/groups |
| 新建 | `api/skill.py` | /api/skill-builder/*, /api/skills |
| 新建 | `api/report.py` | /api/report/* |
| 新建 | `api/system.py` | /api/health, /api/logs, /api/suggestions, /api/status, /api/cost |
| 新建 | `session_store.py` | SessionStore 类：每个 Session 独立 messages/pending/turn_count |
| 修改 | `main.py` | 精简为 app 创建 + Blueprint 注册 + 启动（目标 <120 行） |

**验收**：
- 现有 API 全部正常（回归测试 `pytest tests/`）
- 两个标签页独立会话
- main.py < 120 行

---

### I-8：Agent 规划层 Plan-Execute（5 天）

**目标**：复杂多步任务从 ReAct 循环升级为计划-执行模式。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `agent/planner.py` | `create_plan(intent, tools, tables) -> ExecutionPlan`；LLM 分解为 `[{step_id, tool, args_template, depends_on, description, status}]` |
| 新建 | `agent/executor.py` | `execute_plan(plan, ctx) -> Generator[SSEEvent]`；按 DAG 执行；失败回 planner 重规划 |
| 修改 | `agent/loop.py` | 入口判断复杂度（匹配多步 Skill 或关键词 "报告"/"要点"/"汇总"）→ 走 Plan-Execute；简单查询保持 tool-calling |
| 修改 | `ui/index.html` | 执行计划卡片：步骤列表 + 当前位置 + 可勾选/跳过 |
| 新建 | `tests/test_planner.py` | 计划分解 + 执行顺序单测 |

**验收**：
- 对话 "准备参谈要点" → 展示计划 → 确认 → 按步执行 → 汇总
- 简单查询不显示计划卡片
- 某步失败 → 重规划或跳过 → 最终结果完整

---

### I-9：计算器补齐 + 上下文推荐（4 天）

**目标**：补齐资管核心指标 + 智能推荐。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `calculators/position_diff.py` | 两期持仓变动（新增/减持/清仓/不变） |
| 新建 | `calculators/leverage.py` | 杠杆率（正回购口径） |
| 新建 | `calculators/liquidity.py` | 高流动性资产比例 |
| 新建 | `agent/recommender.py` | `get_suggestions(tables, queries, time) -> list[str]`；基于数据/时间/历史推荐 |
| 修改 | `agent/tools_spec.py` | run_calculator enum 添加 position_diff / leverage / liquidity |
| 新建 | `tests/test_calculators_extended.py` | 新计算器单测，覆盖率 >= 95% |

**验收**：
- 对话 "对比两期持仓" → 表格展示变动
- 新计算器覆盖率 >= 95%

---

### I-10：前端 JS 模块化 + 整体打磨（4-5 天）

**目标**：index.html 从 1800 行拆分为可维护的模块结构。

**文件清单**：

| 操作 | 文件 | 说明 |
|------|------|------|
| 拆分 | `ui/js/app.js` | 入口 + 全局状态 |
| 拆分 | `ui/js/chat.js` | 对话逻辑 + 消息渲染 |
| 拆分 | `ui/js/sse.js` | SSE 事件处理 |
| 拆分 | `ui/js/upload.js` | 文件上传 |
| 拆分 | `ui/js/sidebar.js` | 侧边栏 |
| 拆分 | `ui/js/charts.js` | ECharts 渲染 |
| 拆分 | `ui/js/report.js` | 报告预览 + 导出 |
| 修改 | `ui/index.html` | 只保留 HTML 结构 + CSS + script 引用 |
| 修改 | `main.py` | 静态文件服务支持 ui/js/ |
| 更新 | `CLAUDE.md` | 更新为 v2.0 |
| 更新 | `PROGRESS.md` | 记录全部完成迭代 |

**验收**：
- 前端功能完全不变
- `pytest tests/` 全绿 + 覆盖率 >= 70%
- 手动冒烟：上传 → 分析 → 图表 → 报告 → 导出 Word 完整闭环

---

## 第四章：迭代标准流程

### 开始前
1. 阅读 `CLAUDE.md` + `PROGRESS.md` + 本文件对应迭代章节
2. `pytest tests/ -x` 确认基线全绿
3. `git checkout -b I-N/描述` 创建迭代分支

### 结束时
1. `ruff check .` 零错误
2. `pytest tests/ -x --cov` 全绿 + 覆盖率不降
3. 手动冒烟：`python main.py` → 浏览器打开 → 验收功能
4. 更新 `PROGRESS.md` 记录完成状态
5. `git commit` + `git push`
6. 合并到主分支

---

## 第五章：工作量总览

| 迭代 | 天数 | 重点 | ETCLOVG 层 |
|------|------|------|-----------|
| I-1 | 3-4 | 工程基建 + 测试修复 | — |
| I-1b | 3 | Harness 加固 | T + V + E |
| I-2 | 4-5 | 报告生成 | 功能 |
| I-3 | 3-4 | 图表生成 | 功能 |
| I-3b | 3-4 | 上下文压缩 + 成本追踪 | C + O |
| I-4 | 4-5 | 数据持久化 | 功能 |
| I-5 | 3-4 | 前端改进 | UX |
| I-5b | 2-3 | Hook + 审计 | O + G |
| I-6 | 4-5 | 文件解析 + 搜索 | 功能 |
| I-7 | 4-5 | main.py 拆分 | 架构 |
| I-8 | 5 | Plan-Execute | L |
| I-9 | 4 | 计算器补齐 | 功能 |
| I-10 | 4-5 | JS 模块化 | UX |
| **合计** | **~50 天** | | |

---

## 第六章：成功指标

| 维度 | 指标 | 达成时间 |
|------|------|---------|
| 功能闭环 | 上传→分析→报告→导出 Word 可用 | I-2 后 |
| Harness 质量 | ETCLOVG 每层 ≥ ★★★ | I-5b 后 |
| Agent 可靠性 | 复杂任务完成率 > 80% | I-8 后 |
| 用户体验 | 新用户 5 分钟内完成首次分析 | I-5 后 |
| 工程质量 | 测试 100% 通过，覆盖率 > 70% | I-1 后持续 |
| 可维护性 | 单文件 < 300 行，模块职责清晰 | I-7/I-10 后 |

---

## 参考资料

- [Awesome Harness Engineering](https://github.com/ai-boost/awesome-harness-engineering) — 200+ 资源汇编
- [Dive into Claude Code](https://github.com/VILA-Lab/Dive-into-Claude-Code) — Claude Code 架构分析（512K 行代码、6 层 Harness、7 重安全）
- [Agent Harness Engineering: A Survey](https://openreview.net/forum?id=3hXEPbG0dh) — ETCLOVG 七层分类法
- [OpenClaw Architecture](https://vallettasoftware.com/blog/post/openclaw-architecture-diagram-2026) — Gateway + Node-Host 架构
