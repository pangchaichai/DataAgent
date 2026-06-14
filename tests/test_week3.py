"""
tests/test_week3.py — Week 3 测试：Skills 修复 + 新工具 + 置信度标注

覆盖测试计划：
  L1-01~L1-08  Skills 删除/合并 / preflight 模板检查 / 新工具 / confidence 字段
  L2-01~L2-04  /api/skills/status API 集成测试
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
#  L1-01 ~ L1-02: client_meeting_report 已删除，meeting_report 触发词合并
# ═══════════════════════════════════════════════════════════════

class TestSkillsMerge:
    """L1-01/L1-02: client_meeting_report 删除，meeting_report 触发词合并"""

    def _loader(self):
        from agent.skill_loader import SkillLoader
        from session_store import BASE_DIR
        return SkillLoader(local_dir=str(BASE_DIR / 'skills'))

    def test_L1_01_client_meeting_report_not_in_registry(self):
        """L1-01: registry 中不含 client_meeting_report"""
        loader = self._loader()
        registry = loader.load_registry()
        names = [s.name for s in registry]
        assert "client_meeting_report" not in names

    def test_L1_02_meeting_report_has_merged_trigger_words(self):
        """L1-02: meeting_report 触发词包含合并的关键词"""
        loader = self._loader()
        registry = loader.load_registry()
        mr = next((s for s in registry if s.name == "meeting_report"), None)
        assert mr is not None
        desc = mr.description
        # 原 meeting_report 触发词
        assert "谈参要点" in desc
        # 合并自 client_meeting_report 的触发词
        assert "拜访材料" in desc


# ═══════════════════════════════════════════════════════════════
#  L1-03 ~ L1-04: preflight 模板文件存在性检查
# ═══════════════════════════════════════════════════════════════

class TestPreflightTemplateCheck:
    """L1-03/L1-04: template_file 存在时不阻断，不存在时阻断"""

    def _make_skill(self, name, template_file):
        from agent.skill_loader import SkillInfo
        return SkillInfo(
            name=name,
            description="测试 Skill",
            calc_type="exploratory",
            metadata={"template_file": template_file} if template_file else {},
        )

    def test_L1_03_template_exists_not_blocked(self):
        """L1-03: template_file 存在 → 不阻断"""
        from agent.skill_preflight import prepare_skill_for_execution
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills" / "test_skill"
            skills_dir.mkdir(parents=True)
            (skills_dir / "template.md.j2").write_text("hello")

            skill = self._make_skill("test_skill", "template.md.j2")
            with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
                 patch("agent.skill_preflight._loaded_tables", {}), \
                 patch("agent.skill_preflight._skill_dir", return_value=skills_dir):
                result = prepare_skill_for_execution("", skill)
        assert not result.blocked

    def test_L1_04_template_missing_blocked(self):
        """L1-04: template_file 不存在 → 阻断，block_message 含'模板文件'"""
        from agent.skill_preflight import prepare_skill_for_execution
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / "skills" / "test_skill"
            skills_dir.mkdir(parents=True)
            # 不创建 template.md.j2

            skill = self._make_skill("test_skill", "template.md.j2")
            with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
                 patch("agent.skill_preflight._loaded_tables", {}), \
                 patch("agent.skill_preflight._skill_dir", return_value=skills_dir):
                result = prepare_skill_for_execution("", skill)
        assert result.blocked
        assert "模板文件" in result.block_message


# ═══════════════════════════════════════════════════════════════
#  L1-05 ~ L1-06: 新工具 list_tables / export_data
# ═══════════════════════════════════════════════════════════════

class TestNewTools:
    """L1-05/L1-06: list_tables 和 export_data 工具行为"""

    def _make_ctx(self, conn=None):
        from agent.tools_spec import ToolContext
        ctx = MagicMock(spec=ToolContext)
        ctx.duckdb_conn = conn
        ctx.calculation_config = {}
        return ctx

    def test_L1_05_list_tables_returns_ok(self):
        """L1-05: list_tables 返回 ok=True + tables 列表"""
        from agent.tools_spec import dispatch_tool
        mock_tables = [
            {"name": "holding_20260515", "type": "holding", "rows": 100},
        ]
        with patch("agent.tools_spec._tool_list_tables") as mock_fn:
            mock_fn.return_value = {"ok": True, "count": 1, "tables": mock_tables}
            result = dispatch_tool("list_tables", {}, self._make_ctx())
        assert result["ok"] is True
        assert "tables" in result

    def test_L1_05b_list_tables_direct(self):
        """list_tables 直接调用"""
        from agent.tools_spec import _tool_list_tables
        mock_tables = [{"name": "t1", "type": "holding", "rows": 10}]
        with patch("tools.data_loader.get_loaded_tables", return_value=mock_tables):
            result = _tool_list_tables({}, self._make_ctx())
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["tables"] == mock_tables

    def test_L1_06_export_data_unknown_table_error(self):
        """L1-06: export_data 表不存在时返回 ok=False"""
        from agent.tools_spec import _tool_export_data
        with patch("tools.data_loader.get_loaded_tables", return_value=[]):
            result = _tool_export_data(
                {"table_name": "nonexistent"},
                self._make_ctx(),
            )
        assert result["ok"] is False
        assert "未加载" in result["error"]

    def test_L1_06b_export_data_success(self):
        """L1-06b: export_data 成功时返回文件路径"""
        import duckdb  # noqa: PLC0415, E402

        from agent.tools_spec import _tool_export_data  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmpdir:
            conn = duckdb.connect(":memory:")
            conn.execute("CREATE TABLE t1 (a INTEGER, b VARCHAR)")
            conn.execute("INSERT INTO t1 VALUES (1, 'hello'), (2, 'world')")

            ctx = self._make_ctx(conn=conn)
            mock_tables = [{"name": "t1", "type": "test", "rows": 2}]

            with patch("tools.data_loader.get_loaded_tables", return_value=mock_tables), \
                 patch("session_store.BASE_DIR", Path(tmpdir)):
                result = _tool_export_data(
                    {"table_name": "t1", "filename": "test_export"},
                    ctx,
                )
        assert result["ok"] is True
        assert result["row_count"] == 2
        assert "test_export.csv" in result["filename"]


# ═══════════════════════════════════════════════════════════════
#  L1-07 ~ L1-08: 置信度字段
# ═══════════════════════════════════════════════════════════════

class TestConfidenceField:
    """L1-07/L1-08: _text() confidence 参数"""

    def test_L1_07_text_with_confidence(self):
        """L1-07: _text("hello", confidence="auditable") → event 含 confidence"""
        from agent.loop import _text
        evt = _text("hello", confidence="auditable")
        assert evt["type"] == "text"
        assert evt["data"] == "hello"
        assert evt["confidence"] == "auditable"

    def test_L1_08_text_without_confidence_backward_compat(self):
        """L1-08: _text("hello") 不含 confidence 字段（向后兼容）"""
        from agent.loop import _text
        evt = _text("hello")
        assert evt["type"] == "text"
        assert evt["data"] == "hello"
        assert "confidence" not in evt

    def test_fast_path_emits_auditable(self):
        """fast_path 的 text 事件含 confidence=auditable"""
        from agent.fast_path import run_fast_path
        from agent.skill_loader import SkillInfo

        skill = SkillInfo(
            name="concentration_monitor",
            description="test",
            calc_type="fixed",
            fixed_calculator="calculators.concentration.calc_entity_concentration",
        )
        # dispatch_tool returns a plain dict
        mock_result = {"ok": True, "breach_count": 0, "breaches": [], "total_products": 0}
        mock_tables = [{"name": "h1", "type": "holding", "rows": 10}]

        with patch("agent.tools_spec.dispatch_tool", return_value=mock_result), \
             patch("agent.fast_path._log_trace"):
            events = list(run_fast_path(skill, MagicMock(), mock_tables, "test"))

        text_events = [e for e in events if e.get("type") == "text"]
        assert text_events
        assert text_events[0].get("confidence") == "auditable"


# ═══════════════════════════════════════════════════════════════
#  L2 功能测试
# ═══════════════════════════════════════════════════════════════

class TestWeek3ApiStatus:
    """L2-01 ~ L2-03: /api/skills/status 反映 Week 3 变更"""

    def test_L2_03_client_meeting_report_absent(self, flask_client):
        """L2-03: skills/status 不含 client_meeting_report"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None
        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
             patch("agent.skill_preflight._loaded_tables", {}):
            resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        names = [s["name"] for s in data["skills"]]
        assert "client_meeting_report" not in names

    def test_L2_01_monthly_bond_summary_not_ready_no_template(self, flask_client):
        """L2-01: monthly_bond_summary 缺模板文件时 ready=False"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None

        # monthly_bond_summary 在 skills/ 目录下没有 template.md.j2
        from session_store import BASE_DIR
        template_path = BASE_DIR / "skills" / "monthly_bond_summary" / "template.md.j2"
        if template_path.exists():
            pytest.skip("template.md.j2 already exists, skip this test")

        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
             patch("agent.skill_preflight._loaded_tables", {}):
            resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        mbs = next((s for s in data["skills"] if s["name"] == "monthly_bond_summary"), None)
        if mbs:
            assert mbs["ready"] is False

    def test_L2_02_dept_weekly_report_template_found(self, flask_client):
        """L2-02: dept_weekly_report 有 template.md.j2 时不因模板阻断"""
        from api.skill_api import _skill_status_cache
        _skill_status_cache["data"] = None
        with patch("agent.skill_preflight.get_loaded_tables", return_value=[]), \
             patch("agent.skill_preflight._loaded_tables", {}):
            resp = flask_client.get('/api/skills/status')
        assert resp.status_code == 200
        data = resp.get_json()
        dwr = next((s for s in data["skills"] if s["name"] == "dept_weekly_report"), None)
        if dwr:
            # 有模板文件，但缺数据表，所以 ready=False 是因为数据，不是模板
            # missing_files 不含"模板"
            missing = " ".join(dwr.get("missing_files", []))
            assert "模板" not in missing
