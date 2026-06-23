# DataAgent 大数据量适配方案（基于真实数据样本 + 代码审计）

## 分支策略

**本次优化在新分支上开发**，不在当前 `claude/happy-euler-awvv3j` 分支上修改。
新分支名：`feature/large-data-adaptation`（从 main 分支创建）。

## Context

DataAgent 实际使用场景超出原始设计预期。根据用户提供的 14 个真实数据文件样本分析：

- **代表性样本**：用户提供的 14 个 Excel 文件代表其典型场景，但程序必须同时支持 CSV 和 Excel
- **数据量**：每日 14 个文件，原始总计 ~490MB，~115 万行
- **使用模式**：文件名含日期，结构固定，内容每日更新
- **特殊处理**：标题行、多Sheet合并、千分位分隔符、特定Sheet选择
- **兼容性要求**：所有优化必须同时适用于 CSV 和 Excel 场景，不能固化到特定文件

### 每日数据文件画像（来自真实样本分析）

| # | 文件名模式 | 格式 | 原始大小 | Sheet策略 | 行数 | 列数 | 特殊处理 |
|---|-----------|------|---------|----------|------|------|---------|
| 1 | 持仓产品管理-{YYYY-MM-DD}.xls | .xls | 285MB | 7个同构→合并 | 42万 | 61 | 标题行+千分位 |
| 2 | 底层资产持仓及债券信息表{MMDD}.xlsx | .xlsx | 76MB | 1个 | 40万 | 66 | — |
| 3 | 估值表查询({YYYY-MM-DD}).xlsx | .xlsx | 40KB | 仅Sheet1 | 400 | 12 | — |
| 4 | 监控值查询 - {timestamp}.xlsx | .xlsx | 40KB | 1个 | 40 | 18 | — |
| 5 | 净值结果管理{date}-{date}.xlsx | .xlsx | 500KB | 1个 | 3000 | 43 | 千分位 |
| 6 | 评级结果{YYYYMMDDhhmm}.xls | .xls | 14MB | 1个 | 5000 | 39 | 标题行 |
| 7 | 申赎数据{MMDD}.xlsx | .xlsx | 900KB | 仅Sheet1 | 300 | 12 | 千分位 |
| 8 | 实时资产头寸查询({YYYY-MM-DD}).xlsx | .xlsx | 2.5MB | 1个 | 6.7万 | 7 | — |
| 9 | 投资债券评级结果{YYYYMMDDhhmm}.xls | .xls | 100MB | 3个同构→合并 | 15万 | 42 | 标题行 |
| 10 | 现金流缺口分析({YYYY-MM-DD}).xlsx | .xlsx | 200KB | 1个 | 5000 | 8 | — |
| 11 | 债券质押查询({YYYY-MM-DD}).xlsx | .xlsx | 600KB | 仅Sheet1 | 5000 | 26 | — |
| 12 | 账户流水({YYYY-MM-DD}).xlsx | .xlsx | 7MB | 1个 | 6万 | 15 | 千分位 |
| 13 | 质押式回购投资交易查询({YYYY-MM-DD}).xlsx | .xlsx | 5MB | 1个 | 2.5万 | 25 | — |
| 14 | 组合资金账户头寸({YYYY-MM-DD}).xlsx | .xlsx | 500KB | 1个 | 1万 | 8 | — |

**总计**：~490MB / 115万行 / ~3500万单元格

---

## 现状诊断（基于代码审计）

### 瓶颈 1：DuckDB 内存模式无法承载 115 万行

- `_db_path = ':memory:'`（data_loader.py:56），**从未被任何代码修改**
- 注释说"生产由 main.py 设置"，但 main.py 中无此初始化代码
- `init_duckdb_connection()` 的 `max_memory="200MB"` 和 `threads=2` 是硬编码默认值
- DuckDB 初始化发生在 `api/chat.py:60` 和 `api/skill_api.py:99`（懒加载），不在 main.py
- config.yaml 中 `duckdb.max_memory` 和 `duckdb.threads` **从未被读取**
- `_save_table_metadata()` 和 `_restore_table_registry()` **已完整实现但被 `_db_path == ':memory:'` 门控**

### 瓶颈 2：Excel 全量加载内存峰值

