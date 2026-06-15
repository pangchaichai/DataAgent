"""
session_store.py — 共享会话状态（被 api/ Blueprint 模块导入）
"""
import json
import threading
import time
import uuid
from pathlib import Path

BASE_DIR: Path = Path(__file__).parent

_session_lock = threading.Lock()
_config_file_lock = threading.Lock()

_session: dict = {
    "session_id": "",
    "turn_count": 0,
    "loaded_files": [],
    "messages": [],
    "pending": None,
}

# SSE 流队列：stream_id → (queue.Queue, threading.Thread | None)
_stream_queues: dict[str, tuple] = {}
_stream_queues_lock = threading.Lock()


def _new_session_id() -> str:
    sid = uuid.uuid4().hex[:12]
    (BASE_DIR / 'data' / 'sessions').mkdir(parents=True, exist_ok=True)
    return sid


def _save_session_messages() -> None:
    sid = _session.get("session_id")
    if not sid:
        return
    clean_msgs = []
    for m in _session.get("messages", []):
        cm = {"role": m.get("role"), "content": m.get("content")}
        if m.get("tool_calls"):
            cm["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            cm["tool_call_id"] = m["tool_call_id"]
        if m.get("_display_content") is not None:
            cm["display_content"] = m["_display_content"]
        if m.get("skip_display"):
            cm["skip_display"] = True
        clean_msgs.append(cm)

    title = ""
    for m in _session.get("messages", []):
        if m.get("role") == "user":
            # 用原始用户文本作为标题，不含 skill 注入内容
            text = m.get("_display_content") or m.get("content") or ""
            if text:
                title = str(text)[:40]
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


def reset_session() -> None:
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
        if old_id and not had_messages:
            old_file = BASE_DIR / 'data' / 'sessions' / f'{old_id}.jsonl'
            try:
                old_file.unlink(missing_ok=True)
            except Exception:
                pass
    get_hook_manager().emit("on_session_start", {"session_id": _session["session_id"]})
