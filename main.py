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
import queue
import socket
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from platform_adapter.ui_driver import get_driver
from platform_adapter.notify_driver import get_notify_driver


# ═══════════════════════════════════════════════════════════════
#  基础路径（绝对路径，兼容 PyInstaller 打包 + 任意 CWD）
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def find_free_port() -> int:
    """随机分配空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def load_config(path: str = None) -> dict:
    import yaml
    cfg_path = path or str(BASE_DIR / 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def wait_for_flask(port: int, timeout: float = 10.0):
    """健康检查：等待 Flask 就绪再打开窗口，最多等 timeout 秒"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


# ═══════════════════════════════════════════════════════════════
#  全局状态
# ═══════════════════════════════════════════════════════════════

_session_lock = threading.Lock()
_session = {
    "session_id": "",       # ★R3: 当前会话 ID（生成并持久化）
    "turn_count": 0,
    "loaded_files": [],  # [{path, table_name, date_tag, table_type}]
    "messages": [],      # ★R1: 对话历史 [{role, content, ...}]
    "pending": None,     # ★R1: 暂停状态 {type, tool_call_id, ...}
}

# SSE 流队列：sid → queue.Queue
# EventSource 只支持 GET，因此采用两步模式：
#   1. POST /api/chat → 后台启动 agent，返回 stream_id
#   2. GET /api/stream/<sid> → 消费队列，推送 SSE
_stream_queues: dict[str, queue.Queue] = {}
_stream_queues_lock = threading.Lock()


def _new_session_id() -> str:
    """生成新的会话 ID 并确保 sessions 目录存在"""
    sid = uuid.uuid4().hex[:12]
    (BASE_DIR / 'data' / 'sessions').mkdir(parents=True, exist_ok=True)
    return sid


