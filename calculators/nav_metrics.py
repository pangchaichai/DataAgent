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
) -> list[NavMetricsResult]:
    """
    计算净值核心指标。

    口径说明：
      - 数据来源：nav 表
      - 如果有公布值和系统值两份数据，优先使用公布值
    """
    date_filter = ""
    if valuation_date:
        date_filter = f'WHERE "估值日期" = \'{valuation_date}\''

    sql = f"""
        SELECT
            "产品简称" AS 产品名称,
            "估值日期" AS 日期,
            "单位净值/万份收益(公布)" AS 单位净值,
            "产品总资产(公布)" AS 总资产,
            "产品净资产(公布)" AS 净资产,
            "七日年化收益率(公布)%" AS 七日月化,
            "近1月年化收益率(%)" AS 近1月,
            "近3月年化收益率(%)" AS 近3月,
            "近1年收益率(%)" AS 近1年,
            "今年以来收益率(%)" AS 年初至今,
            "成立以来收益率(%)" AS 成立以来
        FROM {nav_table}
        {date_filter}
        ORDER BY 产品名称, 日期 DESC
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
