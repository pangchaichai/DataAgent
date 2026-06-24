"""
tools/file_ingest.py — 文件加载引擎（CSV / Excel → DuckDB）

从 data_loader.py 拆分而来。职责：
  1. load_file()：主加载入口（CSV/Excel → DuckDB 表）
  2. DuckDB 原生 CSV 加载（零 Python 内存开销）
  3. Pandas 回退加载
  4. 大 Excel 逐 Sheet 流式加载
  5. 表卸载与版本淘汰
"""

from pathlib import Path

import duckdb
import pandas as pd

LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB


# ═══════════════════════════════════════════════════════════════
#  DuckDB 原生 CSV 加载
# ═══════════════════════════════════════════════════════════════

def _load_csv_native(
    conn: duckdb.DuckDBPyConnection,
    file_path: str,
    table_name: str,
    encoding: str,
) -> dict | None:
    """
    用 DuckDB read_csv_auto 直接将 CSV 流式写入 DuckDB 页面。
    成功返回 {'columns': [...], 'row_count': int}，失败返回 None。
    """
    escaped_path = file_path.replace("'", "''")
    try:
        conn.execute(
            f"CREATE OR REPLACE TABLE \"{table_name}\" AS "
            f"SELECT * FROM read_csv_auto('{escaped_path}', "
            f"header=true, all_varchar=true, encoding='{encoding}')"
        )
    except Exception:
        return None

    cols_info = conn.execute(f'DESCRIBE "{table_name}"').fetchall()
    columns = [row[0] for row in cols_info]
    row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    return {'columns': columns, 'row_count': row_count}


def _native_clean_columns(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    columns: list[str],
) -> list[str]:
    """在 DuckDB 内用 ALTER TABLE RENAME COLUMN 清洗列名，返回清洗后的列名列表。"""
    from tools.encoding import clean_column_name

    cleaned = []
    for col in columns:
        new_name = clean_column_name(col)
        if new_name != col:
            safe_old = col.replace('"', '""')
            safe_new = new_name.replace('"', '""')
            try:
                conn.execute(
                    f'ALTER TABLE "{table_name}" RENAME COLUMN "{safe_old}" TO "{safe_new}"'
                )
            except Exception:
                new_name = col
        cleaned.append(new_name)
    return cleaned


def _native_clean_thousands(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    dict_data: dict | None,
    columns: list[str],
) -> None:
    """在 DuckDB 内用 UPDATE + REPLACE 清洗千分位分隔符。"""
    if not dict_data:
        return
    from tools.encoding import clean_column_name

    fields_needing_cleaning = [
        f for f in dict_data.get('fields', [])
        if f.get('requires_cleaning') == 'thousands_separator'
    ]
    for field_def in fields_needing_cleaning:
        for candidate in field_def.get('physical_candidates', []):
            cleaned_candidate = clean_column_name(candidate)
            if cleaned_candidate in columns:
                safe_col = cleaned_candidate.replace('"', '""')
                try:
                    conn.execute(
                        f'UPDATE "{table_name}" SET "{safe_col}" = '
                        f"REPLACE(\"{safe_col}\", ',', '') "
                        f"WHERE \"{safe_col}\" LIKE '%,%'"
                    )
                except Exception:
                    pass
                break


def _native_cast_floats(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    dict_data: dict | None,
    columns: list[str],
) -> None:
    """将字典中标注 dtype=float 的列转为 DOUBLE 类型。"""
    if not dict_data:
        return
    from tools.encoding import clean_column_name

    for field_def in dict_data.get('fields', []):
        if field_def.get('dtype') == 'float':
            for candidate in field_def.get('physical_candidates', []):
                cleaned_candidate = clean_column_name(candidate)
                if cleaned_candidate in columns:
                    safe_col = cleaned_candidate.replace('"', '""')
                    try:
                        conn.execute(
                            f'ALTER TABLE "{table_name}" ALTER COLUMN '
                            f'"{safe_col}" TYPE DOUBLE'
                        )
                    except Exception:
                        pass
                    break


