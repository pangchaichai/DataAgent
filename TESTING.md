# DataAgent 测试策略与执行指南

> **本文件是 Claude Code 在 Linux 研发环境中执行测试的权威指南。**
> 每次迭代测试前，必须阅读本文件和 `data/test_reports/latest_summary.json`。

---

## 一、目标与原则

### 1.1 测试目标
- **正确性保障**：数字的正确性和可追溯性高于一切（第一性约束）
- **回归防护**：每次迭代后，已有功能不被破坏
- **质量度量**：可量化的覆盖率指标，可追溯的测试记录
- **迭代适应**：测试体系随项目演进自动扩展，而非重写

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **固化计算零容忍** | calculators/ 下的合规计算必须 100% 分支覆盖，任何口径变更必须先改测试再改代码 |
| **测试先行于修复** | 发现 bug 时，先写一个红色测试复现它，再修代码让它变绿 |
| **分层隔离** | 单元测试不依赖网络/LLM/文件系统，集成测试用 fixture 隔离 |
| **记录留存** | 每次测试运行自动生成 JSON 摘要 + 覆盖率报告，存入 `data/test_reports/` |
| **增量思维** | 迭代测试只关注变更影响范围，但回归套件必须全跑 |

---

## 二、测试分层体系

```
┌─────────────────────────────────────────────────┐
│  L4 冒烟测试 (smoke)                             │
│  启动 → 页面可访问 → 上传 CSV → 查询返回结果       │
├─────────────────────────────────────────────────┤
│  L3 集成测试 (integration)                       │
│  多模块协作：加载CSV → 字典映射 → Agent查询 → 结果  │
├─────────────────────────────────────────────────┤
│  L2 模块测试 (module)                            │
│  单个模块的公开接口：SQLGuard.validate()等         │
├─────────────────────────────────────────────────┤
│  L1 单元测试 (unit)                              │
│  纯函数/方法：编码检测、千分位清洗、主体归一等       │
└─────────────────────────────────────────────────┘
```

### 各层运行时机

| 层级 | 运行时机 | 预期耗时 | 失败阻断 |
|------|---------|---------|---------|
| L1 单元 | 每次代码修改后 | <5s | 是，阻断提交 |
| L2 模块 | 每次模块修改后 | <15s | 是 |
| L3 集成 | 每次迭代完成后 | <30s | 是 |
| L4 冒烟 | 每次启动前 | <10s | 否，仅告警 |

---

## 三、测试覆盖范围（基线版）

### 3.1 模块覆盖矩阵

