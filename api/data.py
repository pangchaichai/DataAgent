"""
api/data.py — 文件上传、数据表管理、远程数据源路由
"""
import re
from pathlib import Path

from flask import Blueprint, jsonify, request

from session_store import BASE_DIR, _session, _session_lock

data_bp = Blueprint('data', __name__)


@data_bp.route('/api/tables')
def api_tables():
    from tools.data_loader import get_loaded_tables
    return jsonify({"tables": get_loaded_tables()})


@data_bp.route('/api/documents')
def api_documents():
    """返回已上传的文档列表"""
    with _session_lock:
        docs = _session.get("documents", [])
    return jsonify({"documents": docs})


@data_bp.route('/api/tables/<table_name>', methods=['DELETE'])
def api_delete_table(table_name):
    from tools.data_loader import drop_table
    if not drop_table(table_name):
        return jsonify({"ok": False, "error": "表不存在"}), 404
    with _session_lock:
        _session["loaded_files"] = [
            f for f in _session.get("loaded_files", [])
            if f.get("table_name") != table_name
        ]
    return jsonify({"ok": True})


@data_bp.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({"ok": False, "error": "未收到文件"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"ok": False, "error": "文件名为空"}), 400

    pending_dir = BASE_DIR / 'data' / 'uploads' / 'pending'
    pending_dir.mkdir(parents=True, exist_ok=True)
    file_path = str(pending_dir / file.filename)
    file.save(file_path)

    ext = Path(file.filename).suffix.lower()

    if ext in ('.docx', '.pdf', '.txt'):
        from tools.file_reader import read_document
        doc_result = read_document(file_path, max_chars=2000)
        if not doc_result.ok:
            return jsonify({"ok": False, "error": doc_result.error}), 400
        # 将文档从 pending/ 移到永久 documents/ 目录
        doc_dir = BASE_DIR / 'data' / 'uploads' / 'documents'
        doc_dir.mkdir(parents=True, exist_ok=True)
        permanent_path = doc_dir / file.filename
        import shutil
        shutil.move(file_path, str(permanent_path))
        # 追踪已上传文档
        with _session_lock:
            docs = _session.setdefault("documents", [])
            docs.append({
                "filename": file.filename,
                "file_path": str(permanent_path),
                "file_type": doc_result.file_type,
                "word_count": doc_result.word_count,
                "page_count": doc_result.page_count,
                "text_preview": doc_result.text[:500],
                "table_count": len(doc_result.tables),
            })
        return jsonify({
            "ok": True,
            "file_path": str(permanent_path),
            "filename": file.filename,
            "file_kind": "document",
            "file_type": doc_result.file_type,
            "text_preview": doc_result.text[:500],
            "word_count": doc_result.word_count,
            "page_count": doc_result.page_count,
            "table_count": len(doc_result.tables),
        })

    from tools.data_masker import validate_masking_ready
    mask_ok, mask_msg = validate_masking_ready()
    if not mask_ok:
        return jsonify({"ok": False, "error": mask_msg}), 400

    import pandas as pd

    from tools.data_loader import detect_encoding, extract_date_from_filename

    from tools.encoding import clean_column_name, is_garbled

    try:
        if ext == '.csv':
            enc = detect_encoding(file_path)
            df_preview = pd.read_csv(file_path, encoding=enc, dtype=str,
                                     keep_default_na=False, nrows=3)
            if is_garbled(list(df_preview.columns)):
                for fallback_enc in ['utf-8-sig', 'utf-8', 'gb18030', 'gbk']:
                    if fallback_enc.lower() == enc.lower():
                        continue
                    try:
                        df_try = pd.read_csv(file_path, encoding=fallback_enc,
                                             dtype=str, keep_default_na=False, nrows=3)
                        if not is_garbled(list(df_try.columns)):
                            df_preview = df_try
                            break
                    except Exception:
                        continue
            df_preview.columns = [clean_column_name(c) for c in df_preview.columns]
            with open(file_path, 'rb') as _f:
                row_estimate = sum(1 for _ in _f) - 1
        else:
            from tools.excel_preprocessor import preprocess_excel
            prep = preprocess_excel(file_path)
            df_full = prep.df
            df_preview = df_full.head(3)
            row_estimate = len(df_full)
    except Exception as e:
        return jsonify({"ok": False, "error": f"文件读取失败：{str(e)[:200]}"}), 400

    from tools.smart_recognizer import enhanced_detect_table_type

    detection = enhanced_detect_table_type(df_preview, file.filename)
    auto_type = detection.table_type
    # honour an explicit table_type sent by the client (e.g. from tests or
    # direct API calls); fall back to auto-detection when absent or 'unknown'
    requested_type = request.form.get('table_type', '').strip()
    detected_type = requested_type if requested_type and requested_type != 'unknown' else auto_type
    detected_date = extract_date_from_filename(file.filename)

    resp = {
        "ok": True,
        "file_path": file_path,
        "filename": file.filename,
        "file_kind": "data",
        "detected_type": detected_type,
        "detected_date": detected_date or "",
        "columns": list(df_preview.columns),
        "preview_rows": df_preview.values.tolist(),
        "row_estimate": max(row_estimate, len(df_preview)),
        "col_count": len(df_preview.columns),
        "detection_meta": {
            "source": detection.source,
            "confidence": detection.confidence,
            "reason": detection.reason,
            "llm_suggestion": detection.llm_suggestion,
        },
    }
    if ext in ('.xlsx', '.xls'):
        resp["sheets"] = [{"name": s.name, "rows": s.row_count, "cols": s.col_count}
                          for s in prep.sheet_info]
        resp["sheets_concatenated"] = prep.sheets_concatenated
        resp["preprocess_warnings"] = prep.warnings
        first = prep.sheet_info[0] if prep.sheet_info else None
        if first:
            resp["preprocess_info"] = {
                "title_rows_skipped": first.title_rows_skipped,
                "header_levels": first.header_levels,
            }
    return jsonify(resp)