def _save_session_messages():
    """★R3: 将当前会话 messages 持久化到 data/sessions/{id}.jsonl"""
    sid = _session.get("session_id")
    if not sid:
        return
    # 提取可持久化的消息（过滤 tool_calls 中的 function 对象）
    clean_msgs = []
    for m in _session.get("messages", []):
        cm = {"role": m.get("role"), "content": m.get("content")}
        if m.get("tool_calls"):
            cm["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            cm["tool_call_id"] = m["tool_call_id"]
        clean_msgs.append(cm)

    # 生成标题（首条用户消息前40字）
    title = ""
    for m in clean_msgs:
        if m["role"] == "user" and m.get("content"):
            title = str(m["content"])[:40]
            break

    from tools.data_loader import get_loaded_tables
    tables = [t["name"] for t in get_loaded_tables()]

    meta = {
        "id": sid,
        "title": title or "新对话",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tables": tables,
        "turn_count": _session.get("turn_count", 0),
    }

    session_file = BASE_DIR / 'data' / 'sessions' / f'{sid}.jsonl'
    with open(session_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps(meta, ensure_ascii=False) + '\n')
        for m in clean_msgs:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')


def reset_session():
    with _session_lock:
        old_id = _session.get("session_id", "")
        _session["turn_count"] = 0
        _session["messages"] = []
        _session["pending"] = None
        _session["session_id"] = _new_session_id()
        # 删除空会话文件
        if old_id:
            old_file = BASE_DIR / 'data' / 'sessions' / f'{old_id}.jsonl'
            try:
                old_file.unlink(missing_ok=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#  Flask 应用 + API 路由
# ═══════════════════════════════════════════════════════════════

def create_flask_app() -> Flask:
    """创建 Flask 应用，注册所有 API 路由"""
    # 使用绝对路径，兼容任意 CWD 和 PyInstaller
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / 'ui'),
        static_url_path='/static',
        template_folder=str(BASE_DIR / 'ui'),
    )
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

        # 绝对路径，兼容任意 CWD
        upload_dir = BASE_DIR / 'data' / 'uploads' / table_type
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(upload_dir / file.filename)
        file.save(file_path)

        if not table_name:
            stem = Path(file.filename).stem
            table_name = f"{table_type}_{stem}"

        from tools.data_loader import load_file, init_duckdb_connection
        init_duckdb_connection()
        try:
            result = load_file(file_path, table_name, date_tag=date_tag or None, table_type=table_type or None)
        except Exception as e:
            return jsonify({"ok": False, "error": f"文件加载失败：{str(e)[:200]}"}), 500

        with _session_lock:
            _session["loaded_files"].append({
                "path": file_path, "table_name": table_name,
                "date_tag": date_tag or "", "table_type": table_type,
            })

        # ★R2：返回质量诊断报告
        response_data = {"ok": True, "table_name": table_name}
        if result.quality_report:
            from dataclasses import asdict
            response_data["quality_report"] = asdict(result.quality_report)

        return jsonify(response_data)

    # ── POST /api/chat — 启动对话，返回 stream_id ────────────
    # 前端拿到 stream_id 后再用 EventSource 订阅 /api/stream/<sid>
    @app.route('/api/chat', methods=['POST'])
    def api_chat():
        data = request.get_json(force=True) if request.is_json else {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({"ok": False, "error": "消息为空"}), 400

        sid = str(uuid.uuid4())
        q: queue.Queue = queue.Queue()

        with _stream_queues_lock:
            _stream_queues[sid] = q

        # ★R1：读取会话消息历史和暂停状态
        with _session_lock:
            if not _session.get("session_id"):
                _session["session_id"] = _new_session_id()
            current_turn = _session["turn_count"]
            session_msgs = list(_session["messages"])
            pending = _session.get("pending")
            _session["pending"] = None

        # 在后台线程运行 agent loop，事件写入队列
        def run_agent_bg():
            from agent.loop import run_agent_loop
            from agent.llm_client import LLMClient
            from agent.skill_loader import SkillLoader
            from tools.data_loader import init_duckdb_connection

            init_duckdb_connection()
            cfg_path = str(BASE_DIR / 'config.yaml')
            skills_dir = str(BASE_DIR / 'skills')
            llm_client = LLMClient(cfg_path)
            skill_loader = SkillLoader(local_dir=skills_dir)

            try:
                for event in run_agent_loop(
                    message, llm_client, skill_loader,
                    turn_count=current_turn,
                    session_messages=session_msgs,
                    pending=pending,
                ):
                    # ★R1：处理暂停信号 — 保存状态供下次请求续跑
                    if event.get("type") == "__pending__":
                        with _session_lock:
                            _session["pending"] = event["data"]
                            _session["messages"] = list(session_msgs)
                            _save_session_messages()  # ★R3: 暂停时也持久化
                        continue  # 不推给前端

                    q.put(event)

                # 循环正常结束 → 保存最终消息历史
                with _session_lock:
                    _session["messages"] = list(session_msgs)
                    _session["turn_count"] += 1
                    _save_session_messages()  # ★R3: 持久化会话
            except Exception as e:
                q.put({"type": "error", "data": f"Agent 处理异常：{str(e)}"})
            finally:
                q.put(None)  # 哨兵：流结束

        threading.Thread(target=run_agent_bg, daemon=True).start()
        return jsonify({"ok": True, "stream_id": sid})

    # ── POST /api/confirm — 用户确认/取消 ──────────────────
    @app.route('/api/confirm', methods=['POST'])
    def api_confirm():
        """处理 request_confirmation 的用户回应"""
        data = request.get_json(force=True) if request.is_json else {}
        confirmed = data.get('confirmed', False)
        feedback = data.get('feedback', '')

        with _session_lock:
            pending = _session.get("pending")
            if not pending or pending.get("type") != "confirm":
                return jsonify({"ok": False, "error": "没有待确认事项"}), 400
            # 把确认结果注入 pending
            pending["confirmed"] = confirmed
            if feedback:
                pending["feedback"] = feedback
            _session["pending"] = pending

        return jsonify({
            "ok": True,
            "message": "已确认，正在继续..." if confirmed else "已取消",
            "confirmed": confirmed,
        })

    # ── GET /api/stream/<sid> — SSE 流（EventSource 消费）──
    @app.route('/api/stream/<sid>')
    def api_stream(sid):
        with _stream_queues_lock:
            q = _stream_queues.get(sid)
        if q is None:
            return jsonify({"error": "stream not found"}), 404

        def generate():
            try:
                while True:
                    try:
                        event = q.get(timeout=120)
                    except queue.Empty:
                        # 超时保活 ping
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:
                        # 正常结束，推送 stream_end 给前端
                        yield f"data: {json.dumps({'type': 'stream_end', 'data': None}, ensure_ascii=False)}\n\n"
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                with _stream_queues_lock:
                    _stream_queues.pop(sid, None)

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    # ── GET /api/memory/stats — 记忆库统计 ──────────────────
    @app.route('/api/memory/stats')
    def api_memory_stats():
        from agent.memory import load_memory_from_config
        mem = load_memory_from_config(str(BASE_DIR / 'config.yaml'))
        return jsonify(mem.get_stats())

    # ── POST /api/reset — 重置对话会话 ──────────────────────
    @app.route('/api/reset', methods=['POST'])
    def api_reset():
        reset_session()
        return jsonify({"ok": True})

    # ── GET /api/health — 系统健康状态 ─────────────────────
    @app.route('/api/health')
    def api_health():
        try:
            import psutil
            proc = psutil.Process()
            ram_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
        except Exception:
            ram_mb = 0

        with _session_lock:
            token_used = 0
            turn = _session.get("turn_count", 0)

        llm_status = "online"
        llm_name = "deepseek-chat"
        llm_latency = 0

        # 尝试获取 LLM 状态（从 config）
        try:
            from agent.llm_client import LLMClient
            client = LLMClient(str(BASE_DIR / 'config.yaml'))
            llm_name = client.sql_gen_cfg.get('model', 'deepseek-chat')
        except Exception:
            pass

        return jsonify({
            "llm_status": llm_status,
            "llm_name": llm_name,
            "llm_latency": llm_latency,
            "ram_mb": ram_mb,
            "token_used": token_used,
            "token_limit": 64000,
            "turn_count": turn,
        })

    # ── GET /api/skills — Skills 注册表 ──────────────────────
    @app.route('/api/skills')
    def api_skills():
        from agent.skill_loader import SkillLoader
        loader = SkillLoader(local_dir=str(BASE_DIR / 'skills'))
        registry = loader.load_registry()
        skills = [
            {
                "name": s.name,
                "description": s.description.split('\n')[0][:80],
                "calc_type": s.calc_type,
            }
            for s in registry
        ]
        return jsonify({"skills": skills})

    # ── GET /api/groups — 集团系列表 ──────────────────────────
    @app.route('/api/groups')
    def api_groups():
        from tools.entity_manager import EntityManager
        mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
        return jsonify({"groups": mgr.list_groups()})

    # ── GET /api/sessions — 最近会话列表 ────────────────────
    @app.route('/api/sessions')
    def api_sessions():
        sessions_dir = BASE_DIR / 'data' / 'sessions'
        if not sessions_dir.exists():
            return jsonify({"sessions": []})

        sessions = []
        for f in sorted(sessions_dir.glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(f, encoding='utf-8') as fp:
                    meta = json.loads(fp.readline())
                sessions.append({
                    "id": meta.get("id", f.stem),
                    "title": meta.get("title", "未命名"),
                    "updated_at": meta.get("updated_at", ""),
                    "tables": meta.get("tables", []),
                    "turn_count": meta.get("turn_count", 0),
                })
            except Exception:
                continue

        return jsonify({"sessions": sessions})

    # ── GET /api/sessions/<id> — 载入会话消息 ──────────────
    @app.route('/api/sessions/<session_id>')
    def api_session_detail(session_id):
        session_file = BASE_DIR / 'data' / 'sessions' / f'{session_id}.jsonl'
        if not session_file.exists():
            return jsonify({"error": "会话不存在"}), 404

        messages = []
        meta = {}
        try:
            with open(session_file, encoding='utf-8') as f:
                lines = f.readlines()
            if lines:
                meta = json.loads(lines[0])
                for line in lines[1:]:
                    messages.append(json.loads(line))
        except Exception as e:
            return jsonify({"error": f"读取会话失败：{e}"}), 500

        return jsonify({
            "id": meta.get("id", session_id),
            "title": meta.get("title", ""),
            "updated_at": meta.get("updated_at", ""),
            "tables": meta.get("tables", []),
            "messages": messages,
        })

    return app


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

def main():
    # 将工作目录切换到项目根目录，确保各模块的相对路径兼容
    os.chdir(BASE_DIR)

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
