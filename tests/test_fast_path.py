"""
tests/test_fast_path.py — 快速路径单元测试

验证 fast_path.py 和 execution_tracker.py 的核心行为：
  - can_fast_path() 的判断逻辑
  - run_fast_path() 输出的 SSE 事件格式
  - fast path 在 loop.py 中被正确触发
  - execution_tracker 写入 JSONL
"""

import os
import sys
import tempfile
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 测试辅助 ─────────────────────────────────────────────────────

def _setup_holding_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_holding (
            产品名称 VARCHAR,
            限额占用方主体 VARCHAR,
            穿透后市值 DOUBLE
        )
    """)
    conn.execute("""
        INSERT INTO test_holding VALUES
          ('A产品', '象屿集团', 1500000.0),
          ('A产品', '招商银行', 500000.0),
          ('A产品', '中国平安', 400000.0)
    """)
    return conn


def _make_skill_info(calc_type="fixed",
                     fixed_calculator="calculators.concentration.calc_entity_concentration",
                     metadata=None):
    from agent.skill_loader import SkillInfo
    return SkillInfo(
        name="concentration_monitor",
        description="集中度监控",
        calc_type=calc_type,
        fixed_calculator=fixed_calculator,
        metadata=metadata or {},
    )


# ── can_fast_path 测试 ────────────────────────────────────────────

class TestCanFastPath:
    def test_returns_true_for_valid_fixed_skill(self):
        from agent.fast_path import can_fast_path
        info = _make_skill_info()
        assert can_fast_path(info) is True

    def test_returns_false_for_exploratory(self):
        from agent.fast_path import can_fast_path
        info = _make_skill_info(calc_type="exploratory", fixed_calculator="")
        assert can_fast_path(info) is False

    def test_returns_false_for_unknown_calculator_path(self):
        from agent.fast_path import can_fast_path
        info = _make_skill_info(fixed_calculator="calculators.unknown.some_func")
        assert can_fast_path(info) is False

    def test_returns_false_when_fixed_calculator_empty(self):
        from agent.fast_path import can_fast_path
        info = _make_skill_info(fixed_calculator="")
        assert can_fast_path(info) is False


# ── run_fast_path SSE 事件测试 ────────────────────────────────────

class TestRunFastPath:
    def test_emits_correct_sse_sequence(self):
        """fast path 必须输出 tool_start → tool_end → text|error → stream_end"""
        from agent.fast_path import run_fast_path
        from agent.tools_spec import ToolContext

        conn = _setup_holding_table(duckdb.connect(":memory:"))
        ctx = ToolContext(_conn=conn)
        info = _make_skill_info()
        tables = [{"name": "test_holding", "type": "holding", "date_tag": "20260515"}]

        events = list(run_fast_path(info, ctx, tables, user_message="检查集中度"))

        event_types = [e["type"] for e in events]
        assert event_types[0] == "tool_start"
        assert event_types[-1] == "stream_end"
        assert "tool_end" in event_types
        assert "text" in event_types or "error" in event_types

    def test_tool_start_uses_run_calculator(self):
        from agent.fast_path import run_fast_path
        from agent.tools_spec import ToolContext

        conn = _setup_holding_table(duckdb.connect(":memory:"))
        ctx = ToolContext(_conn=conn)
        info = _make_skill_info()
        tables = [{"name": "test_holding", "type": "holding", "date_tag": "20260515"}]

        events = list(run_fast_path(info, ctx, tables, user_message="检查集中度"))
        ts = next(e for e in events if e["type"] == "tool_start")
        assert ts["data"]["tool"] == "run_calculator"

    def test_no_breach_message(self):
        """无超标时应输出包含 ✅ 的文本"""
        from agent.fast_path import run_fast_path
        from agent.tools_spec import ToolContext

        # 持仓占比都很小，不超标
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE test_holding2 (
                产品名称 VARCHAR, 限额占用方主体 VARCHAR, 穿透后市值 DOUBLE
            )
        """)
        conn.execute("""
            INSERT INTO test_holding2 VALUES
              ('A产品', '主体A', 100.0),
              ('A产品', '主体B', 100.0),
              ('A产品', '主体C', 100.0),
              ('A产品', '主体D', 100.0),
              ('A产品', '主体E', 100.0),
              ('A产品', '主体F', 100.0),
              ('A产品', '主体G', 100.0),
              ('A产品', '主体H', 100.0),
              ('A产品', '主体I', 100.0),
              ('A产品', '主体J', 100.0),
              ('A产品', '主体K', 100.0)
        """)
        ctx = ToolContext(_conn=conn)
        info = _make_skill_info()
        tables = [{"name": "test_holding2", "type": "holding", "date_tag": "20260515"}]

        events = list(run_fast_path(info, ctx, tables, user_message="集中度检查"))
        text_event = next((e for e in events if e["type"] == "text"), None)
        assert text_event is not None
        assert "✅" in text_event["data"]

    def test_breach_message(self):
        """有超标时输出应包含超标提示"""
        from agent.fast_path import run_fast_path
        from agent.tools_spec import ToolContext

        conn = _setup_holding_table(duckdb.connect(":memory:"))
        ctx = ToolContext(_conn=conn)
        info = _make_skill_info()
        tables = [{"name": "test_holding", "type": "holding", "date_tag": "20260515"}]

        events = list(run_fast_path(info, ctx, tables, user_message="集中度超标检查"))
        text_event = next((e for e in events if e["type"] == "text"), None)
        assert text_event is not None
        # 象屿集团持仓 1500000 / 2400000 ≈ 62.5%，必然超标
        assert "超标" in text_event["data"] or "象屿" in text_event["data"]


