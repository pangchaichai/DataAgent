"""
tools/quality.py — 数据质量诊断

上传后自动检测数据质量问题，把隐患前置暴露：
- 关键字段空值率
- 日期范围
- 主体别名覆盖率
- 跨表 JOIN 兼容性
- 阻断级问题 vs 关注级警告

所有计算使用 DuckDB 聚合 SQL，不逐行 Python 循环。
"""

from dataclasses import dataclass, field

import duckdb

# ═══════════════════════════════════════════════════════════════
#  阈值常量
# ═══════════════════════════════════════════════════════════════

KEY_NULL_CRITICAL = 0.05         # 关键字段空值率 > 5% → critical
ENTITY_UNMATCHED_CRITICAL = 0.10  # 主体未识别率 > 10% → critical
JOIN_COMPAT_WARN = 0.80          # JOIN 匹配率 < 80% → warning


# ═══════════════════════════════════════════════════════════════
#  QualityReport dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class QualityReport:
    """数据质量诊断报告"""
    null_rates: dict[str, float] = field(default_factory=dict)
    date_range: dict | None = None       # {"column": str, "min": str, "max": str}
    entity_coverage: dict = field(default_factory=dict)
    # {"matched": int, "total": int, "unmatched": [str, ...]}
    join_compatibility: dict = field(default_factory=dict)
    # {"target_table": {"join_key": str, "match_rate": float, "unmatched": int}}
    critical_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  主计算函数
# ═══════════════════════════════════════════════════════════════

def compute_quality_report(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_type: str,
    field_map: dict,
    key_fields: list[str] | None = None,
) -> QualityReport:
    """
    对已加载的数据表计算质量诊断报告。

    参数:
      conn:        DuckDB 连接
      table_name:  已注册的表名
      table_type:  表类型 (holding/nav/rating_entity/rating_bond/...)
      field_map:   语义名→实际列名映射 (来自 LoadResult.field_map)
      key_fields:  关键字段列表（语义名），来自数据字典的 required/is_key 字段

    返回 QualityReport。
    """
    report = QualityReport()

    # ── 1. 空值率 ──────────────────────────────────────
    report.null_rates = _compute_null_rates(conn, table_name)

    # 检查关键字段空值率
    if key_fields:
        for field_semantic in key_fields:
            physical = field_map.get(field_semantic, field_semantic)
            null_rate = report.null_rates.get(physical, 0)
            if null_rate > KEY_NULL_CRITICAL:
                report.critical_issues.append(
                    f"关键字段「{field_semantic}」空值率 {null_rate:.1%}，超过阈值 {KEY_NULL_CRITICAL:.0%}"
                )
            elif null_rate > 0:
                report.warnings.append(
                    f"关键字段「{field_semantic}」空值率 {null_rate:.1%}"
                )

    # 非关键字段高空值率 → warning
    for col, rate in report.null_rates.items():
        if rate > 0.5 and col not in (key_fields or []):
            report.warnings.append(f"列「{col}」空值率 {rate:.1%}，建议确认")

    # ── 2. 日期范围 ────────────────────────────────────
    report.date_range = _detect_date_range(conn, table_name, field_map)

    # ── 3. 主体覆盖率 ──────────────────────────────────
    if table_type in ('holding', 'rating_entity', 'rating_bond'):
        report.entity_coverage = _compute_entity_coverage(conn, table_name, field_map)
        total = report.entity_coverage.get("total", 0)
        matched = report.entity_coverage.get("matched", 0)
        if total > 0:
            unmatched_rate = 1 - matched / total
            if unmatched_rate > ENTITY_UNMATCHED_CRITICAL:
                report.critical_issues.append(
                    f"主体未识别率 {unmatched_rate:.1%}（{total - matched}/{total}），"
                    f"超过阈值 {ENTITY_UNMATCHED_CRITICAL:.0%}"
                )
            elif unmatched_rate > 0:
                report.warnings.append(
                    f"部分主体未识别（{total - matched}/{total}），"
                    f"可能影响跨表 JOIN 准确性"
                )

    # ── 4. JOIN 兼容性 ─────────────────────────────────
    report.join_compatibility = _compute_join_compatibility(conn, table_name, table_type, field_map)
    for target, info in report.join_compatibility.items():
        if info.get("match_rate", 0) < JOIN_COMPAT_WARN:
            report.warnings.append(
                f"与 {target} 的 JOIN 匹配率仅 {info['match_rate']:.1%}，"
                f"{info.get('unmatched', 0)} 条无法匹配"
            )

    return report


# ═══════════════════════════════════════════════════════════════
#  子计算函数
# ═══════════════════════════════════════════════════════════════

