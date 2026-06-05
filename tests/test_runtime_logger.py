"""
tests/test_runtime_logger.py — 运行时日志系统单元测试
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.runtime_logger import (
    RuntimeLogger, LogEntry,
    LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO, LEVEL_DEBUG,
    CAT_LIFECYCLE, CAT_USER_ACTION, CAT_AGENT, CAT_TOOL,
    CAT_LLM, CAT_ERROR, CAT_PERFORMANCE,
    init_logger, get_logger,
)


# ═══════════════════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════════════════

def _make_logger(mode='basic', tmpdir=None) -> RuntimeLogger:
    """创建测试用 logger，日志写入临时目录"""
    logger = RuntimeLogger(mode=mode)
    if tmpdir:
        import tools.runtime_logger as mod
        mod.LOG_DIR = Path(tmpdir)
        Path(tmpdir).mkdir(parents=True, exist_ok=True)
    return logger


def _read_log_lines(tmpdir: str) -> list[dict]:
    """读取临时目录中当天的日志"""
    today = datetime.now().strftime('%Y%m%d')
    log_file = Path(tmpdir) / f'dataagent_{today}.jsonl'
    if not log_file.exists():
        return []
    entries = []
    with open(log_file, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


# ═══════════════════════════════════════════════════════════════
#  Basic 模式测试
# ═══════════════════════════════════════════════════════════════

def test_basic_mode_logs_errors():
    """basic 模式下 ERROR 级别应被记录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.error(CAT_ERROR, '测试错误', {'code': 500})
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['level'] == LEVEL_ERROR
        assert entries[0]['event'] == '测试错误'


def test_basic_mode_logs_warnings():
    """basic 模式下 WARNING 应被记录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.warning(CAT_TOOL, '查询超时')
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['level'] == LEVEL_WARNING


def test_basic_mode_logs_lifecycle():
    """basic 模式下 lifecycle 类别始终记录（即使是 INFO 级别）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.info(CAT_LIFECYCLE, '应用启动', {'port': 8080})
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['category'] == CAT_LIFECYCLE


def test_basic_mode_skips_debug():
    """basic 模式下非关键类别的 DEBUG 应被跳过"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.debug(CAT_TOOL, 'run_sql 执行', {'duration_ms': 120})
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 0


def test_basic_mode_skips_detailed_user_action():
    """basic 模式下 user_action INFO 应被跳过"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.info(CAT_USER_ACTION, '文件上传', {'file': 'test.csv'})
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 0


# ═══════════════════════════════════════════════════════════════
#  Detailed 模式测试
# ═══════════════════════════════════════════════════════════════

def test_detailed_mode_logs_everything():
    """detailed 模式下所有级别和类别都应记录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('detailed', tmpdir)
        logger.error(CAT_ERROR, '错误')
        logger.warning(CAT_TOOL, '警告')
        logger.info(CAT_USER_ACTION, '操作')
        logger.debug(CAT_AGENT, '调试', duration_ms=50.5)
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 4


def test_detailed_mode_includes_duration():
    """detailed 模式应记录 duration_ms"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('detailed', tmpdir)
        logger.debug(CAT_TOOL, '工具调用', duration_ms=123.4)
        entries = _read_log_lines(tmpdir)
        assert entries[0]['duration_ms'] == 123.4


# ═══════════════════════════════════════════════════════════════
#  模式切换测试
# ═══════════════════════════════════════════════════════════════

def test_mode_switch():
    """运行时切换模式应立即生效"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)

        # basic 模式下 debug 不记录
        logger.debug(CAT_TOOL, '应被跳过')
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 0

        # 切到 detailed
        logger.mode = 'detailed'
        logger.debug(CAT_TOOL, '现在应记录')
        entries = _read_log_lines(tmpdir)
        # 模式切换本身产生一条 lifecycle 日志 + debug 日志
        assert len(entries) >= 2

        # 切回 basic
        logger.mode = 'basic'
        logger.debug(CAT_TOOL, '又被跳过了')
        final_entries = _read_log_lines(tmpdir)
        # 只多了模式切换日志，debug 不应增加
        assert any(e['event'] == '现在应记录' for e in final_entries)


# ═══════════════════════════════════════════════════════════════
#  便捷方法测试
# ═══════════════════════════════════════════════════════════════

def test_log_app_start():
    """log_app_start 应记录启动信息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.log_app_start(port=8080, mode='BrowserDriver', log_mode='basic')
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['detail']['port'] == 8080


