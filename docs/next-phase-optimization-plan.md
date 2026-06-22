# DataAgent 三个优化方向设计方案

## Context

用户在 Windows UAT 期间提出三个架构层面的优化方向，涉及数据治理、文件处理和金融计量能力：

1. **同类表重叠列名问题**：上传持仓表 + 底层持仓表时，两表存在相同或同义列名，在上传/治理/使用各阶段如何处理
2. **Excel 多 Sheet + 编码问题**：xls/xlsx 格式处理、多 Sheet 枚举与选择
3. **复杂金融计量需求**：当前版本是否支持，以及如何借助现有能力实现

本计划仅做设计，不做代码改动。

---

## 方向一：同类表重叠/同义列名处理

### 问题分析

当前数据流中存在一个正确性隐患和两个体验缺口：

| 问题 | 位置 | 严重程度 |
|------|------|---------|
| `get_all_field_maps()` 合并多表映射时后表覆盖前表 | `tools/data_loader.py:210-219` | **Bug**（静默丢失映射） |
| 上传时无跨表列名重叠检测 | `tools/quality.py` | 体验缺口 |
| LLM 生成 SQL 时无跨表列名消歧指导 | `agent/context.py` | 查询质量 |

**具体场景**：用户上传"持仓表"和"底层持仓表"，两者都有"产品名称""市值"等列，但：
- "产品名称"在两表中可能映射到不同物理列（`产品简称` vs `理财产品名称`）
- "市值"在两表中含义不同（一个是穿透后市值，一个是估值市值）
- LLM 生成 `SELECT "产品名称" FROM ...` 不带表限定，DuckDB 报 ambiguous column

### 方案设计

#### 阶段 A：修复字段映射合并 Bug（P0，正确性）

**改动文件**：`tools/data_loader.py`、`agent/tool_dispatch.py`、`tools/query_runner.py`

1. **新增 `get_qualified_field_maps()`**（`data_loader.py`）：返回 `dict[str, dict[str, str]]`（表名→{语义名→物理列}），替代当前的扁平合并
2. **新增 `apply_field_map_qualified()`**（`query_runner.py`）：基于 sqlglot AST 判断 Column 节点所属表：
   - 有表限定（`table.col`）→ 查对应表的映射
   - 无限定但仅一张表有此语义名 → 自动映射
   - 多表有同名语义名 → 不替换，交给 DuckDB 报错触发 Agent 自愈重试
3. **修改 `_tool_run_sql()`**（`tool_dispatch.py:153`）：调用新函数替代 `get_all_field_maps()`
4. **保留旧 `get_all_field_maps()`**：加注释标记弃用，保持兼容

#### 阶段 B：上传时跨表重叠检测（P1，体验）

**改动文件**：`tools/quality.py`、`tools/data_loader.py`、`api/data.py`、`ui/js/upload.js`

1. **新增 `detect_column_overlaps()`**（`quality.py`）：新表加载后扫描已有表：
   - 物理列名直接匹配（`new_columns & existing_columns`）
   - 语义名匹配但物理列不同（真冲突，需提醒）
   - 语义名+物理列都相同（JOIN 候选键，可建议关系）
   - 返回结构化重叠报告
2. **`LoadResult` 新增 `column_overlaps` 字段**（`data_loader.py`）
3. **上传确认响应包含 overlaps**（`api/data.py`）
4. **前端渲染重叠提示**（`upload.js`）：折叠面板，如"此表与 holding_20260515 共享列名'产品名称'（映射到不同物理列），跨表查询时请注意区分"

#### 阶段 C：LLM 上下文消歧增强（P1，查询质量）

**改动文件**：`agent/context.py`、`prompts/system_prompt.txt`

1. **`build_schema_context()` 新增"跨表列名指南"段落**：
   - 构建反向索引 `{物理列名: [所在表]}` → 出现在 2+ 张表的列名列出
   - 同义列（同语义名不同物理列）→ 明确标注
   - 指令：跨表查询必须用 `"表名"."列名"` 限定格式
2. **system prompt 新增规则**：写 SQL 引用出现在多张表中的列时，必须用表限定引用

### 风险

- 阶段 A 改动面小（`get_all_field_maps` 仅一处调用），向后兼容
- 阶段 B 仅增加信息展示，不阻断上传流程
- 阶段 C 依赖 LLM 遵循指令，但 Agent 自愈重试已覆盖"ambiguous column"错误场景

### 验证

