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
import re
import socket
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

from platform_adapter.notify_driver import get_notify_driver
from platform_adapter.ui_driver import get_driver

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
    from agent.hooks import get_hook_manager
    with _session_lock:
        old_id = _session.get("session_id", "")
        had_messages = bool(_session.get("messages"))
        if old_id:
            get_hook_manager().emit("on_session_end", {"session_id": old_id})
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
    get_hook_manager().emit("on_session_start", {"session_id": _session["session_id"]})


# ═══════════════════════════════════════════════════════════════
#  Flask 应用 + API 路由
# ═══════════════════════════════════════════════════════════════

def create_flask_app() -> Flask:
    """创建 Flask 应用，注册所有 API 路由"""
    import tools.data_loader as _dl
    _dl._db_path = str(BASE_DIR / 'data' / 'dataagent.duckdb')
    _dl.init_duckdb_connection()

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

    # ── POST /api/upload — 阶段1：上传并返回智能识别预览 ─────────
    @app.route('/api/upload', methods=['POST'])
    def api_upload():
        if 'file' not in request.files:
            return jsonify({"ok": False, "error": "未收到文件"}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({"ok": False, "error": "文件名为空"}), 400

        # 暂存到 uploads/pending/
        pending_dir = BASE_DIR / 'data' / 'uploads' / 'pending'
        pending_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(pending_dir / file.filename)
        file.save(file_path)

        ext = Path(file.filename).suffix.lower()

        # ── 文档类型（Word/PDF）→ 直接返回解析预览 ───────────────
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

        # ── 结构化数据（CSV/Excel）→ 智能检测 + 预览 ──────────────
        from tools.data_loader import (
            auto_detect_table_type, detect_encoding, extract_date_from_filename,
        )
        import pandas as pd
        try:
            if ext == '.csv':
                enc = detect_encoding(file_path)
                df_preview = pd.read_csv(file_path, encoding=enc, dtype=str,
                                         keep_default_na=False, nrows=3)
                with open(file_path, 'rb') as _f:
                    row_estimate = sum(1 for _ in _f) - 1
            else:
                df_preview = pd.read_excel(file_path, dtype=str, nrows=3)
                row_estimate = len(pd.read_excel(file_path, dtype=str))
        except Exception as e:
            return jsonify({"ok": False, "error": f"文件读取失败：{str(e)[:200]}"}), 400

        detected_type = auto_detect_table_type(df_preview, file.filename)
        detected_date = extract_date_from_filename(file.filename)

        return jsonify({
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
        })

    # ── POST /api/upload/confirm — 阶段2：用户确认后入库 ─────────
    @app.route('/api/upload/confirm', methods=['POST'])
    def api_upload_confirm():
        data = request.get_json(force=True) or {}
        file_path = data.get('file_path', '')
        table_type = data.get('table_type', 'unknown')
        date_tag = data.get('date_tag', '')
        table_name = data.get('table_name', '')
        filename = data.get('filename', Path(file_path).name)

        # 安全校验：路径必须在 uploads/ 目录内
        uploads_dir = BASE_DIR / 'data' / 'uploads'
        try:
            Path(file_path).resolve().relative_to(uploads_dir.resolve())
        except ValueError:
            return jsonify({"ok": False, "error": "非法文件路径"}), 400

        if not Path(file_path).exists():
            return jsonify({"ok": False, "error": "文件不存在，请重新上传"}), 400

        # 将文件移入正式目录
        dest_dir = BASE_DIR / 'data' / 'uploads' / table_type
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = str(dest_dir / filename)
        import shutil
        shutil.move(file_path, dest_path)

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

        response_data = {"ok": True, "table_name": table_name,
                         "row_count": result.row_count, "col_count": result.col_count}
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

        # 记录用户操作日志
        from tools.runtime_logger import get_logger as _get_logger
        _get_logger().log_chat_start(message)

        # 在后台线程运行 agent loop，事件写入队列
        def run_agent_bg():
            from agent.llm_client import LLMClient
            from agent.loop import run_agent_loop
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

    # ── GET /api/llm/providers — LLM Provider 列表 ────────
    @app.route('/api/llm/providers', methods=['GET'])
    def api_llm_providers():
        """返回已配置的 LLM provider 列表及当前选择"""
        providers = llm_client.list_providers()
        return jsonify({
            "providers": providers,
            "current": llm_client.sql_gen_cfg.get('primary', 'enterprise_internal'),
        })

    # ── POST /api/llm/test — 测试 Provider 连通性 ─────────
    @app.route('/api/llm/test', methods=['POST'])
    def api_llm_test():
        """测试指定 provider 的连通性（用于 UI 状态灯）"""
        data = request.get_json(silent=True) or {}
        provider = data.get('provider')
        result = llm_client.test_connection(provider)
        return jsonify(result)

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

    # ── GET /api/status — 系统状态（I-5）────────────────────
    @app.route('/api/status')
    def api_status():
        from tools.data_loader import get_loaded_tables
        tables = get_loaded_tables()
        llm_ok = True
        try:
            from agent.llm_client import LLMClient
            client = LLMClient(str(BASE_DIR / 'config.yaml'))
            key = client.sql_gen_cfg.get('api_key', '')
            llm_ok = bool(key and not key.startswith('sk-placeholder'))
        except Exception:
            llm_ok = False
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        data_fresh = all(
            t.get('date_tag', '') == today
            for t in tables if t.get('date_tag')
        ) if tables else None
        return jsonify({
            "llm_ok": llm_ok,
            "tables_count": len(tables),
            "tables": tables,
            "data_fresh": data_fresh,
        })

    # ── GET /api/suggestions — 推荐查询（I-5）────────────────
    @app.route('/api/suggestions')
    def api_suggestions():
        from tools.data_loader import get_loaded_tables
        tables = get_loaded_tables()
        types = {t['type'] for t in tables}
        suggestions = []
        if 'holding' in types:
            suggestions.append("查询各产品的主要持仓情况，按市值降序排列")
            suggestions.append("统计不同资产类别的持仓比例")
        if 'holding' in types:
            suggestions.append("检查主体集中度是否有超标情况，阈值10%")
        if 'nav' in types:
            suggestions.append("分析近期净值走势，计算区间收益率")
        if 'holding' in types and 'rating_entity' in types:
            suggestions.append("结合评级数据分析持仓信用分布")
        if not types:
            suggestions = [
                "上传持仓CSV文件开始分析",
                "查询持仓情况",
                "合规监控：主体集中度检查",
            ]
        return jsonify({"suggestions": suggestions[:5]})

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
        raw_key = cfg.get('llm', {}).get('deepseek', {}).get('api_key', '')
        api_key_set = bool(raw_key and raw_key not in ('', '你的DeepSeek_API_Key', '${DEEPSEEK_API_KEY}'))
        return jsonify({
            "user_profile": cfg.get('user_profile', {}),
            "calculation_config": cfg.get('calculation_config', {}),
            "memory": cfg.get('memory', {"enabled": False}),
            "scheduler": cfg.get('scheduler', {"enabled": True}),
            "app": cfg.get('app', {}),
            "api_key_set": api_key_set,
            "llm_model": cfg.get('llm', {}).get('deepseek', {}).get('model', 'deepseek-chat'),
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
            if data.get('api_key'):
                # Only write to deepseek block; never overwrite enterprise report_text config
                cfg.setdefault('llm', {}).setdefault('deepseek', {})['api_key'] = data['api_key']
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

        from agent.llm_client import LLMClient
        from tools.skill_builder import (
            build_skill_generation_prompt,
            generate_skill_md,
            parse_llm_skill_response,
            save_draft,
        )

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
        return jsonify(result.to_dict())

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

        import yaml

        from tools.runtime_logger import get_logger
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

    # ── GET /api/report/download/<filename> — 下载 Word 报告 ─
    @app.route('/api/report/download/<filename>')
    def api_report_download(filename):
        import re
        from flask import send_from_directory
        # 安全校验：只允许 alphanumeric + _ + - + .docx
        if not re.match(r'^[\w\-]+\.docx$', filename):
            return jsonify({"error": "非法文件名"}), 400
        output_dir = os.path.join(BASE_DIR, 'data', 'outputs')
        file_path = os.path.join(output_dir, filename)
        if not os.path.isfile(file_path):
            return jsonify({"error": "文件不存在"}), 404
        return send_from_directory(output_dir, filename, as_attachment=True)

    # ── GET /api/report/templates — 报告模板列表 ─────────────
    @app.route('/api/report/templates')
    def api_report_templates():
        from tools.report_builder import list_templates
        return jsonify({"templates": list_templates()})

    # ── GET /api/cost — 当前会话 LLM 成本统计（I-3b）─────────
    @app.route('/api/cost')
    def api_cost():
        from tools.cost_tracker import get_cost_tracker
        return jsonify(get_cost_tracker().to_dict())

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
