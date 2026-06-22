"""
api/data.py — 文件上传、数据表管理路由
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
        return jsonify({
            "ok": True,
            "file_path": file_path,
            "filename": file.filename,
            "file_kind": "document",
            "file_type": doc_result.file_type,
            "text_preview": doc_result.text[:500],
            "word_count": doc_result.word_count,
            "page_count": doc_result.page_count,
            "table_count": len(doc_result.tables),
        })

    import pandas as pd

    from tools.data_loader import (
        auto_detect_table_type,
        detect_encoding,
        extract_date_from_filename,
    )
    try:
        if ext == '.csv':
            enc = detect_encoding(file_path)
            df_preview = pd.read_csv(file_path, encoding=enc, dtype=str,
                                     keep_default_na=False, nrows=3)
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

    auto_type = auto_detect_table_type(df_preview, file.filename)
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

    from tools.data_loader import auto_detect_table_type, detect_encoding, extract_date_from_filename
    ext = file_path.suffix.lower()
    try:
        if ext == '.csv':
            enc = detect_encoding(str(file_path))
            df_preview = pd.read_csv(str(file_path), encoding=enc, dtype=str,
                                     keep_default_na=False, nrows=3)
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

    auto_type = auto_detect_table_type(df_preview, filename)
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