@data_bp.route('/api/upload/confirm', methods=['POST'])
def api_upload_confirm():
    data = request.get_json(force=True) or {}
    file_path = data.get('file_path', '')
    table_type = data.get('table_type', 'unknown')
    date_tag = data.get('date_tag', '')
    table_name = data.get('table_name', '')
    filename = data.get('filename', Path(file_path).name)

    uploads_dir = BASE_DIR / 'data' / 'uploads'
    try:
        Path(file_path).resolve().relative_to(uploads_dir.resolve())
    except ValueError:
        return jsonify({"ok": False, "error": "非法文件路径"}), 400

    if not Path(file_path).exists():
        return jsonify({"ok": False, "error": "文件不存在，请重新上传"}), 400

    dest_dir = BASE_DIR / 'data' / 'uploads' / table_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = str(dest_dir / filename)
    import shutil
    try:
        shutil.move(file_path, dest_path)
    except OSError as e:
        return jsonify({"ok": False, "error": f"文件移动失败：{str(e)[:200]}"}), 500

    if not table_name:
        stem = Path(filename).stem
        safe_stem = re.sub(r'[^a-zA-Z0-9一-鿿_\-]', '_', stem)
        table_name = f"{table_type}_{safe_stem}"

    masking_info = None
    from tools.data_masker import get_masking_config, mask_dataframe, parse_mask_fields
    mc = get_masking_config()
    if mc['enabled'] and mc['fields']:
        mask_fields = parse_mask_fields(mc['fields'])
        if mask_fields:
            try:
                import pandas as pd
                from tools.data_loader import detect_encoding
                ext_confirm = Path(dest_path).suffix.lower()
                if ext_confirm == '.csv':
                    enc = detect_encoding(dest_path)
                    df_raw = pd.read_csv(dest_path, encoding=enc, dtype=str,
                                         keep_default_na=False)
                else:
                    df_raw = pd.read_excel(dest_path, dtype=str)
                df_masked, _mapping = mask_dataframe(df_raw, mask_fields)
                if ext_confirm == '.csv':
                    df_masked.to_csv(dest_path, index=False, encoding='utf-8-sig')
                else:
                    df_masked.to_excel(dest_path, index=False)
                masked_cols = [c for c in _mapping if _mapping[c]]
                if masked_cols:
                    masking_info = {
                        "masked_fields": masked_cols,
                        "total_values_masked": sum(
                            len(_mapping[c]) for c in masked_cols
                        ),
                    }
            except Exception:
                pass

    from tools.data_loader import load_file
    try:
        result = load_file(dest_path, table_name,
                           date_tag=date_tag or None,
                           table_type=table_type or None)
    except Exception as e:
        return jsonify({"ok": False, "error": f"文件加载失败：{str(e)[:200]}"}), 500

    with _session_lock:
        _session["loaded_files"].append({
            "path": dest_path, "table_name": table_name,
            "date_tag": date_tag or "", "table_type": table_type,
        })

    from tools.runtime_logger import get_logger as _get_log
    _get_log().log_file_upload(filename, table_name, result.row_count, result.col_count)

    response_data = {
        "ok": True,
        "table_name": table_name,
        "row_count": result.row_count,
        "col_count": result.col_count,
    }
    if masking_info:
        response_data["masking_info"] = masking_info
    if result.quality_report:
        from dataclasses import asdict
        response_data["quality_report"] = asdict(result.quality_report)
    return jsonify(response_data)


