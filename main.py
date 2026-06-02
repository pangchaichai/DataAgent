"""
main.py — DataAgent 入口

支持两种运行模式（通过环境变量 DATAAGENT_ENV 控制）：
  DATAAGENT_ENV=dev  → 浏览器模式（Linux/Mac 开发）
  DATAAGENT_ENV=prod → PyWebView 模式（Windows 生产）
  不设置             → 自动检测

Linux 开发启动：
  python main.py
  # 或显式指定
  DATAAGENT_ENV=dev python main.py

Windows 生产启动：
  python main.py
  # 或双击打包后的 DataAgent.exe
"""

import json
import os
import socket
import time
import yaml
from pathlib import Path

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from platform_adapter.ui_driver import get_driver
from platform_adapter.notify_driver import get_notify_driver


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def find_free_port() -> int:
    """随机分配空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def load_config(path: str = 'config.yaml') -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


# ═══════════════════════════════════════════════════════════════
#  全局状态（Phase 1 简化为内存 session）
# ═══════════════════════════════════════════════════════════════

_session = {
    "turn_count": 0,
    "loaded_files": [],  # [{path, table_name, date_tag, table_type}]
}


def reset_session():
    _session["turn_count"] = 0


# ═══════════════════════════════════════════════════════════════
#  Flask 应用 + API 路由
# ═══════════════════════════════════════════════════════════════

def create_flask_app() -> Flask:
    """创建 Flask 应用，注册所有 API 路由"""
    app = Flask(__name__, static_folder='ui', static_url_path='/static', template_folder='ui')
    CORS(app)

    # ── 前端页面 ────────────────────────────────────────────
    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    # ── GET /api/tables — 已加载数据表列表 ──────────────────
    @app.route('/api/tables')
    def api_tables():
        from tools.data_loader import get_loaded_tables
        return jsonify({"tables": get_loaded_tables()})

    # ── POST /api/upload — 上传数据文件 ─────────────────────
    @app.route('/api/upload', methods=['POST'])
    def api_upload():
        if 'file' not in request.files:
            return jsonify({"ok": False, "error": "未收到文件"}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({"ok": False, "error": "文件名为空"}), 400

        table_type = request.form.get('table_type', 'unknown')
        date_tag = request.form.get('date_tag', '')
        table_name = request.form.get('table_name', '')

        # 保存文件到 data/uploads/{table_type}/
        upload_dir = Path('data/uploads') / table_type
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(upload_dir / file.filename)
        file.save(file_path)

        # 自动生成表名
        if not table_name:
            stem = Path(file.filename).stem
            table_name = f"{table_type}_{stem}"

        from tools.data_loader import load_file, init_duckdb_connection
        init_duckdb_connection()
        try:
            load_file(file_path, table_name, date_tag=date_tag or None, table_type=table_type or None)
        except Exception as e:
            return jsonify({"ok": False, "error": f"文件加载失败：{str(e)[:200]}"}), 500

        _session["loaded_files"].append({
            "path": file_path, "table_name": table_name,
            "date_tag": date_tag or "", "table_type": table_type,
        })

        return jsonify({"ok": True, "table_name": table_name})

    # ── POST /api/chat — 对话 SSE 流 ────────────────────────
    @app.route('/api/chat', methods=['POST'])
    def api_chat():
        data = request.get_json(force=True) if request.is_json else {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({"ok": False, "error": "消息为空"}), 400

        root = app.root_path  # 闭包捕获

        def generate():
            import os as _os
            from agent.loop import run_agent_loop
            from agent.llm_client import LLMClient
            from agent.skill_loader import SkillLoader
            from tools.data_loader import init_duckdb_connection

            init_duckdb_connection()
            cfg_path = _os.path.join(root, 'config.yaml')
            skills_dir = _os.path.join(root, 'skills')
            llm_client = LLMClient(cfg_path)
            skill_loader = SkillLoader(local_dir=skills_dir)

            try:
                for event in run_agent_loop(message, llm_client, skill_loader, _session["turn_count"]):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                _session["turn_count"] += 1
            except Exception as e:
                error_event = {"type": "error", "data": f"Agent 处理异常：{str(e)}"}
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    # ── POST /api/reset — 重置对话会话 ──────────────────────
    @app.route('/api/reset', methods=['POST'])
    def api_reset():
        reset_session()
        return jsonify({"ok": True})

    return app


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

def main():
    config = load_config()
    port = find_free_port()

    notify = get_notify_driver()
    notify.push(f"DataAgent 启动中... 端口：{port}", level="info")

    if config.get('scheduler', {}).get('enabled', False):
        from scheduler.task_manager import TaskManager
        task_mgr = TaskManager(
            task_config_path=config['scheduler']['task_config'],
            agent_loop_fn=None,
            notify_fn=notify.push,
        )
        task_mgr.load_and_register()
        task_mgr.on_startup()
        task_mgr.start_background()

    app = create_flask_app()

    driver = get_driver()
    print(f"运行模式：{type(driver).__name__}")

    driver.start(
        flask_app=app,
        port=port,
        title=config.get('app', {}).get('window_title', 'DataAgent'),
        width=config.get('app', {}).get('window_width', 1280),
        height=config.get('app', {}).get('window_height', 800),
    )


if __name__ == '__main__':
    main()
