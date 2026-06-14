"""
agent/execution_tracker.py — 执行追踪（JSONL 写入端）

记录每次 Agent 执行的 trace：技能名、计算器、耗时、结果。
读取端（stats API、退化信号检测）推迟到 v3.1，先积累 2-4 周数据再实现。

写入路径：data/traces/traces_YYYY-MM-DD.jsonl
"""

import json
import threading
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent / "data" / "traces"
_lock = threading.Lock()
_instance: "ExecutionTracker | None" = None


class ExecutionTracker:
    def __init__(self, base_dir: Path = _BASE):
        self._base = base_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        skill_name: str = "",
        calc_name: str = "",
        user_message: str = "",
        success: bool = True,
        duration_ms: float = 0.0,
        fast_path: bool = False,
        tool_calls: list | None = None,
        error: str = "",
    ) -> None:
        """写一条 trace 到当日 JSONL 文件（线程安全）。"""
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "skill": skill_name,
            "calculator": calc_name,
            "user_msg": user_message[:100],
            "fast_path": fast_path,
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "tool_calls": tool_calls or [],
            "error": error[:200] if error else "",
        }
        today = datetime.utcnow().strftime("%Y-%m-%d")
        path = self._base / f"traces_{today}.jsonl"
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_tracker() -> ExecutionTracker:
    """返回全局单例（懒加载）。"""
    global _instance
    if _instance is None:
        _instance = ExecutionTracker()
    return _instance
