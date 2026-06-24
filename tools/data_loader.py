"""
tools/data_loader.py — 数据加载门面模块

拆分后的职责：
  1. LoadResult dataclass
  2. DuckDB 连接管理（全局单例 + 元数据持久化）
  3. 表注册表 / 字段映射查询
  4. 表类型自动检测 / 文件名日期提取
  5. 从子模块 re-export 公共 API（保持外部 import 兼容）

子模块：
  tools/encoding.py     — 编码检测 + 列名清洗
  tools/dict_mapper.py  — 数据字典映射 + 主体归一 + 用户档案校验
  tools/file_ingest.py  — CSV/Excel 文件加载引擎
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

# ═══════════════════════════════════════════════════════════════
#  子模块 re-export（保持外部 import 兼容）
# ═══════════════════════════════════════════════════════════════

from tools.encoding import (  # noqa: F401
    clean_column_name,
    clean_thousands_separator,
    detect_encoding,
)
from tools.dict_mapper import (  # noqa: F401
    DICT_TABLE_MAP,
    apply_dictionary_mapping,
    load_dictionary,
    normalize_entity_column,
    validate_user_profile_products,
)
from tools.file_ingest import (  # noqa: F401
    LARGE_FILE_THRESHOLD,
    drop_table,
    evict_old_versions,
    load_file,
)


# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class LoadResult:
    """单次文件加载结果"""
    table_name: str
    file_path: str
    row_count: int
    col_count: int
    encoding: str
    date_tag: str | None
    field_map: dict
    unmatched_cols: list
    missing_required: list
    warnings: list
    table_type: str
    quality_report: object | None = None


# ═══════════════════════════════════════════════════════════════
#  DuckDB 连接（全局单例）
# ═══════════════════════════════════════════════════════════════

_global_conn: duckdb.DuckDBPyConnection | None = None

_loaded_tables: dict[str, LoadResult] = {}

_db_path: str = ':memory:'

_METADATA_PATH = Path(__file__).parent.parent / 'data' / 'table_metadata.json'


# ─── 表类型自动检测关键词 ─────────────────────────────────────
_HOLDING_KEYWORDS = {"持仓", "市值", "穿透", "资产代码", "持有量", "持仓日期"}
_NAV_KEYWORDS = {"净值", "累计净值", "万份收益", "七日年化", "单位净值"}
_RATING_ENTITY_KEYWORDS = {"主体评级", "主体名称", "发行人评级", "内部评级"}
_RATING_BOND_KEYWORDS = {"债项评级", "债券代码", "债券评级", "ISIN", "评级日期"}


def _detect_with_scores(df, filename: str = "") -> tuple[str, dict[str, int]]:
    """内部：关键词评分，返回 (best_type, scores)。"""
    cols_text = " ".join(df.columns)
    filename_lower = filename.lower()
    scores = {
        "holding": sum(1 for k in _HOLDING_KEYWORDS if k in cols_text),
        "nav": sum(1 for k in _NAV_KEYWORDS if k in cols_text),
        "rating_entity": sum(1 for k in _RATING_ENTITY_KEYWORDS if k in cols_text),
        "rating_bond": sum(1 for k in _RATING_BOND_KEYWORDS if k in cols_text),
    }
    if "持仓" in filename_lower or "holding" in filename_lower:
        scores["holding"] += 2
    if "净值" in filename_lower or "nav" in filename_lower:
        scores["nav"] += 2
    if "主体" in filename_lower and "评级" in filename_lower:
        scores["rating_entity"] += 2
    if "债券" in filename_lower and "评级" in filename_lower:
        scores["rating_bond"] += 2

    best = max(scores, key=scores.get)
    return (best if scores[best] > 0 else "unknown"), scores


def auto_detect_table_type(df, filename: str = "") -> str:
    """
    根据列名关键词自动检测表类型。
    Returns: 'holding' | 'nav' | 'rating_entity' | 'rating_bond' | 'unknown'
    """
    result, _ = _detect_with_scores(df, filename)
    return result


def extract_date_from_filename(filename: str) -> str | None:
    """
    从文件名提取日期字符串（返回 YYYYMMDD 格式）。
    支持：YYYY-MM-DD / YYYYMMDD / YYMMDD / MMDD
    """
    from datetime import datetime

    m = re.search(r'(20\d{2})-(\d{2})-(\d{2})', filename)
    if m:
        return m.group(1) + m.group(2) + m.group(3)
    m = re.search(r'(20\d{6})', filename)
    if m:
        return m.group(1)
    m = re.search(r'(?<!\d)(2[3-9]\d{4})(?!\d)', filename)
    if m:
        return "20" + m.group(1)
    m = re.search(r'(?<!\d)(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)', filename)
    if m:
        return datetime.now().strftime("%Y") + m.group(0)
    return None


# ═══════════════════════════════════════════════════════════════
#  元数据持久化
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  DuckDB 连接管理
# ═══════════════════════════════════════════════════════════════

def init_duckdb_connection(
    max_memory: str = "200MB", threads: int = 2,
) -> duckdb.DuckDBPyConnection:
    """创建并返回全局 DuckDB 连接（单例）。"""
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


# ═══════════════════════════════════════════════════════════════
#  表注册表查询
# ═══════════════════════════════════════════════════════════════

def get_loaded_tables() -> list[dict]:
    """
    返回已加载的所有表信息。
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


def get_all_field_maps() -> dict[str, str]:
    """
    返回所有已加载表的合并字段映射 {语义名 → 物理列名}。
    多表映射冲突时 last-one-wins 并记录 warning。
    """
    combined: dict[str, str] = {}
    for r in _loaded_tables.values():
        if r.field_map:
            for semantic, physical in r.field_map.items():
                if semantic in combined and combined[semantic] != physical:
                    print(
                        f"[data_loader] ⚠️ 字段映射冲突：「{semantic}」"
                        f" 在 {r.table_name} 中映射为「{physical}」"
                        f"（先前映射为「{combined[semantic]}」），使用后者"
                    )
                combined[semantic] = physical
    return combined


def get_field_map_for_table(table_name: str) -> dict[str, str] | None:
    """返回指定表的字段映射。表不存在或无映射时返回 None。"""
    loaded = _loaded_tables.get(table_name)
    if loaded and loaded.field_map:
        return dict(loaded.field_map)
    return None