| 模块 | 测试文件 | 关键测试场景 | 最低覆盖率 |
|------|---------|------------|----------|
| **calculators/concentration** | test_calculators.py | 单主体集中度、集团合并、阈值过滤、零总值跳过、多产品 | 95% |
| **calculators/nav_metrics** | test_calculators.py | 净值计算、年化收益、产品过滤 | 95% |
| **calculators/asset_structure** | test_calculators.py | 资产结构、Top-N、产品维度/全局 | 95% |
| **calculators/credit_distribution** | test_calculators.py | 评级分布、评级迁移、产品过滤 | 95% |
| **calculators/position_diff** | test_calculators.py | 持仓差异计算、新增/减少/变化明细 | 95% |
| **calculators/leverage** | test_calculators.py | 杠杆率计算、产品维度 | 95% |
| **calculators/liquidity** | test_calculators.py | 流动性指标、分级计算 | 95% |
| **tools/data_loader** | test_tools.py | GB18030/UTF-8/GBK 编码、千分位、字段映射、时效校验 | 85% |
| **tools/query_runner** | test_tools.py | SQLGuard 全规则、超时、表名校验、CTE/子查询 | 90% |
| **tools/profiler** | test_profiler.py | 空值率、样本去重、数值范围、列级剖析 | 80% |
| **tools/quality** | test_tools.py | 空值诊断、覆盖率、JOIN 兼容性、日期范围 | 80% |
| **tools/entity_normalizer** | test_tools.py | 别名归一、未知主体处理、JOIN 键校验 | 85% |
| **tools/compliance_audit** | test_tools.py | 事件写入、字段完整性、JSONL 格式 | 80% |
| **tools/report_builder** | test_report_builder.py | Jinja2 渲染、Word 导出、模板列表、标题/表格格式 | 80% |
| **tools/chart_builder** | test_chart_builder.py | 5 种图表类型、自动选型、ECharts 配置生成 | 80% |
| **tools/file_reader** | test_file_reader.py | Word/PDF 解析、文本提取、字数统计 | 75% |
| **tools/web_search** | test_web_search.py | DuckDuckGo 搜索、结果截断、异常处理 | 75% |
| **tools/cost_tracker** | test_hooks.py | Token 计费、会话累计、用量报告 | 75% |
| **tools/skill_builder** | (集成测试) | SKILL.md 生成、校验（格式/安全/质量）、草稿管理 | 75% |
| **agent/llm_client** | test_agent.py | 配置加载、SQL 提取、function-calling 解析、降级处理 | 75% |
| **agent/loop** | test_agent.py | 工具调度、暂停续跑、最大轮次、错误分类自愈 | 80% |
| **agent/tools_spec** | test_agent.py | 5 工具分发、参数校验、结果格式 | 80% |
| **agent/skill_loader** | test_agent.py | 注册表加载、calc_type 校验、Skill 检测 | 75% |
| **agent/memory** | test_agent.py | 存取纠正、BM25 检索、开关控制 | 80% |
| **agent/hooks** | test_hooks.py | 事件钩子、SHA-256 hash chain、审计完整性 | 80% |
| **agent/self_check** | test_self_check.py | 结果自检、异常检测、置信度评分 | 75% |
| **agent/context** | test_context.py | 三级压缩、Token 预算、历史截断 | 80% |
| **agent/planner** | test_planner.py | 规划触发条件、Plan 生成、步骤分解 | 80% |
| **agent/executor** | test_executor.py | 按步骤执行、步骤追踪、失败处理 | 80% |
| **platform_adapter/** | test_platform.py | 浏览器驱动选择、控制台通知回退 | 70% |

### 3.2 安全关键测试（必须 100% 通过）

这些测试失败时 **必须阻断** 后续开发：

```
tests/test_tools.py::TestSQLGuard::*           # SQL 注入防护
tests/test_calculators.py::*                    # 合规计算口径
tests/test_tools.py::*encoding*                 # 编码正确性
tests/test_agent.py::TestToolCallingLoop::*     # Agent 工具调度安全
```

---

## 四、迭代测试流程（核心方法论）

### 4.1 迭代测试三步法

每次项目迭代后，Claude Code 按以下流程执行测试：

```
步骤 1: 变更分析（Impact Analysis）
  ┌─ git diff --name-only HEAD~N  →  获取变更文件列表
  ├─ 分类：哪些是源码、哪些是配置、哪些是测试
  ├─ 影响范围推断：变更模块的上下游依赖
  └─ 输出：受影响模块列表 + 需要运行的测试集

步骤 2: 测试执行（Test Execution）
  ┌─ 运行受影响模块的直接测试
  ├─ 运行上下游依赖模块的回归测试
  ├─ 运行全量测试套件（pytest tests/ -v）
  └─ 生成覆盖率报告

步骤 3: 差距分析（Gap Analysis）
  ┌─ 对比变更前后覆盖率
  ├─ 识别新增代码中未覆盖的分支
  ├─ 补充缺失测试
  └─ 更新测试记录
```

### 4.2 变更 → 测试映射规则

| 变更文件 | 直接测试 | 回归测试 |
|---------|---------|---------|
| `calculators/*.py` | test_calculators.py | test_agent.py（run_calculator 路径） |
| `tools/data_loader.py` | test_tools.py::数据加载相关 | test_profiler.py, test_agent.py |
| `tools/query_runner.py` | test_tools.py::SQLGuard相关 | test_agent.py（run_sql 路径） |
| `tools/report_builder.py` | test_report_builder.py | test_agent.py |
| `tools/chart_builder.py` | test_chart_builder.py | 无 |
| `tools/file_reader.py` | test_file_reader.py | 无 |
| `tools/web_search.py` | test_web_search.py | 无 |
| `tools/skill_builder.py` | 集成测试（/api/skill-builder/*） | 无 |
| `tools/cost_tracker.py` | test_hooks.py | 无 |
| `agent/loop.py` | test_agent.py::TestAgentLoop* | 全量 |
| `agent/llm_client.py` | test_agent.py::TestLLMClient | test_agent.py::TestToolCallingLoop |
| `agent/tools_spec.py` | test_agent.py::TestToolCallingLoop | 全量 |
| `agent/hooks.py` | test_hooks.py | test_agent.py |
| `agent/self_check.py` | test_self_check.py | test_agent.py |
| `agent/context.py` | test_context.py | test_agent.py |
| `agent/planner.py` | test_planner.py | test_executor.py |
| `agent/executor.py` | test_executor.py | test_agent.py |
| `tools/profiler.py` | test_profiler.py | test_agent.py（profile_table 路径） |
| `tools/quality.py` | test_tools.py::TestQuality* | test_agent.py |
| `agent/memory.py` | test_agent.py::TestAgentMemory | 无 |
| `agent/skill_loader.py` | test_agent.py::TestSkillLoader | test_agent.py::TestAgentLoop* |
| `platform_adapter/*.py` | test_platform.py | 无 |
| `api/*.py` | 集成测试（手动/UAT） | 全量 |
| `config.yaml` | 全量 | 全量 |
| `data_dictionary/*.yaml` | test_tools.py::字段映射 | test_calculators.py |
| `ui/index.html` | 冒烟测试（手动） | 无 |
| `ui/js/*.js` | 冒烟测试（手动） | 无 |
| `skills/*/SKILL.md` | test_agent.py::TestSkillLoader | 无 |

### 4.3 新模块测试要求

当迭代引入新 Python 模块时，必须同时提供：

1. **测试文件**：`tests/test_{module_name}.py`（或在现有文件中新增 TestClass）
2. **最低场景覆盖**：
   - 正常路径（happy path）× 至少 2 个用例
   - 边界条件 × 至少 1 个用例
   - 错误处理 × 至少 1 个用例
3. **fixture 复用**：优先使用 conftest.py 中的共享 fixture

---

## 五、测试执行命令参考

### 5.1 日常开发

```bash
# 运行全部测试（含覆盖率）
pytest tests/

