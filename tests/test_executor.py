"""
tests/test_executor.py — Plan-Execute 执行层单元测试（I-8）
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_plan(n_steps: int = 2):
    from agent.planner import Plan, PlanStep
    steps = [
        PlanStep(
            step_id=str(i + 1),
            name=f"步骤{i + 1}",
            tool="run_sql",
            objective=f"目标{i + 1}",
            depends_on=[str(i)] if i > 0 else [],
        )
        for i in range(n_steps)
    ]
    return Plan(query="测试查询", steps=steps, rationale="测试")


# ═══════════════════════════════════════════════════════════════
#  _StepTracker
# ═══════════════════════════════════════════════════════════════

class TestStepTracker:
    def test_match_first_step(self):
        from agent.executor import _StepTracker
        plan = _make_plan(2)
        tracker = _StepTracker(plan.steps)
        step = tracker.match_next("run_sql")
        assert step is not None
        assert step.step_id == "1"

    def test_no_match_while_in_step(self):
        from agent.executor import _StepTracker
        plan = _make_plan(2)
        tracker = _StepTracker(plan.steps)
        tracker.match_next("run_sql")  # start step 1
        # Still in step 1, next call should return None
        step = tracker.match_next("run_sql")
        assert step is None

    def test_advance_moves_to_next(self):
        from agent.executor import _StepTracker
        plan = _make_plan(2)
        tracker = _StepTracker(plan.steps)
        tracker.match_next("run_sql")  # step 1 starts
        tracker.advance()              # step 1 done
        step = tracker.match_next("run_sql")  # step 2 starts
        assert step is not None
        assert step.step_id == "2"

    def test_current_step_while_in_step(self):
        from agent.executor import _StepTracker
        plan = _make_plan(2)
        tracker = _StepTracker(plan.steps)
        tracker.match_next("run_sql")
        current = tracker.current_step()
        assert current is not None
        assert current.step_id == "1"

    def test_current_step_none_after_advance_all(self):
        from agent.executor import _StepTracker
        plan = _make_plan(1)
        tracker = _StepTracker(plan.steps)
        tracker.match_next("run_sql")
        tracker.advance()
        assert tracker.current_step() is None


# ═══════════════════════════════════════════════════════════════
#  run_with_plan
# ═══════════════════════════════════════════════════════════════

class TestRunWithPlan:
    def _mock_loop_events(self, events):
        """Mock run_agent_loop to yield given events."""
        def _fake_loop(*args, **kwargs):
            yield from events
        return _fake_loop

    def test_emits_plan_event_first(self):
        from agent.executor import run_with_plan
        plan = _make_plan(2)
        mock_llm = MagicMock()
        mock_skill = MagicMock()

        fake_events = [
            {"type": "text", "data": "结果"},
            {"type": "stream_end", "data": None},
        ]

        with patch("agent.executor.run_agent_loop",
                   side_effect=self._mock_loop_events(fake_events)):
            events = list(run_with_plan(plan, "查询", mock_llm, mock_skill))

        assert events[0]["type"] == "plan"
        assert "steps" in events[0]["data"]

    def test_emits_plan_done_at_end(self):
        from agent.executor import run_with_plan
        plan = _make_plan(2)
        mock_llm = MagicMock()
        mock_skill = MagicMock()

        fake_events = [{"type": "stream_end", "data": None}]

        with patch("agent.executor.run_agent_loop",
                   side_effect=self._mock_loop_events(fake_events)):
            events = list(run_with_plan(plan, "查询", mock_llm, mock_skill))

        event_types = [e["type"] for e in events]
        assert "plan_done" in event_types

    def test_plan_step_event_on_tool_start(self):
        from agent.executor import run_with_plan
        plan = _make_plan(2)
        mock_llm = MagicMock()
        mock_skill = MagicMock()

        fake_events = [
            {"type": "tool_start", "data": {"tool": "run_sql", "label": "查询", "id": "t1"}},
            {"type": "tool_end", "data": {"success": True, "summary": "ok", "id": "t1"}},
            {"type": "stream_end", "data": None},
        ]

        with patch("agent.executor.run_agent_loop",
                   side_effect=self._mock_loop_events(fake_events)):
            events = list(run_with_plan(plan, "查询", mock_llm, mock_skill))

        plan_step_events = [e for e in events if e["type"] == "plan_step"]
        assert len(plan_step_events) >= 1
        statuses = [e["data"]["status"] for e in plan_step_events]
        assert "running" in statuses

    def test_loop_events_passed_through(self):
        from agent.executor import run_with_plan
        plan = _make_plan(1)
        mock_llm = MagicMock()
        mock_skill = MagicMock()

        fake_events = [
            {"type": "text", "data": "分析完成"},
            {"type": "stream_end", "data": None},
        ]

        with patch("agent.executor.run_agent_loop",
                   side_effect=self._mock_loop_events(fake_events)):
            events = list(run_with_plan(plan, "查询", mock_llm, mock_skill))

        text_events = [e for e in events if e["type"] == "text"]
        assert any("分析完成" in e["data"] for e in text_events)

    def test_plan_hint_injected_into_message(self):
        from agent.executor import run_with_plan
        plan = _make_plan(2)
        mock_llm = MagicMock()
        mock_skill = MagicMock()

        captured_args = {}

        def _capture_loop(msg, *args, **kwargs):
            captured_args["message"] = msg
            yield {"type": "stream_end", "data": None}

        with patch("agent.executor.run_agent_loop", side_effect=_capture_loop):
            list(run_with_plan(plan, "原始查询", mock_llm, mock_skill))

        assert "步骤1" in captured_args["message"]
        assert "原始查询" in captured_args["message"]