# ═══════════════════════════════════════════════════════════════
#  Pandas CSV 回退加载
# ═══════════════════════════════════════════════════════════════

def _load_csv_pandas(
    file_path: str, encoding: str, warnings: list[str],
) -> pd.DataFrame:
    """Pandas CSV 加载（DuckDB 原生失败时的回退路径）。"""
    df = None
    candidates = [encoding] + [
        e for e in ['gb18030', 'utf-8', 'gbk', 'latin-1']
        if e.lower() != encoding.lower()
    ]
    last_err = None
    for enc in candidates:
        try:
            df = pd.read_csv(file_path, encoding=enc, dtype=str,
                             keep_default_na=False, na_values=[''])
            break
        except (UnicodeDecodeError, LookupError) as e:
            last_err = e
            continue
    if df is None:
        try:
            df = pd.read_csv(file_path, encoding='utf-8',
                             encoding_errors='replace', dtype=str,
                             keep_default_na=False, na_values=[''])
        except TypeError:
            with open(file_path, encoding='utf-8', errors='replace') as fh:
                df = pd.read_csv(fh, dtype=str,
                                 keep_default_na=False, na_values=[''])
        warnings.append(
            f"编码检测失败（{last_err}），已用 utf-8+replace 兜底读取，请确认数据是否正确"
        )
    return df


# ═══════════════════════════════════════════════════════════════
#  列映射辅助（无 DataFrame 路径）
# ═══════════════════════════════════════════════════════════════

def _apply_mapping_on_columns(
    columns: list[str], table_type: str | None,
) -> tuple[dict, list, list]:
    """对列名列表应用字典映射（用于 DuckDB 原生加载路径，无 DataFrame）。"""
    if not table_type:
        return {}, list(columns), []

    from tools.dict_mapper import load_dictionary

    dict_data = load_dictionary(table_type)
    if dict_data is None:
        return {}, list(columns), []

    field_map: dict[str, str] = {}
    missing_required: list[str] = []
    actual_cols = set(columns)
    fields = dict_data.get('fields', [])

    for field_def in fields:
        semantic = field_def['semantic']
        found = False
        for candidate in field_def.get('physical_candidates', []):
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
#  加载后收尾
# ═══════════════════════════════════════════════════════════════

def _finalize_load(
    conn: duckdb.DuckDBPyConnection,
    safe_table: str,
    result,
    table_type: str | None,
    dict_data: dict | None,
) -> None:
    """加载后公共收尾：质量诊断 + 注册 + 持久化 + Hook。"""
    from tools.data_loader import _loaded_tables, _save_table_metadata

    if table_type and dict_data:
        try:
            from tools.quality import compute_quality_report
            key_fields = [
                f['semantic'] for f in dict_data.get('fields', [])
                if f.get('required') or f.get('is_key')
            ]
            result.quality_report = compute_quality_report(
                conn, safe_table, table_type, result.field_map,
                key_fields=key_fields if key_fields else None,
            )
        except Exception as e:
            result.warnings.append(f"质量诊断失败：{e}")

    _loaded_tables[safe_table] = result
    _save_table_metadata()

    try:
        from agent.hooks import get_hook_manager
        get_hook_manager().emit("on_data_load", {
            "table_name": safe_table,
            "table_type": result.table_type,
            "row_count": result.row_count,
            "date_tag": result.date_tag,
        })
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  主加载函数
# ═══════════════════════════════════════════════════════════════

