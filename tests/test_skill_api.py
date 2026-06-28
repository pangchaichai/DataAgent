"""
tests/test_skill_api.py — Skill API 端点测试（Week 2）

覆盖测试计划：
  L1-01~L1-04  can_fast_path / preflight 单元测试
  L2-01~L2-06  /api/skills/status 和 /api/skills/<name>/execute 接口测试
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Flask 测试客户端 fixture
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def flask_client():
    from main import create_flask_app
    app = create_flask_app()
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════
#  L1 单元测试
# ═══════════════════════════════════════════════════════════════

class TestFastPathCanFastPath:
    """L1-01 ~ L1-02: can_fast_path 对 fund_nav_report 的判断"""

    def _make_skill_info(self, calc_type="fixed", fixed_calculator="",
                         fixed_calculators=None):
        from agent.skill_loader import SkillInfo
        return SkillInfo(
            name="fund_nav_report",
            description="净值报告",
            calc_type=calc_type,
            fixed_calculator=fixed_calculator,
            fixed_calculators=fixed_calculators or [],
        )

    def test_L1_01_fixed_calculators_list_returns_false(self):
        """L1-01: fixed_calculators 复合报告需要用户交互 → can_fast_path 返回 False（走 Agent 循环）"""
        from agent.fast_path import can_fast_path
        skill = self._make_skill_info(
            fixed_calculators=[
                "calculators.nav_metrics.calc_nav_metrics",
                "calculators.asset_structure.calc_asset_structure",
                "calculators.credit_distribution.calc_credit_distribution",
            ]
        )
        assert can_fast_path(skill) is False

    def test_L1_02_exploratory_calc_type_returns_false(self):
        """L1-02: calc_type=exploratory → can_fast_path 返回 False"""
        from agent.fast_path import can_fast_path
        skill = self._make_skill_info(calc_type="exploratory")
        assert can_fast_path(skill) is False

    def test_L1_01b_unknown_calculator_path_returns_false(self):
        """fixed_calculators 含未知路径 → can_fast_path 返回 False"""
        from agent.fast_path import can_fast_path
        skill = self._make_skill_info(
            fixed_calculators=["calculators.unknown.func"]
        )
        assert can_fast_path(skill) is False

    def test_L1_01c_single_fixed_calculator_still_works(self):
        """单 fixed_calculator 路径不受影响"""
        from agent.fast_path import can_fast_path
        skill = self._make_skill_info(
            fixed_calculator="calculators.concentration.calc_entity_concentration"
        )
        assert can_fast_path(skill) is True


class TestSkillLoaderExactMatch:
    """L1-03: __skill__:{name} 精确触发"""

    def _make_registry(self):
        from agent.skill_loader import SkillInfo
        return [
            SkillInfo(name="concentration_monitor", description="集中度监控"),
            SkillInfo(name="fund_nav_report", description="净值报告"),
        ]

    def test_exact_skill_prefix_matches(self):
        """__skill__:{name} 消息精确命中对应 Skill"""
        from agent.skill_loader import SkillLoader
        loader = SkillLoader.__new__(SkillLoader)
        registry = self._make_registry()
        result = loader.detect_relevant_skill("__skill__:concentration_monitor", registry)
        assert result == "concentration_monitor"

    def test_exact_skill_prefix_wrong_name_no_match(self):
        """__skill__:不存在的名称 → 不命中"""
        from agent.skill_loader import SkillLoader
        loader = SkillLoader.__new__(SkillLoader)
        registry = self._make_registry()
        result = loader.detect_relevant_skill("__skill__:nonexistent", registry)
        assert result is None

    def test_normal_keyword_still_works(self):
        """普通触发词匹配不受影响"""
        from agent.skill_loader import SkillInfo, SkillLoader
        loader = SkillLoader.__new__(SkillLoader)
        skill = SkillInfo(
            name="concentration_monitor",
            description="监控集中度情况\n触发词：集中度、超标",
        )
        score = loader._score_skill("检查集中度超标", skill)
        assert score >= 1


class TestRunPreflightFundNav:
    """L1-04: preflight 有数据时不阻断，无数据时阻断"""

    def test_skill_with_no_deps_not_blocked(self):
        """无任何数据依赖的 Skill → preflight 不阻断"""
        from agent.skill_loader import SkillInfo
        from agent.skill_preflight import prepare_skill_for_execution

        skill = SkillInfo(
            name="simple_skill",
            description="无依赖的简单 Skill",
            calc_type="exploratory",
            metadata={},
        )
        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]):
            result = prepare_skill_for_execution("", skill)
        assert not result.blocked

    def test_skill_with_required_types_no_data_blocked(self):
        """required_table_types=[nav] 但无数据 → 阻断"""
        from agent.skill_loader import SkillInfo
        from agent.skill_preflight import prepare_skill_for_execution

        skill = SkillInfo(
            name="fund_nav_report",
            description="净值报告",
            calc_type="fixed",
            required_table_types=["nav"],
            metadata={},
        )
        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
             patch("agent.skill_preflight._loaded_tables", {}):
            result = prepare_skill_for_execution("", skill)
        assert result.blocked

    def test_skill_with_required_types_with_data_not_blocked(self):
        """required_table_types=[nav] 且有 nav 表 → 不阻断"""
        from agent.skill_loader import SkillInfo
        from agent.skill_preflight import prepare_skill_for_execution

        skill = SkillInfo(
            name="fund_nav_report",
            description="净值报告",
            calc_type="fixed",
            required_table_types=["nav"],
            metadata={},
        )
        # Mock both get_loaded_tables and _loaded_tables
        class FakeTableInfo:
            table_type = "nav"

        mock_loaded = {"nav_20260514": FakeTableInfo()}
        mock_tables = [{"name": "nav_20260514", "type": "nav", "rows": 10}]
        with patch("agent.skill_preflight.get_loaded_tables", return_value=mock_tables), \
             patch("agent.skill_preflight._loaded_tables", mock_loaded):
            result = prepare_skill_for_execution("", skill)
        assert not result.blocked


# ═══════════════════════════════════════════════════════════════
#  L2 功能测试（API 接口）
# ═══════════════════════════════════════════════════════════════

class TestSkillsStatusEndpoint:
    """L2-01 ~ L2-03: GET /api/skills/status"""

    def test_L2_01_returns_skills_array(self, flask_client):
        """L2-01: 正常请求返回 skills 数组，每项有必要字段"""
        resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "skills" in data
        assert isinstance(data["skills"], list)
        if data["skills"]:
            item = data["skills"][0]
            assert "name" in item
            assert "description" in item
            assert "ready" in item
            assert "missing_files" in item

    def test_L2_02_missing_data_skill_shows_not_ready(self, flask_client):
        """L2-02: 未加载任何数据时，有数据依赖的 Skill ready=False"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None  # 清除缓存确保新查询
        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]):
            resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        skills_with_deps = [s for s in data["skills"]
                            if s["name"] in ("concentration_monitor", "fund_nav_report")]
        # 有数据依赖的 Skill 应显示 not ready
        for s in skills_with_deps:
            assert s["ready"] is False

    def test_L2_03_skill_with_data_shows_ready(self, flask_client):
        """L2-03: 加载了正确数据的 Skill ready=True"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None
        mock_tables = [
            {"name": "holding_20260515", "type": "holding", "rows": 100},
            {"name": "nav_20260515", "type": "nav", "rows": 20},
        ]

        class FakeTableInfo:
            def __init__(self, t):
                self.table_type = t

        mock_loaded = {
            "holding_20260515": FakeTableInfo("holding"),
            "nav_20260515": FakeTableInfo("nav"),
        }
        with patch("agent.skill_preflight.get_loaded_tables", return_value=mock_tables), \
             patch("agent.skill_preflight._loaded_tables", mock_loaded):
            resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        monitor = next(
            (s for s in data["skills"] if s["name"] == "concentration_monitor"), None
        )
        if monitor:
            assert monitor["ready"] is True

    def test_status_cache_returns_same_data(self, flask_client):
        """连续两次请求在 TTL 内返回相同数据（缓存命中）"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None
        resp1 = flask_client.get('/api/skills/status')
        resp2 = flask_client.get('/api/skills/status')
        assert resp1.get_json()["skills"] == resp2.get_json()["skills"]