- `excel_preprocessor.py` 的 `_read_raw_sheets()` 一次读取整个工作簿所有 Sheet
- 285MB .xls 文件：xlrd 加载 ~285MB + 7个Sheet的Python列表 + pandas concat → 峰值 ~600-700MB
- 目标机器 4-8GB RAM（Windows + WebView2 已占 1-2GB）

### 瓶颈 3：每天手动操作 14 个文件

- `workdir_loader.py` 仅有 `list_workdir_files()` 和 `scan_for_pattern()`，无自动加载
- 用户必须逐个点击"加载"按钮

### 瓶颈 4：字段映射只覆盖 6 种表类型

- `DICT_TABLE_MAP`（data_loader.py:383）仅有 holding/nav/rating_entity/rating_bond/monitoring/weekly_report
- 14 种文件中有 8 种无字典定义

### 瓶颈 5：日期提取不支持 YYYY-MM-DD 格式

- `extract_date_from_filename()`（data_loader.py:96-114）仅支持 YYYYMMDD/YYMMDD/MMDD
- 真实文件使用 `2026-06-16`（带连字符）和 `2026-06-22T084857.169`（时间戳），均无法提取

---

## 实施方案（3 个 Phase）

### Phase 0：DuckDB 文件持久化 + 内存优化加载

**目标**：数据持久化（重启不丢失）+ 大文件加载内存可控。

#### 0A. 启用 DuckDB 文件模式

**已有基础**（无需新写）：
- `_save_table_metadata()` (data_loader.py:117-142) — 已实现，文件模式下自动保存
- `_restore_table_registry()` (data_loader.py:145-169) — 已实现，文件模式下启动恢复
- `.gitignore` 已有 `data/*.duckdb` 排除规则

**改动 1：config.example.yaml + config.yaml — 新增 db_path**
```yaml
duckdb:
  max_memory: "300MB"    # 提升；文件模式下此值为 buffer pool 上限
  threads: 2
  db_path: "data/dataagent.duckdb"  # 新增
```

**改动 2：main.py — 在 `main()` 函数中、`create_flask_app()` 之前初始化 DuckDB**

```python
# 在 config = load_config() 之后（~line 121）插入：
import tools.data_loader as _dl

# 设置 DuckDB 文件路径
db_cfg = config.get('duckdb', {})
db_path = db_cfg.get('db_path', '')
if db_path and db_path != ':memory:':
    _dl._db_path = str(BASE_DIR / db_path)
    # 确保目录存在
    (BASE_DIR / db_path).parent.mkdir(parents=True, exist_ok=True)

# 用 config 值初始化（替代懒加载时的硬编码默认值）
_dl.init_duckdb_connection(
    max_memory=str(db_cfg.get('max_memory', '200MB')),
    threads=int(db_cfg.get('threads', 2)),
)
```

这使得 `_restore_table_registry()` 在启动时被调用，DuckDB 文件中的表自动恢复到 `_loaded_tables` 注册表。

**改动 3：data_loader.py — 确保 api/chat.py 和 api/skill_api.py 的懒加载不覆盖**

`init_duckdb_connection()` 已是单例模式（line 178 `if _global_conn is not None: return`），main.py 先初始化后，API handler 的懒调用会直接返回已有连接。无需改动 API 层。

**改动 4：.gitignore — 补充 WAL 文件**
```
data/*.duckdb.wal
```

#### 0B. DuckDB 原生 CSV 加载（绕过 Pandas）

**适用场景**：用户上传 CSV 文件时（非 Excel），使用 DuckDB 原生 `read_csv_auto()` 直接加载，绕过 pandas，Python 侧几乎零内存开销。

DuckDB 1.x 支持 `read_csv_auto()`，可直接将 CSV 流式写入 DuckDB 页面。

**data_loader.py `load_file()` — 在现有 CSV 分支（line 545-572）之前尝试原生路径：**

```python
if ext == '.csv':
    encoding = detect_encoding(file_path)
    try:
        result = _load_csv_native(conn, file_path, safe_table, encoding)
        if result:
            # 原生加载成功，后续执行列名清洗、字典映射、实体归一
            df_columns = result['columns']  # 从 DESCRIBE 获取
            ...
    except Exception:
        pass  # 回退到 pandas 路径
```

