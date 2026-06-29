"""
calculators/nav_metrics.py — 净值指标固化计算

净资产值、收益率、年化收益率等核心指标。
配置项通过 config.yaml 注入，本模块禁止 LLM 修改。
"""

from dataclasses import dataclass

import duckdb


@dataclass
class NavMetricsResult:
    product_name: str
    nav_date: str
    unit_nav: float           # 单位净值
    total_assets: float       # 产品总资产
    net_assets: float         # 产品净资产
    return_7d: float | None   # 七日年化收益率(%)
    return_1m: float | None   # 近1月年化收益率(%)
    return_3m: float | None   # 近3月年化收益率(%)
    return_1y: float | None   # 近1年收益率(%)
    return_ytd: float | None  # 今年以来收益率(%)
    return_since_inception: float | None  # 成立以来收益率(%)


def calc_nav_metrics(
    conn: duckdb.DuckDBPyConnection,
    nav_table: str,
    valuation_date: str = "",   # 空=最新日期
    product_filter: list[str] = None,
    cols: dict = None,          # 语义名→物理列名映射，None=使用默认硬编码列名
) -> list[NavMetricsResult]:
    """
    计算净值核心指标。

    口径说明：
      - 数据来源：nav 表
      - 如果有公布值和系统值两份数据，优先使用公布值
    """
    from calculators.columns import (
        COL_NAV_DATE,
        COL_NAV_NET_ASSETS,
        COL_NAV_PRODUCT,
        COL_NAV_RETURN_1M,
        COL_NAV_RETURN_1Y,
        COL_NAV_RETURN_3M,
        COL_NAV_RETURN_7D,
        COL_NAV_RETURN_INCEPTION,
        COL_NAV_RETURN_YTD,
        COL_NAV_TOTAL_ASSETS,
        COL_NAV_UNIT,
    )

    _defaults = {
        COL_NAV_PRODUCT: "产品简称",
        COL_NAV_DATE: "估值日期",
        COL_NAV_UNIT: "单位净值/万份收益(公布)",
        COL_NAV_TOTAL_ASSETS: "产品总资产(公布)",
        COL_NAV_NET_ASSETS: "产品净资产(公布)",
        COL_NAV_RETURN_7D: "七日年化收益率(公布)%",
        COL_NAV_RETURN_1M: "近1月年化收益率(%)",
        COL_NAV_RETURN_3M: "近3月年化收益率(%)",
        COL_NAV_RETURN_1Y: "近1年收益率(%)",
        COL_NAV_RETURN_YTD: "今年以来收益率(%)",
        COL_NAV_RETURN_INCEPTION: "成立以来收益率(%)",
    }

    def _col(semantic: str) -> str:
        if cols and semantic in cols:
            return cols[semantic]
        return _defaults.get(semantic, semantic)

    c_product = _col(COL_NAV_PRODUCT)
    c_date = _col(COL_NAV_DATE)
    c_unit = _col(COL_NAV_UNIT)
    c_total_assets = _col(COL_NAV_TOTAL_ASSETS)
    c_net_assets = _col(COL_NAV_NET_ASSETS)
    c_r7d = _col(COL_NAV_RETURN_7D)
    c_r1m = _col(COL_NAV_RETURN_1M)
    c_r3m = _col(COL_NAV_RETURN_3M)
    c_r1y = _col(COL_NAV_RETURN_1Y)
    c_rytd = _col(COL_NAV_RETURN_YTD)
    c_rinception = _col(COL_NAV_RETURN_INCEPTION)

    date_filter = ""
    if valuation_date:
        date_filter = f'WHERE "{c_date}" = \'{valuation_date}\''

    sql = f"""
        SELECT
            "{c_product}" AS 产品名称,
            "{c_date}" AS 日期,
            "{c_unit}" AS 单位净值,
            "{c_total_assets}" AS 总资产,
            "{c_net_assets}" AS 净资产,
            "{c_r7d}" AS 七日月化,
            "{c_r1m}" AS 近1月,
            "{c_r3m}" AS 近3月,
            "{c_r1y}" AS 近1年,
            "{c_rytd}" AS 年初至今,
            "{c_rinception}" AS 成立以来
        FROM {nav_table}
        {date_filter}
        ORDER BY "{c_product}", "{c_date}" DESC
    """

    df = conn.execute(sql).df()

    if product_filter:
        df = df[df['产品名称'].isin(product_filter)]

    results = []
    for _, row in df.iterrows():
        results.append(NavMetricsResult(
            product_name=row['产品名称'],
            nav_date=str(row['日期']),
            unit_nav=_safe_float(row['单位净值']),
            total_assets=_safe_float(row['总资产']),
            net_assets=_safe_float(row['净资产']),
            return_7d=_safe_float(row['七日月化']),
            return_1m=_safe_float(row['近1月']),
            return_3m=_safe_float(row['近3月']),
            return_1y=_safe_float(row['近1年']),
            return_ytd=_safe_float(row['年初至今']),
            return_since_inception=_safe_float(row['成立以来']),
        ))
    return results


def _safe_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None
