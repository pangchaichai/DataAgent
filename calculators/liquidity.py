"""
calculators/liquidity.py — 流动性分析固化计算

按流动性分层统计持仓，检查高流动性资产占比是否满足合规要求。
口径固化后禁止 LLM 修改。
"""

from dataclasses import dataclass, field

import duckdb

# 流动性分层映射（G06一级分类 → 层级）
# 层级越低流动性越强：1=高流动性，2=中，3=低，4=非流动
_DEFAULT_LIQUIDITY_TIERS: dict[str, int] = {
    "利率债": 1,
    "国债": 1,
    "政策性金融债": 1,
    "现金及银行存款": 1,
    "货币市场工具": 1,
    "公募基金": 1,
    "高评级信用债": 2,
    "信用债": 2,
    "企业债": 2,
    "公司债": 2,
    "中期票据": 2,
    "银行间债券": 2,
    "可转债": 2,
    "权益": 3,
    "股票": 3,
    "股权": 3,
    "ABS": 3,
    "资产支持证券": 3,
    "私募基金": 4,
    "未上市股权": 4,
    "不动产": 4,
}

_TIER_LABELS = {1: "高流动性", 2: "中流动性", 3: "低流动性", 4: "非流动"}


@dataclass
class LiquidityBandResult:
    product_name: str
    tier: int                        # 1-4
    tier_label: str                  # 高/中/低/非流动
    market_value: float
    ratio_pct: float
    security_count: int


@dataclass
class LiquidityResult:
    product_name: str
    total_assets: float
    liquid_ratio_pct: float          # 1+2层占比
    high_liquidity_ratio_pct: float  # 1层占比
    illiquid_ratio_pct: float        # 3+4层占比
    bands: list[LiquidityBandResult] = field(default_factory=list)
    threshold_liquid_pct: float = 0.0
    is_breach: bool = False
    data_date: str = ""


def calc_liquidity(
    conn: duckdb.DuckDBPyConnection,
    holding_table: str,
    market_value_field: str,
    category_field: str = "G06一级分类",
    threshold_liquid_pct: float = 20.0,
    liquidity_tiers: dict = None,
    product_filter: list = None,
    data_date: str = "",
    cols: dict = None,
) -> list[LiquidityResult]:
    """
    计算持仓流动性分布。

    口径：
      高流动性资产占比 = 第1层市值 / 总市值 × 100%
      合规要求：高+中流动性占比 >= threshold_liquid_pct

    参数：
      threshold_liquid_pct: 最低流动性要求（默认20%，即低于此则超标）
      liquidity_tiers: 资产类别→层级映射；None=使用默认
      cols: 语义名→物理列名映射，None=向后兼容
    """
    from calculators.columns import COL_ASSET_CODE, COL_PRODUCT_NAME

    c_product = (cols or {}).get(COL_PRODUCT_NAME, "产品名称")
    c_asset_code = (cols or {}).get(COL_ASSET_CODE, "资产代码")
    c_category = (cols or {}).get(category_field, category_field)

    tiers = liquidity_tiers or _DEFAULT_LIQUIDITY_TIERS

    prod_clause = ""
    if product_filter:
        p_list = ", ".join(f"'{p}'" for p in product_filter)
        prod_clause = f'WHERE "{c_product}" IN ({p_list})'

    sql = f"""
        SELECT "{c_product}" AS 产品名称,
               "{c_category}" AS 资产类别,
               SUM("{market_value_field}") AS 市值,
               COUNT(DISTINCT "{c_asset_code}") AS 品种数
        FROM {holding_table}
        {prod_clause}
        GROUP BY "{c_product}", "{c_category}"
    """
    df = conn.execute(sql).df()

    # 归层
    df["tier"] = df["资产类别"].map(lambda c: tiers.get(str(c), 3))

    results = []
    for product, grp in df.groupby("产品名称"):
        total_mv = float(grp["市值"].sum())
        if total_mv <= 0:
            continue

        bands = []
        for tier_id, sub in grp.groupby("tier"):
            mv = float(sub["市值"].sum())
            cnt = int(sub["品种数"].sum())
            bands.append(LiquidityBandResult(
                product_name=product,
                tier=tier_id,
                tier_label=_TIER_LABELS.get(tier_id, f"层{tier_id}"),
                market_value=round(mv, 2),
                ratio_pct=round(mv / total_mv * 100, 2),
                security_count=cnt,
            ))

        tier1_mv = float(grp[grp["tier"] == 1]["市值"].sum())
        tier12_mv = float(grp[grp["tier"].isin([1, 2])]["市值"].sum())
        tier34_mv = float(grp[grp["tier"].isin([3, 4])]["市值"].sum())

        liquid_pct = round(tier12_mv / total_mv * 100, 2)
        high_liquid_pct = round(tier1_mv / total_mv * 100, 2)
        illiquid_pct = round(tier34_mv / total_mv * 100, 2)

        results.append(LiquidityResult(
            product_name=product,
            total_assets=round(total_mv, 2),
            liquid_ratio_pct=liquid_pct,
            high_liquidity_ratio_pct=high_liquid_pct,
            illiquid_ratio_pct=illiquid_pct,
            bands=sorted(bands, key=lambda b: b.tier),
            threshold_liquid_pct=threshold_liquid_pct,
            is_breach=liquid_pct < threshold_liquid_pct,
            data_date=data_date,
        ))

    results.sort(key=lambda r: r.liquid_ratio_pct)
    return results
