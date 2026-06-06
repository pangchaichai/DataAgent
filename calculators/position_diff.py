"""
calculators/position_diff.py — 跨期持仓差异固化计算

比较两期持仓表，识别：新建仓、清仓、加仓、减仓，及市值变化。
口径固化后禁止 LLM 修改。
"""

from dataclasses import dataclass

import duckdb


@dataclass
class PositionChange:
    asset_code: str       # 资产代码
    asset_name: str       # 资产名称
    product_name: str     # 产品名称
    change_type: str      # "新建仓" / "清仓" / "加仓" / "减仓" / "不变"
    mv_t1: float          # 前期市值（无持仓则 0）
    mv_t2: float          # 后期市值（无持仓则 0）
    mv_delta: float       # 市值变化（t2 - t1）
    mv_delta_pct: float   # 相对变化百分比（t1=0 时为 None 表示新建）
    date_t1: str          # 前期日期标签
    date_t2: str          # 后期日期标签


def calc_position_diff(
    conn: duckdb.DuckDBPyConnection,
    table_t1: str,
    table_t2: str,
    market_value_field: str,
    date_t1: str = "",
    date_t2: str = "",
    product_filter: list = None,
    min_mv_threshold: float = 0.0,
) -> list[PositionChange]:
    """
    计算两期持仓差异。

    参数：
      table_t1: 前期持仓表名
      table_t2: 后期持仓表名
      market_value_field: 市值字段名（两表保持一致）
      date_t1, date_t2: 日期标签（用于结果展示）
      product_filter: 产品过滤列表，None=全部
      min_mv_threshold: 忽略绝对变化小于此值的行（降噪）
    """
    prod_clause = ""
    if product_filter:
        p_list = ", ".join(f"'{p}'" for p in product_filter)
        prod_clause = f"WHERE 产品名称 IN ({p_list})"

    # ── 分别汇总两期按产品+资产代码的市值 ────────────────────
    sql_t1 = f"""
        SELECT 产品名称, 资产代码, 资产名称,
               SUM("{market_value_field}") AS mv
        FROM {table_t1}
        {prod_clause}
        GROUP BY 产品名称, 资产代码, 资产名称
    """
    sql_t2 = f"""
        SELECT 产品名称, 资产代码, 资产名称,
               SUM("{market_value_field}") AS mv
        FROM {table_t2}
        {prod_clause}
        GROUP BY 产品名称, 资产代码, 资产名称
    """

    df1 = conn.execute(sql_t1).df().set_index(["产品名称", "资产代码"])
    df2 = conn.execute(sql_t2).df().set_index(["产品名称", "资产代码"])

    # ── Full outer join（手动实现：union of keys）────────────
    all_keys = set(df1.index.tolist()) | set(df2.index.tolist())

    results = []
    for product, code in all_keys:
        key = (product, code)
        row1 = df1.loc[key] if key in df1.index else None
        row2 = df2.loc[key] if key in df2.index else None

        mv1 = float(row1["mv"]) if row1 is not None else 0.0
        mv2 = float(row2["mv"]) if row2 is not None else 0.0
        name = (row2["资产名称"] if row2 is not None else
                row1["资产名称"] if row1 is not None else code)

        delta = mv2 - mv1
        if abs(delta) < min_mv_threshold:
            continue

        if mv1 == 0:
            change_type = "新建仓"
            delta_pct = None
        elif mv2 == 0:
            change_type = "清仓"
            delta_pct = -100.0
        elif delta > 0:
            change_type = "加仓"
            delta_pct = round(delta / mv1 * 100, 2)
        elif delta < 0:
            change_type = "减仓"
            delta_pct = round(delta / mv1 * 100, 2)
        else:
            change_type = "不变"
            delta_pct = 0.0

        results.append(PositionChange(
            asset_code=code,
            asset_name=str(name),
            product_name=product,
            change_type=change_type,
            mv_t1=round(mv1, 2),
            mv_t2=round(mv2, 2),
            mv_delta=round(delta, 2),
            mv_delta_pct=delta_pct,
            date_t1=date_t1,
            date_t2=date_t2,
        ))

    results.sort(key=lambda r: abs(r.mv_delta), reverse=True)
    return results