@data_bp.route('/api/workdir/files')
def api_workdir_files():
    from tools.workdir_loader import get_work_dir, list_workdir_files
    work_dir = get_work_dir()
    files = list_workdir_files()
    return jsonify({
        "work_dir": str(work_dir) if work_dir else "",
        "files": files,
    })


@data_bp.route('/api/workdir/preview', methods=['POST'])
def api_workdir_preview():
    data = request.get_json(force=True) or {}
    filename = (data.get('filename') or '').strip()
    if not filename:
        return jsonify({"ok": False, "error": "文件名不能为空"}), 400

    from tools.workdir_loader import get_work_dir
    work_dir = get_work_dir()
    if not work_dir:
        return jsonify({"ok": False, "error": "工作目录未配置"}), 400

    file_path = work_dir / filename
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"ok": False, "error": "文件不存在"}), 404

    # Safety: ensure path is inside work_dir
    try:
        file_path.resolve().relative_to(work_dir.resolve())
    except ValueError:
        return jsonify({"ok": False, "error": "非法文件路径"}), 400

    import pandas as pd

    from tools.data_loader import detect_encoding, extract_date_from_filename
    from tools.encoding import clean_column_name, is_garbled

    ext = file_path.suffix.lower()
    try:
        if ext == '.csv':
            enc = detect_encoding(str(file_path))
            df_preview = pd.read_csv(str(file_path), encoding=enc, dtype=str,
                                     keep_default_na=False, nrows=3)
            if is_garbled(list(df_preview.columns)):
                for fallback_enc in ['utf-8-sig', 'utf-8', 'gb18030', 'gbk']:
                    if fallback_enc.lower() == enc.lower():
                        continue
                    try:
                        df_try = pd.read_csv(str(file_path), encoding=fallback_enc,
                                             dtype=str, keep_default_na=False, nrows=3)
                        if not is_garbled(list(df_try.columns)):
                            df_preview = df_try
                            break
                    except Exception:
                        continue
            df_preview.columns = [clean_column_name(c) for c in df_preview.columns]
            with open(str(file_path), 'rb') as _f:
                row_estimate = sum(1 for _ in _f) - 1
        else:
            from tools.excel_preprocessor import preprocess_excel
            prep_wd = preprocess_excel(str(file_path))
            df_full_wd = prep_wd.df
            df_preview = df_full_wd.head(3)
            row_estimate = len(df_full_wd)
    except Exception as e:
        return jsonify({"ok": False, "error": f"文件读取失败：{str(e)[:200]}"}), 400

    from tools.smart_recognizer import enhanced_detect_table_type

    detection_wd = enhanced_detect_table_type(df_preview, filename)
    auto_type = detection_wd.table_type
    detected_date = extract_date_from_filename(filename)
    stem = file_path.stem
    import re as _re
    safe_stem = _re.sub(r'[^a-zA-Z0-9一-鿿_\-]', '_', stem)

    resp_wd = {
        "ok": True,
        "file_path": str(file_path),
        "filename": filename,
        "file_kind": "data",
        "from_workdir": True,
        "detected_type": auto_type,
        "detected_date": detected_date or "",
        "columns": list(df_preview.columns),
        "preview_rows": df_preview.values.tolist(),
        "row_estimate": max(row_estimate, len(df_preview)),
        "col_count": len(df_preview.columns),
        "suggested_table_name": f"{auto_type}_{safe_stem}",
        "detection_meta": {
            "source": detection_wd.source,
            "confidence": detection_wd.confidence,
            "reason": detection_wd.reason,
            "llm_suggestion": detection_wd.llm_suggestion,
        },
    }
    if ext in ('.xlsx', '.xls'):
        resp_wd["sheets"] = [{"name": s.name, "rows": s.row_count, "cols": s.col_count}
                             for s in prep_wd.sheet_info]
        resp_wd["sheets_concatenated"] = prep_wd.sheets_concatenated
        resp_wd["preprocess_warnings"] = prep_wd.warnings
        first_wd = prep_wd.sheet_info[0] if prep_wd.sheet_info else None
        if first_wd:
            resp_wd["preprocess_info"] = {
                "title_rows_skipped": first_wd.title_rows_skipped,
                "header_levels": first_wd.header_levels,
            }
    return jsonify(resp_wd)