# ── loop.py 集成测试 ──────────────────────────────────────────────

class TestFastPathInLoop:
    def _get_skill_loader(self):
        from agent.skill_loader import SkillLoader
        skills_dir = os.path.join(os.path.dirname(__file__), '..', 'skills')
        return SkillLoader(local_dir=skills_dir)

    def test_fast_path_triggers_for_concentration_monitor(self):
        """concentration_monitor 触发词应走快速路径（无 LLM 调用）"""
        from tests.test_agent import MockChatLLM, _make_chat_result

        _setup_holding_table(duckdb.connect(":memory:"))
        from tools.data_loader import LoadResult, _loaded_tables
        _loaded_tables["test_holding"] = LoadResult(
            table_name="test_holding",
            file_path="",
            row_count=3,
            col_count=3,
            encoding="utf-8",
            date_tag="20260515",
            field_map={},
            unmatched_cols=[],
            missing_required=[],
            warnings=[],
            table_type="holding",
        )

        # Mock LLM — fast path 正常工作时不应被调用
        mock_llm = MockChatLLM([
            _make_chat_result(text="不应该到这里", tool_calls=[]),
        ])
        skill_loader = self._get_skill_loader()

        from agent.loop import run_agent_loop
        events = list(run_agent_loop("检查集中度是否超标", mock_llm, skill_loader))

        # LLM 不应被调用
        assert mock_llm.call_count == 0, (
            f"fast path 应跳过 LLM，但 LLM 被调用了 {mock_llm.call_count} 次"
        )

        # 应有 stream_end
        assert events[-1]["type"] == "stream_end"

        # 清理
        _loaded_tables.pop("test_holding", None)


# ── execution_tracker 测试 ────────────────────────────────────────

class TestExecutionTracker:
    def test_writes_jsonl(self):
        import json

        from agent.execution_tracker import ExecutionTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ExecutionTracker(base_dir=Path(tmpdir))
            tracker.record(
                skill_name="concentration_monitor",
                calc_name="entity_concentration",
                user_message="检查集中度",
                success=True,
                duration_ms=123.4,
                fast_path=True,
            )

            files = list(Path(tmpdir).glob("traces_*.jsonl"))
            assert len(files) == 1
            lines = files[0].read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1

            entry = json.loads(lines[0])
            assert entry["skill"] == "concentration_monitor"
            assert entry["fast_path"] is True
            assert entry["success"] is True
            assert entry["duration_ms"] == 123.4
            assert entry["user_msg"] == "检查集中度"

    def test_truncates_long_user_message(self):
        import json

        from agent.execution_tracker import ExecutionTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ExecutionTracker(base_dir=Path(tmpdir))
            tracker.record(user_message="x" * 200)

            files = list(Path(tmpdir).glob("traces_*.jsonl"))
            entry = json.loads(files[0].read_text(encoding="utf-8").strip())
            assert len(entry["user_msg"]) == 100
