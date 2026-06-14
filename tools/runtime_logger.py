"""
tools/runtime_logger.py — 运行时日志系统（两级模式）

职责：
  提供结构化的运行日志，用于异常排查和问题定位。
  - basic 模式（默认）：仅记录 ERROR/WARNING + 关键生命周期事件
  - detailed 模式：额外记录用户操作、Agent 状态、工具调用、LLM 交互、性能指标

日志文件：
  data/logs/dataagent_YYYYMMDD.jsonl  — 按日滚动
  data/logs/ 目录下超过 max_days 天的日志自动清理

设计原则：
  - 零依赖：仅用 Python 标准库，不引入 loguru/structlog
  - 线程安全：所有写操作加锁
  - 性能无感：basic 模式下每条日志 < 0.1ms
  - 隐私安全：不记录用户数据内容，仅记录元信息
"""

import json
import os
import threading
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

LOG_DIR = Path(__file__).resolve().parent.parent / 'data' / 'logs'

# 日志级别
LEVEL_ERROR = 'ERROR'
LEVEL_WARNING = 'WARNING'
LEVEL_INFO = 'INFO'
LEVEL_DEBUG = 'DEBUG'

# basic 模式记录的级别
BASIC_LEVELS = {LEVEL_ERROR, LEVEL_WARNING}

# 日志类别
CAT_LIFECYCLE = 'lifecycle'       # 启动、关闭、配置变更
CAT_USER_ACTION = 'user_action'   # 上传文件、发送消息、确认操作
CAT_AGENT = 'agent'               # Agent 循环状态
CAT_TOOL = 'tool'                 # 工具调用
CAT_LLM = 'llm'                   # LLM 请求/响应
CAT_DATA = 'data'                 # 数据加载/卸载
CAT_ERROR = 'error'               # 异常
CAT_PERFORMANCE = 'performance'   # 内存/耗时

# basic 模式记录的类别（不论级别）
BASIC_CATEGORIES = {CAT_LIFECYCLE, CAT_ERROR}

DEFAULT_MAX_DAYS = 30
DEFAULT_MAX_FILE_MB = 50


# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class LogEntry:
    timestamp: str
    level: str
    category: str
    event: str
    detail: dict | None = None
    duration_ms: float | None = None
    session_id: str = ""


# ═══════════════════════════════════════════════════════════════
#  RuntimeLogger
# ═══════════════════════════════════════════════════════════════

