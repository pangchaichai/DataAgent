"""
tools/dict_mapper.py — 数据字典映射 + 主体归一 + 用户档案校验

从 data_loader.py 拆分而来。职责：
  1. DICT_TABLE_MAP：表类型 → 字典 YAML 文件映射
  2. 加载字典 + 合并共享同义词
  3. apply_dictionary_mapping：语义名 → 实际列名映射
  4. 主体归一（委托 entity_normalizer）
  5. 用户档案产品名校验
"""

from pathlib import Path

import pandas as pd
import yaml

# ═══════════════════════════════════════════════════════════════
#  表类型 → 字典文件映射
# ═══════════════════════════════════════════════════════════════

DICT_TABLE_MAP = {
    "holding": "holding_dict.yaml",
    "nav": "nav_dict.yaml",
    "rating_entity": "rating_entity_dict.yaml",
    "rating_bond": "rating_bond_dict.yaml",
    "monitoring": "monitoring_dict.yaml",
    "weekly_report": "weekly_report_dict.yaml",
    "holding_detail": "holding_detail_dict.yaml",
    "valuation": "valuation_dict.yaml",
    "subscription": "subscription_dict.yaml",
    "asset_position": "asset_position_dict.yaml",
    "cashflow_gap": "cashflow_gap_dict.yaml",
    "bond_pledge": "bond_pledge_dict.yaml",
    "account_flow": "account_flow_dict.yaml",
    "repo_trade": "repo_trade_dict.yaml",
    "fund_position": "fund_position_dict.yaml",
}


# ═══════════════════════════════════════════════════════════════
#  共享同义词
# ═══════════════════════════════════════════════════════════════

_shared_synonyms_cache: dict | None = None


def _load_shared_synonyms() -> dict[str, list[str]]:
    """加载共享同义词库，返回 {synonym_group_name: [候选列名]}。"""
    global _shared_synonyms_cache
    if _shared_synonyms_cache is not None:
        return _shared_synonyms_cache
    path = Path(__file__).resolve().parent.parent / "data_dictionary" / "shared_synonyms.yaml"
    if not path.exists():
        _shared_synonyms_cache = {}
        return _shared_synonyms_cache
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    _shared_synonyms_cache = data.get('synonym_groups', {})
    return _shared_synonyms_cache


_SEMANTIC_TO_SYNONYM_GROUP = {
    "产品名称": "product_name",
    "限额占用主体": "entity_name",
    "资产代码": "asset_code",
    "资产名称": "asset_name",
    "统计日期": "stat_date",
    "持仓日期": "stat_date",
    "估值日期": "stat_date",
    "记账日期": "stat_date",
}


def _merge_shared_synonyms(dict_data: dict) -> dict:
    """将共享同义词合并到字典字段的 physical_candidates（去重、保持原有优先级）。"""
    synonyms = _load_shared_synonyms()
    if not synonyms:
        return dict_data

    for field_def in dict_data.get('fields', []):
        semantic = field_def.get('semantic', '')
        group_name = _SEMANTIC_TO_SYNONYM_GROUP.get(semantic)
        if not group_name:
            continue
        group_values = synonyms.get(group_name, [])
        if not group_values:
            continue
        existing = field_def.get('physical_candidates', [])
        existing_set = set(existing)
        for val in group_values:
            if val not in existing_set:
                existing.append(val)
                existing_set.add(val)
        field_def['physical_candidates'] = existing

    return dict_data


# ═══════════════════════════════════════════════════════════════
#  字典加载 + 字段映射
# ═══════════════════════════════════════════════════════════════

def load_dictionary(table_type: str) -> dict | None:
    """加载对应类型的数据字典，合并共享同义词后返回。文件不存在则返回 None。"""
    filename = DICT_TABLE_MAP.get(table_type)
    if not filename:
        return None
    path = Path(__file__).resolve().parent.parent / "data_dictionary" / filename
    if not path.exists():
        return None
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    if data:
        data = _merge_shared_synonyms(data)
    return data


def apply_dictionary_mapping(df: pd.DataFrame, table_type: str) -> tuple[dict, list, list]:
    """
    遍历 data_dictionary/{table_type}_dict.yaml 中的字段定义，
    在 DataFrame 的实际列名中查找匹配的 physical_candidates，
    建立「语义名 → 实际列名」的映射。

    返回:
      field_map:         {语义名: 实际列名}
      unmatched_cols:    CSV 中存在但字典中未定义的列名
      missing_required:  字典中 required=True 但在 CSV 中未找到的字段
    """
    field_map: dict[str, str] = {}
    unmatched_cols: list[str] = []
    missing_required: list[str] = []

    actual_cols = set(df.columns)
    dict_data = load_dictionary(table_type)

    if dict_data is None:
        return {}, list(actual_cols), []

    fields = dict_data.get('fields', [])

    for field_def in fields:
        semantic = field_def['semantic']
        candidates = field_def.get('physical_candidates', [])
        found = False
        for candidate in candidates:
            if candidate in actual_cols:
                field_map[semantic] = candidate
                found = True
                break
        if not found and field_def.get('required', False):
            missing_required.append(semantic)

    all_candidates = set()
    for field_def in fields:
        all_candidates.update(field_def.get('physical_candidates', []))
    unmatched_cols = [c for c in actual_cols if c not in all_candidates]

    return field_map, unmatched_cols, missing_required


# ═══════════════════════════════════════════════════════════════
#  主体归一（委托给 entity_normalizer）
# ═══════════════════════════════════════════════════════════════

def normalize_entity_column(df: pd.DataFrame, field_map: dict, table_type: str) -> str | None:
    """
    对「限额占用主体」字段进行归一化处理。
    在 DataFrame 中新增「限额占用主体_标准」列。
    返回：归一化后的列名，无需归一则返回 None。
    """
    if table_type not in ('holding', 'rating_entity', 'rating_bond'):
        return None

    entity_col = field_map.get('限额占用主体')
    if entity_col is None or entity_col not in df.columns:
        return None

    try:
        from tools.entity_normalizer import EntityNormalizer
        normalizer = EntityNormalizer()
        new_col = '限额占用主体_标准'
        df[new_col] = df[entity_col].apply(normalizer.normalize)
        return new_col
    except Exception as e:
        print(f"[dict_mapper] ⚠️ 实体归一出错（跳过）：{e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  用户档案产品名校验
# ═══════════════════════════════════════════════════════════════

def validate_user_profile_products(
    loaded_product_names: set, config: dict
) -> list[str]:
    """
    校验 config.yaml 中 user_profile.managed_products 与实际数据中的产品名。
    返回不一致警告列表。
    """
    warnings = []
    managed = config.get('user_profile', {}).get('managed_products', [])
    managed_set = {p.strip() for p in managed if p.strip()}
    if not managed_set:
        return warnings

    missing = managed_set - loaded_product_names
    if missing:
        warnings.append(f"配置中管理的产品在数据中未找到：{'、'.join(sorted(missing))}")

    extra = loaded_product_names - managed_set
    if extra:
        warnings.append(f"数据中存在配置中未声明的产品：{'、'.join(sorted(extra))}")

    return warnings