def test_log_exception():
    """log_exception 应始终记录（含 traceback）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        try:
            raise ValueError("测试异常")
        except Exception as e:
            logger.log_exception(CAT_ERROR, 'DuckDB 错误', e)
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['detail']['exception_type'] == 'ValueError'
        assert 'traceback' in entries[0]['detail']


def test_log_tool_call():
    """log_tool_call 成功时 detailed 记录，失败时 basic 也记录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        # 成功调用 → basic 模式不记录（DEBUG 级别）
        logger.log_tool_call('run_sql', {'sql': 'SELECT...'}, ok=True, duration_ms=50)
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 0

        # 失败调用 → WARNING 级别，basic 也记录
        logger.log_tool_call('run_sql', {'sql': 'SELECT...'}, ok=False,
                             error='no such column', duration_ms=10)
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert entries[0]['level'] == LEVEL_WARNING


def test_log_chat_start():
    """log_chat_start 应截断消息预览"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('detailed', tmpdir)
        long_msg = "查询象屿系全部产品的持仓集中度是否超过监管阈值" + "x" * 100
        logger.log_chat_start(long_msg)
        entries = _read_log_lines(tmpdir)
        assert len(entries) == 1
        assert len(entries[0]['detail']['preview']) <= 50


# ═══════════════════════════════════════════════════════════════
#  日志查询测试
# ═══════════════════════════════════════════════════════════════

def test_read_logs():
    """read_logs 应返回当天日志"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('detailed', tmpdir)
        logger.error(CAT_ERROR, '错误1')
        logger.info(CAT_LIFECYCLE, '启动')
        logger.debug(CAT_TOOL, 'SQL')

        results = logger.read_logs()
        assert len(results) == 3


def test_read_logs_with_filter():
    """read_logs 支持按级别和类别过滤"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('detailed', tmpdir)
        logger.error(CAT_ERROR, '错误')
        logger.info(CAT_LIFECYCLE, '启动')
        logger.debug(CAT_TOOL, 'SQL')

        errors_only = logger.read_logs(level_filter=LEVEL_ERROR)
        assert len(errors_only) == 1
        assert errors_only[0]['event'] == '错误'

        tools_only = logger.read_logs(category_filter=CAT_TOOL)
        assert len(tools_only) == 1


def test_get_log_files():
    """get_log_files 应列出日志文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.error(CAT_ERROR, '测试')
        files = logger.get_log_files()
        assert len(files) >= 1
        assert files[0]['size_kb'] > 0


def test_get_stats():
    """get_stats 应返回统计信息"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.error(CAT_ERROR, '测试')
        stats = logger.get_stats()
        assert stats['mode'] == 'basic'
        assert stats['file_count'] >= 1


# ═══════════════════════════════════════════════════════════════
#  日志清理测试
# ═══════════════════════════════════════════════════════════════

def test_cleanup_old_logs():
    """cleanup_old_logs 应删除过期文件"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger._max_days = 0  # 立即过期

        # 手动创建一个"旧"日志文件
        old_file = Path(tmpdir) / 'dataagent_20200101.jsonl'
        old_file.write_text('{"test": true}\n')
        assert old_file.exists()

        logger.cleanup_old_logs()
        assert not old_file.exists()


# ═══════════════════════════════════════════════════════════════
#  全局单例测试
# ═══════════════════════════════════════════════════════════════

def test_init_and_get_logger():
    """init_logger 和 get_logger 应返回同一实例"""
    logger1 = init_logger(mode='detailed')
    logger2 = get_logger()
    assert logger1 is logger2
    assert logger2.mode == 'detailed'
    # 还原
    init_logger(mode='basic')


# ═══════════════════════════════════════════════════════════════
#  session_id 测试
# ═══════════════════════════════════════════════════════════════

def test_session_id_in_entries():
    """日志条目应包含 session_id"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = _make_logger('basic', tmpdir)
        logger.session_id = "abc123"
        logger.error(CAT_ERROR, '测试')
        entries = _read_log_lines(tmpdir)
        assert entries[0]['session_id'] == 'abc123'


# ═══════════════════════════════════════════════════════════════
#  运行
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
