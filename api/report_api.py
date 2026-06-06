"""
api/report_api.py — 报告生成、下载与模板路由
"""
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, send_from_directory

from session_store import BASE_DIR

report_bp = Blueprint('report', __name__)


@report_bp.route('/api/report/generate', methods=['POST'])
def api_report_generate():
    data = request.get_json(force=True) if request.is_json else {}
    template_name = (data.get('template_name') or '').strip()
    report_data = data.get('data') or {}
    export_word = bool(data.get('export_word', False))

    if not template_name:
        return jsonify({"ok": False, "error": "缺少 template_name 参数"}), 400
    if not isinstance(report_data, dict):
        return jsonify({"ok": False, "error": "data 必须为 JSON 对象"}), 400

    from tools.report_builder import export_word as do_export, render_report
    result = render_report(template_name, report_data)
    if not result.ok:
        return jsonify({"ok": False, "error": result.error}), 400

    response = {"ok": True, "markdown": result.markdown, "template": template_name}

    if export_word:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{template_name}_{ts}.docx"
        output_path = str(BASE_DIR / 'data' / 'outputs' / filename)
        word_result = do_export(result.markdown, output_path)
        if word_result.ok:
            response["word_file"] = filename
            response["word_path"] = word_result.word_path
        else:
            response["word_warning"] = word_result.error

    return jsonify(response)


@report_bp.route('/api/report/download/<filename>')
def api_report_download(filename):
    if not re.match(r'^[\w\-]+\.docx$', filename):
        return jsonify({"error": "非法文件名"}), 400
    output_dir = os.path.join(BASE_DIR, 'data', 'outputs')
    file_path = os.path.join(output_dir, filename)
    if not os.path.isfile(file_path):
        return jsonify({"error": "文件不存在"}), 404
    return send_from_directory(output_dir, filename, as_attachment=True)


@report_bp.route('/api/report/templates')
def api_report_templates():
    from tools.report_builder import list_templates
    return jsonify({"templates": list_templates()})
