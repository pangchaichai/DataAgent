"""
calculators/leverage.py — 杠杆率固化计算

计算各产品的杠杆率：总资产 / 净资产值（NAV）。
口径固化后禁止 LLM 修改。
"""

from dataclasses import dataclass

import duckdb


@dataclass
class LeverageResult:
    product_name: str       # 产品名称
    total_assets: float     # 总资产（持仓市值合计）
    net_asset_value: float  # 净资产值（来自净值表）
    leverage_ratio: float   # 杠杆率（总资产/净资产）
    threshold: float        # 监控阈值
    is_breach: bool         # 是否超标
    data_date: str          # 数据日期


def calc_leverage(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    nav_table: str,
    market_value_field: str,
    nav_field: str = "单位净值",
    share_field: str = "基金份额",
    threshold: float = 2.0,
    product_filter: list = None,
    data_date: str = "",
    cols: dict = None,
) -> list[LeverageResult]:
    """
    计算持仓杠杆率。

    口径：杠杆率 = 持仓总市值 / (单位净值 × 基金份额)
    threshold: 超标阈值（如 2.0 表示杠杆率 > 200% 即超标）

    参数：
      holding_table: 持仓表名（含总市值列）
      nav_table: 净值表名（含产品名、单位净值、份额列）
      market_value_field: 持仓表中市值字段名
      nav_field: 净值表中单位净值字段名
      share_field: 净值表中份额字段名（乘以单位净值得 NAV）
      cols: 语义名→物理列名映射，None=向后兼容
    """
    from calculators.columns import COL_PRODUCT_NAME

    c_product = (cols or {}).get(COL_PRODUCT_NAME, "产品名称")

    prod_clause = ""
    if product_filter:
        p_list = ", ".join(f"'{p}'" for p in product_filter)
        prod_clause = f'WHERE "{c_product}" IN ({p_list})'

    sql_assets = f"""
        SELECT "{c_product}" AS 产品名称, SUM("{market_value_field}") AS total_assets
        FROM {holding_table}
        {prod_clause}
        GROUP BY "{c_product}"
    """

    sql_nav = f"""
        SELECT "{c_product}" AS 产品名称,
               "{nav_field}" * "{share_field}" AS nav
        FROM {nav_table}
        {prod_clause}
    """

    df_assets = conn.execute(sql_assets).df().set_index("产品名称")
    df_nav = conn.execute(sql_nav).df().set_index("产品名称")

    results = []
    for product in df_assets.index:
        total_assets = float(df_assets.loc[product, "total_assets"])
        if product not in df_nav.index:
            continue
        nav = float(df_nav.loc[product, "nav"])
        if nav <= 0:
            continue

        ratio = round(total_assets / nav, 4)
        results.append(LeverageResult(
            product_name=product,
            total_assets=round(total_assets, 2),
            net_asset_value=round(nav, 2),
            leverage_ratio=ratio,
            threshold=threshold,
            is_breach=ratio > threshold,
            data_date=data_date,
        ))

    results.sort(key=lambda r: r.leverage_ratio, reverse=True)
    return results
