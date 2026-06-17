"""
calculators/columns.py — 语义列名常量 + 字段映射解析

所有固化计算器使用的列名在此集中定义为语义常量。
resolve_columns() 通过 data_dictionary 字段映射将语义名翻译为物理列名。

设计原则：
  - 计算器只引用语义常量（如 COL_PRODUCT_NAME）
  - 实际执行 SQL 时，通过 cols 字典获取物理列名
  - cols=None 时使用语义名本身作为默认值（向后兼容）
  - 字段映射找不到时显式报错，不猜测
"""

# ═══════════════════════════════════════════════════════════════
#  语义列名常量（持仓表）
# ═══════════════════════════════════════════════════════════════

COL_PRODUCT_NAME = "产品名称"
COL_ASSET_CODE = "资产代码"
COL_ASSET_NAME = "资产名称"
COL_MV_PENETRATED = "穿透后市值"
COL_MV_SEMI = "半穿透市值"
COL_ENTITY = "限额占用主体"
COL_ASSET_CATEGORY = "资产大类"
COL_ASSET_SUBCATEGORY = "资产细类"
COL_EXTERNAL_RATING = "外部评级"
COL_REMAINING_MATURITY = "剩余期限"
COL_MATURITY_DATE = "到期日"
COL_HOLDING_DATE = "持仓日期"
COL_G06_L1 = "G06一级分类"
COL_G06_L2 = "G06二级分类"

# ═══════════════════════════════════════════════════════════════
#  语义列名常量（净值表）
# ═══════════════════════════════════════════════════════════════

COL_NAV_PRODUCT = "产品名称"
COL_NAV_DATE = "估值日期"
COL_NAV_UNIT = "单位净值"
COL_NAV_TOTAL_ASSETS = "产品总资产"
COL_NAV_NET_ASSETS = "产品净资产"
COL_NAV_RETURN_7D = "七日年化收益率"
COL_NAV_RETURN_1M = "近1月年化收益率"
COL_NAV_RETURN_3M = "近3月年化收益率"
COL_NAV_RETURN_1Y = "近1年收益率"
COL_NAV_RETURN_YTD = "今年以来收益率"
COL_NAV_RETURN_INCEPTION = "成立以来收益率"

# ═══════════════════════════════════════════════════════════════
#  杠杆率计算用列名
# ═══════════════════════════════════════════════════════════════

COL_NAV_UNIT_VALUE = "单位净值"
COL_FUND_SHARE = "基金份额"


class ColumnResolutionError(Exception):
    """字段映射中找不到必需列时抛出"""


def resolve_columns(
    field_map: dict[str, str] | None,
    required: list[str],
    optional: list[str] | None = None,
) -> dict[str, str]:
    """
    将语义列名解析为物理列名。

    参数：
      field_map:  {语义名: 物理列名} — 来自 data_loader 的字典映射
                  None 时返回语义名自身（向后兼容，直调计算器场景）
      required:   必须解析成功的语义列名列表
      optional:   可选的语义列名列表（找不到时用语义名本身）

    返回：
      {语义名: 物理列名} 字典

    异常：
      ColumnResolutionError — required 中的列在 field_map 中找不到
    """
    if field_map is None:
        all_cols = required + (optional or [])
        return {c: c for c in all_cols}

    cols: dict[str, str] = {}
    missing: list[str] = []

    for semantic in required:
        physical = field_map.get(semantic)
        if physical:
            cols[semantic] = physical
        else:
            missing.append(semantic)

    if missing:
        available = ", ".join(sorted(field_map.keys())[:20])
        raise ColumnResolutionError(
            f"字段映射中缺少必需列：{', '.join(missing)}。"
            f"已有映射：{available}。"
            f"请检查数据字典配置或上传的数据文件列名。"
        )

    for semantic in (optional or []):
        cols[semantic] = field_map.get(semantic, semantic)

    return cols