# 仅运行快速单元测试
pytest tests/ -m "unit or calculator"

# 运行特定模块测试
pytest tests/test_calculators.py -v

# 运行匹配关键字的测试
pytest tests/ -k "concentration or sqlguard"

# 仅运行安全关键测试
pytest tests/test_tools.py -k "SQLGuard" tests/test_calculators.py -v
```

### 5.2 迭代测试

```bash
# 查看变更文件
git diff --name-only HEAD~1

# 根据变更运行受影响测试（示例：data_loader 变更）
pytest tests/test_tools.py tests/test_profiler.py tests/test_agent.py -v

# 全量回归
pytest tests/ -v --tb=long

# 覆盖率差异（需要基线）
pytest tests/ --cov-report=json:data/test_reports/coverage_current.json
```

### 5.3 测试报告查看

```bash
# 查看最新测试摘要
cat data/test_reports/latest_summary.json

# 查看覆盖率 HTML 报告
# 文件位于 data/test_reports/coverage_html/index.html

# 查看 JUnit XML（可被 CI 系统解析）
cat data/test_reports/junit.xml
```

---

## 六、测试质量标准

### 6.1 覆盖率门槛

| 模块类别 | 行覆盖率 | 分支覆盖率 |
|---------|---------|----------|
| calculators/（合规关键） | ≥ 95% | ≥ 90% |
| tools/query_runner（安全关键） | ≥ 90% | ≥ 85% |
| agent/（核心逻辑） | ≥ 80% | ≥ 70% |
| tools/（其他工具） | ≥ 80% | ≥ 70% |
| platform_adapter/ | ≥ 70% | — |

### 6.2 测试质量检查清单

每次测试编写后自查：

- [ ] 测试名称清晰表达意图：`test_集团合并后浓度正确计算` 而非 `test_func1`
- [ ] 断言具体：`assert result.concentration == 80.0` 而非 `assert result is not None`
- [ ] 使用 fixture 隔离，不依赖测试执行顺序
- [ ] 不依赖外部网络、LLM API、文件系统绝对路径
- [ ] 边界条件有覆盖：空表、零值、超长字符串、特殊编码
- [ ] 合规计算测试包含已知正确答案的验证数据

### 6.3 测试命名规范

```python
class TestEntityConcentration:
    def test_单产品基本集中度计算(self):           # 正常路径
    def test_集团合并后主体集中度聚合(self):       # 业务规则
    def test_总市值为零时跳过不报错(self):          # 边界条件
    def test_阈值过滤只返回超标主体(self):          # 过滤逻辑
    def test_不存在的产品返回空结果(self):          # 错误处理