@data_bp.route('/api/workdir/load', methods=['POST'])
def api_workdir_load():
    data = request.get_json(force=True) or {}
    filename = (data.get('filename') or '').strip()
    table_type = data.get('table_type', 'unknown')
    date_tag = data.get('date_tag', '')
    table_name = data.get('table_name', '').strip()

    if not filename:
        return jsonify({"ok": False, "error": "文件名不能为空"}), 400

    from tools.workdir_loader import get_work_dir
    work_dir = get_work_dir()
    if not work_dir:
        return jsonify({"ok": False, "error": "工作目录未配置"}), 400

    file_path = work_dir / filename
    if not file_path.exists():
        return jsonify({"ok": False, "error": "文件不存在"}), 404

    try:
        file_path.resolve().relative_to(work_dir.resolve())
    except ValueError:
        return jsonify({"ok": False, "error": "非法文件路径"}), 400

    if not table_name:
        import re as _re
        safe_stem = _re.sub(r'[^a-zA-Z0-9一-鿿_\-]', '_', file_path.stem)
        table_name = f"{table_type}_{safe_stem}"

    from tools.data_loader import load_file
    try:
        result = load_file(str(file_path), table_name,
                           date_tag=date_tag or None,
                           table_type=table_type or None)
    except Exception as e:
        return jsonify({"ok": False, "error": f"加载失败：{str(e)[:200]}"}), 500

    from session_store import _session, _session_lock
    with _session_lock:
        _session["loaded_files"].append({
            "path": str(file_path), "table_name": table_name,
            "date_tag": date_tag or "", "table_type": table_type,
            "from_workdir": True,
        })

    from tools.runtime_logger import get_logger as _get_log
    _get_log().log_file_upload(filename, table_name, result.row_count, result.col_count)

    response_data = {
        "ok": True,
        "table_name": table_name,
        "row_count": result.row_count,
        "col_count": result.col_count,
    }
    if result.quality_report:
        from dataclasses import asdict
        response_data["quality_report"] = asdict(result.quality_report)
    return jsonify(response_data)