- 上传两张共享列名的表 → 上传确认弹窗显示重叠提示
- LLM 跨表查询生成 SQL 带表限定 → 或自愈重试成功
- 单元测试：`test_column_overlap.py`（mock 两表相同列名 → 检测结果正确）

---

## 方向二：Excel 多 Sheet + 编码处理

### 问题分析

| 现状 | 问题 |
|------|------|
| `pd.read_excel(file_path, dtype=str)` | 仅读首个 Sheet，无选择 |
| CSV 有多编码竞争评分 | Excel 二进制格式不需要文本编码检测（xlsx=XML/ZIP, xls=BIFF），但 xls 内部字符集可能有问题 |
| 无 Sheet 枚举 | 用户看不到文件有几个 Sheet |
| 无合并单元格处理 | openpyxl 自动填充合并区域，但可能导致误判列名 |

**编码说明**：xlsx 是 ZIP 压缩的 XML，内部固定 UTF-8，不存在编码问题。xls (BIFF) 格式由 xlrd 处理，也自带字符集信息。所以 Excel 文件的"编码"问题本质上不存在 — 不需要像 CSV 那样做编码检测。真正的问题是：
- 列名行不在第一行（标题行/合并单元格）
- 数值被 Excel 格式化（日期、百分比、千分位）
- 隐藏 Sheet 或过滤状态

### 方案设计

#### 阶段 A：Sheet 枚举与预览（P1，核心功能）

**改动文件**：`tools/data_loader.py`、`api/data.py`、`ui/js/upload.js`、`ui/index.html`

1. **新增 `enumerate_sheets()`**（`data_loader.py`）：
   ```python
   def enumerate_sheets(file_path: str) -> list[dict]:
       """返回 [{name, index, row_estimate, col_count, is_hidden}]"""
   ```
   - xlsx：用 `openpyxl.load_workbook(read_only=True)` 获取 `wb.sheetnames` + 每个 sheet 的 `max_row`/`max_column`/`sheet_state`
   - xls：用 `pd.ExcelFile(file_path).sheet_names`（xlrd 如不可用则 graceful fallback）
   - CSV：返回单元素列表 `[{"name": "Sheet1", ...}]`

2. **修改 `/api/upload`**（`api/data.py`）：
   - Excel 文件调用 `enumerate_sheets()` 后返回 `sheets` 列表
   - 预览读取接受 `sheet_name` 参数：`pd.read_excel(file_path, sheet_name=..., dtype=str, nrows=3)`
   - 响应新增 `multi_sheet: true/false`

3. **新增 `/api/upload/preview_sheet`**（`api/data.py`）：
   ```
   POST {file_path, sheet_name} → {columns, preview_rows, detected_type, detected_date}
   ```
   用于切换 Sheet 时实时刷新预览

4. **前端 Sheet 选择器**（`upload.js` + `index.html`）：
   - 上传确认弹窗新增"选择工作表"区域（仅多 Sheet 时显示）
   - 水平 tab 条，点击切换调用 `/api/upload/preview_sheet`
   - 可选"将所有工作表分别导入"复选框

#### 阶段 B：load_file 支持 Sheet 参数（P1）

**改动文件**：`tools/data_loader.py`、`api/data.py`

1. **`load_file()` 新增 `sheet_name` 参数**（默认 None = 首个 Sheet，向后兼容）
2. **`/api/upload/confirm` 接受 `sheet_name`**
3. **批量模式**：接受 `sheets: [name1, name2]`，循环调用 `load_file()`，表名加 Sheet 后缀

#### 阶段 C：Excel 特有格式处理（P2，健壮性）

**改动文件**：`tools/data_loader.py`

1. **列名行自动检测**：
   ```python
   def detect_header_row(file_path, sheet_name=0) -> int:
       """读取前 5 行，判断哪行是真正的列名行"""
   ```
   启发式：行 0 如果只有 1-2 个非空单元格（合并标题行特征），跳过尝试行 1
2. **合并单元格提醒**：openpyxl 检测 `ws.merged_cells`，有合并时在 quality_report 中添加警告
3. **数值格式清理**：复用现有 `clean_thousands_separator()`，对百分比格式（`12.5%`→`0.125`）添加处理

### 依赖

- `openpyxl`：已在 requirements.txt（xlsx 引擎）
- `xlrd`：需新增到 requirements.txt（xls 引擎），作为可选依赖 `try/except ImportError`

### 风险

- 所有改动向后兼容（`sheet_name=None` = 现有行为）
- openpyxl `read_only=True` 模式低内存开销
- xls 格式日益少见，xlrd 为可选依赖即可