```

---

## 七、测试记录与追溯

### 7.1 自动记录

每次 `pytest` 运行自动生成以下文件：

| 文件 | 路径 | 内容 |
|------|------|------|
| 测试摘要 | `data/test_reports/latest_summary.json` | 通过/失败数、耗时、失败用例列表 |
| 覆盖率 JSON | `data/test_reports/coverage.json` | 各模块行覆盖率 |
| 覆盖率 HTML | `data/test_reports/coverage_html/` | 可视化覆盖率报告 |
| JUnit XML | `data/test_reports/junit.xml` | CI 兼容格式 |

### 7.2 迭代测试日志

每次迭代测试完成后，Claude Code 应在 `data/test_reports/` 下生成迭代测试记录：

**文件命名**：`iteration_{date}_{brief_description}.md`

**内容模板**：

```markdown
# 迭代测试记录

- 日期: YYYY-MM-DD
- 迭代内容: [简要描述本次迭代做了什么]
- 关联 commit: [commit hash]

## 变更范围
- 修改文件: [列表]
- 影响模块: [列表]

## 测试执行
- 总用例数: X
- 通过: X | 失败: X | 跳过: X
- 覆盖率: X% (对比上次: +/-X%)
- 耗时: Xs

## 新增测试
- [新测试用例列表及说明]

## 发现问题
- [测试过程中发现的问题]

## 覆盖率变化
| 模块 | 上次 | 本次 | 变化 |
|------|------|------|------|
```

### 7.3 .gitignore 配置

`data/test_reports/` 中的 HTML 报告和大型 JSON 不提交到 git，
但 `latest_summary.json` 和迭代记录 `.md` 文件 **保留** 以便追溯。

---

## 八、Claude Code 测试执行规程

### 8.1 Claude Code 作为测试执行者的行为规范

当被要求进行测试时，Claude Code 必须：

1. **先读本文件**（TESTING.md），了解测试体系
2. **先读 latest_summary.json**，了解上次测试状态
3. **分析变更范围**，确定本次测试重点
4. **执行测试**，不跳过失败用例
5. **分析结果**，对失败用例给出根因分析
6. **补充测试**，对未覆盖的新代码编写测试
7. **生成记录**，写入迭代测试记录

### 8.2 测试失败处理优先级

| 失败类型 | 优先级 | 处理方式 |
|---------|-------|---------|
| 合规计算结果错误 | P0 | 立即修复，不得继续其他开发 |
| SQLGuard 绕过 | P0 | 立即修复 |
| Agent 工具调度错误 | P1 | 当前迭代内修复 |
| 编码检测失败 | P1 | 当前迭代内修复 |
| 覆盖率低于门槛 | P2 | 补充测试后再提交 |
| 冒烟测试失败 | P2 | 排查后修复 |

### 8.3 禁止事项

- **禁止** 删除或跳过失败的测试用例来"修复"问题
- **禁止** 在测试中 mock 掉被测逻辑本身
- **禁止** 用 `@pytest.mark.skip` 绕过暂时失败的测试（应使用 `@pytest.mark.xfail(reason="...")` 标记已知问题）
- **禁止** 合规计算测试中使用近似断言（`pytest.approx` 除非有明确的浮点精度说明）

---

## 九、持续演进机制

### 9.1 测试体系更新触发条件

以下变更发生时，必须同步更新本文件：

- 新增模块目录（如新增 `validators/`）→ 更新第三章覆盖矩阵
- 新增 calculator → 更新覆盖矩阵 + 安全关键测试列表
- 架构层变更（如新增中间件）→ 更新测试分层体系
- 覆盖率门槛调整 → 更新第六章

### 9.2 测试债务追踪

已知测试缺口（随迭代更新）：

| 模块 | 缺口描述 | 优先级 | 状态 |
|------|---------|-------|------|
| api/*.py (Blueprint 路由) | 路由端点无自动化测试，0% 覆盖率 | P1 | 待补充 |
| tools/skill_builder | validate/publish 流程无独立单测 | P2 | 待补充 |
| tools/entity_manager | 集团 CRUD 测试不完整 | P2 | 待补充 |
| ui/js/*.js | 前端 JS 无测试（需引入 JS 测试框架） | P3 | 待设计 |
| 端到端流程 | 上传→查询→结果全链路 | P2 | 待设计 |
| 内存回归 | Python 进程 <200MB 验证 | P2 | 待 Windows 环境 |

---

## 十、迭代测试计划（Iteration Test Plan）

### 10.1 为什么要先设计测试

测试后置意味着：写完功能才发现设计有缺陷，修复成本是提前发现的 5-10 倍。
**测试设计先行**的价值：
- 强迫在编码前想清楚"这个功能的成功标准是什么"
- 让 L4 UAT 场景提前明确，避免上线后才发现业务流程不通
- 给 Code Review 提供验证依据，而非依赖感觉

### 10.2 何时触发（When）

以下任一情况触发迭代测试计划：
- 新增 Python 模块（包括 api/、agent/、tools/、calculators/ 下的文件）
- 修改 Agent 循环、工具分发、SQLGuard、固化计算函数
- 新增或修改 Skill（包括 SKILL.md calc_type 变更）
- 修改前端 JS 模块（涉及 SSE 流程、数据上传、Skill 执行）
- 阶段性里程碑（Week N 完成）

### 10.3 如何操作（How）

1. 在 `data/test_plans/` 下创建 `YYYYMMDD_{迭代名}.md`
2. 按下方模板填写变更范围、影响分析、四层测试用例设计
3. 开始编码（测试计划是前置条件，不是后置记录）
4. 编码完成后，填写执行结果列
5. 在 PROGRESS.md 对应条目标注测试状态

### 10.4 存放位置（Where）

```
data/test_plans/
├── 20260614_v3_week2_skill_cards_and_nav_fix.md   ← 第一份（示例）
├── YYYYMMDD_{迭代名}.md
└── ...
```

注：`data/test_plans/` 下的文件**提交到 git**，作为质量审计记录。

### 10.5 迭代测试计划模板

```markdown
# 迭代测试计划 — {迭代名称}