@data_bp.route('/api/workdir/load_all', methods=['POST'])
def api_workdir_load_all():
    """批量加载工作目录下所有 CSV/Excel 文件（跳过已加载的表）。"""
    from tools.workdir_loader import get_work_dir
    work_dir = get_work_dir()
    if not work_dir:
        return jsonify({"ok": False, "error": "工作目录未配置"}), 400

    allowed_exts = {'.csv', '.xlsx', '.xls'}
    files = [f for f in work_dir.iterdir()
             if f.is_file() and f.suffix.lower() in allowed_exts]
    if not files:
        return jsonify({"ok": True, "results": [], "message": "工作目录无 CSV/Excel 文件"})

    from tools.data_loader import extract_date_from_filename, get_loaded_tables, load_file
    from tools.smart_recognizer import enhanced_detect_table_type
    import pandas as pd, re as _re
    from tools.encoding import clean_column_name, detect_encoding, is_garbled

    already_loaded = {t['file_path'] for t in get_loaded_tables() if t.get('file_path')}
    results = []

    from session_store import _session, _session_lock

    for file_path in sorted(files, key=lambda f: f.name):
        if str(file_path) in already_loaded:
            results.append({"filename": file_path.name, "ok": True, "skipped": True,
                            "message": "已加载，跳过"})
            continue
        try:
            ext = file_path.suffix.lower()
            if ext == '.csv':
                enc = detect_encoding(str(file_path))
                df_preview = pd.read_csv(str(file_path), encoding=enc, dtype=str,
                                         keep_default_na=False, nrows=3)
                if is_garbled(list(df_preview.columns)):
                    for fb in ['utf-8-sig', 'utf-8', 'gb18030', 'gbk']:
                        if fb.lower() == enc.lower():
                            continue
                        try:
                            t = pd.read_csv(str(file_path), encoding=fb, dtype=str,
                                            keep_default_na=False, nrows=3)
                            if not is_garbled(list(t.columns)):
                                df_preview = t
                                break
                        except Exception:
                            continue
                df_preview.columns = [clean_column_name(c) for c in df_preview.columns]
            else:
                from tools.excel_preprocessor import preprocess_excel
                prep = preprocess_excel(str(file_path))
                df_preview = prep.df.head(3)

            detection = enhanced_detect_table_type(df_preview, file_path.name)
            table_type = detection.table_type
            date_tag = extract_date_from_filename(file_path.name) or ''
            safe_stem = _re.sub(r'[^a-zA-Z0-9一-鿿_\-]', '_', file_path.stem)
            table_name = f"{table_type}_{safe_stem}"

            result = load_file(str(file_path), table_name,
                               date_tag=date_tag or None,
                               table_type=table_type or None)
            with _session_lock:
                _session["loaded_files"].append({
                    "path": str(file_path), "table_name": table_name,
                    "date_tag": date_tag, "table_type": table_type,
                    "from_workdir": True,
                })
            results.append({"filename": file_path.name, "ok": True, "skipped": False,
                            "table_name": table_name, "rows": result.row_count})
        except Exception as e:
            results.append({"filename": file_path.name, "ok": False, "skipped": False,
                            "error": str(e)[:200]})

    success = sum(1 for r in results if r.get('ok') and not r.get('skipped'))
    skipped = sum(1 for r in results if r.get('skipped'))
    failed = sum(1 for r in results if not r.get('ok'))
    return jsonify({"ok": True, "results": results,
                    "success": success, "skipped": skipped, "failed": failed})


@data_bp.route('/api/tables/<table_name>/profile')
def api_table_profile(table_name):
    from tools.data_loader import get_connection, get_loaded_tables
    tables = get_loaded_tables()
    if not any(t['name'] == table_name for t in tables):
        return jsonify({"error": "表不存在"}), 404
    conn = get_connection()
    if not conn:
        return jsonify({"error": "数据库连接不可用"}), 500
    from tools.profiler import profile_table
    try:
        result = profile_table(conn, table_name)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"剖析失败：{str(e)[:200]}"}), 500


@data_bp.route('/api/tables/<table_name>/quality')
def api_table_quality(table_name):
    from tools.data_loader import _loaded_tables, get_connection, get_loaded_tables
    tables = get_loaded_tables()
    match = next((t for t in tables if t['name'] == table_name), None)
    if not match:
        return jsonify({"error": "表不存在"}), 404
    conn = get_connection()
    if not conn:
        return jsonify({"error": "数据库连接不可用"}), 500
    from dataclasses import asdict

    from tools.quality import compute_quality_report
    try:
        table_type = match.get('type', 'unknown')
        loaded_info = _loaded_tables.get(table_name)
        field_map = loaded_info.field_map if loaded_info and hasattr(loaded_info, 'field_map') else {}
        report = compute_quality_report(
            conn, table_name,
            table_type=table_type,
            field_map=field_map or {},
        )
        return jsonify({"ok": True, "report": asdict(report)})
    except Exception as e:
        return jsonify({"error": f"诊断失败：{str(e)[:200]}"}), 500


