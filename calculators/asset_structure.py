"""
calculators/asset_structure.py — 资产结构固化计算

按资产大类、产品维度统计持仓结构分布。
"""

from dataclasses import dataclass

import duckdb


@dataclass
class AssetStructureResult:
    category: str          # 资产大类
    product_name: str      # 产品名称
    market_value: float    # 持仓市值
    ratio_pct: float       # 占比(%)
    security_count: int    # 持仓品种数


def calc_asset_structure(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    market_value_field: str,
    group_by_product: bool = True,
    category_field: str = "G06一级分类",
):
    """
    计算资产结构分布。

    参数：
      group_by_product=True  → 按产品+资产大类分组
      group_by_product=False → 全局按资产大类汇总
    """
    if group_by_product:
        select = '"产品名称" AS 产品名称,'
        group = '"产品名称", ' + f'"{category_field}"'
    else:
        select = ''
        group = f'"{category_field}"'

    sql = f"""
        SELECT
            {select}
            "{category_field}" AS 资产大类,
            SUM("{market_value_field}") AS 市值,
            COUNT(DISTINCT "资产代码") AS 品种数
        FROM {holding_table}
        WHERE "{category_field}" IS NOT NULL
        GROUP BY {group}
    """

    df = conn.execute(sql).df()

    # 计算总市值
    total_mv = df['市值'].sum()

    results = []
    for _, row in df.iterrows():
        mv = row['市值']
        product_name = row.get('产品名称', '全部产品') if group_by_product else '全部产品'
        # 占比：按分组 vs 全局
        if group_by_product:
            product_total = df[df['产品名称'] == product_name]['市值'].sum()
            ratio = mv / product_total * 100 if product_total > 0 else 0
        else:
            ratio = mv / total_mv * 100 if total_mv > 0 else 0

        results.append(AssetStructureResult(
            category=row['资产大类'],
            product_name=product_name,
            market_value=round(mv, 2),
            ratio_pct=round(ratio, 2),
            security_count=int(row['品种数']),
        ))
    return results


def calc_top_n_holdings(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    market_value_field: str,
    n: int = 10,
    product_filter: str = None,
) -> list[dict]:
    """取前N大持仓（按市值降序）"""
    product_clause = f'WHERE "产品名称" = \'{product_filter}\'' if product_filter else ''
    # 只选取存在的列
    existing_cols = {c[0] for c in conn.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name='{holding_table}'"
    ).fetchall()}
    cols = ["产品名称", "资产名称", "资产代码", market_value_field, "外部评级", "G06一级分类"]
    valid_cols = [c for c in cols if c in existing_cols]
    col_str = ", ".join(f'"{c}"' for c in valid_cols)

    sql = f"""
        SELECT {col_str}
        FROM {holding_table}
        {product_clause}
        ORDER BY "{market_value_field}" DESC
        LIMIT {n}
    """
    rows = conn.execute(sql).fetchall()
    results = []
    for r in rows:
        d = {}
        for i, col in enumerate(valid_cols):
            d[col] = str(r[i]) if r[i] is not None else ""
        results.append({
            "product": d.get("产品名称", ""),
            "name": d.get("资产名称", ""),
            "code": d.get("资产代码", ""),
            "value": round(float(d.get(market_value_field, 0) or 0), 2),
            "rating": d.get("外部评级", ""),
            "category": d.get("G06一级分类", ""),
        })
    return results