- **日期**：YYYY-MM-DD
- **迭代目标**：一句话说明本次迭代要实现什么
- **预计完成**：YYYY-MM-DD
- **关联 PROGRESS.md 条目**：## v3.0 Week N — ...

---

## 一、变更范围

| 变更文件 / 模块 | 变更类型（新增/修改/删除）| 说明 |
|---------------|------------------------|------|
| api/skill_api.py | 新增 | 新增两个端点 |
| ui/js/sidebar.js | 修改 | Skill 卡片渲染 |

## 二、影响面分析

- **上游依赖**（调用本次变更模块的代码）：
- **下游依赖**（本次变更模块调用的代码）：
- **共享状态**（session_store、DuckDB 连接等）：
- **前端 SSE 流**（变更是否影响 SSE 事件结构）：

## 三、测试用例设计

### L1 — 单元测试

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L1-01 | | | P0 | todo |
| L1-02 | | | P1 | todo |

### L2 — 功能测试（模块级接口）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L2-01 | | | P0 | todo |

### L3 — 集成测试（多模块协作）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L3-01 | | | P0 | todo |

### L4 — UAT 验收场景（业务用户手动执行）

| 场景 ID | 用户角色 | 操作步骤 | 预期结果 | 验收标准 | 状态 |
|--------|---------|---------|---------|---------|------|
| U4-01 | 投资经理 | | | | 待验收 |

---

## 四、执行结果（编码完成后填写）

- **测试运行日期**：
- **pytest 结果**：X 通过 / Y 失败 / Z 跳过
- **覆盖率变化**：

### L1~L3 用例执行摘要

| 测试 ID | 实际结果 | 备注 |
|--------|---------|------|

### 已知问题 / 遗留项

- 问题描述 → 优先级 → 计划修复时间

### UAT 状态