新增内部函数 `_load_csv_native(conn, file_path, table_name, encoding)`：
1. `CREATE OR REPLACE TABLE ... AS SELECT * FROM read_csv_auto(path, header=true, all_varchar=true)`
2. 获取列名：`DESCRIBE table_name`
3. 列名清洗：通过 `ALTER TABLE RENAME COLUMN`（非修改 DataFrame）
4. 千分位清洗：通过 DuckDB SQL `UPDATE SET col = REPLACE(col, ',', '')` 批量处理
5. 类型转换：`ALTER TABLE ALTER COLUMN ... TYPE DOUBLE`
6. 返回基础元数据（行数、列名）

**注意**：`SQLGuard.BLOCKED_FUNCTIONS` 已包含 `read_csv_auto`（query_runner.py:30），这只阻止用户 SQL 中使用，不影响 data_loader 内部调用。

**Pandas 回退场景**（保持现有代码不删除）：
- DuckDB 原生不支持的编码（罕见 GB2312 变体）
- 原生加载失败时的兜底
- 需要特殊 pandas 预处理的场景

#### 0C. Excel 逐Sheet流式加载

**问题根因**：`excel_preprocessor.py:_read_raw_sheets()` 将所有Sheet一次性读入内存。

**改动 1：excel_preprocessor.py — 新增 `preprocess_excel_streaming()`**

```python
def preprocess_excel_streaming(
    file_path: str,
    sheet_select: str | list[int] | None = None,
) -> Iterator[tuple[PreprocessResult, bool]]:
    """逐Sheet产出处理结果。yield (result, is_compatible_with_first)。
    
    调用方将每个 Sheet 注册到 DuckDB 后释放 DataFrame。
    同构Sheet合并通过 DuckDB INSERT INTO 实现（非 pandas concat）。
    """
```

实现要点：
- .xls 文件：xlrd 整体加载无法避免，但逐 Sheet 构建 DataFrame + 立即 yield
- .xlsx 文件：openpyxl `load_workbook()` 也是整体加载，但同样逐Sheet yield
- `sheet_select="first"` 时只处理第一个非空 Sheet
- `sheet_select=[0,2]` 时只处理指定索引
- 检测相邻Sheet列名一致性（复用 `_check_column_compatibility`），标记 is_compatible

**改动 2：data_loader.py `load_file()` — 新增 `sheet_select` 参数和大文件路径**

在现有 Excel 分支（line 575-580）中：

```python
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB

elif ext in ('.xlsx', '.xls'):
    encoding = 'n/a'
    file_size = Path(file_path).stat().st_size
    
    if file_size > LARGE_FILE_THRESHOLD:
        # 大文件：逐Sheet加载 → DuckDB → 释放
        return _load_excel_streaming(
            conn, file_path, safe_table, table_type, date_tag,
            sheet_select=sheet_select,
        )
    else:
        # 小文件：现有路径
        from tools.excel_preprocessor import preprocess_excel
        prep = preprocess_excel(file_path)
        df = prep.df
        warnings.extend(prep.warnings)
```

新增 `_load_excel_streaming()` 内部函数：
1. 调用 `preprocess_excel_streaming(file_path, sheet_select)` 
2. 第一个Sheet：清洗 + 字典映射 + 实体归一 + `CREATE TABLE`
3. 后续同构Sheet：清洗 + `INSERT INTO`（跳过重复的映射/归一）
4. 每个Sheet后 `del df; gc.collect()`
5. 返回 LoadResult

**内存效果**：
- 285MB .xls (7 Sheet × 6万行)：峰值从 ~700MB 降到 ~350MB（xlrd ~285MB + 1 Sheet DataFrame ~60MB）
- 100MB .xls (3 Sheet)：峰值从 ~300MB 降到 ~150MB

#### 0D. 日期提取增强

**改动：data_loader.py `extract_date_from_filename()` — 新增两种模式**

在现有 3 种模式之前插入：

```python
# YYYY-MM-DD（如 2026-06-16）
m = re.search(r'(20\d{2})-(\d{2})-(\d{2})', filename)
if m:
    return m.group(1) + m.group(2) + m.group(3)

# ISO timestamp 前缀（如 2026-06-22T084857）
m = re.search(r'(20\d{2})-(\d{2})-(\d{2})T', filename)
if m:
    return m.group(1) + m.group(2) + m.group(3)
```

现有 YYYYMMDD/YYMMDD/MMDD 模式保持不变（向后兼容）。

#### 0E. 测试

