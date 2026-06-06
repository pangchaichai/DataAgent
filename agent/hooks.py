"""
agent/hooks.py — 可编程扩展点（ETCLOVG O 层，I-5b）

HookManager 提供 7 种事件的注册/触发机制。
所有 hook 同步调用，异常不阻塞主流程。
"""

from __future__ import annotations

import threading


class HookManager:
    """线程安全的 Hook 事件管理器。"""

    EVENTS = [
        "on_session_start",
        "on_session_end",
        "pre_tool_use",
        "post_tool_use",
        "on_data_load",
        "on_error",
        "on_agent_turn_end",
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._hooks: dict[str, list] = {e: [] for e in self.EVENTS}

    def register(self, event: str, callback) -> bool:
        """
        注册 hook 回调。event 必须是 EVENTS 中的一种，否则忽略。
        callback(context: dict) 同步调用。
        """
        if event not in self._hooks:
            return False
        with self._lock:
            self._hooks[event].append(callback)
        return True

    def unregister(self, event: str, callback) -> bool:
        """取消注册（用于测试清理）。"""
        if event not in self._hooks:
            return False
        with self._lock:
            try:
                self._hooks[event].remove(callback)
                return True
            except ValueError:
                return False

    def emit(self, event: str, context: dict | None = None) -> list:
        """
        触发事件，依次调用所有已注册 callback。
        callback 异常被静默捕获，不影响主流程。
        返回所有非 None 的返回值列表。
        """
        with self._lock:
            callbacks = list(self._hooks.get(event, []))
        results = []
        ctx = context or {}
        for cb in callbacks:
            try:
                r = cb(ctx)
                if r is not None:
                    results.append(r)
            except Exception:
                pass
        return results

    def clear(self, event: str | None = None) -> None:
        """清空 hook（测试用）。"""
        with self._lock:
            if event:
                if event in self._hooks:
                    self._hooks[event].clear()
            else:
                for k in self._hooks:
                    self._hooks[k].clear()


# ═══════════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════════

_hook_manager: HookManager | None = None
_mgr_lock = threading.Lock()


def get_hook_manager() -> HookManager:
    global _hook_manager
    with _mgr_lock:
        if _hook_manager is None:
            _hook_manager = HookManager()
    return _hook_manager
