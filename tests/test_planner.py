"""
tests/test_planner.py — Agent 规划层单元测试（I-8）
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  should_plan 启发式判断
# ═══════════════════════════════════════════════════════════════

class TestShouldPlan:
    def test_simple_query_no_plan(self):
        from agent.planner import should_plan
        assert not should_plan("查询持仓情况")

    def test_empty_query(self):
        from agent.planner import should_plan
        assert not should_plan("")

    def test_short_query(self):
        from agent.planner import should_plan
        assert not should_plan("帮我查")

    def test_sequential_keyword_然后(self):
        from agent.planner import should_plan
        assert should_plan("先查询持仓，然后生成合规报告")

    def test_sequential_keyword_最后(self):
        from agent.planner import should_plan
        assert should_plan("先检查集中度，接着查净值，最后导出报告")

    def test_multi_action_verbs(self):
        from agent.planner import should_plan
        # 包含"检查"+"生成"两个动作动词
        assert should_plan("检查主体集中度并生成报告")

    def test_三_or_more_action_verbs(self):
        from agent.planner import should_plan
        assert should_plan("查询持仓，统计分布，生成汇总报告")

    def test_single_action_no_plan(self):
        from agent.planner import should_plan
        assert not should_plan("只是查询今日净值数据")


# ═══════════════════════════════════════════════════════════════
#  _parse_plan_json
# ═══════════════════════════════════════════════════════════════

class TestParsePlanJson:
    def _parse(self, text):
        from agent.planner import _parse_plan_json
        return _parse_plan_json(text)

    def test_valid_json_array(self):
        text = '''[
          {"step_id": "1", "name": "剖析表结构", "tool": "profile_table",
           "objective": "了解列名", "depends_on": []},
          {"step_id": "2", "name": "执行查询", "tool": "run_sql",
           "objective": "查询持仓", "depends_on": ["1"]}
        ]'''
        steps = self._parse(text)
        assert len(steps) == 2
        assert steps[0].step_id == "1"
        assert steps[0].name == "剖析表结构"
        assert steps[0].tool == "profile_table"
        assert steps[1].depends_on == ["1"]

    def test_json_in_markdown_block(self):
        text = '''```json
[{"step_id": "1", "name": "检查集中度", "tool": "run_calculator",
  "objective": "计算主体集中度", "depends_on": []}]
```'''
        steps = self._parse(text)
        assert len(steps) == 1
        assert steps[0].tool == "run_calculator"

    def test_json_with_surrounding_text(self):
        text = '''以下是执行计划：
[{"step_id": "1", "name": "分析", "tool": "run_sql",
  "objective": "查询数据", "depends_on": []}]
计划结束。'''
        steps = self._parse(text)
        assert len(steps) == 1

    def test_invalid_json_returns_empty(self):
        steps = self._parse("这不是JSON")
        assert steps == []

    def test_empty_array(self):
        steps = self._parse("[]")
        assert steps == []

    def test_missing_fields_use_defaults(self):
        text = '[{"step_id": "1"}]'
        steps = self._parse(text)
        assert len(steps) == 1
        assert steps[0].step_id == "1"
        assert steps[0].name == "步骤1"
        assert steps[0].tool == "run_sql"
        assert steps[0].depends_on == []


# ═══════════════════════════════════════════════════════════════
#  Plan 格式化
# ═══════════════════════════════════════════════════════════════

class TestPlanFormatting:
    def _make_plan(self):
        from agent.planner import Plan, PlanStep
        return Plan(
            query="检查集中度并生成报告",
            steps=[
                PlanStep("1", "检查主体集中度", "run_calculator",
                         "计算各主体占比", []),
                PlanStep("2", "生成运作报告", "run_calculator",
                         "汇总结果生成Word报告", ["1"]),
            ],
            rationale="需要2步操作",
        )

    def test_to_prompt_hint_contains_steps(self):
        plan = self._make_plan()
        hint = plan.to_prompt_hint()
        assert "步骤1" in hint
        assert "步骤2" in hint
        assert "检查主体集中度" in hint

    def test_to_prompt_hint_shows_dependency(self):
        plan = self._make_plan()
        hint = plan.to_prompt_hint()
        assert "依赖步骤" in hint or "1" in hint

    def test_to_sse_data_structure(self):
        plan = self._make_plan()
        data = plan.to_sse_data()
        assert "steps" in data
        assert len(data["steps"]) == 2
        assert data["steps"][0]["id"] == "1"
        assert data["steps"][0]["name"] == "检查主体集中度"
        assert "rationale" in data

    def test_empty_plan_prompt_hint(self):
        from agent.planner import Plan
        empty_plan = Plan(query="test", steps=[])
        assert empty_plan.to_prompt_hint() == ""


# ═══════════════════════════════════════════════════════════════
#  build_plan（mock LLM）
# ═══════════════════════════════════════════════════════════════

class TestBuildPlan:
    def _mock_llm(self, response_text: str):
        mock = MagicMock()
        result = MagicMock()
        result.success = True
        result.text = response_text
        mock.chat.return_value = result
        return mock

    def test_build_plan_returns_plan(self):
        from agent.planner import build_plan
        llm = self._mock_llm('''[
          {"step_id": "1", "name": "剖析数据", "tool": "profile_table",
           "objective": "了解表结构", "depends_on": []},
          {"step_id": "2", "name": "执行查询", "tool": "run_sql",
           "objective": "查询持仓", "depends_on": ["1"]}
        ]''')
        plan = build_plan("检查持仓并生成报告", llm)
        assert plan is not None
        assert len(plan.steps) == 2

    def test_build_plan_llm_failure_returns_none(self):
        from agent.planner import build_plan
        mock = MagicMock()
        result = MagicMock()
        result.success = False
        result.text = ""
        mock.chat.return_value = result
        plan = build_plan("test", mock)
        assert plan is None

    def test_build_plan_single_step_returns_none(self):
        from agent.planner import build_plan
        llm = self._mock_llm('[{"step_id": "1", "name": "查询", "tool": "run_sql", "objective": "查", "depends_on": []}]')
        plan = build_plan("查询持仓", llm)
        assert plan is None  # 单步不触发规划

    def test_build_plan_exception_returns_none(self):
        from agent.planner import build_plan
        mock = MagicMock()
        mock.chat.side_effect = Exception("LLM unavailable")
        plan = build_plan("复杂查询", mock)
        assert plan is None