- **文件模式持久化测试**：创建临时 .duckdb → 加载样本 → 关闭连接 → 重新打开 → 验证表存在 + `_loaded_tables` 恢复
- **CSV 原生加载测试**：UTF-8 和 GB18030 编码的 CSV → 验证原生路径成功 + Pandas 回退正常
- **逐Sheet加载测试**：用「持仓产品管理」样本（7 Sheet）验证合并正确、行数一致
- **sheet_select 测试**："first" 只取首Sheet，[0,2] 取指定Sheet
- **日期提取测试**：覆盖 `2026-06-16`、`0616`、`20260616`、`2026-06-22T084857.169`
- **回归**：`pytest tests/ -v` 全量通过（现有测试使用 `:memory:` 不受影响）

---

### Phase 1：工作目录自动加载

**目标**：配置一次，每天启动自动加载/更新 14 个数据文件。

**前提**：Phase 0 完成（DuckDB 文件模式 + 逐Sheet加载 + 日期提取增强）。

#### 1A. 自动加载配置

**config.example.yaml** 新增 `auto_load` 段：

```yaml
app:
  work_dir: ""              # 用户在设置面板中配置
  auto_load:
    enabled: false          # 默认关闭，用户显式开启
    max_versions: 3         # 每种类型最多保留几个日期版本
    file_rules:             # 基于真实文件名设计
      - pattern: "持仓产品管理-*.xls"
        table_type: holding
        sheet_mode: merge_all
      - pattern: "底层资产持仓及债券信息表*.xlsx"
        table_type: holding_detail
      - pattern: "估值表查询(*.xlsx"
        table_type: valuation
        sheet_select: first
      - pattern: "监控值查询*.xlsx"
        table_type: monitoring
      - pattern: "净值结果管理*.xlsx"
        table_type: nav
      - pattern: "评级结果[0-9]*.xls"
        table_type: rating_entity
      - pattern: "申赎数据*.xlsx"
        table_type: subscription
        sheet_select: first
      - pattern: "实时资产头寸查询(*.xlsx"
        table_type: asset_position
      - pattern: "投资债券评级结果*.xls"
        table_type: rating_bond
        sheet_mode: merge_all
      - pattern: "现金流缺口分析(*.xlsx"
        table_type: cashflow_gap
      - pattern: "债券质押查询(*.xlsx"
        table_type: bond_pledge
        sheet_select: first
      - pattern: "账户流水(*.xlsx"
        table_type: account_flow
      - pattern: "质押式回购投资交易查询(*.xlsx"
        table_type: repo_trade
      - pattern: "组合资金账户头寸(*.xlsx"
        table_type: fund_position
```

#### 1B. 自动加载引擎

**workdir_loader.py** 新增 `auto_load_workdir()` 函数：

```python
def auto_load_workdir(config: dict) -> list[dict]:
    """启动时自动加载工作目录中的数据文件。"""
```

流程：
1. 读取 `config.app.auto_load.file_rules`
2. 调用已有 `list_workdir_files()` 获取工作目录文件列表
3. 对每个规则，用已有 `scan_for_pattern()` 匹配文件
4. 对每个匹配文件：
   - 调用增强后的 `extract_date_from_filename()` 提取日期
   - 生成表名：`{table_type}_{date}` 或 `{table_type}_{stem}`
   - **增量检测**：DuckDB 文件模式下，如果 `_loaded_tables` 已有同名表且 file_path 的 mtime 未变 → 跳过
   - 调用 `load_file(sheet_select=rule.get('sheet_select'))` 加载
5. 版本淘汰：按 `max_versions` 删除同类型中最旧的表

复用的现有函数：
- `list_workdir_files()` (workdir_loader.py:39-61)
- `scan_for_pattern()` (workdir_loader.py:64-89)  
- `extract_date_from_filename()` (data_loader.py:96-114, Phase 0C 已增强)
- `load_file()` (data_loader.py:514-684, Phase 0B 已增强)

#### 1C. 版本淘汰

**data_loader.py** 新增 `evict_old_versions(table_type: str, max_versions: int)`：
1. 从 `_loaded_tables` 筛选同 `table_type` 的表
2. 按 `date_tag` 降序排列
3. 超出 `max_versions` 的执行已有 `drop_table()` (data_loader.py:687)
4. 文件模式下 `_save_table_metadata()` 自动更新

#### 1D. 主入口集成

**main.py** — 在 DuckDB 初始化之后、`create_flask_app()` 之前插入：