def _compute_null_rates(conn, table_name: str) -> dict[str, float]:
    """计算每列的空值率"""
    row_count = conn.execute(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).fetchone()[0]
    if row_count == 0:
        return {}

    cols = conn.execute(
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
    ).fetchall()

    null_rates = {}
    for (col_name,) in cols:
        null_count = conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE "{col_name}" IS NULL'
        ).fetchone()[0]
        null_rates[col_name] = round(null_count / row_count, 4)

    return null_rates


def _detect_date_range(conn, table_name: str, field_map: dict) -> dict | None:
    """检测日期列并返回 min/max 范围"""
    # 候选日期列：字段映射中 dtype=date 的列，或列名含"日期"
    date_cols = []
    for semantic, physical in field_map.items():
        if '日期' in semantic or 'date' in semantic.lower():
            date_cols.append(physical)

    if not date_cols:
        # 从所有列中推断
        cols = conn.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table_name}'"
        ).fetchall()
        for (col_name,) in cols:
            if '日期' in col_name:
                date_cols.append(col_name)

    for col in date_cols[:3]:  # 最多检查 3 个候选列
        try:
            result = conn.execute(
                f'SELECT MIN("{col}")::VARCHAR, MAX("{col}")::VARCHAR '
                f'FROM "{table_name}" WHERE "{col}" IS NOT NULL'
            ).fetchone()
            if result[0] is not None:
                return {"column": col, "min": str(result[0]), "max": str(result[1])}
        except Exception:
            continue

    return None


def _compute_entity_coverage(conn, table_name: str, field_map: dict) -> dict:
    """计算主体别名覆盖率"""
    from tools.entity_normalizer import EntityNormalizer

    # 找到主体列
    entity_col = (
        field_map.get("限额占用主体")
        or field_map.get("限额占用方主体")
        or field_map.get("主体名称")
    )
    if not entity_col:
        return {"matched": 0, "total": 0, "unmatched": []}

    # 获取所有不重复的主体名
    entities = conn.execute(
        f'SELECT DISTINCT "{entity_col}" FROM "{table_name}" '
        f'WHERE "{entity_col}" IS NOT NULL'
    ).fetchall()

    normalizer = EntityNormalizer()
    matched = 0
    unmatched_list = []
    for (name,) in entities:
        normalized = normalizer.normalize(name)
        if normalized != name or normalizer.alias_to_canonical.get(name):
            matched += 1
        else:
            if len(unmatched_list) < 10:
                unmatched_list.append(name)

    total = len(entities)
    return {
        "matched": matched,
        "total": total,
        "unmatched": unmatched_list[:10],
        "entity_column": entity_col,
    }


def _compute_join_compatibility(
    conn, table_name: str, table_type: str, field_map: dict
) -> dict:
    """预检与已加载其他表的 JOIN 兼容性"""
    from tools.data_loader import _loaded_tables

    compatibility = {}

    # 确定当前表的 JOIN 键
    join_key = None
    if table_type in ('holding', 'rating_entity', 'rating_bond'):
        join_key = field_map.get("限额占用主体") or field_map.get("限额占用方主体")
    elif table_type == 'nav':
        join_key = field_map.get("产品简称") or field_map.get("产品名称")

    if not join_key:
        return compatibility

    current_vals = set()
    try:
        rows = conn.execute(
            f'SELECT DISTINCT "{join_key}" FROM "{table_name}" '
            f'WHERE "{join_key}" IS NOT NULL LIMIT 5000'
        ).fetchall()
        current_vals = {r[0] for r in rows}
    except Exception:
        return compatibility

    for other_name, other_info in _loaded_tables.items():
        if other_name == table_name:
            continue
        other_type = other_info.table_type

        # 确定目标表的 JOIN 键
        target_key = _guess_join_key(other_type, other_info.field_map)
        if not target_key:
            continue

        try:
            other_rows = conn.execute(
                f'SELECT DISTINCT "{target_key}" FROM "{other_name}" '
                f'WHERE "{target_key}" IS NOT NULL LIMIT 5000'
            ).fetchall()
            other_vals = {r[0] for r in other_rows}
        except Exception:
            continue

        if not current_vals:
            continue

        matched = len(current_vals & other_vals)
        match_rate = matched / len(current_vals) if current_vals else 1.0

        compatibility[other_name] = {
            "join_key": join_key,
            "target_key": target_key,
            "match_rate": round(match_rate, 4),
            "unmatched": len(current_vals) - matched,
            "target_table_type": other_type,
        }

    return compatibility


def _guess_join_key(table_type: str, field_map: dict) -> str | None:
    """根据表类型推断 JOIN 键"""
    if table_type in ('holding', 'rating_entity', 'rating_bond'):
        return (
            field_map.get("限额占用主体")
            or field_map.get("限额占用方主体")
            or field_map.get("主体名称")
        )
    elif table_type == 'nav':
        return field_map.get("产品简称") or field_map.get("产品名称")
    return None