# ═══════════════════════════════════════════════════════════════
#  远程数据源 API
# ═══════════════════════════════════════════════════════════════

@data_bp.route('/api/datasource/connections')
def api_datasource_connections():
    from tools.remote_db import get_remote_db_manager
    mgr = get_remote_db_manager()
    return jsonify({'ok': True, 'connections': mgr.list_connections()})


@data_bp.route('/api/datasource/test', methods=['POST'])
def api_datasource_test():
    from tools.remote_db import DBConnection, get_remote_db_manager
    data = request.get_json(force=True) or {}
    conn = DBConnection(
        name=data.get('name', ''),
        db_type=data.get('db_type', ''),
        host=data.get('host', ''),
        port=int(data.get('port', 0)),
        database=data.get('database', ''),
        username=data.get('username', ''),
        password=data.get('password', ''),
        default_schema=data.get('default_schema', ''),
    )
    mgr = get_remote_db_manager()
    return jsonify(mgr.test_connection(conn))


@data_bp.route('/api/datasource/save', methods=['POST'])
def api_datasource_save():
    from tools.remote_db import DBConnection, get_remote_db_manager
    data = request.get_json(force=True) or {}
    conn = DBConnection(
        name=data.get('name', '').strip(),
        db_type=data.get('db_type', ''),
        host=data.get('host', ''),
        port=int(data.get('port', 0)),
        database=data.get('database', ''),
        username=data.get('username', ''),
        password=data.get('password', ''),
        default_schema=data.get('default_schema', ''),
    )
    mgr = get_remote_db_manager()
    return jsonify(mgr.save_connection(conn))


@data_bp.route('/api/datasource/connection/<name>', methods=['DELETE'])
def api_datasource_delete(name):
    from tools.remote_db import get_remote_db_manager
    mgr = get_remote_db_manager()
    return jsonify(mgr.delete_connection(name))


@data_bp.route('/api/datasource/tables')
def api_datasource_tables():
    conn_name = request.args.get('conn', '')
    if not conn_name:
        return jsonify({'ok': False, 'error': '缺少连接名称'}), 400
    from tools.remote_db import get_remote_db_manager
    mgr = get_remote_db_manager()
    return jsonify(mgr.list_tables(conn_name))


@data_bp.route('/api/datasource/preview', methods=['POST'])
def api_datasource_preview():
    data = request.get_json(force=True) or {}
    conn_name = data.get('conn', '')
    table = data.get('table', '')
    limit = int(data.get('limit', 100))
    if not conn_name or not table:
        return jsonify({'ok': False, 'error': '缺少连接名称或表名'}), 400

    from tools.remote_db import get_remote_db_manager
    mgr = get_remote_db_manager()
    result = mgr.preview_table(conn_name, table, limit)
    if not result['ok']:
        return jsonify(result)

    rqr = result['result']
    preview_rows = rqr.df.head(100).values.tolist()
    columns = list(rqr.df.columns)
    return jsonify({
        'ok': True,
        'columns': columns,
        'preview_rows': preview_rows,
        'row_count': result['row_count'],
        'col_count': result['col_count'],
        'query_time_ms': result['query_time_ms'],
    })


@data_bp.route('/api/datasource/import', methods=['POST'])
def api_datasource_import():
    data = request.get_json(force=True) or {}
    conn_name = data.get('conn', '')
    table_or_sql = data.get('table', '') or data.get('sql', '')
    local_table_name = data.get('table_name', '')
    table_type = data.get('table_type', 'unknown')
    date_tag = data.get('date_tag', '')

    if not conn_name or not table_or_sql:
        return jsonify({'ok': False, 'error': '缺少连接名称或数据源'}), 400
    if not local_table_name:
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', table_or_sql[:50])
        local_table_name = f'{table_type}_{safe}'

    from tools.remote_db import get_remote_db_manager
    mgr = get_remote_db_manager()
    result = mgr.import_to_local(
        conn_name, table_or_sql, local_table_name,
        table_type=table_type,
        date_tag=date_tag or None,
    )

    if result.get('ok'):
        from tools.runtime_logger import get_logger as _get_log
        _get_log().log_file_upload(
            f'remote:{conn_name}/{table_or_sql}',
            result['table_name'],
            result['row_count'],
            result['col_count'],
        )

    return jsonify(result)