```python
# 启动时自动加载工作目录数据
auto_cfg = config.get('app', {}).get('auto_load', {})
if auto_cfg.get('enabled', False):
    from tools.workdir_loader import auto_load_workdir
    loaded = auto_load_workdir(config)
    logger.info(f"自动加载 {len(loaded)} 个数据文件")
```

**DuckDB 文件模式下的启动优化**：
- 首次启动：加载全部文件（~2-5分钟，取决于文件大小）
- 后续启动：`_restore_table_registry()` 恢复注册表 → `auto_load_workdir()` 检测 mtime → 仅加载新增/变化的文件（秒级）

#### 1E. 测试

- 创建临时工作目录 + 样本文件 → 配置 auto_load → 验证自动加载
- DuckDB 文件模式增量：首次全量 → 重启 → 验证跳过已加载文件
- 版本淘汰：max_versions=1，加载两天数据 → 验证旧版本被删除
- 工作目录为空/不存在 → 不报错
- 文件不匹配任何规则 → 跳过

---

### Phase 2：字段映射扩展

**目标**：为新增的 8 种文件类型建立数据字典，共享同义词减少维护成本。

#### 2A. 扩展 DICT_TABLE_MAP

**data_loader.py:383-390** — 新增 8 个映射：

```python
DICT_TABLE_MAP = {
    # 现有 6 个
    "holding": "holding_dict.yaml",
    "nav": "nav_dict.yaml",
    "rating_entity": "rating_entity_dict.yaml",
    "rating_bond": "rating_bond_dict.yaml",
    "monitoring": "monitoring_dict.yaml",
    "weekly_report": "weekly_report_dict.yaml",
    # 新增 8 个
    "holding_detail": "holding_detail_dict.yaml",
    "valuation": "valuation_dict.yaml",
    "subscription": "subscription_dict.yaml",
    "asset_position": "asset_position_dict.yaml",
    "cashflow_gap": "cashflow_gap_dict.yaml",
    "bond_pledge": "bond_pledge_dict.yaml",
    "account_flow": "account_flow_dict.yaml",
    "repo_trade": "repo_trade_dict.yaml",
    "fund_position": "fund_position_dict.yaml",
}
```

#### 2B. 共享同义词库

**新建 `data_dictionary/shared_synonyms.yaml`**：

```yaml
synonym_groups:
  product_name:
    - 产品名称
    - 产品简称
    - 组合名称
    - 组合/组合包名称
    - 理财产品名称
    - 产品全称
    - 基金名称
    - 资产名称        # 估值表中"资产名称"实为产品名

  entity_name:
    - 限额占用主体
    - 限额占用方主体
    - 主体名称
    - 发行人
    - 发行人名称
    - 企业名称
    - 评级主体
    - 实际信用承担方名称
    - 实际融资人

  asset_code:
    - 资产代码
    - 债券代码
    - 证券代码
    - 资产编码

  asset_name:
    - 资产名称
    - 资产简称
    - 债券名称
    - 证券简称
    - 债券简称

  stat_date:
    - 统计日期
    - 持仓日期
    - 数据日期
    - 估值日期
    - 报告日期
    - 查询日
    - 监控日期
    - 记账日期
```

**data_loader.py `load_dictionary()`（line 393）改动**：加载 YAML 后调用 `_merge_shared_synonyms()` 合并同义词到各字段的 `physical_candidates`。

#### 2C. 新增 8 个数据字典 YAML

基于样本文件实际列名编写。每个字典遵循 `holding_dict.yaml` 的 schema：`semantic`、`physical_candidates`、`dtype`、`required`、`requires_cleaning`。

示例 — `data_dictionary/holding_detail_dict.yaml`（底层资产持仓及债券信息表，66 列）：
```yaml
description: 底层资产持仓及债券信息表
table_type: holding_detail
fields:
  - semantic: 持仓日期
    dtype: date
    required: true
    physical_candidates: [持仓日期]
  - semantic: 资产代码
    dtype: str
    required: true
    physical_candidates: [资产代码]
  - semantic: 资产市值_穿透后
    dtype: float
    requires_cleaning: thousands_separator
    physical_candidates: [资产市值_穿透后]
  - semantic: 产品名称
    dtype: str
    physical_candidates: [产品简称, 产品代码]
  - semantic: 限额占用主体
    dtype: str
    physical_candidates: [限额占用方主体, 评级主体, 发行人]
  # ... 其余关键字段
```

#### 2D. 修复 `get_all_field_maps()` 多表冲突

