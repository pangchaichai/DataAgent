"""
tools/data_masker.py — 内测脱敏防控模块
对上传数据中指定字段进行确定性脱敏，保持数据内部关联性。
"""
import hashlib
import random
import string

import pandas as pd

ALPHA = string.ascii_letters
DIGITS = string.digits
ALPHANUM = ALPHA + DIGITS


def _make_seed(value: str, global_seed: int = 42) -> int:
    h = hashlib.md5(f"{global_seed}:{value}".encode('utf-8')).hexdigest()
    return int(h[:8], 16)


def _generate_masked(original: str, seed_val: int) -> str:
    if not original or not str(original).strip():
        return str(original)
    original = str(original)
    rng = random.Random(seed_val)
    has_cjk = any('一' <= ch <= '鿿' for ch in original)
    has_digit = any(ch in DIGITS for ch in original)
    has_alpha = any(ch in ALPHA for ch in original)

    def gen_char():
        pools = []
        if has_alpha:
            pools.append('alpha')
        if has_digit:
            pools.append('digit')
        if has_cjk:
            pools.append('cjk')
        if not pools:
            return rng.choice(ALPHANUM)
        kind = rng.choice(pools)
        if kind == 'alpha':
            return rng.choice(ALPHA)
        elif kind == 'digit':
            return rng.choice(DIGITS)
        else:
            return chr(rng.randint(0x4e00, 0x9fff))

    length = max(2, rng.randint(len(original) - 2, len(original) + 2))
    return ''.join(gen_char() for _ in range(length))


def mask_dataframe(df: pd.DataFrame, mask_fields: list[str],
                   global_seed: int = 42) -> tuple[pd.DataFrame, dict]:
    """对 DataFrame 中指定字段进行脱敏。

    Returns:
        (masked_df, mapping) — mapping 格式: {field: {原值: 脱敏值}}
    """
    df = df.copy()
    mapping = {}
    actual_fields = []
    for field in mask_fields:
        field = field.strip()
        if not field:
            continue
        matched = [c for c in df.columns if c.strip() == field]
        if matched:
            actual_fields.append(matched[0])

    for col in actual_fields:
        col_map = {}
        for idx, val in df[col].items():
            s = str(val) if pd.notna(val) else ''
            if not s.strip():
                continue
            if s not in col_map:
                seed = _make_seed(s, global_seed)
                col_map[s] = _generate_masked(s, seed)
            df.at[idx, col] = col_map[s]
        mapping[col] = col_map

    return df, mapping


def parse_mask_fields(raw: str) -> list[str]:
    """解析逗号分隔的字段名（支持中英文逗号）。"""
    if not raw:
        return []
    fields = raw.replace('，', ',').split(',')
    return [f.strip() for f in fields if f.strip()]


def get_masking_config() -> dict:
    """从 config.yaml 读取脱敏配置。

    仅当 config.yaml 存在且包含 masking 段时才生效。
    config.example.yaml 不触发脱敏验证。
    """
    import yaml
    from session_store import BASE_DIR
    cfg_path = BASE_DIR / 'config.yaml'
    if not cfg_path.exists():
        return {'enabled': False, 'fields': ''}
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return {'enabled': False, 'fields': ''}
    masking = cfg.get('masking', {})
    if not masking:
        return {'enabled': False, 'fields': ''}
    return {
        'enabled': masking.get('enabled', True),
        'fields': masking.get('fields', ''),
    }


def validate_masking_ready() -> tuple[bool, str]:
    """检查脱敏配置是否就绪（开关开启且字段已配置）。

    Returns:
        (ok, message)
    """
    mc = get_masking_config()
    if not mc['enabled']:
        return True, ''
    fields = parse_mask_fields(mc['fields'])
    if not fields:
        return False, '内测脱敏已开启但未配置脱敏字段，请前往「设置」页面配置需要脱敏的字段名'
    return True, ''
