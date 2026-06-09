"""
api/chat.py — 对话、流式输出、会话管理路由
"""
import json
import queue
import threading
import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

from session_store import (
    BASE_DIR,
    _new_session_id,
    _save_session_messages,
    _session,
    _session_lock,
    _stream_queues,
    _stream_queues_lock,
    reset_session,
)

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(force=True) if request.is_json else {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({"ok": False, "error": "消息为空"}), 400
    document_context = data.get('document_context') or None

    sid = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()

    with _stream_queues_lock:
        _stream_queues[sid] = (q, None)

    with _session_lock:
        if not _session.get("session_id"):
            _session["session_id"] = _new_session_id()
        current_turn = _session["turn_count"]
        session_msgs = list(_session["messages"])
        pending = _session.get("pending")
        _session["pending"] = None

    from tools.runtime_logger import get_logger as _get_logger
    _get_logger().log_chat_start(message)

    def run_agent_bg():
        from agent.executor import run_with_plan
        from agent.llm_client import LLMClient
        from agent.loop import run_agent_loop
        from agent.planner import build_plan, should_plan
        from agent.skill_loader import SkillLoader
        from tools.data_loader import get_loaded_tables, init_duckdb_connection

        init_duckdb_connection()
        cfg_path = str(BASE_DIR / 'config.yaml')
        skills_dir = str(BASE_DIR / 'skills')
        llm_client = LLMClient(cfg_path)
        skill_loader = SkillLoader(local_dir=skills_dir)

        # 判断是否需要规划（仅对新请求，续跑时跳过）
        loop_kwargs = dict(
            turn_count=current_turn,
            session_messages=session_msgs,
            pending=pending,
            document_context=document_context,
        )
        if not pending and should_plan(message) and get_loaded_tables():
            plan = build_plan(
                message, llm_client,
                schema_ctx="",
                skills_ctx="",
            )
            if plan:
                loop_iter = run_with_plan(plan, message, llm_client, skill_loader,
                                          **loop_kwargs)
            else:
                loop_iter = run_agent_loop(message, llm_client, skill_loader,
                                           **loop_kwargs)
        else:
            loop_iter = run_agent_loop(message, llm_client, skill_loader,
                                       **loop_kwargs)

        try:
            for event in loop_iter:
                if event.get("type") == "__pending__":
                    with _session_lock:
                        _session["pending"] = event["data"]
                        _session["messages"] = list(session_msgs)
                        _save_session_messages()
                    continue

                q.put(event)

            with _session_lock:
                _session["messages"] = list(session_msgs)
                _session["turn_count"] += 1
                _save_session_messages()
        except Exception as e:
            from tools.runtime_logger import get_logger as _get_log
            _get_log().log_exception('agent', 'Agent 循环异常', e)
            q.put({"type": "error", "data": f"Agent 处理异常：{str(e)}"})
        finally:
            q.put(None)

    t = threading.Thread(target=run_agent_bg, daemon=True)
    t.start()
    with _stream_queues_lock:
        if sid in _stream_queues:
            _stream_queues[sid] = (q, t)
    return jsonify({"ok": True, "stream_id": sid})


@chat_bp.route('/api/stream/<sid>')
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


@chat_bp.route('/api/confirm', methods=['POST'])
def api_confirm():
    data = request.get_json(force=True) if request.is_json else {}
    confirmed = data.get('confirmed', False)
    feedback = data.get('feedback', '')

    with _session_lock:
        pending = _session.get("pending")
        if not pending or pending.get("type") != "confirm":
            return jsonify({"ok": False, "error": "没有待确认事项"}), 400
        pending["confirmed"] = confirmed
        if feedback:
            pending["feedback"] = feedback
        _session["pending"] = pending

    return jsonify({
        "ok": True,
        "message": "已确认，正在继续..." if confirmed else "已取消",
        "confirmed": confirmed,
    })


@chat_bp.route('/api/reset', methods=['POST'])
def api_reset():
    reset_session()
    return jsonify({"ok": True})


@chat_bp.route('/api/sessions')
def api_sessions():
    sessions_dir = BASE_DIR / 'data' / 'sessions'
    if not sessions_dir.exists():
        return jsonify({"sessions": []})

    sessions = []
    for f in sorted(sessions_dir.glob('*.jsonl'),
                    key=lambda p: p.stat().st_mtime, reverse=True):
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


@chat_bp.route('/api/sessions/<session_id>')
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


@chat_bp.route('/api/sessions/<session_id>', methods=['DELETE'])
def api_delete_session(session_id):
    import re as _re
    if not _re.match(r'^[a-f0-9]{12}$', session_id):
        return jsonify({"ok": False, "error": "无效会话ID"}), 400
    session_file = BASE_DIR / 'data' / 'sessions' / f'{session_id}.jsonl'
    if not session_file.exists():
        return jsonify({"ok": False, "error": "会话不存在"}), 404
    try:
        session_file.unlink()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})