**data_loader.py:210-219** — 当前 `combined.update()` 是 last-one-wins：

改进（最小化改动）：
- 合并时检测冲突（同一语义名映射到不同物理列），记录 warning 日志
- 不改变 `get_all_field_maps()` 返回值格式（向后兼容）
- 在 `agent/tool_dispatch.py` 的 `_tool_run_sql()` 中，优先使用 `get_field_map_for_table()`（已存在，line 222）精确获取 SQL 引用表的映射

#### 2E. 测试

- 加载每种新类型样本 → 验证字典映射正确
- 共享同义词：持仓文件用"组合名称"列 → 验证映射到"产品名称"
- 多表冲突检测日志
- 全量回归

---

## 关键文件改动清单

| 文件 | Phase | 改动类型 | 说明 |
|------|-------|---------|------|
| `config.example.yaml` | 0,1 | 修改 | 新增 `duckdb.db_path` + `app.auto_load` 段 |
| `config.yaml` | 0,1 | 修改 | 同 config.example.yaml |
| `main.py` | 0,1 | 修改 | DuckDB 早期初始化（~line 121 后）+ 自动加载入口 |
| `tools/data_loader.py` | 0,1,2 | 修改 | `load_file()` 新增 sheet_select + 大文件路径；`extract_date_from_filename()` 增强；`DICT_TABLE_MAP` 扩展；`_merge_shared_synonyms()`；`evict_old_versions()` |
| `tools/excel_preprocessor.py` | 0 | 修改 | 新增 `preprocess_excel_streaming()` |
| `tools/workdir_loader.py` | 1 | 修改 | 新增 `auto_load_workdir()` |
| `.gitignore` | 0 | 修改 | 新增 `data/*.duckdb.wal` |
| `data_dictionary/shared_synonyms.yaml` | 2 | **新建** | 共享同义词库 |
| `data_dictionary/*_dict.yaml` × 8 | 2 | **新建** | 8 种新文件类型字典 |

**不改动的文件**（已确认无需修改）：
- `api/chat.py`、`api/skill_api.py` — DuckDB init 是单例，main.py 先初始化后 API 层无需改动
- `tools/query_runner.py` — `apply_field_map()` 和 `SQLGuard` 无需改动
- `calculators/columns.py` — `resolve_columns()` 无需改动

---

## 实施排期

```
Phase 0（DuckDB 文件模式 + 内存优化）— 3-4 天
  Step 1: config.yaml + main.py DuckDB 初始化 + .gitignore（0A）
  Step 2: excel_preprocessor 逐Sheet流式 + data_loader 大文件路径（0B）
  Step 3: extract_date_from_filename 增强（0C）
  Step 4: 测试（0D）

Phase 1（自动加载）— 3-4 天
  Step 1: config auto_load 段 + workdir_loader auto_load_workdir()（1A+1B）
  Step 2: data_loader evict_old_versions() + main.py 集成（1C+1D）
  Step 3: 测试（1E）

Phase 2（字段映射扩展）— 3-4 天
  Step 1: shared_synonyms.yaml + load_dictionary 合并逻辑（2A+2B）
  Step 2: 8 个新字典 YAML + DICT_TABLE_MAP 扩展（2C）
  Step 3: get_all_field_maps 冲突检测 + 测试（2D+2E）
```

Phase 0 是 Phase 1 的前提。Phase 2 可与 Phase 1 并行。

---

## 验证方式

1. **文件模式持久化**（Phase 0 完成后）：
   - 加载 3 个样本文件 → 关闭 → 重启 → `_loaded_tables` 自动恢复 + 数据完好
   - 查询已恢复的表返回正确数据

2. **内存优化**（Phase 0 完成后）：
   - 用「持仓产品管理」样本（7 Sheet）验证逐Sheet加载 + 合并正确
   - `gc.collect()` 后 Python RSS 回到合理水平

3. **自动加载端到端**（Phase 1 完成后）：
   - 配置 work_dir + auto_load → 启动 → 14 个文件自动加载
   - 重启 → DuckDB 文件恢复 + 增量检测（mtime 未变 → 跳过）
   - 添加新日期文件 → 加载 + 旧版本淘汰

4. **字段映射**（Phase 2 完成后）：
   - 14 种文件类型各加载 → 字典映射正确
   - 共享同义词合并有效

5. **全量回归**：每个 Phase 后 `pytest tests/ -v` 零失败
