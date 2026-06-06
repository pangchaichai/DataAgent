"""
tests/conftest.py — 全局测试 fixtures 和钩子

职责：
1. 统一 sys.path 注入（各 test_*.py 不再需要手动 insert）
2. 共享 fixtures（DuckDB 连接、临时 CSV、mock LLM）
3. 测试报告目录自动创建
4. 测试会话结束后生成摘要
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORT_DIR = PROJECT_ROOT / "data" / "test_reports"


def pytest_configure(config):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": session.testscollected,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "exit_status": exitstatus,
        "duration_seconds": round(time.time() - session.config._start_time, 2)
            if hasattr(session.config, "_start_time") else None,
        "failed_tests": [],
    }
    for item in session.items:
        report = getattr(item, "_report", None)
        if report:
            if report.passed:
                summary["passed"] += 1
            elif report.failed:
                summary["failed"] += 1
                summary["failed_tests"].append({
                    "nodeid": item.nodeid,
                    "message": getattr(report, "message", "")[:500],
                })
            elif report.skipped:
                summary["skipped"] += 1

    summary_path = REPORT_DIR / "latest_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))


def pytest_runtest_makereport(item, call):
    if call.when == "call":
        from _pytest.runner import pytest_runtest_makereport as _make
        report = call.excinfo is None
        class SimpleReport:
            passed = call.excinfo is None
            failed = call.excinfo is not None
            skipped = False
            message = str(call.excinfo)[:500] if call.excinfo else ""
        item._report = SimpleReport()


def pytest_collection_modifyitems(config, items):
    config._start_time = time.time()


# ══════════════════════════════════════════════════════════════
#  共享 Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def duckdb_conn():
    import duckdb
    conn = duckdb.connect(":memory:")
    conn.execute("SET memory_limit='200MB'")
    conn.execute("SET threads=2")
    yield conn
    conn.close()


@pytest.fixture
def sample_holding_csv():
    content = (
        '产品名称,资产代码,资产名称,资产市值_穿透后,限额占用方主体,外部评级,持仓日期\n'
        'XX稳健理财01号,0123456789,21象屿MTN001,"1,234,567.89",厦门象屿集团有限公司,AAA,2026-05-15\n'
        'XX稳健理财01号,9876543210,22建发SCP003,"5,678,000.00",厦门建发集团有限公司,AA+,2026-05-15\n'
        'YY进取理财02号,1122334455,21象屿股份CP002,"890,123.45",象屿股份,AA,2026-05-15\n'
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="gb18030"
    ) as f:
        f.write(content)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def mock_llm_response():
    def _make(text="", tool_calls=None):
        class FakeResult:
            def __init__(self):
                self.text = text
                self.tool_calls = tool_calls or []
        return FakeResult()
    return _make
