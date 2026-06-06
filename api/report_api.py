"""
api/report_api.py — 报告下载与模板路由
"""
import os
import re

from flask import Blueprint, jsonify, send_from_directory

from session_store import BASE_DIR

report_bp = Blueprint('report', __name__)


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