- [ ] U4-01 — 待业务方验收
- [ ] U4-02 — 待业务方验收
```

---

## 十一、UAT 验收测试场景设计

### 11.1 UAT 的定位

UAT（用户验收测试）针对**投资业务人员**在 Windows 应用上的真实使用体验。
与 L1~L3 自动化测试不同，UAT 是**人工执行的剧本**：由测试人员（或业务用户）按步骤
在真实 Windows 环境中操作，验证系统的业务价值，而非技术正确性。

当前阶段（Linux 研发环境）：
- UAT 场景以文档形式维护在迭代测试计划中
- 技术层面的 UAT 替代：L3 集成测试覆盖业务流程的关键路径
- 真正的 UAT 在每次 Windows 内测包发布后由业务方确认

未来（v3.1 后）：可引入 Playwright 驱动浏览器模式自动化部分 UAT。

### 11.2 标准 UAT 场景库

#### 类别 A：数据上传

| 场景 ID | 用户角色 | 前置条件 | 操作步骤 | 预期结果 | 验收标准 |
|--------|---------|---------|---------|---------|---------|
| UAT-A1 | 投资经理 | 有持仓 CSV（GB18030 编码，含千分位）| 1. 点击上传 2. 选择文件 3. 确认预览 | 字段正确识别，乱码为零，行数吻合 | 预览表格与 Excel 打开一致 |
| UAT-A2 | 投资经理 | 有 2 个同类型文件（两期持仓）| 同时上传两个文件 | 系统提示"上传了2张持仓表，是否进行跨期对比？" | 提示语清晰，用户能理解 |
| UAT-A3 | 投资经理 | 文件名含特殊字符 | 上传带括号/空格文件名的 CSV | 正常上传，表名自动清洁 | 不报错，侧边栏显示该表 |

#### 类别 B：自然语言查询

| 场景 ID | 用户角色 | 前置条件 | 操作步骤 | 预期结果 | 验收标准 |
|--------|---------|---------|---------|---------|---------|
| UAT-B1 | 投资经理 | 已上传持仓表 | 输入"查一下象屿系的持仓" | 返回含象屿集团相关主体的持仓明细 | 主体归一正确，无遗漏别名 |
| UAT-B2 | 投资经理 | 已上传持仓表 | 输入"画一个饼图，按大类资产分布" | 展示饼图，类别比例正确 | 图表颜色清晰，可点击图例 |
| UAT-B3 | 投资经理 | 无任何表 | 输入任意查询 | 提示"请先上传数据" | 不报技术错误 |

#### 类别 C：Skills 执行

| 场景 ID | 用户角色 | 前置条件 | 操作步骤 | 预期结果 | 验收标准 |
|--------|---------|---------|---------|---------|---------|
| UAT-C1 | 投资经理 | 已上传持仓表 | 侧边栏点击"集中度监控"执行按钮 | 猫头鹰动画出现，返回集中度报告 | 数字与 Excel 手算一致 |
| UAT-C2 | 投资经理 | 未上传持仓表 | 侧边栏点击"集中度监控"执行按钮 | 提示"缺少持仓数据，请先上传" | 不执行，提示友好 |
| UAT-C3 | 投资经理 | 已上传持仓表 | 触发集中度监控，有主体超标 | 出现超标告警横幅，合规日志写入 | 告警主体与 Excel 一致 |
| UAT-C4 | 投资经理 | 已上传净值表 | 侧边栏点击"净值报告" | 返回含 3 类指标的格式化报告 | 数字来自 calculators/，非 LLM 生成 |

#### 类别 D：配置管理

| 场景 ID | 用户角色 | 前置条件 | 操作步骤 | 预期结果 | 验收标准 |
|--------|---------|---------|---------|---------|---------|
| UAT-D1 | 管理员 | 有内网 LLM 地址 | 设置面板填写 URL → 测试连接 | 显示"连接成功"或具体错误原因 | 不暴露技术堆栈信息 |
| UAT-D2 | 管理员 | 无 LLM 配置 | 发送查询 | 提示"请先配置 LLM" | 不崩溃 |

### 11.3 UAT 用例编写规范

```markdown
## UAT 场景：{场景名称}

**场景 ID**：UAT-XX
**用户角色**：投资经理 / 研究员 / 管理员
**优先级**：P0（核心流程）/ P1（重要功能）/ P2（边缘场景）

### 前置条件
- 系统已启动（Windows 11，DataAgent.exe 运行中）
- 已上传：{数据文件描述}
- LLM 已配置并连接正常

### 操作步骤
1. {具体操作，用非技术语言描述}
2. {等待 X 秒}
3. {继续操作}

### 预期结果
- 界面显示：{截图描述或文字描述}
- 数值正确性：{与什么对比验证}

