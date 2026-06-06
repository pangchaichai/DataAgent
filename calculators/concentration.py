"""
calculators/concentration.py

集中度固化计算模块

本模块实现主体集中度和单券集中度的精确计算。
口径由合规部门确认后写死，禁止 LLM 修改或替换此处逻辑。
配置项（阈值、穿透口径、集团合并开关）通过 config.yaml 注入。

单元测试见 tests/test_calculators.py
"""

from dataclasses import dataclass

import duckdb


@dataclass
class ConcentrationResult:
    product_name: str
    entity_or_bond: str      # 主体名称 或 债券代码
    concentration_pct: float # 集中度百分比（如 12.5 代表 12.5%）
    market_value: float      # 持仓市值
    total_nav: float         # 组合总市值
    threshold_pct: float     # 监控阈值
    is_breach: bool          # 是否超标
    data_date: str           # 数据日期
    market_value_field: str  # 实际使用的市值字段（审计用）


def calc_entity_concentration(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    market_value_field: str,  # 由 config 的 calculation_config 传入，不由 LLM 决定
    threshold_pct: float,
    use_group_merge: bool,
    group_mapping: dict,      # {主体名: 集团系名} 来自 groups.yaml
    entity_alias: dict,       # {别名: 标准名} 来自 entity_alias.yaml
    product_filter: list = None,  # None 表示所有产品
) -> list[ConcentrationResult]:
    """
    计算主体集中度，检查是否超标。

    口径（C-01确认后固化，此处是待确认版本）：
      主体集中度 = 该主体相关资产穿透后市值 / 组合总穿透后市值 × 100%
      当 use_group_merge=True 时，同一集团系的所有主体合并计算

    参数：
      conn: DuckDB 连接
      holding_table: 持仓表名（含日期后缀，如 holding_20260515）
      market_value_field: 市值字段的实际列名（来自数据字典映射后的物理列名）
      threshold_pct: 超标阈值（百分比，如 10.0 代表 10%）
      use_group_merge: 是否按集团合并口径计算
      group_mapping: 主体→集团归属映射
      entity_alias: 别名→标准名归一映射
      product_filter: 指定产品名称列表，None 表示所有产品

    返回：超标的记录列表（空列表 = 无超标）
    注意：本函数使用固化 SQL 模板，不接受外部 SQL 输入
    """
    # ── 固化 SQL 模板（不暴露给 LLM）────────────────────
    # 口径：C-01 确认后，修改此处的 market_value_field 引用方式
    # 字段名使用双引号防止特殊字符问题

    product_filter_clause = ""
    if product_filter:
        placeholders = ", ".join([f"'{p}'" for p in product_filter])
        product_filter_clause = f"WHERE 产品名称 IN ({placeholders})"

    sql_total = f"""
        SELECT 产品名称, SUM("{market_value_field}") AS 组合总市值
        FROM {holding_table}
        {product_filter_clause}
        GROUP BY 产品名称
    """

    sql_entity = f"""
        SELECT 产品名称, 限额占用方主体, SUM("{market_value_field}") AS 主体市值
        FROM {holding_table}
        {product_filter_clause}
        GROUP BY 产品名称, 限额占用方主体
    """

    totals = conn.execute(sql_total).df().set_index("产品名称")["组合总市值"].to_dict()
    entity_holdings = conn.execute(sql_entity).df()

    # ── 实体归一 ─────────────────────────────────────────
    entity_holdings["标准主体"] = entity_holdings["限额占用方主体"].apply(
        lambda x: entity_alias.get(x, x)  # 无别名则用原名
    )

    # ── 集团合并（如开启）───────────────────────────────
    if use_group_merge:
        entity_holdings["统计主体"] = entity_holdings["标准主体"].apply(
            lambda x: group_mapping.get(x, x)  # 无归属则保持主体名
        )
    else:
        entity_holdings["统计主体"] = entity_holdings["标准主体"]

    # ── 汇总集中度 ────────────────────────────────────────
    grouped = entity_holdings.groupby(["产品名称", "统计主体"])["主体市值"].sum().reset_index()

    results = []
    for _, row in grouped.iterrows():
        product = row["产品名称"]
        entity = row["统计主体"]
        mv = row["主体市值"]
        total = totals.get(product, 0)
        if total <= 0:
            continue
        concentration = mv / total * 100
        results.append(ConcentrationResult(
            product_name=product,
            entity_or_bond=entity,
            concentration_pct=round(concentration, 2),
            market_value=round(mv, 2),
            total_nav=round(total, 2),
            threshold_pct=threshold_pct,
            is_breach=concentration > threshold_pct,
            data_date="",  # 调用方填入
            market_value_field=market_value_field,
        ))

    return [r for r in results if r.is_breach]