class RuntimeLogger:
    """
    运行时日志记录器。

    用法：
      logger = RuntimeLogger(mode='basic', max_days=30)
      logger.info(CAT_LIFECYCLE, '应用启动', {'port': 8080})
      logger.error(CAT_ERROR, 'DuckDB 查询失败', {'sql': '...', 'error': '...'})

      # detailed 模式下额外记录
      logger.debug(CAT_TOOL, 'run_sql 执行', {'duration_ms': 120})
    """

    def __init__(self, mode: str = 'basic', max_days: int = DEFAULT_MAX_DAYS,
                 max_file_mb: int = DEFAULT_MAX_FILE_MB):
        self._mode = mode          # 'basic' | 'detailed'
        self._max_days = max_days
        self._max_file_mb = max_file_mb
        self._lock = threading.Lock()
        self._session_id = ""
        self._current_file: str | None = None
        self._current_date: str = ""
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── 属性 ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value not in ('basic', 'detailed'):
            return
        old = self._mode
        self._mode = value
        if old != value:
            self._write_entry(LogEntry(
                timestamp=_now(),
                level=LEVEL_INFO,
                category=CAT_LIFECYCLE,
                event=f'日志模式切换：{old} → {value}',
                session_id=self._session_id,
            ))

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str):
        self._session_id = value

    # ── 公开日志方法 ──────────────────────────────────────────

    def error(self, category: str, event: str, detail: dict = None):
        self._log(LEVEL_ERROR, category, event, detail)

    def warning(self, category: str, event: str, detail: dict = None):
        self._log(LEVEL_WARNING, category, event, detail)

    def info(self, category: str, event: str, detail: dict = None):
        self._log(LEVEL_INFO, category, event, detail)

    def debug(self, category: str, event: str, detail: dict = None,
              duration_ms: float = None):
        self._log(LEVEL_DEBUG, category, event, detail, duration_ms)

    def log_exception(self, category: str, event: str, exc: Exception):
        """记录异常（始终记录，不论模式）"""
        self._log(LEVEL_ERROR, category, event, {
            'exception_type': type(exc).__name__,
            'exception_msg': str(exc)[:500],
            'traceback': traceback.format_exc()[-1000:],
        })

    # ── 便捷方法（常见场景） ──────────────────────────────────

    def log_app_start(self, port: int, mode: str, log_mode: str):
        self._log(LEVEL_INFO, CAT_LIFECYCLE, '应用启动', {
            'port': port, 'run_mode': mode, 'log_mode': log_mode,
        })

    def log_app_stop(self):
        self._log(LEVEL_INFO, CAT_LIFECYCLE, '应用关闭')

    def log_file_upload(self, filename: str, table_name: str,
                        rows: int, cols: int):
        self._log(LEVEL_INFO, CAT_USER_ACTION, '文件上传', {
            'filename': filename, 'table_name': table_name,
            'rows': rows, 'cols': cols,
        })

    def log_chat_start(self, message_preview: str):
        """message_preview 只取前 50 字符，不记录完整用户输入"""
        self._log(LEVEL_INFO, CAT_USER_ACTION, '用户发送消息', {
            'preview': message_preview[:50],
        })

    def log_agent_turn(self, turn: int, tool_name: str = "",
                       tool_ok: bool = True, duration_ms: float = None):
        self._log(LEVEL_DEBUG, CAT_AGENT, 'Agent 轮次', {
            'turn': turn, 'tool': tool_name, 'ok': tool_ok,
        }, duration_ms)

    def log_tool_call(self, tool_name: str, args_summary: dict,
                      ok: bool, duration_ms: float = None,
                      error: str = ""):
        level = LEVEL_DEBUG if ok else LEVEL_WARNING
        self._log(level, CAT_TOOL, f'工具调用：{tool_name}', {
            'tool': tool_name, 'ok': ok,
            'args_keys': list(args_summary.keys()),
            'error': error[:200] if error else '',
        }, duration_ms)

    def log_llm_call(self, endpoint: str, model: str, ok: bool,
                     tokens_used: int = 0, duration_ms: float = None,
                     error: str = ""):
        level = LEVEL_DEBUG if ok else LEVEL_WARNING
        self._log(level, CAT_LLM, f'LLM 调用：{endpoint}', {
            'endpoint': endpoint, 'model': model, 'ok': ok,
            'tokens': tokens_used, 'error': error[:200] if error else '',
        }, duration_ms)

    def log_data_load(self, table_name: str, encoding: str,
                      rows: int, duration_ms: float = None):
        self._log(LEVEL_DEBUG, CAT_DATA, '数据加载', {
            'table': table_name, 'encoding': encoding, 'rows': rows,
        }, duration_ms)

    def log_memory_snapshot(self, rss_mb: float, duckdb_mb: float = 0):
        self._log(LEVEL_DEBUG, CAT_PERFORMANCE, '内存快照', {
            'rss_mb': round(rss_mb, 1),
            'duckdb_mb': round(duckdb_mb, 1),
        })

    def log_sql_execution(self, sql_preview: str, ok: bool,
                          row_count: int = 0, duration_ms: float = None,
                          error: str = ""):
        level = LEVEL_DEBUG if ok else LEVEL_WARNING
        self._log(level, CAT_TOOL, 'SQL 执行', {
            'sql_preview': sql_preview[:100],
            'ok': ok, 'row_count': row_count,
            'error': error[:200] if error else '',
        }, duration_ms)

    # ── 日志查询 ──────────────────────────────────────────────

    def read_logs(self, date_str: str = "", level_filter: str = "",
                  category_filter: str = "",
                  limit: int = 200) -> list[dict]:
        """读取指定日期的日志"""
        if not date_str:
            date_str = datetime.now().strftime('%Y%m%d')
        log_path = LOG_DIR / f'dataagent_{date_str}.jsonl'
        if not log_path.exists():
            return []

        entries = []
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if level_filter and entry.get('level') != level_filter:
                    continue
                if category_filter and entry.get('category') != category_filter:
                    continue
                entries.append(entry)

        return entries[-limit:]

    def get_log_files(self) -> list[dict]:
        """列出可用的日志文件"""
        if not LOG_DIR.exists():
            return []
        files = []
        for f in sorted(LOG_DIR.glob('dataagent_*.jsonl'), reverse=True):
            stat = f.stat()
            files.append({
                "date": f.stem.replace('dataagent_', ''),
                "size_kb": round(stat.st_size / 1024, 1),
                "file": f.name,
            })
        return files[:90]

    def get_stats(self) -> dict:
        """日志系统统计"""
        files = self.get_log_files()
        total_kb = sum(f['size_kb'] for f in files)
        token_total = self._sum_tokens_today()
        return {
            "mode": self._mode,
            "file_count": len(files),
            "total_size_mb": round(total_kb / 1024, 2),
            "max_days": self._max_days,
            "log_dir": str(LOG_DIR),
            "token_total": token_total,
        }

    def _sum_tokens_today(self) -> int:
        """统计今日 LLM 调用的 token 总量"""
        today_file = LOG_DIR / f"dataagent_{datetime.now().strftime('%Y%m%d')}.jsonl"
        if not today_file.exists():
            return 0
        total = 0
        try:
            with open(today_file, encoding='utf-8') as f:
                for line in f:
                    if '"category":"llm"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                        detail = entry.get('detail', {})
                        if isinstance(detail, dict):
                            total += detail.get('tokens', 0)
                    except (json.JSONDecodeError, TypeError):
                        continue
        except Exception:
            pass
        return total

    # ── 清理 ──────────────────────────────────────────────────

    def cleanup_old_logs(self):
        """删除超过 max_days 天的日志文件"""
        if not LOG_DIR.exists():
            return
        cutoff = datetime.now() - timedelta(days=self._max_days)
        cutoff_str = cutoff.strftime('%Y%m%d')
        removed = 0
        for f in LOG_DIR.glob('dataagent_*.jsonl'):
            date_part = f.stem.replace('dataagent_', '')
            if date_part < cutoff_str:
                f.unlink()
                removed += 1
        if removed:
            self._log(LEVEL_INFO, CAT_LIFECYCLE, '日志清理',
                      {'removed_files': removed})

    # ── 内部方法 ──────────────────────────────────────────────

    def _log(self, level: str, category: str, event: str,
             detail: dict = None, duration_ms: float = None):
        """核心写日志方法，根据模式决定是否记录"""
        if not self._should_log(level, category):
            return

        entry = LogEntry(
            timestamp=_now(),
            level=level,
            category=category,
            event=event,
            detail=detail,
            duration_ms=duration_ms,
            session_id=self._session_id,
        )
        self._write_entry(entry)

    def _should_log(self, level: str, category: str) -> bool:
        """判断当前模式下是否应记录此日志"""
        if self._mode == 'detailed':
            return True
        # basic 模式：ERROR/WARNING 始终记录 + 生命周期/异常类别始终记录
        if level in BASIC_LEVELS:
            return True
        if category in BASIC_CATEGORIES:
            return True
        return False

    def _write_entry(self, entry: LogEntry):
        """线程安全地写入一条日志"""
        today = datetime.now().strftime('%Y%m%d')
        with self._lock:
            if today != self._current_date:
                self._current_date = today
                self._current_file = str(LOG_DIR / f'dataagent_{today}.jsonl')

            try:
                line = json.dumps(asdict(entry), ensure_ascii=False, default=str)
                with open(self._current_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception:
                pass  # 日志系统自身不能抛异常影响业务

            self._check_file_size()

    def _check_file_size(self):
        """检查当前日志文件大小，超限则截断"""
        if not self._current_file:
            return
        try:
            size_mb = os.path.getsize(self._current_file) / (1024 * 1024)
            if size_mb > self._max_file_mb:
                # 保留最后 1/3
                with open(self._current_file, encoding='utf-8') as f:
                    lines = f.readlines()
                keep = lines[len(lines) * 2 // 3:]
                with open(self._current_file, 'w', encoding='utf-8') as f:
                    f.writelines(keep)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now().isoformat(timespec='milliseconds')


# ═══════════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════════

_logger_instance: RuntimeLogger | None = None
_logger_lock = threading.Lock()


def get_logger() -> RuntimeLogger:
    """获取全局日志实例（懒初始化）"""
    global _logger_instance
    if _logger_instance is None:
        with _logger_lock:
            if _logger_instance is None:
                _logger_instance = RuntimeLogger(mode='basic')
    return _logger_instance


def init_logger(mode: str = 'basic', max_days: int = DEFAULT_MAX_DAYS) -> RuntimeLogger:
    """初始化全局日志实例（在 main.py 启动时调用）"""
    global _logger_instance
    with _logger_lock:
        _logger_instance = RuntimeLogger(mode=mode, max_days=max_days)
    return _logger_instance
