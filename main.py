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

import requests as _requests_lib
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
_config_file_lock = threading.Lock()
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
        had_messages = bool(_session.get("messages"))
        _session["turn_count"] = 0
        _session["messages"] = []
        _session["pending"] = None
        _session["session_id"] = _new_session_id()
        # 仅删除从未发过消息的空会话（有消息的已由 _save_session_messages 持久化，应保留）
        if old_id and not had_messages:
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

    # ── POST /api/upload — 上传文件（数据表或文档）─────────────
    @app.route('/api/upload', methods=['POST'])
    def api_upload():
        if 'file' not in request.files:
            return jsonify({"ok": False, "error": "未收到文件"}), 400

        file = request.files['file']
        if not file.filename:
            return jsonify({"ok": False, "error": "文件名为空"}), 400

        ext = Path(file.filename).suffix.lower()

        # ── 文档类：Word / PDF / TXT ─────────────────────────
        if ext in ('.docx', '.pdf', '.txt'):
            doc_dir = BASE_DIR / 'data' / 'uploads' / 'documents'
            doc_dir.mkdir(parents=True, exist_ok=True)
            file_path = str(doc_dir / file.filename)
            file.save(file_path)

            from tools.file_reader import read_document
            doc_result = read_document(file_path, max_chars=3000)
            if not doc_result.ok:
                return jsonify({"ok": False, "error": doc_result.error}), 400

            from tools.runtime_logger import get_logger as _get_log
            _get_log().log_file_upload(file.filename, "(document)", 0, 0)

            return jsonify({
                "ok": True,
                "file_kind": "document",
                "file_type": doc_result.file_type,
                "filename": file.filename,
                "file_path": file_path,
                "text_preview": doc_result.text[:500],
                "word_count": doc_result.word_count,
                "page_count": doc_result.page_count,
                "table_count": len(doc_result.tables),
            })

        # ── 数据表：CSV / Excel ──────────────────────────────
        table_type = request.form.get('table_type', 'unknown')
        date_tag = request.form.get('date_tag', '')
        table_name = request.form.get('table_name', '')

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

        from tools.runtime_logger import get_logger as _get_log
        _get_log().log_file_upload(file.filename, table_name,
                                   result.row_count if hasattr(result, 'row_count') else 0,
                                   result.col_count if hasattr(result, 'col_count') else 0)

        response_data = {"ok": True, "file_kind": "data", "table_name": table_name}
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
            _stream_queues[sid] = (q, None)

        # ★R1：读取会话消息历史和暂停状态
        with _session_lock:
            if not _session.get("session_id"):
                _session["session_id"] = _new_session_id()
            current_turn = _session["turn_count"]
            session_msgs = list(_session["messages"])
            pending = _session.get("pending")
            _session["pending"] = None

        # 记录用户操作日志
        from tools.runtime_logger import get_logger as _get_logger
        _get_logger().log_chat_start(message)

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
                from tools.runtime_logger import get_logger as _get_log
                _get_log().log_exception('agent', 'Agent 循环异常', e)
                q.put({"type": "error", "data": {"message": f"Agent 处理异常：{str(e)}"}})
            finally:
                q.put(None)  # 哨兵：流结束

        t = threading.Thread(target=run_agent_bg, daemon=True)
        t.start()

        # Store thread reference for liveness check in SSE generator
        with _stream_queues_lock:
            if sid in _stream_queues:
                _stream_queues[sid] = (q, t)

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
            entry = _stream_queues.get(sid)
        if entry is None:
            return jsonify({"error": "stream not found"}), 404
        q, bg_thread = entry

        def generate():
            try:
                while True:
                    try:
                        event = q.get(timeout=30)
                    except queue.Empty:
                        # 检查后台线程是否还活着
                        if bg_thread is not None and not bg_thread.is_alive():
                            yield f"data: {json.dumps({'type': 'stream_end', 'data': None}, ensure_ascii=False)}\n\n"
                            break
                        yield ": keep-alive\n\n"
                        continue
                    if event is None:
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
            turn = _session.get("turn_count", 0)

        llm_name = "deepseek-chat"
        llm_provider = "unknown"

        try:
            from agent.llm_client import LLMClient
            client = LLMClient(str(BASE_DIR / 'config.yaml'))
            primary = client.sql_gen_cfg.get('primary', 'enterprise_internal')
            provider_cfg = client.providers.get(primary, {})
            llm_name = provider_cfg.get('model', '') or client.sql_gen_cfg.get('model', 'deepseek-chat')
            llm_provider = primary
        except Exception:
            pass

        # 从 runtime_logger 获取今日实际 token 用量
        token_used = 0
        try:
            from tools.runtime_logger import get_logger
            stats = get_logger().get_stats()
            token_used = stats.get('token_total', 0)
        except Exception:
            pass

        from tools.data_loader import get_loaded_tables
        tables = get_loaded_tables()

        return jsonify({
            "llm_name": llm_name,
            "llm_provider": llm_provider,
            "ram_mb": ram_mb,
            "token_used": token_used,
            "token_limit": 64000,
            "turn_count": turn,
            "tables_count": len(tables),
        })

    # ── POST /api/llm/test — 测试 LLM 连接 ─────────────────
    @app.route('/api/llm/test', methods=['POST'])
    def api_llm_test():
        try:
            from agent.llm_client import LLMClient
            client = LLMClient(str(BASE_DIR / 'config.yaml'))
            primary = client.sql_gen_cfg.get('primary', 'deepseek')
            provider_cfg = client.providers.get(primary, {})
            url = provider_cfg.get('url', '')
            model = provider_cfg.get('model', '')
            api_key = provider_cfg.get('api_key', '')
            if not url or not api_key or api_key in ('你的DeepSeek_API_Key', '${DEEPSEEK_API_KEY}'):
                return jsonify({"ok": False, "error": "请先配置有效的 API Key 和服务地址"})
            resp = _requests_lib.post(
                f"{url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                timeout=15,
            )
            if resp.status_code == 200:
                return jsonify({"ok": True, "model": model, "provider": primary})
            else:
                err = resp.text[:200]
                return jsonify({"ok": False, "error": f"HTTP {resp.status_code}: {err}"})
        except _requests_lib.Timeout:
            return jsonify({"ok": False, "error": "连接超时（15秒）"})
        except _requests_lib.ConnectionError:
            return jsonify({"ok": False, "error": "无法连接到服务地址，请检查网络或 URL"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]})

    # ── GET /api/skills — Skills 注册表 ──────────────────────
    @app.route('/api/skills')
    def api_skills():
        from agent.skill_loader import SkillLoader
        loader = SkillLoader(local_dir=str(BASE_DIR / 'skills'))
        registry = loader.load_registry()
        skills = [
            {
                "name": s.name,
                "description": s.description,
                "calc_type": s.calc_type,
                "trigger_words": getattr(s, 'trigger_words', []),
                "required_tables": getattr(s, 'required_table_types', []),
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

    # ── GET /api/config — 读取配置（安全版，API Key 不返回明文）
    @app.route('/api/config')
    def api_config_read():
        import yaml
        cfg_path = BASE_DIR / 'config.yaml'
        src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
        try:
            with open(src, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            return jsonify({"error": f"读取配置失败：{e}"}), 500
        llm_cfg = cfg.get('llm', {})
        primary = llm_cfg.get('sql_gen', {}).get('primary', 'deepseek')
        provider_cfg = llm_cfg.get(primary, llm_cfg.get('deepseek', {}))
        raw_key = provider_cfg.get('api_key', '')
        api_key_set = bool(raw_key and raw_key not in ('', '你的DeepSeek_API_Key', '${DEEPSEEK_API_KEY}'))
        return jsonify({
            "user_profile": cfg.get('user_profile', {}),
            "calculation_config": cfg.get('calculation_config', {}),
            "memory": cfg.get('memory', {"enabled": False}),
            "scheduler": cfg.get('scheduler', {"enabled": True}),
            "app": cfg.get('app', {}),
            "api_key_set": api_key_set,
            "llm_url": provider_cfg.get('url', ''),
            "llm_model": provider_cfg.get('model', 'deepseek-chat'),
            "llm_provider": primary,
            "logging": cfg.get('logging', {"mode": "basic", "max_days": 30}),
        })

    # ── POST /api/config — 写入配置 ─────────────────────────
    @app.route('/api/config', methods=['POST'])
    def api_config_write():
        import yaml
        data = request.get_json(force=True) if request.is_json else {}
        cfg_path = BASE_DIR / 'config.yaml'
        with _config_file_lock:
            src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
            try:
                with open(src, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception:
                cfg = {}
            if 'user_profile' in data:
                cfg.setdefault('user_profile', {})
                for field in ('name', 'department', 'role', 'managed_products'):
                    if field in data['user_profile']:
                        cfg['user_profile'][field] = data['user_profile'][field]
            if 'calculation_config' in data:
                cfg.setdefault('calculation_config', {})
                cc = data['calculation_config']
                if 'concentration' in cc:
                    cfg['calculation_config'].setdefault('concentration', {})
                    for field in ('threshold_entity', 'threshold_single_bond',
                                  'market_value_field', 'use_group_merge', 'data_max_age_days'):
                        if field in cc['concentration']:
                            cfg['calculation_config']['concentration'][field] = cc['concentration'][field]
            if 'memory' in data and 'enabled' in data['memory']:
                cfg.setdefault('memory', {})['enabled'] = bool(data['memory']['enabled'])
            if 'scheduler' in data and 'enabled' in data['scheduler']:
                cfg.setdefault('scheduler', {})['enabled'] = bool(data['scheduler']['enabled'])
            if data.get('llm_url') or data.get('llm_model') or data.get('api_key'):
                llm_block = cfg.setdefault('llm', {})
                primary = llm_block.get('sql_gen', {}).get('primary', 'deepseek')
                provider_block = llm_block.setdefault(primary, llm_block.setdefault('deepseek', {}))
                if data.get('api_key'):
                    provider_block['api_key'] = data['api_key']
                if data.get('llm_url'):
                    provider_block['url'] = data['llm_url']
                if data.get('llm_model'):
                    provider_block['model'] = data['llm_model']
            try:
                tmp_path = cfg_path.with_suffix('.yaml.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                tmp_path.replace(cfg_path)
            except Exception as e:
                return jsonify({"ok": False, "error": f"写入配置失败：{e}"}), 500
        return jsonify({"ok": True})

    # ── POST /api/groups — 创建集团 ──────────────────────────
    @app.route('/api/groups', methods=['POST'])
    def api_create_group():
        data = request.get_json(force=True) if request.is_json else {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({"ok": False, "error": "集团名称不能为空"}), 400
        from tools.entity_manager import EntityManager
        mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
        try:
            mgr.create_group(name, data.get('members', []))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

    # ── POST /api/groups/<name>/members — 添加主体 ───────────
    @app.route('/api/groups/<name>/members', methods=['POST'])
    def api_add_member(name):
        data = request.get_json(force=True) if request.is_json else {}
        entity = (data.get('entity') or '').strip()
        if not entity:
            return jsonify({"ok": False, "error": "主体名称不能为空"}), 400
        from tools.entity_manager import EntityManager
        mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
        try:
            mgr.add_member(name, entity)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

    # ── DELETE /api/groups/<name>/members — 移除主体（entity 从请求体读取）
    @app.route('/api/groups/<name>/members', methods=['DELETE'])
    def api_remove_member(name):
        data = request.get_json(force=True) if request.is_json else {}
        entity_name = (data.get('entity') or '').strip()
        if not entity_name:
            return jsonify({"ok": False, "error": "主体名称不能为空"}), 400
        from tools.entity_manager import EntityManager
        mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
        try:
            mgr.remove_member(name, entity_name)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

    # ── DELETE /api/groups/<name> — 删除集团 ─────────────────
    @app.route('/api/groups/<name>', methods=['DELETE'])
    def api_delete_group(name):
        from tools.entity_manager import EntityManager
        mgr = EntityManager(str(BASE_DIR / 'groups.yaml'))
        try:
            mgr.delete_group(name)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True})

    # ── DELETE /api/sessions/<id> — 删除会话文件 ─────────────
    @app.route('/api/sessions/<session_id>', methods=['DELETE'])
    def api_delete_session(session_id):
        import re
        if not re.match(r'^[a-f0-9]{12}$', session_id):
            return jsonify({"ok": False, "error": "无效会话ID"}), 400
        session_file = BASE_DIR / 'data' / 'sessions' / f'{session_id}.jsonl'
        try:
            session_file.unlink(missing_ok=True)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})

    # ── DELETE /api/tables/<name> — 卸载数据表 ───────────────
    @app.route('/api/tables/<table_name>', methods=['DELETE'])
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

    # ── GET /api/tables/<name>/profile — 表结构剖析 ─────────
    @app.route('/api/tables/<table_name>/profile')
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

    # ── GET /api/tables/<name>/quality — 数据质量诊断 ────────
    @app.route('/api/tables/<table_name>/quality')
    def api_table_quality(table_name):
        from tools.data_loader import get_connection, get_loaded_tables, _loaded_tables
        tables = get_loaded_tables()
        match = next((t for t in tables if t['name'] == table_name), None)
        if not match:
            return jsonify({"error": "表不存在"}), 404
        conn = get_connection()
        if not conn:
            return jsonify({"error": "数据库连接不可用"}), 500
        from tools.quality import compute_quality_report
        from dataclasses import asdict
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

    # ── GET /api/tasks — 定时任务列表 ────────────────────────
    @app.route('/api/tasks')
    def api_tasks():
        import yaml
        tasks_path = BASE_DIR / 'tasks' / 'task_config.yaml'
        if not tasks_path.exists():
            return jsonify({"tasks": []})
        try:
            with open(tasks_path, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            return jsonify({"tasks": cfg.get('tasks', [])})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── POST /api/memory/clear — 清空记忆库 ──────────────────
    @app.route('/api/memory/clear', methods=['POST'])
    def api_memory_clear():
        from agent.memory import load_memory_from_config
        mem = load_memory_from_config(str(BASE_DIR / 'config.yaml'))
        if not mem.enabled:
            return jsonify({"ok": False, "error": "记忆功能未启用，请先在设置中开启"}), 400
        mem.clear()
        return jsonify({"ok": True})

    # ══════════════════════════════════════════════════════════
    #  Skill Builder API
    # ══════════════════════════════════════════════════════════

    # ── GET /api/skill-builder/drafts — 草稿列表 ──────────────
    @app.route('/api/skill-builder/drafts')
    def api_skill_drafts():
        from tools.skill_builder import list_drafts
        return jsonify({"drafts": list_drafts()})

    # ── POST /api/skill-builder/generate — LLM 辅助生成 ───────
    @app.route('/api/skill-builder/generate', methods=['POST'])
    def api_skill_generate():
        data = request.get_json(force=True) if request.is_json else {}
        description = (data.get('description') or '').strip()
        if not description:
            return jsonify({"ok": False, "error": "请描述你想创建的 Skill 功能"}), 400

        from tools.skill_builder import (
            build_skill_generation_prompt, parse_llm_skill_response,
            generate_skill_md, save_draft, SkillDraft,
        )
        from agent.llm_client import LLMClient

        try:
            llm = LLMClient(str(BASE_DIR / 'config.yaml'))
            prompt = build_skill_generation_prompt(description)
            result = llm.chat(
                [{"role": "user", "content": prompt}],
                tools=None,
            )
            if not result.success or not result.text:
                return jsonify({"ok": False, "error": "AI 生成失败，请重试"}), 500

            draft = parse_llm_skill_response(result.text)
            if not draft:
                return jsonify({"ok": False, "error": "AI 返回格式异常，请重新描述"}), 500

            content = generate_skill_md(draft)
            save_draft(draft.name, content)

            return jsonify({
                "ok": True,
                "name": draft.name,
                "content": content,
                "draft": {
                    "name": draft.name,
                    "description": draft.description,
                    "trigger_words": draft.trigger_words,
                    "calc_type": draft.calc_type,
                },
            })
        except Exception as e:
            return jsonify({"ok": False, "error": f"生成异常：{str(e)[:200]}"}), 500

    # ── POST /api/skill-builder/validate — 校验 ──────────────
    @app.route('/api/skill-builder/validate', methods=['POST'])
    def api_skill_validate():
        data = request.get_json(force=True) if request.is_json else {}
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({"ok": False, "error": "内容为空"}), 400

        from tools.skill_builder import validate_skill_md
        result = validate_skill_md(content, str(BASE_DIR / 'skills'))
        return jsonify({"ok": result.ok, "validation": result.to_dict()})

    # ── POST /api/skill-builder/save-draft — 保存草稿 ────────
    @app.route('/api/skill-builder/save-draft', methods=['POST'])
    def api_skill_save_draft():
        data = request.get_json(force=True) if request.is_json else {}
        name = (data.get('name') or '').strip()
        content = (data.get('content') or '').strip()
        if not name or not content:
            return jsonify({"ok": False, "error": "名称或内容为空"}), 400

        from tools.skill_builder import save_draft
        return jsonify(save_draft(name, content))

    # ── GET /api/skill-builder/draft/<name> — 加载草稿 ────────
    @app.route('/api/skill-builder/draft/<name>')
    def api_skill_load_draft(name):
        from tools.skill_builder import load_draft
        content = load_draft(name)
        if content is None:
            return jsonify({"error": "草稿不存在"}), 404
        return jsonify({"ok": True, "name": name, "content": content})

    # ── DELETE /api/skill-builder/draft/<name> — 删除草稿 ─────
    @app.route('/api/skill-builder/draft/<name>', methods=['DELETE'])
    def api_skill_delete_draft(name):
        from tools.skill_builder import delete_draft
        if not delete_draft(name):
            return jsonify({"ok": False, "error": "草稿不存在"}), 404
        return jsonify({"ok": True})

    # ── POST /api/skill-builder/publish — 发布 ───────────────
    @app.route('/api/skill-builder/publish', methods=['POST'])
    def api_skill_publish():
        data = request.get_json(force=True) if request.is_json else {}
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({"ok": False, "error": "内容为空"}), 400

        from tools.skill_builder import publish_skill
        result = publish_skill(content, str(BASE_DIR / 'skills'))
        status = 200 if result['ok'] else 400
        return jsonify(result), status

    # ══════════════════════════════════════════════════════════
    #  Runtime Logger API
    # ══════════════════════════════════════════════════════════

    # ── GET /api/logs — 查看日志 ──────────────────────────────
    @app.route('/api/logs')
    def api_logs():
        from tools.runtime_logger import get_logger
        logger = get_logger()
        date_str = request.args.get('date', '')
        level = request.args.get('level', '')
        category = request.args.get('category', '')
        limit = min(int(request.args.get('limit', 200)), 1000)
        return jsonify({
            "entries": logger.read_logs(date_str, level, category, limit),
        })

    # ── GET /api/logs/files — 日志文件列表 ────────────────────
    @app.route('/api/logs/files')
    def api_log_files():
        from tools.runtime_logger import get_logger
        return jsonify({"files": get_logger().get_log_files()})

    # ── GET /api/logs/stats — 日志统计 ────────────────────────
    @app.route('/api/logs/stats')
    def api_log_stats():
        from tools.runtime_logger import get_logger
        return jsonify(get_logger().get_stats())

    # ── POST /api/logs/mode — 切换日志模式 ────────────────────
    @app.route('/api/logs/mode', methods=['POST'])
    def api_log_mode():
        data = request.get_json(force=True) if request.is_json else {}
        mode = data.get('mode', '')
        if mode not in ('basic', 'detailed'):
            return jsonify({"ok": False, "error": "模式必须为 basic 或 detailed"}), 400

        from tools.runtime_logger import get_logger
        import yaml
        logger = get_logger()
        logger.mode = mode

        # 同步写入 config.yaml
        with _config_file_lock:
            cfg_path = BASE_DIR / 'config.yaml'
            src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
            try:
                with open(src, encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                cfg.setdefault('logging', {})['mode'] = mode
                tmp = cfg_path.with_suffix('.yaml.tmp')
                with open(tmp, 'w', encoding='utf-8') as f:
                    yaml.dump(cfg, f, allow_unicode=True,
                              default_flow_style=False, sort_keys=False)
                tmp.replace(cfg_path)
            except Exception:
                pass

        return jsonify({"ok": True, "mode": mode})

    # ── POST /api/logs/cleanup — 手动清理旧日志 ──────────────
    @app.route('/api/logs/cleanup', methods=['POST'])
    def api_log_cleanup():
        from tools.runtime_logger import get_logger
        get_logger().cleanup_old_logs()
        return jsonify({"ok": True})

    # ── POST /api/report/export-word — 导出 Word 报告 ─────────
    @app.route('/api/report/export-word', methods=['POST'])
    def api_export_word():
        data = request.get_json(force=True) if request.is_json else {}
        content = (data.get('content') or '').strip()
        report_name = (data.get('report_name') or 'report').strip()
        if not content:
            return jsonify({"ok": False, "error": "内容为空"}), 400
        from tools.report_builder import export_report_word
        import re
        safe_name = re.sub(r'[^\w一-鿿\-]', '_', report_name)[:40]
        result = export_report_word(content, safe_name)
        return jsonify(result)

    # ── GET /api/report/download/<filename> — 下载报告文件 ────
    @app.route('/api/report/download/<path:filename>')
    def api_report_download(filename):
        import re
        from flask import send_from_directory
        if re.search(r'[/\\]', filename):
            return jsonify({"error": "非法文件名"}), 400
        outputs_dir = BASE_DIR / 'data' / 'outputs'
        file_path = outputs_dir / filename
        if not file_path.exists():
            return jsonify({"error": "文件不存在"}), 404
        return send_from_directory(
            str(outputs_dir), filename,
            as_attachment=True,
            download_name=filename,
        )

    return app


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

def main():
    # 将工作目录切换到项目根目录，确保各模块的相对路径兼容
    os.chdir(BASE_DIR)

    config = load_config()
    port = find_free_port()

    # 初始化运行时日志
    from tools.runtime_logger import init_logger
    log_mode = config.get('logging', {}).get('mode', 'basic')
    log_max_days = config.get('logging', {}).get('max_days', 30)
    logger = init_logger(mode=log_mode, max_days=log_max_days)
    logger.cleanup_old_logs()

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
    run_mode = type(driver).__name__
    print(f"运行模式：{run_mode}")
    logger.log_app_start(port=port, mode=run_mode, log_mode=log_mode)

    driver.start(
        flask_app=app,
        port=port,
        title=config.get('app', {}).get('window_title', 'DataAgent'),
        width=config.get('app', {}).get('window_width', 1280),
        height=config.get('app', {}).get('window_height', 800),
    )


if __name__ == '__main__':
    main()