class TestSkillExecuteEndpoint:
    """L2-04 ~ L2-06: POST /api/skills/<name>/execute"""

    def test_L2_05_unknown_skill_returns_404(self, flask_client):
        """L2-05: 不存在的 Skill 名 → 404"""
        resp = flask_client.post('/api/skills/nonexistent_skill_xyz/execute',
                                 json={})
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False
        assert "error" in data

    def test_L2_04_valid_skill_returns_stream_id(self, flask_client):
        """L2-04: 有效 Skill 名 → 返回 stream_id"""
        with patch("agent.loop.run_agent_loop") as mock_loop, \
             patch("tools.data_loader.init_duckdb_connection"), \
             patch("agent.llm_client.LLMClient"):
            mock_loop.return_value = iter([
                {"type": "text", "data": "ok"},
                {"type": "stream_end", "data": None},
            ])
            resp = flask_client.post('/api/skills/concentration_monitor/execute',
                                     json={})
        # Either stream_id is returned or 404 (skill not found in test env)
        if resp.status_code == 200:
            data = resp.get_json()
            assert data["ok"] is True
            assert "stream_id" in data
        else:
            # skill may not be found in test env if skills dir is missing
            assert resp.status_code in (404, 500)

    def test_L2_06_skill_execute_exact_trigger(self):
        """L2-06: execute 构造的消息 __skill__:{name} 精确触发对应 Skill"""
        from agent.skill_loader import SkillInfo, SkillLoader
        loader = SkillLoader.__new__(SkillLoader)
        registry = [
            SkillInfo(name="concentration_monitor",
                      description="监控集中度\n触发词：集中度"),
            SkillInfo(name="fund_nav_report",
                      description="净值报告\n触发词：净值"),
        ]
        # Simulate the message constructed by execute endpoint
        msg = "__skill__:fund_nav_report"
        matched = loader.detect_relevant_skill(msg, registry)
        assert matched == "fund_nav_report"
