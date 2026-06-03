# Step R2：上传即数据质量诊断（降低标注门槛 / 守口径正确）

> 价值：让用户上传后立刻看到"这份数据有哪些会影响计算正确性的问题"，把隐患前置暴露，而不是等算错了才发现。可与 R1 并行。

---

## 前置阅读

- `tools/data_loader.py`（`load_file()` 返回 `LoadResult`；`field_map`/`unmatched_cols`/`missing_required`）
- `tools/entity_normalizer.py`（别名归一）
- `main.py` 的 `/api/upload` 路由（返回 `{ok, table_name, ...}`）
- `ui/index.html` 的 `uploadFile()`（目前只 alert 成功/失败）

---

## 目标

`load_file()` 末尾计算 `QualityReport`，经 `/api/upload` 返回，前端渲染"质量卡片"。

```python
@dataclass
class QualityReport:
    null_rates: dict[str, float]        # 列 → 空值率(0~1)
    date_range: tuple[str, str] | None  # 检测到的日期列范围
    entity_coverage: dict               # {"matched": int, "unmatched": [前10个未识别主体]}
    join_compatibility: dict            # {目标表名: 匹配率(0~1)}
    critical_issues: list[str]          # 阻断级（关键字段空值>5% / 主体未识别>10% / JOIN<80%）
    warnings: list[str]                 # 关注级
```

---

## 实现要点（新增 `tools/quality.py`，避免 data_loader 超 300 行）

```python
def compute_quality_report(df, table_type, field_map, conn) -> QualityReport:
    # 1. null_rates：每列空值率；is_key 字段(来自字典 required/is_key)空值>5% → critical
    # 2. date_range：识别日期列(字典 dtype=date 或列名含'日期')，min/max
    # 3. entity_coverage：对归一后主体列，统计命中 entity_alias 的比例，未命中前10个
    # 4. join_compatibility：对每张已加载、可 JOIN 的表，按 JOIN 键预检匹配率
    # 5. 汇总 critical_issues / warnings
```

- 阈值集中成常量，便于调：`KEY_NULL_CRITICAL=0.05`、`ENTITY_UNMATCHED_CRITICAL=0.10`、`JOIN_COMPAT_CRITICAL=0.80`。
- 性能：只扫已在内存的 DuckDB 表，用聚合 SQL，不逐行 Python 循环。

`load_file()` 改动（最小）：返回值追加 `quality_report` 字段（`LoadResult` 增字段，默认 `None` 保持旧单测兼容）。

`/api/upload` 返回追加：`"quality_report": asdict(report)`。

---

## 与 R1 的联动（重要）

把质量报告也**喂给 Agent**：当用户基于某表提问时，loop 的系统上下文里注入该表的 `critical_issues` 摘要，使 Agent 能主动提示"该表限额占用主体空值 3.2%，集中度结果可能偏低，是否继续"。这正是"像分析师一样主动"的体现。

---

## SSE / 前端

- 上传后由 `/api/upload`（非 SSE）直接返回 `quality_report`；前端 `uploadFile()` 成功分支调用 `renderQualityCard(report)`（R3 实现）。
- 过渡期（R3 未完成）：前端先用一段文本列出 `critical_issues`。

---

## 验收（`tests/test_tools.py` 或新增 `tests/test_quality.py`）

- `test_quality_null_rates()`：构造含空值 df，断言关键字段空值率与 critical 标注。
- `test_quality_entity_coverage()`：部分主体不在 alias，断言 unmatched 列表与比例。
- `test_quality_join_compatibility()`：两表 JOIN 键部分对不齐，断言匹配率。
- 手动：上传真实持仓 CSV → 返回里能看到 critical/warnings；上传一张干净表 → 无 critical。

---

## 交付物

- [ ] `tools/quality.py` + `QualityReport`
- [ ] `tools/data_loader.py`：`LoadResult` 加 `quality_report`，`load_file` 末尾计算
- [ ] `main.py` `/api/upload` 返回追加 `quality_report`
- [ ] loop 上下文注入该表 critical 摘要（与 R1 协同）
- [ ] 单测 3 项；旧测试绿
- [ ] 更新 PROGRESS-refactor.md