### 验证

- 上传多 Sheet xlsx → 显示 Sheet 选择器 → 切换 Sheet 预览更新
- 选择非首个 Sheet → 正确加载为 DuckDB 表
- 单 Sheet 文件 → Sheet 选择器不显示（与现有行为一致）
- 测试：`test_excel_multisheet.py`（用 openpyxl 创建测试 xlsx fixture）

---

## 方向三：复杂金融计量需求

### 当前能力评估

DataAgent 已有三层分析能力：

| 层级 | 机制 | 覆盖场景 | 限制 |
|------|------|---------|------|
| **固化计算器**（7个） | Python 函数 + DuckDB SQL | 集中度/净值/资产结构/评级/杠杆/流动性/持仓变动 | 不可扩展（需改代码） |
| **探索式 SQL** | LLM 生成 + SQLGuard | 任意 SELECT 查询 | 单次 ≤1000 行，30s 超时 |
| **多步编排** | Plan-Execute + Skills | 多工具组合分析 | 依赖 LLM 推理质量 |

**DuckDB 已支持的高级 SQL 能力**（用户可能不知道可以用）：
- 窗口函数：`LAG`/`LEAD`/`ROW_NUMBER`/`RANK`/`NTILE` → 时序分析
- 统计聚合：`STDDEV`/`VARIANCE`/`CORR`/`PERCENTILE_CONT` → 风险指标
- 日期运算：`DATEDIFF`/`DATE_TRUNC` → 期限分析
- CTE + 子查询 → 多步复杂计算

### 三层扩展策略

#### Tier A：SQL 可解 — 新增探索式 Skills（零代码改动）

通过创建新 SKILL.md 文件，引导 LLM 生成正确的 SQL，利用 DuckDB 已有能力：

| 新 Skill | 计算内容 | SQL 核心 |
|---------|---------|---------|
| `duration_analysis` | 加权平均剩余期限 | `SUM("剩余期限" * "穿透后市值") / SUM("穿透后市值")` |
| `risk_metrics` | HHI 集中度指数 | `SUM(POWER(ratio, 2))` |
| `maturity_profile` | 期限结构分布 | `CASE WHEN "剩余期限" < 1 THEN '0-1Y' ...` + `GROUP BY` |
| `period_comparison` | 多期对比分析 | `JOIN` 两张同类表 + 计算变动率 |
| `percentile_analysis` | 分位数分析 | `PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ...)` |

**实施**：在 `skills/` 目录下创建对应 SKILL.md，`calc_type: exploratory`，包含触发词、执行步骤、SQL 示例。

**优先级**：P1（立即可做，用户价值高，零风险）

#### Tier B：需 Python 计算 — 新增固化计算器模块

DuckDB SQL 无法优雅实现的计算，需 Python 从 DuckDB 取数后处理：

| 新计算器 | 文件 | 计算内容 | 为何不能纯 SQL |
|---------|------|---------|-------------|
| **VaR** | `calculators/risk_analytics.py` | 历史 VaR / CVaR | 需累积收益率序列 + 分位数 |
| **久期** | `calculators/duration_calc.py` | 修正久期 / 凸性近似 | 需现金流折现迭代 |
| **归因** | `calculators/attribution.py` | Brinson 归因分析 | 需对标基准 + 多步交叉计算 |

**实施模式**（以 VaR 为例）：
```python
# calculators/risk_analytics.py
def calc_historical_var(conn, nav_table, lookback_days=250, confidence=0.95, cols=None):
    # 1. 从 DuckDB 取日净值数据
    # 2. pandas 计算日收益率
    # 3. 历史 VaR = np.percentile(returns, (1-confidence)*100)
    # 4. CVaR = returns[returns <= var].mean()
    # 5. 返回 VaRResult dataclass
```

**注册路径**：
- `agent/tool_defs.py`：TOOL_DEFINITIONS 中 run_calculator 的 enum 新增选项
- `agent/tool_dispatch.py`：新增 `_run_risk_var()` dispatch 函数
- `agent/fast_path.py`：可选添加快速路径

**优先级**：P2（需编写代码+测试，先做 VaR 和久期）

#### Tier C：需 scipy/numpy — 高级量化（远期）

| 能力 | 依赖 | 场景 |
|------|------|------|
| Monte Carlo VaR | numpy.random | 模拟型风险计量 |
| 收益率曲线拟合（Nelson-Siegel） | scipy.optimize | 利率风险分析 |
| 凸性精确计算 | numpy 向量化 | 债券组合估值 |
| 情景分析 | numpy 矩阵 | 压力测试 |

