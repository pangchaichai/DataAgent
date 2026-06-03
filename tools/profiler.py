"""
tools/profiler.py — 数据表剖析器

让 Agent 自己读懂数据结构，降低用户标注负担。
只读操作：SELECT ... LIMIT + information_schema，不读原始文件。

用法:
  from tools.profiler import profile_table
  info = profile_table(conn, "holding_20260515")
  info = profile_table(conn, "holding_20260515", columns=["产品名称", "市值"])
"""

import duckdb


def profile_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    columns: list[str] | None = None,
    sanitize: bool = False,
) -> dict:
    """
    剖析一张已加载的数据表。

    参数:
      conn:       DuckDB 连接
      table_name: 已加载表的名称
      columns:    可选，只剖析指定列；不传则全部列

    返回:
      {
        "table": str,
        "row_count": int,
        "columns": [
          {
            "name": str,
            "dtype": str,
            "null_rate": float,         # 0.0 ~ 1.0
            "distinct_count": int,       # 去重值数量
            "samples": [str, ...] | None,   # 文本列：最多5个去重样本值
            "min": float | None,         # 数值列
            "max": float | None,         # 数值列
          },
          ...
        ],
        "field_map": {语义名: 实际列名},   # 来自数据字典（若有）
      }
    """
    # ── 获取行数 ──────────────────────────────────────────
    row_count = conn.execute(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).fetchone()[0]

    # ── 获取列信息 ─────────────────────────────────────────
    col_rows = conn.execute(
        f"SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
    ).fetchall()

    all_columns = [c[0] for c in col_rows]
    dtype_map = {c[0]: c[1] for c in col_rows}

    # 如果指定了 columns，只剖析这些
    target_cols = columns if columns else all_columns
    # 过滤掉不存在的列
    target_cols = [c for c in target_cols if c in all_columns]

    # ── 逐列剖析 ─────────────────────────────────────────
    col_info = []
    for col_name in target_cols:
        dtype = dtype_map.get(col_name, "unknown")
        info = {"name": col_name, "dtype": dtype}

        # 空值率
        null_count = conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}" WHERE "{col_name}" IS NULL'
        ).fetchone()[0]
        info["null_rate"] = round(null_count / row_count, 4) if row_count > 0 else 1.0

        # 去重数
        distinct = conn.execute(
            f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table_name}"'
        ).fetchone()[0]
        info["distinct_count"] = distinct

        # 数值列：min/max
        if _is_numeric_dtype(dtype):
            try:
                stats = conn.execute(
                    f'SELECT MIN("{col_name}")::VARCHAR, MAX("{col_name}")::VARCHAR '
                    f'FROM "{table_name}" WHERE "{col_name}" IS NOT NULL'
                ).fetchone()
                info["min"] = _safe_float(stats[0])
                info["max"] = _safe_float(stats[1])
            except Exception:
                info["min"] = None
                info["max"] = None

        # 文本列：样本值
        if _is_text_dtype(dtype):
            try:
                samples = conn.execute(
                    f'SELECT DISTINCT "{col_name}" FROM "{table_name}" '
                    f'WHERE "{col_name}" IS NOT NULL LIMIT 5'
                ).fetchall()
                raw_samples = [str(s[0])[:100] for s in samples]
                if sanitize:
                    info["samples"] = _sanitize_samples(raw_samples, col_name)
                else:
                    info["samples"] = raw_samples
            except Exception:
                info["samples"] = []

        col_info.append(info)

    # ── 附加字典映射 ─────────────────────────────────────
    field_map = _get_field_map(table_name)

    return {
        "table": table_name,
        "row_count": row_count,
        "columns": col_info,
        "field_map": field_map,
    }


def _is_numeric_dtype(dtype: str) -> bool:
    """判断 DuckDB dtype 是否为数值类型"""
    dtype_lower = dtype.lower()
    numeric_types = (
        "integer", "bigint", "smallint", "tinyint", "hugeint",
        "float", "double", "decimal", "numeric", "real",
    )
    return any(t in dtype_lower for t in numeric_types)


def _is_text_dtype(dtype: str) -> bool:
    """判断 DuckDB dtype 是否为文本类型"""
    dtype_lower = dtype.lower()
    return "varchar" in dtype_lower or "char" in dtype_lower or "text" in dtype_lower


def _safe_float(val) -> float | None:
    """安全转为 float"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _sanitize_samples(samples: list[str], col_name: str) -> list[str]:
    """★R4: 外网场景脱敏样本值。保留结构信息，隐藏具体数据。"""
    sanitized = []
    for s in samples:
        if not s:
            sanitized.append(s)
            continue
        cn = col_name.lower()
        if any(k in cn for k in ('主体', 'entity', '名称', 'name', '产品', 'product')):
            # 实体名 → 保留长度信息
            sanitized.append(f"[实体-{len(s)}字]")
        elif any(k in cn for k in ('市值', '金额', 'amount', 'value', '规模')):
            # 金额 → 量级
            sanitized.append("[数值]")
        elif any(k in cn for k in ('日期', 'date', '时间', 'time')):
            sanitized.append("[日期]")
        else:
            sanitized.append(f"[文本-{len(s)}字]")
    return sanitized


def _get_field_map(table_name: str) -> dict:
    """从已加载表注册表中获取字段映射"""
    from tools.data_loader import _loaded_tables
    loaded = _loaded_tables.get(table_name)
    if loaded and loaded.field_map:
        return {k: v for k, v in loaded.field_map.items()}
    return {}