### 验收标准（通过/失败判定）
- ✅ 通过：{具体条件}
- ❌ 失败：{具体条件}

### 验收记录
- **验收日期**：
- **验收人**：
- **结果**：通过 / 失败 / 待修复
- **备注**：
```

---

## 十二、四层测试完成关卡（Phase Gate Criteria）

### 12.1 各层通过标准

| 测试层 | 通过标准 | 执行方式 | 阻断提交？|
|-------|---------|---------|---------|
| **L1 单元** | 0 失败；覆盖率 ≥ 第六章门槛 | `pytest tests/ -m unit` 自动 | 是 |
| **L2 功能** | 测试计划中所有 L2 用例状态为 pass | `pytest tests/test_{module}.py` 自动 | 是 |
| **L3 集成** | 测试计划中所有 L3 用例状态为 pass；无回归 | `pytest tests/ -v` 全量 | 是 |
| **L4 UAT** | 场景已文档化 + 状态为"待验收"或"已验收" | 人工执行或业务方确认 | 否（不阻断技术提交）|

### 12.2 迭代"完成"的定义

**技术完成**（允许提交）：
- L1 + L2 + L3 全部通过（pytest 全绿）
- 测试计划中 L4 场景已书面记录（状态可以是"待验收"）
- PROGRESS.md 中标注：`✅ 已测（L1+L2+L3通过，L4待UAT）`

**业务完成**（Phase 可标记为 DONE）：
- 技术完成的全部条件
- L4 UAT 场景状态更新为"已验收"（业务方签字或确认）
- PROGRESS.md 中标注：`✅ 已验收`

### 12.3 P0/P1 缺口处理规则

| 缺口类型 | 处理方式 | 时限 |
|---------|---------|------|
| P0 缺口（合规计算错误 / SQLGuard 绕过 / 安全漏洞）| 立即停止其他开发，修复后才能继续 | 当场 |
| P1 缺口（Agent 调度错误 / 编码检测失败 / 核心 API 失败）| 在当前迭代内修复 | 迭代结束前 |
| P2 缺口（覆盖率未达门槛 / 边缘场景未覆盖）| 补充测试，下次迭代前修复 | 下次迭代开始前 |

### 12.4 测试状态标记约定（PROGRESS.md 使用）

```
✅ 已测（L1+L2+L3通过，L4待UAT）   ← 技术完成，可以提交
✅ 已验收                           ← 业务完成，Phase 可标记 DONE
⚠️ 部分覆盖（原因说明）              ← 有已知缺口，需在 HANDOFF.md 记录
❌ 测试失败（具体测试名）             ← 阻断状态，不得提交
🔲 未测试                           ← 尚未执行测试计划
```

### 12.5 测试债务追踪更新（补充）

在第九章 9.2 基础上，新增以下模块的覆盖状态：

| 模块 | 测试文件 | 覆盖状态 | 优先级 |
|------|---------|---------|-------|
| `agent/fast_path.py` | `tests/test_fast_path.py`（11 个测试）| ✅ 已覆盖 | — |
| `agent/execution_tracker.py` | `tests/test_fast_path.py`（JSONL 写入）| ✅ 已覆盖 | — |
| `agent/skill_preflight.py` | `tests/test_skill_preflight.py`（16 个测试）| ✅ 已覆盖 | — |
| `tools/workdir_loader.py` | `tests/test_workdir_loader.py`（9 个测试）| ✅ 已覆盖 | — |
| `api/skill_api.py`（新端点）| 待新建 `tests/test_skill_api.py` | ❌ 0% 覆盖 | P1 |
| `ui/js/sidebar.js`（Skill 卡片）| 无自动化测试（UAT-C1~C3 覆盖）| ⚠️ 仅 UAT | P2 |
| `ui/js/chat.js`（executeSkill）| 无自动化测试（UAT-C1 覆盖）| ⚠️ 仅 UAT | P2 |

---

## 附录：测试 marker 速查

```bash
pytest tests/ -m unit          # L1 纯单元测试
pytest tests/ -m integration   # L3 集成测试
pytest tests/ -m calculator    # 合规计算（必须全通过）
pytest tests/ -m sqlguard      # SQL 安全防护
pytest tests/ -m agent         # Agent 循环
pytest tests/ -m smoke         # 冒烟快速检查
pytest tests/ -m "not slow"    # 跳过慢测试
```