**实施**：numpy/scipy 作为可选依赖（`try: import numpy`），不可用时返回明确提示。PyInstaller 打包会增加 ~50MB，在 `requirements-prod.txt` 中标注可选。

**优先级**：P3（远期，需求确认后再做）

### 推荐用户工作流（基于现有能力）

即使不添加任何新代码，用户也可以通过以下方式实现复杂分析：

1. **自定义 Skill 创建**：通过 Skill Builder（`#/rules` 页面）描述分析需求 → LLM 生成 SKILL.md → 校验发布 → 一键执行
2. **多步对话**：直接在 Chat 中描述复杂需求，Agent Plan-Execute 自动分步（如"帮我分析持仓的期限结构分布，按产品分组，算出每个产品 0-1Y / 1-3Y / 3-5Y / 5Y+ 的市值占比"）
3. **组合使用**：先执行固化计算器（集中度/净值），再追加探索式查询（LLM 生成交叉分析 SQL）

### 数据可用性约束

| 计算 | 必需数据列 | 当前持仓表通常有 | 是否可行 |
|------|-----------|----------------|---------|
| 加权平均期限 | 剩余期限 + 市值 | 通常有 | 立即可做 |
| HHI 集中度 | 主体 + 市值 | 有 | 立即可做 |
| 期限分布 | 剩余期限 + 市值 | 通常有 | 立即可做 |
| 修正久期 | 票面利率 + 到期收益率 + 期限 | 可能缺票息/收益率 | 有数据时可做 |
| VaR | 历史日净值序列（250+天） | 需多日净值表 | 数据量足时可做 |
| Brinson 归因 | 基准权重 + 收益 | 需额外基准数据 | 需新增基准表类型 |

### 验证

- Tier A Skills：创建 → 上传对应数据 → Chat 中触发 → 结果正确
- Tier B 计算器：单元测试（已知参考值对比）+ 集成测试（从上传到计算全流程）
- 所有新计算器遵循现有模式：`cols=None` 参数、`resolve_columns()` 调用、SelfChecker 校验

---

## 全局实施优先级

| 序号 | 任务 | 方向 | 优先级 | 改动范围 | 风险 |
|------|------|------|--------|---------|------|
| 1 | 修复 `get_all_field_maps()` 合并覆盖 Bug | 方向一-A | **P0** | 3 文件 | 低（仅一处调用） |
| 2 | 创建 4-5 个量化分析 Skills | 方向三-A | P1 | 仅新增 SKILL.md | **零** |
| 3 | Excel 多 Sheet 枚举与选择 | 方向二-A/B | P1 | 4 文件 + 新端点 | 低（向后兼容） |
| 4 | LLM 跨表列名消歧指导 | 方向一-C | P1 | 2 文件 | 低 |
| 5 | 上传时跨表重叠检测提示 | 方向一-B | P2 | 4 文件 | 低 |
| 6 | VaR / 久期计算器 | 方向三-B | P2 | 新文件 + 注册 | 中（需测试验证精度） |
| 7 | Excel 格式特殊处理 | 方向二-C | P2 | 1 文件 | 低 |
| 8 | scipy 高级量化 | 方向三-C | P3 | 新文件 + 可选依赖 | 打包体积增加 |

---

## 关键文件清单

| 文件 | 方向一 | 方向二 | 方向三 |
|------|--------|--------|--------|
| `tools/data_loader.py` | 修改（qualified maps） | 修改（enumerate_sheets, sheet_name 参数） | — |
| `tools/query_runner.py` | 修改（qualified apply） | — | — |
| `agent/tool_dispatch.py` | 修改（调用新函数） | — | 修改（注册新计算器） |
| `agent/context.py` | 修改（跨表列名指南） | — | — |
| `tools/quality.py` | 修改（overlap 检测） | — | — |
| `api/data.py` | 修改（返回 overlaps） | 修改（Sheet 枚举/预览端点） | — |
| `ui/js/upload.js` | 修改（显示重叠提示） | 修改（Sheet 选择器） | — |
| `agent/tool_defs.py` | — | — | 修改（新增计算器枚举） |
| `calculators/risk_analytics.py` | — | — | 新建 |
| `calculators/duration_calc.py` | — | — | 新建 |
| `skills/duration_analysis/SKILL.md` | — | — | 新建 |
| `skills/risk_metrics/SKILL.md` | — | — | 新建 |
| `skills/maturity_profile/SKILL.md` | — | — | 新建 |
