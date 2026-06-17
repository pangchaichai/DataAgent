"""
calculators/credit_distribution.py — 信用评级分布固化计算

统计持仓的信用评级结构分布（内评/外评）。
"""

from dataclasses import dataclass

import duckdb


@dataclass
class CreditDistributionResult:
    rating: str            # 评级（如 AAA, AA+, AA, ...）
    rating_type: str       # 内部评级 / 外部评级
    market_value: float    # 持仓市值
    ratio_pct: float       # 占比(%)
    security_count: int    # 品种数


def calc_credit_distribution(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    market_value_field: str,
    rating_field: str = "外部评级",
    product_filter: list[str] = None,
    exclude_null: bool = True,
    cols: dict = None,
) -> list[CreditDistributionResult]:
    """
    计算信用评级分布。

    参数：
      rating_field: "外部评级" 或 "内部评级"（需要表中存在对应列）
      product_filter: 限定产品列表
      cols: 语义名→物理列名映射，None=向后兼容
    """
    from calculators.columns import COL_ASSET_CODE, COL_PRODUCT_NAME

    c_product = (cols or {}).get(COL_PRODUCT_NAME, "产品名称")
    c_asset_code = (cols or {}).get(COL_ASSET_CODE, "资产代码")
    c_rating = (cols or {}).get(rating_field, rating_field)

    product_clause = ""
    if product_filter:
        names = ", ".join([f"'{p}'" for p in product_filter])
        product_clause = f'AND "{c_product}" IN ({names})'

    null_clause = f'AND "{c_rating}" IS NOT NULL' if exclude_null else ''

    sql = f"""
        SELECT
            "{c_rating}" AS 评级,
            SUM("{market_value_field}") AS 市值,
            COUNT(DISTINCT "{c_asset_code}") AS 品种数
        FROM {holding_table}
        WHERE 1=1 {product_clause} {null_clause}
        GROUP BY "{c_rating}"
        ORDER BY 市值 DESC
    """

    df = conn.execute(sql).df()
    total = df['市值'].sum()

    results = []
    for _, row in df.iterrows():
        mv = row['市值']
        results.append(CreditDistributionResult(
            rating=str(row['评级']),
            rating_type=rating_field,
            market_value=round(mv, 2),
            ratio_pct=round(mv / total * 100, 2) if total > 0 else 0,
            security_count=int(row['品种数']),
        ))
    return results


def calc_rating_migration(
    conn: duckdb.DuckDBPyConnection,
    rating_table_current: str,
    rating_table_previous: str,
    entity_name_field: str = "企业名称",
    rating_field: str = "内部评级结果",
) -> list[dict]:
    """
    评级迁移分析：对比两期评级数据，找出评级上移/下移/持平的主体。

    返回 [{entity, rating_before, rating_after, change}, ...]
    仅返回有变化的主体。
    """
    sql = f"""
        SELECT
            a."{entity_name_field}" AS 主体名称,
            a."{rating_field}" AS 当前评级,
            b."{rating_field}" AS 前期评级
        FROM {rating_table_current} a
        LEFT JOIN {rating_table_previous} b
            ON a."{entity_name_field}" = b."{entity_name_field}"
        WHERE a."{rating_field}" != b."{rating_field}"
           OR b."{rating_field}" IS NULL
    """
    rows = conn.execute(sql).fetchall()
    results = []
    for r in rows:
        results.append({
            "entity": r[0],
            "rating_current": r[1],
            "rating_previous": r[2],
            "change": "新增" if r[2] is None else (
                "上调" if _rating_order(r[1]) > _rating_order(r[2]) else "下调"
            ),
        })
    return results


def _rating_order(rating: str) -> int:
    """评级转数值以便比较大小（AAA=最高）"""
    order = {
        'AAA': 10, 'AA+': 9, 'AA': 8, 'AA-': 7,
        'A+': 6, 'A': 5, 'A-': 4,
        'BBB+': 3, 'BBB': 2, 'BBB-': 1,
    }
    return order.get(str(rating).strip(), 0)
