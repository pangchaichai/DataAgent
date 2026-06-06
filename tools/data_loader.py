"""
tools/data_loader.py — 数据文件加载器

职责：
  1. DuckDB 连接初始化（内存限制 80MB，线程数 2）
  2. CSV/Excel 文件加载（chardet 编码检测 + 千分位清洗 + 列名清洗）
  3. 加载后自动应用 data_dictionary/ 字段映射
  4. 对「限额占用主体」字段自动调用 entity_normalizer 归一
  5. 时效标注 + 用户档案产品名校验

约束：
  - DuckDB 只读 open 模式通过 query_runner 的 SQLGuard 保证，本模块不设权限
  - 所有列名清洗后应不含首尾空格、不含不可见字符
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import chardet
import duckdb
import pandas as pd
import yaml

# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class LoadResult:
    """单次文件加载结果"""
    table_name: str          # 注册到 DuckDB 的表名
    file_path: str           # 原始文件路径
    row_count: int           # 行数
    col_count: int           # 列数
    encoding: str            # 检测到的编码
    date_tag: str | None  # 数据日期（用户指定或从文件名推断）
    field_map: dict          # 语义名 → 实际列名 的映射
    unmatched_cols: list     # CSV 中存在但字典中未定义的列名
    missing_required: list   # 字典中 required=True 但在 CSV 中未找到的字段
    warnings: list           # 加载过程中的警告信息
    table_type: str          # 表类型（holding/nav/rating_entity/rating_bond/unknown）
    quality_report: object | None = None  # ★R2: 数据质量诊断报告


# ═══════════════════════════════════════════════════════════════
#  DuckDB 连接（全局单例）
# ═══════════════════════════════════════════════════════════════

_global_conn: duckdb.DuckDBPyConnection | None = None

# 已加载表注册表：{table_name: LoadResult}
_loaded_tables: dict[str, LoadResult] = {}

# DB 路径：':memory:' 表示内存模式（测试默认）；生产由 main.py 设置为文件路径
_db_path: str = ':memory:'

# 元数据 JSON 路径（文件模式时持久化 _loaded_tables）
_METADATA_PATH = Path(__file__).parent.parent / 'data' / 'table_metadata.json'

# ─── 表类型自动检测关键词 ─────────────────────────────────────
_HOLDING_KEYWORDS = {"持仓", "市值", "穿透", "资产代码", "持有量", "持仓日期"}
_NAV_KEYWORDS = {"净值", "累计净值", "万份收益", "七日年化", "单位净值"}
_RATING_ENTITY_KEYWORDS = {"主体评级", "主体名称", "发行人评级", "内部评级"}
_RATING_BOND_KEYWORDS = {"债项评级", "债券代码", "债券评级", "ISIN", "评级日期"}


def auto_detect_table_type(df: pd.DataFrame, filename: str = "") -> str:
    """
    根据列名关键词自动检测表类型。
    Returns: 'holding' | 'nav' | 'rating_entity' | 'rating_bond' | 'unknown'
    """
    cols_text = " ".join(df.columns)
    filename_lower = filename.lower()
    scores = {
        "holding": sum(1 for k in _HOLDING_KEYWORDS if k in cols_text),
        "nav": sum(1 for k in _NAV_KEYWORDS if k in cols_text),
        "rating_entity": sum(1 for k in _RATING_ENTITY_KEYWORDS if k in cols_text),
        "rating_bond": sum(1 for k in _RATING_BOND_KEYWORDS if k in cols_text),
    }
    # Filename hints (bonus)
    if "持仓" in filename_lower or "holding" in filename_lower:
        scores["holding"] += 2
    if "净值" in filename_lower or "nav" in filename_lower:
        scores["nav"] += 2
    if "主体" in filename_lower and "评级" in filename_lower:
        scores["rating_entity"] += 2
    if "债券" in filename_lower and "评级" in filename_lower:
        scores["rating_bond"] += 2

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def extract_date_from_filename(filename: str) -> str | None:
    """
    从文件名提取日期字符串（返回 YYYYMMDD 格式）。
    支持模式：20260515 / 260515（两位年→补20） / 0515（当前年）
    """
    from datetime import datetime
    # 8位完整日期
    m = re.search(r'(20\d{6})', filename)
    if m:
        return m.group(1)
    # 6位 YYMMDD（如 260515）
    m = re.search(r'(?<!\d)(2[3-9]\d{4})(?!\d)', filename)
    if m:
        return "20" + m.group(1)
    # 4位 MMDD（如 0515）
    m = re.search(r'(?<!\d)(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)', filename)
    if m:
        return datetime.now().strftime("%Y") + m.group(0)
    return None


def _save_table_metadata() -> None:
    """将 _loaded_tables 持久化到 JSON（仅文件模式）。"""
    if _db_path == ':memory:':
        return
    data: dict[str, dict] = {}
    for name, r in _loaded_tables.items():
        data[name] = {
            "table_name": r.table_name,
            "file_path": r.file_path,
            "row_count": r.row_count,
            "col_count": r.col_count,
            "encoding": r.encoding,
            "date_tag": r.date_tag,
            "field_map": r.field_map,
            "unmatched_cols": r.unmatched_cols,
            "missing_required": r.missing_required,
            "warnings": r.warnings,
            "table_type": r.table_type,
        }
    try:
        _METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _METADATA_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except Exception:
        pass


def _restore_table_registry() -> None:
    """从 JSON 恢复 _loaded_tables（启动时调用，仅文件模式）。"""
    if not _METADATA_PATH.exists():
        return
    try:
        data = json.loads(_METADATA_PATH.read_text(encoding='utf-8'))
    except Exception:
        return
    existing = {r[0] for r in _global_conn.execute("SHOW TABLES").fetchall()}
    for name, d in data.items():
        if name not in existing:
            continue
        _loaded_tables[name] = LoadResult(
            table_name=d["table_name"],
            file_path=d.get("file_path", ""),
            row_count=d.get("row_count", 0),
            col_count=d.get("col_count", 0),
            encoding=d.get("encoding", ""),
            date_tag=d.get("date_tag"),
            field_map=d.get("field_map", {}),
            unmatched_cols=d.get("unmatched_cols", []),
            missing_required=d.get("missing_required", []),
            warnings=d.get("warnings", []),
            table_type=d.get("table_type", "unknown"),
        )


def init_duckdb_connection(max_memory: str = "200MB", threads: int = 2) -> duckdb.DuckDBPyConnection:
    """
    创建并返回全局 DuckDB 连接（单例）。
    生产模式使用文件持久化（_db_path 由 main.py 设置）；测试默认 :memory:。
    """
    global _global_conn
    if _global_conn is not None:
        return _global_conn
    _global_conn = duckdb.connect(_db_path)
    _global_conn.execute(f"SET max_memory='{max_memory}'")
    _global_conn.execute(f"SET threads={threads}")
    if _db_path != ':memory:':
        _restore_table_registry()
    return _global_conn


def get_connection() -> duckdb.DuckDBPyConnection:
    """获取已初始化的 DuckDB 连接（未初始化则自动创建）"""
    return init_duckdb_connection()


def get_loaded_tables() -> list[dict]:
    """
    返回已加载的所有表信息，用于侧边栏展示和 SQLGuard 动态校验。
    格式：[{name, rows, cols, type, date_tag}, ...]
    """
    return [
        {
            "name": r.table_name,
            "rows": r.row_count,
            "cols": r.col_count,
            "type": r.table_type,
            "date_tag": r.date_tag or "",
        }
        for r in _loaded_tables.values()
    ]


# ═══════════════════════════════════════════════════════════════
#  编码检测 + 列名清洗
# ═══════════════════════════════════════════════════════════════

def _is_cjk_char(cp: int) -> bool:
    """判断码点是否为 CJK 统一表意文字（含扩展区）"""
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or \
           (0x20000 <= cp <= 0x2FFFF) or (0xF900 <= cp <= 0xFAFF)


def _is_suspicious_char(cp: int) -> bool:
    """判断码点是否为可疑的乱码特征字符（box-drawing、Cyrillic、Latin-Ext等）
    这些字符出现在假定为中文的列名中通常意味着编码错误。"""
    # Box Drawing (U+2500-U+257F), Cyrillic (U+0400-U+04FF),
    # Latin Extended-A/B (U+0100-U+024F), IPA Extensions (U+0250-U+02AF)
    return (0x2500 <= cp <= 0x257F) or (0x0400 <= cp <= 0x04FF) or \
           (0x0100 <= cp <= 0x024F)


def _score_encoding(file_path: str, encoding: str) -> tuple[int, str]:
    """
    尝试用指定编码读取 CSV，对解码质量综合评分。
    返回 (score, reason)，分数越高越好。负分表示不可用。
    """
    import io
    try:
        # 读原始字节
        with open(file_path, 'rb') as f:
            raw = f.read(200000)  # 前 200KB 足够判断
        text = raw.decode(encoding)
        lines = text.split('\n')
        if len(lines) < 2:
            return (-1, "行数不足")

        header = lines[0]
        if not header.strip():
            return (-1, "空表头")

        score = 0
        total = len(header)
        cjk = suspicious = ascii_chars = 0

        for ch in header:
            cp = ord(ch)
            if _is_cjk_char(cp):
                cjk += 1
            elif _is_suspicious_char(cp):
                suspicious += 1
            elif cp < 128:
                ascii_chars += 1

        # 评分逻辑：
        # + CJK 字符：每个 +2 分（强信号，这是中文 CSV）
        # + ASCII：每个 +0.1 分（正常，中文列名通常中英混合）
        # - 可疑字符：每个 -3 分（强烈的编码错误信号）
        # - 只有 ASCII 没有 CJK：中性，给低分（可能是英文 CSV，任何编码都能读）
        score += cjk * 2
        score += ascii_chars * 0.1
        score -= suspicious * 3

        # 如果 CJK + 可疑字符都很少 → 可能是纯英文文件，给基线分
        if cjk == 0 and suspicious == 0:
            score = 10  # 纯 ASCII/英文，编码无关紧要

        # 解码成功率：用 pandas 试读验证
        try:
            df = pd.read_csv(io.StringIO(text), encoding='utf-8', dtype=str,
                             nrows=5, keep_default_na=False, na_values=[''])
            # pandas 能成功解析 → +5 分
            score += 5
        except Exception:
            score -= 10

        reason = (f"CJK={cjk} suspect={suspicious} ascii={ascii_chars} "
                  f"→ score={score}")
        return (score, reason)

    except (UnicodeDecodeError, LookupError):
        return (-100, f"无法用 {encoding} 解码")


def detect_encoding(file_path: str, sample_bytes: int = 50000) -> str:
    """★ 自适应编码检测：多编码竞争评分，自动选最优 ★"""
    # 候选编码列表（按常见程度排序，但最终由评分决定）
    candidates = ['utf-8', 'gb18030', 'gbk', 'gb2312', 'latin-1']

    # 先问 chardet 作为参考
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(sample_bytes)
        chardet_result = chardet.detect(raw)
        chardet_enc = chardet_result.get('encoding', 'utf-8')
        # 把 chardet 的结果放在候选列表最前面
        if chardet_enc and chardet_enc not in candidates:
            candidates.insert(0, chardet_enc)
        elif chardet_enc in candidates:
            candidates.remove(chardet_enc)
            candidates.insert(0, chardet_enc)
    except Exception:
        pass

    # 对所有候选编码评分
    best_score = -999
    best_enc = 'utf-8'
    results = []

    for enc in candidates:
        score, reason = _score_encoding(file_path, enc)
        results.append((enc, score, reason))
        if score > best_score:
            best_score = score
            best_enc = enc

    # 日志输出评分详情
    results.sort(key=lambda x: x[1], reverse=True)
    for enc, score, reason in results[:4]:
        marker = ' ★' if enc == best_enc else ''
        print(f"[data_loader]   {enc}: {reason}{marker}")

    if best_score < 0:
        print("[data_loader] ⚠️ 所有编码评分均为负，退回 utf-8")

    return best_enc


def clean_column_name(name: str) -> str:
    """
    清洗列名：去首尾空格、去不可见字符、去括号内注释（保留原列名的主要部分）。
    注意：括号可能包含有用信息（如单位），此处仅做轻量清洗。
    """
    name = name.strip()
    # 移除不可见字符（零宽空格等）
    name = re.sub(r'[​‌‍⁠﻿]', '', name)
    return name


def clean_thousands_separator(value) -> str:
    """移除千分位逗号：'1,234,567.89' → '1234567.89'"""
    s = str(value).strip()
    if not s or s.lower() == 'nan':
        return s
    # 匹配千分位逗号模式：数字中间的逗号
    if re.match(r'^-?[\d,]+\.?\d*$', s):
        s = s.replace(',', '')
    return s


# ═══════════════════════════════════════════════════════════════
#  字典映射
# ═══════════════════════════════════════════════════════════════

DICT_TABLE_MAP = {
    "holding": "holding_dict.yaml",
    "nav": "nav_dict.yaml",
    "rating_entity": "rating_entity_dict.yaml",
    "rating_bond": "rating_bond_dict.yaml",
    "monitoring": "monitoring_dict.yaml",
    "weekly_report": "weekly_report_dict.yaml",
}


def load_dictionary(table_type: str) -> dict | None:
    """加载对应类型的数据字典，文件不存在则返回 None"""
    filename = DICT_TABLE_MAP.get(table_type)
    if not filename:
        return None
    path = Path(__file__).resolve().parent.parent / "data_dictionary" / filename
    if not path.exists():
        return None
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def apply_dictionary_mapping(df: pd.DataFrame, table_type: str) -> tuple[dict, list, list]:
    """
    遍历 data_dictionary/{table_type}_dict.yaml 中的字段定义，
    在 DataFrame 的实际列名中查找匹配的 physical_candidates，
    建立「语义名 → 实际列名」的映射。

    返回:
      field_map:         {语义名: 实际列名}
      unmatched_cols:    CSV 中存在但字典中未定义的列名（提示用户但不报错）
      missing_required:  字典中 required=True 但在 CSV 中未找到的字段（需显式提示）
    """
    field_map: dict[str, str] = {}
    unmatched_cols: list[str] = []
    missing_required: list[str] = []

    actual_cols = set(df.columns)
    dict_data = load_dictionary(table_type)

    if dict_data is None:
        # 无字典时，所有列作为未匹配处理
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

    # 找出实际列中未被任何字典定义覆盖的列
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

    返回：归一化后的列名（用于 SQL 查询），无需归一则返回 None。
    """
    if table_type not in ('holding', 'rating_entity', 'rating_bond'):
        return None

    # 确定需要归一化的原始列
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
        print(f"[data_loader] ⚠️ 实体归一出错（跳过）：{e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  用户档案产品名校验
# ═══════════════════════════════════════════════════════════════

def validate_user_profile_products(
    loaded_product_names: set, config: dict
) -> list[str]:
    """
    校验 config.yaml 中 user_profile.managed_products 与实际数据中的产品名。
    返回不一致警告列表，供界面展示。
    """
    warnings = []
    managed = config.get('user_profile', {}).get('managed_products', [])
    managed_set = {p.strip() for p in managed if p.strip()}
    if not managed_set:
        return warnings  # 未配置用户档案，不校验

    # 配置文件中有但数据中没有的产品
    missing = managed_set - loaded_product_names
    if missing:
        warnings.append(f"配置中管理的产品在数据中未找到：{'、'.join(sorted(missing))}")

    # 数据中有但配置中未声明的产品（可能跨部门数据混入）
    extra = loaded_product_names - managed_set
    if extra:
        warnings.append(f"数据中存在配置中未声明的产品：{'、'.join(sorted(extra))}")

    return warnings


# ═══════════════════════════════════════════════════════════════
#  主加载函数
# ═══════════════════════════════════════════════════════════════

def load_file(
    file_path: str,
    table_name: str,
    date_tag: str | None = None,
    table_type: str | None = None,
) -> LoadResult:
    """
    加载 CSV/Excel 文件到 DuckDB。

    参数:
      file_path:   文件绝对路径
      table_name:  注册到 DuckDB 的表名（如 holding_20260515）
      date_tag:    数据日期（如 20260515），用于时效校验
      table_type:  表类型（holding/nav/rating_entity/rating_bond），用于字典映射

    处理流程：
      1. chardet 检测编码
      2. pandas 读取 CSV/Excel
      3. 列名清洗 + 千分位数值清洗
      4. 数据字典字段映射
      5. 实体归一（如适用）
      6. 注册到 DuckDB
      7. 返回 LoadResult
    """
    conn = get_connection()
    warnings: list[str] = []

    # ── 1. 检测编码 + 读取 ──────────────────────────────────
    ext = Path(file_path).suffix.lower()
    encoding = 'utf-8'

    if ext == '.csv':
        encoding = detect_encoding(file_path)
        try:
            df = pd.read_csv(file_path, encoding=encoding, dtype=str,
                             keep_default_na=False, na_values=[''])
        except (UnicodeDecodeError, LookupError):
            # 兜底：UTF-8 + error replace
            df = pd.read_csv(file_path, encoding='utf-8', dtype=str,
                             errors='replace')
            encoding = 'utf-8 (fallback)'
            warnings.append("编码回退至 utf-8（errors=replace）")

    elif ext in ('.xlsx', '.xls'):
        encoding = 'n/a'
        df = pd.read_excel(file_path, dtype=str)
    else:
        raise ValueError(f"不支持的文件格式：{ext}（支持 .csv, .xlsx, .xls）")

    # ── 2. 列名清洗 ────────────────────────────────────────
    df.columns = [clean_column_name(c) for c in df.columns]

    # ── 3. 千分位数值清洗 + 类型转换 ───────────────────
    dict_data = None
    if table_type:
        dict_data = load_dictionary(table_type)
        if dict_data:
            fields_needing_cleaning = [
                f for f in dict_data.get('fields', [])
                if f.get('requires_cleaning') == 'thousands_separator'
            ]
            for field_def in fields_needing_cleaning:
                for candidate in field_def.get('physical_candidates', []):
                    if candidate in df.columns:
                        df[candidate] = df[candidate].apply(clean_thousands_separator)
                        break

            # 将字典中标注 dtype=float 的列转为数值类型
            for field_def in dict_data.get('fields', []):
                if field_def.get('dtype') == 'float':
                    for candidate in field_def.get('physical_candidates', []):
                        if candidate in df.columns:
                            df[candidate] = pd.to_numeric(df[candidate], errors='coerce')
                            break

    # ── 4. 数据字典字段映射 ──────────────────────────────
    field_map: dict[str, str] = {}
    unmatched_cols: list[str] = []
    missing_required: list[str] = []

    if table_type:
        field_map, unmatched_cols, missing_required = apply_dictionary_mapping(df, table_type)
        if missing_required:
            warnings.append(
                f"字典中标记为必填的字段在数据中未找到：{'、'.join(missing_required)}"
            )
        if unmatched_cols:
            # 非错误，仅记录（辅助字段可能未被字典覆盖）
            pass

    # ── 5. 实体归一化 ─────────────────────────────────────
    if table_type:
        normalized_col = normalize_entity_column(df, field_map, table_type)
        if normalized_col:
            field_map['限额占用主体_标准'] = normalized_col

    # ── 6. 注册到 DuckDB ─────────────────────────────────
    quoted_cols = [f'"{c}"' for c in df.columns]
    safe_table = table_name.replace('-', '_').replace('.', '_')
    col_defs = ', '.join(quoted_cols)

    conn.execute(f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT {col_defs} FROM df')
    row_count = conn.execute(f'SELECT COUNT(*) FROM "{safe_table}"').fetchone()[0]

    # ── 7. 构建返回结果 ──────────────────────────────────
    result = LoadResult(
        table_name=safe_table,
        file_path=file_path,
        row_count=row_count,
        col_count=len(df.columns),
        encoding=encoding,
        date_tag=date_tag,
        field_map=field_map,
        unmatched_cols=unmatched_cols,
        missing_required=missing_required,
        warnings=warnings,
        table_type=table_type or 'unknown',
    )

    # ── 8. 数据质量诊断 ──────────────────────────────────
    if table_type and dict_data:
        try:
            from tools.quality import compute_quality_report
            key_fields = [
                f['semantic'] for f in dict_data.get('fields', [])
                if f.get('required') or f.get('is_key')
            ]
            result.quality_report = compute_quality_report(
                conn, safe_table, table_type, field_map,
                key_fields=key_fields if key_fields else None,
            )
        except Exception as e:
            result.warnings.append(f"质量诊断失败：{e}")

    _loaded_tables[safe_table] = result
    _save_table_metadata()
    return result


def drop_table(table_name: str) -> bool:
    """从 DuckDB 卸载表并从注册表移除，返回 True 表示成功"""
    global _loaded_tables
    if table_name not in _loaded_tables:
        return False
    conn = get_connection()
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    except Exception:
        pass
    del _loaded_tables[table_name]
    _save_table_metadata()
    return True