def load_file(
    file_path: str,
    table_name: str,
    date_tag: str | None = None,
    table_type: str | None = None,
    sheet_select: str | list[int] | None = None,
):
    """
    加载 CSV/Excel 文件到 DuckDB。

    参数:
      file_path:    文件绝对路径
      table_name:   注册到 DuckDB 的表名（如 holding_20260515）
      date_tag:     数据日期（如 20260515），用于时效校验
      table_type:   表类型（holding/nav/rating_entity/rating_bond），用于字典映射
      sheet_select: Excel Sheet 选择（"first" / "merge_all" / [0,2]）

    返回: LoadResult
    """
    from tools.data_loader import LoadResult, get_connection
    from tools.dict_mapper import (
        apply_dictionary_mapping,
        load_dictionary,
        normalize_entity_column,
    )
    from tools.encoding import clean_column_name, clean_thousands_separator, detect_encoding

    conn = get_connection()
    warnings: list[str] = []

    ext = Path(file_path).suffix.lower()
    encoding = 'utf-8'
    safe_table = table_name.replace('-', '_').replace('.', '_')

    if ext == '.csv':
        encoding = detect_encoding(file_path)
        dict_data = load_dictionary(table_type) if table_type else None

        native_result = _load_csv_native(conn, file_path, safe_table, encoding)
        if native_result is not None:
            columns = _native_clean_columns(conn, safe_table, native_result['columns'])
            _native_clean_thousands(conn, safe_table, dict_data, columns)
            _native_cast_floats(conn, safe_table, dict_data, columns)

            field_map, unmatched_cols, missing_required = (
                _apply_mapping_on_columns(columns, table_type)
            )
            if missing_required:
                warnings.append(
                    f"字典中标记为必填的字段在数据中未找到：{'、'.join(missing_required)}"
                )

            result = LoadResult(
                table_name=safe_table,
                file_path=file_path,
                row_count=native_result['row_count'],
                col_count=len(columns),
                encoding=encoding,
                date_tag=date_tag,
                field_map=field_map,
                unmatched_cols=unmatched_cols,
                missing_required=missing_required,
                warnings=warnings,
                table_type=table_type or 'unknown',
            )
            _finalize_load(conn, safe_table, result, table_type, dict_data)
            return result

        df = _load_csv_pandas(file_path, encoding, warnings)

    elif ext in ('.xlsx', '.xls'):
        encoding = 'n/a'
        file_size = Path(file_path).stat().st_size

        if file_size > LARGE_FILE_THRESHOLD:
            return _load_excel_streaming(
                conn, file_path, safe_table, table_type, date_tag,
                sheet_select=sheet_select,
            )
        else:
            from tools.excel_preprocessor import preprocess_excel
            prep = preprocess_excel(file_path, sheet_select=sheet_select)
            df = prep.df
            warnings.extend(prep.warnings)
    else:
        raise ValueError(f"不支持的文件格式：{ext}（支持 .csv, .xlsx, .xls）")

    # 列名清洗
    df.columns = [clean_column_name(c) for c in df.columns]

    # 千分位数值清洗 + 类型转换
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

            for field_def in dict_data.get('fields', []):
                if field_def.get('dtype') == 'float':
                    for candidate in field_def.get('physical_candidates', []):
                        if candidate in df.columns:
                            df[candidate] = pd.to_numeric(df[candidate], errors='coerce')
                            break

    # 数据字典字段映射
    field_map: dict[str, str] = {}
    unmatched_cols: list[str] = []
    missing_required: list[str] = []

    if table_type:
        field_map, unmatched_cols, missing_required = apply_dictionary_mapping(df, table_type)
        if missing_required:
            warnings.append(
                f"字典中标记为必填的字段在数据中未找到：{'、'.join(missing_required)}"
            )

    # 实体归一化
    if table_type:
        normalized_col = normalize_entity_column(df, field_map, table_type)
        if normalized_col:
            field_map['限额占用主体_标准'] = normalized_col

    # 注册到 DuckDB
    quoted_cols = [f'"{c}"' for c in df.columns]
    col_defs = ', '.join(quoted_cols)

    conn.execute(f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT {col_defs} FROM df')
    row_count = conn.execute(f'SELECT COUNT(*) FROM "{safe_table}"').fetchone()[0]

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

    _finalize_load(conn, safe_table, result, table_type, dict_data)
    return result


# ═══════════════════════════════════════════════════════════════
#  大 Excel 流式加载
# ═══════════════════════════════════════════════════════════════

def _load_excel_streaming(
    conn: duckdb.DuckDBPyConnection,
    file_path: str,
    safe_table: str,
    table_type: str | None,
    date_tag: str | None,
    sheet_select: str | list[int] | None = None,
):
    """大 Excel 文件逐 Sheet 流式加载。"""
    import gc

    from tools.data_loader import LoadResult
    from tools.dict_mapper import (
        apply_dictionary_mapping,
        load_dictionary,
        normalize_entity_column,
    )
    from tools.encoding import clean_column_name, clean_thousands_separator
    from tools.excel_preprocessor import preprocess_excel_streaming

    warnings: list[str] = []
    total_rows = 0
    col_count = 0
    field_map: dict[str, str] = {}
    unmatched_cols: list[str] = []
    missing_required: list[str] = []
    dict_data = load_dictionary(table_type) if table_type else None
    sheet_count = 0

    for df, info, is_compatible in preprocess_excel_streaming(
        file_path, sheet_select=sheet_select
    ):
        df.columns = [clean_column_name(c) for c in df.columns]

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
            for field_def in dict_data.get('fields', []):
                if field_def.get('dtype') == 'float':
                    for candidate in field_def.get('physical_candidates', []):
                        if candidate in df.columns:
                            df[candidate] = pd.to_numeric(df[candidate], errors='coerce')
                            break

        if sheet_count == 0:
            if table_type:
                field_map, unmatched_cols, missing_required = (
                    apply_dictionary_mapping(df, table_type)
                )
                normalized_col = normalize_entity_column(df, field_map, table_type)
                if normalized_col:
                    field_map['限额占用主体_标准'] = normalized_col

            quoted_cols = [f'"{c}"' for c in df.columns]
            col_defs = ', '.join(quoted_cols)
            conn.execute(
                f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT {col_defs} FROM df'
            )
            col_count = len(df.columns)
        elif is_compatible:
            if table_type and table_type in ('holding', 'rating_entity', 'rating_bond'):
                normalize_entity_column(df, field_map, table_type)
            quoted_cols = [f'"{c}"' for c in df.columns]
            col_defs = ', '.join(quoted_cols)
            conn.execute(
                f'INSERT INTO "{safe_table}" SELECT {col_defs} FROM df'
            )
        else:
            warnings.append(
                f"Sheet「{info.name}」列结构不同，已跳过"
            )
            del df
            gc.collect()
            sheet_count += 1
            continue

        total_rows += info.row_count
        del df
        gc.collect()
        sheet_count += 1

    if sheet_count == 0:
        raise ValueError(f"Excel 文件无有效数据：{file_path}")

    if sheet_count > 1:
        warnings.append(f"已流式加载 {sheet_count} 个 Sheet（共 {total_rows} 行）")

    if missing_required:
        warnings.append(
            f"字典中标记为必填的字段在数据中未找到：{'、'.join(missing_required)}"
        )

    row_count = conn.execute(f'SELECT COUNT(*) FROM "{safe_table}"').fetchone()[0]

    result = LoadResult(
        table_name=safe_table,
        file_path=file_path,
        row_count=row_count,
        col_count=col_count,
        encoding='n/a',
        date_tag=date_tag,
        field_map=field_map,
        unmatched_cols=unmatched_cols,
        missing_required=missing_required,
        warnings=warnings,
        table_type=table_type or 'unknown',
    )

    _finalize_load(conn, safe_table, result, table_type, dict_data)
    return result


# ═══════════════════════════════════════════════════════════════
#  表卸载与版本淘汰
# ═══════════════════════════════════════════════════════════════

def drop_table(table_name: str) -> bool:
    """从 DuckDB 卸载表并从注册表移除，返回 True 表示成功"""
    from tools.data_loader import _loaded_tables, _save_table_metadata, get_connection

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


def evict_old_versions(table_type: str, max_versions: int) -> list[str]:
    """按 date_tag 降序保留最新 max_versions 个同类型表，淘汰多余版本。"""
    from tools.data_loader import _loaded_tables

    same_type = [
        (name, r) for name, r in _loaded_tables.items()
        if r.table_type == table_type and r.date_tag
    ]
    same_type.sort(key=lambda x: x[1].date_tag or '', reverse=True)

    evicted = []
    for name, _ in same_type[max_versions:]:
        drop_table(name)
        evicted.append(name)
    return evicted