# ═══════════════════════════════════════════════════════════════
#  金融资讯 API（Choice / iFind / Wind）
# ═══════════════════════════════════════════════════════════════

@data_bp.route('/api/vendor/status')
def api_vendor_status():
    from tools.vendor_api import get_vendor_adapter
    adapter = get_vendor_adapter()
    return jsonify({'ok': True, 'vendors': adapter.get_available_vendors()})


@data_bp.route('/api/vendor/connect', methods=['POST'])
def api_vendor_connect():
    data = request.get_json(force=True) or {}
    vendor = data.get('vendor', '')
    if not vendor:
        return jsonify({'ok': False, 'error': '缺少供应商名称'}), 400
    from tools.vendor_api import get_vendor_adapter
    adapter = get_vendor_adapter()
    return jsonify(adapter.connect(vendor))


@data_bp.route('/api/vendor/disconnect', methods=['POST'])
def api_vendor_disconnect():
    data = request.get_json(force=True) or {}
    vendor = data.get('vendor', '')
    if not vendor:
        return jsonify({'ok': False, 'error': '缺少供应商名称'}), 400
    from tools.vendor_api import get_vendor_adapter
    adapter = get_vendor_adapter()
    return jsonify(adapter.disconnect(vendor))


@data_bp.route('/api/vendor/fetch', methods=['POST'])
def api_vendor_fetch():
    data = request.get_json(force=True) or {}
    vendor = data.get('vendor', '')
    codes = data.get('codes', [])
    fields = data.get('fields', [])
    if not vendor or not codes or not fields:
        return jsonify({'ok': False, 'error': '缺少必要参数（vendor/codes/fields）'}), 400

    from tools.vendor_api import get_vendor_adapter
    adapter = get_vendor_adapter()
    result = adapter.fetch_data(
        vendor, codes, fields,
        start_date=data.get('start_date', ''),
        end_date=data.get('end_date', ''),
        query_type=data.get('query_type', 'snapshot'),
    )
    if not result['ok']:
        return jsonify(result)

    rqr = result['result']
    return jsonify({
        'ok': True,
        'columns': list(rqr.df.columns),
        'preview_rows': rqr.df.head(100).values.tolist(),
        'row_count': rqr.row_count,
        'col_count': rqr.col_count,
        'query_time_ms': rqr.query_time_ms,
    })


@data_bp.route('/api/vendor/import', methods=['POST'])
def api_vendor_import():
    data = request.get_json(force=True) or {}
    vendor = data.get('vendor', '')
    codes = data.get('codes', [])
    fields = data.get('fields', [])
    local_table_name = data.get('table_name', '')
    if not vendor or not codes or not fields:
        return jsonify({'ok': False, 'error': '缺少必要参数（vendor/codes/fields）'}), 400
    if not local_table_name:
        safe = re.sub(r'[^a-zA-Z0-9_]', '_', '_'.join(codes[:3]))
        local_table_name = f'vendor_{vendor}_{safe}'

    from tools.vendor_api import get_vendor_adapter
    adapter = get_vendor_adapter()
    result = adapter.import_vendor_data(
        vendor, codes, fields,
        local_table_name=local_table_name,
        table_type=data.get('table_type', 'unknown'),
        date_tag=data.get('date_tag', ''),
        start_date=data.get('start_date', ''),
        end_date=data.get('end_date', ''),
        query_type=data.get('query_type', 'snapshot'),
    )

    if result.get('ok'):
        from tools.runtime_logger import get_logger as _get_log
        _get_log().log_file_upload(
            f'vendor:{vendor}/{",".join(codes[:3])}',
            result['table_name'],
            result['row_count'],
            result['col_count'],
        )

    return jsonify(result)
