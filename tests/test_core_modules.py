"""
tests/test_core_modules.py — Core module unit tests

Covers:
  - session_store.py     (session init / save / load)
  - entity_normalizer.py (alias mapping / edge cases)
  - quality.py           (null rates / coverage / JOIN compat)
  - compliance_audit.py  (JSONL logging / hash chain / field validation)
  - entity_manager.py    (group CRUD)
"""

import json
import os
import sys
import tempfile

import duckdb
import pandas as pd
import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def entity_alias_file(tmp_path):
    """Create a temporary entity_alias.yaml for testing."""
    alias_data = {
        "entities": [
            {
                "canonical": "象屿集团",
                "aliases": [
                    "厦门象屿集团有限公司",
                    "象屿集团有限公司",
                    "厦门象屿",
                    "象屿",
                ],
                "group": "象屿系",
            },
            {
                "canonical": "象屿股份",
                "aliases": ["厦门象屿股份有限公司"],
                "group": "象屿系",
            },
            {
                "canonical": "建发集团",
                "aliases": ["厦门建发集团有限公司", "建发集团有限公司"],
                "group": "建发系",
            },
        ]
    }
    alias_file = tmp_path / "entity_alias.yaml"
    alias_file.write_text(
        yaml.dump(alias_data, allow_unicode=True), encoding="utf-8"
    )
    return str(alias_file)


@pytest.fixture
def groups_file(tmp_path):
    """Create a temporary groups.yaml for testing."""
    groups_data = {
        "象屿系": ["象屿集团", "象屿股份"],
        "建发系": ["建发集团"],
    }
    groups_path = tmp_path / "groups.yaml"
    groups_path.write_text(
        yaml.dump(groups_data, allow_unicode=True), encoding="utf-8"
    )
    return str(groups_path)


@pytest.fixture
def empty_groups_file(tmp_path):
    """Create a temporary empty groups.yaml."""
    groups_path = tmp_path / "groups.yaml"
    groups_path.write_text("{}", encoding="utf-8")
    return str(groups_path)


@pytest.fixture
def duckdb_conn():
    """In-memory DuckDB connection for testing."""
    conn = duckdb.connect(":memory:")
    conn.execute("SET memory_limit='200MB'")
    conn.execute("SET threads=2")
    yield conn
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  1. session_store tests
# ═══════════════════════════════════════════════════════════════

class TestSessionStore:
    """Tests for session_store.py."""

    def test_import(self):
        """session_store module imports successfully."""
        import session_store
        assert hasattr(session_store, "_session")
        assert hasattr(session_store, "reset_session")
        assert hasattr(session_store, "_save_session_messages")

    def test_session_structure(self):
        """_session dict has the expected keys."""
        from session_store import _session

        expected_keys = {"session_id", "turn_count", "loaded_files", "messages", "pending"}
        assert expected_keys.issubset(set(_session.keys()))

    def test_session_defaults(self):
        """_session has correct default values."""
        from session_store import _session

        assert isinstance(_session["turn_count"], int)
        assert isinstance(_session["loaded_files"], list)
        assert isinstance(_session["messages"], list)

    def test_new_session_id_format(self):
        """_new_session_id returns a 12-char hex string."""
        from session_store import _new_session_id

        sid = _new_session_id()
        assert isinstance(sid, str)
        assert len(sid) == 12
        # Should be valid hex
        int(sid, 16)

    def test_save_and_load_session(self, tmp_path, monkeypatch):
        """Session messages can be saved to and loaded from a JSONL file."""
        import session_store

        # Redirect BASE_DIR to tmp_path so file I/O stays in temp
        monkeypatch.setattr(session_store, "BASE_DIR", tmp_path)
        sessions_dir = tmp_path / "data" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Mock get_loaded_tables to avoid importing data_loader internals
        monkeypatch.setattr(
            "tools.data_loader.get_loaded_tables", lambda: []
        )

        # Set up a session with some messages
        session_store._session["session_id"] = "test12345678"
        session_store._session["turn_count"] = 2
        session_store._session["messages"] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        # Save
        session_store._save_session_messages()

        # Verify file was written
        session_file = sessions_dir / "test12345678.jsonl"
        assert session_file.exists()

        # Load and verify
        lines = session_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3  # 1 meta + 2 messages

        meta = json.loads(lines[0])
        assert meta["id"] == "test12345678"
        assert meta["title"] == "hello"

        msg1 = json.loads(lines[1])
        assert msg1["role"] == "user"
        assert msg1["content"] == "hello"

        msg2 = json.loads(lines[2])
        assert msg2["role"] == "assistant"
        assert msg2["content"] == "hi there"

    def test_save_session_no_id(self, tmp_path, monkeypatch):
        """_save_session_messages does nothing when session_id is empty."""
        import session_store

        monkeypatch.setattr(session_store, "BASE_DIR", tmp_path)
        session_store._session["session_id"] = ""
        session_store._session["messages"] = [{"role": "user", "content": "test"}]

        # Should not raise
        session_store._save_session_messages()

        sessions_dir = tmp_path / "data" / "sessions"
        if sessions_dir.exists():
            assert len(list(sessions_dir.iterdir())) == 0


# ═══════════════════════════════════════════════════════════════
#  2. entity_normalizer tests
# ═══════════════════════════════════════════════════════════════

class TestEntityNormalizer:
    """Tests for tools/entity_normalizer.py."""

    def test_known_alias_maps_correctly(self, entity_alias_file):
        """A known alias should map to its canonical name."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.normalize("厦门象屿集团有限公司") == "象屿集团"
        assert normalizer.normalize("象屿") == "象屿集团"
        assert normalizer.normalize("象屿集团有限公司") == "象屿集团"

    def test_canonical_maps_to_itself(self, entity_alias_file):
        """A canonical name should map to itself."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.normalize("象屿集团") == "象屿集团"
        assert normalizer.normalize("建发集团") == "建发集团"

    def test_unknown_entity_returns_original(self, entity_alias_file):
        """An unknown entity name should return the original value."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.normalize("未知公司") == "未知公司"
        assert normalizer.normalize("Some Corp") == "Some Corp"

    def test_empty_string_handling(self, entity_alias_file):
        """Empty string input should return empty string."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.normalize("") == ""

    def test_none_handling(self, entity_alias_file):
        """None input should be handled gracefully (dict.get returns None as key)."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        # dict.get(None, None) returns None — the function returns the original
        result = normalizer.normalize(None)
        assert result is None

    def test_get_group(self, entity_alias_file):
        """get_group returns the group name for a known entity."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.get_group("象屿集团") == "象屿系"
        assert normalizer.get_group("厦门象屿") == "象屿系"
        assert normalizer.get_group("建发集团有限公司") == "建发系"

    def test_get_group_unknown(self, entity_alias_file):
        """get_group returns empty string for an unknown entity."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        assert normalizer.get_group("未知公司") == ""

    def test_validate_join_keys_clean(self, entity_alias_file):
        """validate_join_keys returns (True, []) when all keys match."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        left = ["厦门象屿集团有限公司", "建发集团有限公司"]
        right = ["象屿集团", "建发集团"]
        is_clean, unmatched = normalizer.validate_join_keys(left, right, "限额占用主体")
        assert is_clean is True
        assert unmatched == []

    def test_validate_join_keys_mismatch(self, entity_alias_file):
        """validate_join_keys detects unmatched entries."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        left = ["象屿集团", "未知主体X", "未知主体Y"]
        right = ["象屿集团"]
        is_clean, unmatched = normalizer.validate_join_keys(left, right, "限额占用主体")
        assert is_clean is False
        assert "未知主体X" in unmatched
        assert "未知主体Y" in unmatched
        assert "象屿集团" not in unmatched

    def test_multiple_aliases_same_canonical(self, entity_alias_file):
        """Multiple aliases should all resolve to the same canonical name."""
        from tools.entity_normalizer import EntityNormalizer

        normalizer = EntityNormalizer(entity_alias_file)
        aliases = ["厦门象屿集团有限公司", "象屿集团有限公司", "厦门象屿", "象屿"]
        results = {normalizer.normalize(a) for a in aliases}
        assert results == {"象屿集团"}


# ═══════════════════════════════════════════════════════════════
#  3. quality.py tests (QualityAuditor)
# ═══════════════════════════════════════════════════════════════

class TestQualityAuditor:
    """Tests for tools/quality.py."""

    def test_import_and_classes(self):
        """quality.py imports successfully and exposes key classes/functions."""
        from tools.quality import QualityReport, compute_quality_report
        assert QualityReport is not None
        assert callable(compute_quality_report)

    def test_quality_report_defaults(self):
        """QualityReport dataclass has correct default values."""
        from tools.quality import QualityReport

        report = QualityReport()
        assert report.null_rates == {}
        assert report.date_range is None
        assert report.entity_coverage == {}
        assert report.join_compatibility == {}
        assert report.critical_issues == []
        assert report.warnings == []

    def test_null_rate_calculation(self, duckdb_conn):
        """_compute_null_rates correctly calculates null rates."""
        from tools.quality import _compute_null_rates

        # Create a table with known nulls
        duckdb_conn.execute("""
            CREATE TABLE test_nulls AS SELECT * FROM (VALUES
                ('A', 100, 'X'),
                ('B', NULL, 'Y'),
                (NULL, 300, NULL),
                ('D', NULL, NULL)
            ) t(col_a, col_b, col_c)
        """)

        rates = _compute_null_rates(duckdb_conn, "test_nulls")
        assert rates["col_a"] == pytest.approx(0.25, abs=0.01)  # 1/4
        assert rates["col_b"] == pytest.approx(0.50, abs=0.01)  # 2/4
        assert rates["col_c"] == pytest.approx(0.50, abs=0.01)  # 2/4

    def test_null_rate_empty_table(self, duckdb_conn):
        """_compute_null_rates returns empty dict for an empty table."""
        from tools.quality import _compute_null_rates

        duckdb_conn.execute("CREATE TABLE empty_tbl (a VARCHAR, b INTEGER)")
        rates = _compute_null_rates(duckdb_conn, "empty_tbl")
        assert rates == {}

    def test_coverage_report_format(self):
        """QualityReport can hold coverage info with expected structure."""
        from tools.quality import QualityReport

        report = QualityReport()
        report.null_rates = {"col_a": 0.05, "col_b": 0.0}
        report.entity_coverage = {
            "matched": 8,
            "total": 10,
            "unmatched": ["未知A", "未知B"],
        }
        assert report.entity_coverage["matched"] == 8
        assert report.entity_coverage["total"] == 10
        assert len(report.entity_coverage["unmatched"]) == 2

    def test_compute_quality_report_basic(self, duckdb_conn):
        """compute_quality_report produces a QualityReport with null rates."""
        from tools.quality import QualityReport, compute_quality_report

        duckdb_conn.execute("""
            CREATE TABLE holding_test AS SELECT * FROM (VALUES
                ('产品A', '代码1', 100.0, '象屿集团', '2026-05-15'),
                ('产品B', '代码2', NULL, '建发集团', '2026-05-15'),
                ('产品C', NULL, 300.0, NULL, NULL)
            ) t(产品名称, 资产代码, 资产市值, 限额占用方主体, 持仓日期)
        """)

        field_map = {
            "产品名称": "产品名称",
            "资产代码": "资产代码",
            "资产市值": "资产市值",
            "限额占用方主体": "限额占用方主体",
            "持仓日期": "持仓日期",
        }

        report = compute_quality_report(
            conn=duckdb_conn,
            table_name="holding_test",
            table_type="other",  # avoid entity coverage for this basic test
            field_map=field_map,
            key_fields=["资产代码"],
        )
        assert isinstance(report, QualityReport)
        assert "资产代码" in report.null_rates
        assert report.null_rates["资产代码"] == pytest.approx(1 / 3, abs=0.01)

    def test_join_compatibility_no_other_tables(self, duckdb_conn):
        """JOIN compatibility returns empty when no other tables are loaded."""
        from tools.quality import _compute_join_compatibility
        from unittest.mock import patch

        duckdb_conn.execute("""
            CREATE TABLE solo_table AS SELECT * FROM (VALUES
                ('象屿集团'),
                ('建发集团')
            ) t(限额占用方主体)
        """)

        # Mock _loaded_tables at the source module where it is defined
        with patch("tools.data_loader._loaded_tables", {}):
            result = _compute_join_compatibility(
                duckdb_conn,
                "solo_table",
                "holding",
                {"限额占用主体": "限额占用方主体"},
            )
        assert result == {}

    def test_date_range_detection(self, duckdb_conn):
        """_detect_date_range finds date columns by name."""
        from tools.quality import _detect_date_range

        duckdb_conn.execute("""
            CREATE TABLE date_test AS SELECT * FROM (VALUES
                ('2026-01-01', 'A'),
                ('2026-06-15', 'B'),
                ('2026-03-10', 'C')
            ) t(统计日期, 名称)
        """)

        result = _detect_date_range(
            duckdb_conn, "date_test", {"统计日期": "统计日期"}
        )
        assert result is not None
        assert result["column"] == "统计日期"
        assert "2026-01-01" in result["min"]
        assert "2026-06-15" in result["max"]


# ═══════════════════════════════════════════════════════════════
#  4. compliance_audit.py tests
# ═══════════════════════════════════════════════════════════════

class TestComplianceAudit:
    """Tests for tools/compliance_audit.py."""

    def test_import_and_key_functions(self):
        """compliance_audit module exports expected functions and classes."""
        from tools.compliance_audit import (
            AuditEvent,
            AuditResult,
            log_compliance_event,
            read_audit_log,
            verify_chain,
        )
        assert callable(log_compliance_event)
        assert callable(read_audit_log)
        assert callable(verify_chain)
        assert AuditEvent is not None
        assert AuditResult is not None

    def test_log_compliance_event_writes_jsonl(self, tmp_path, monkeypatch):
        """log_compliance_event writes a valid JSONL line."""
        import tools.compliance_audit as audit

        # Redirect audit directory to tmp_path
        monkeypatch.setattr(
            audit, "_audit_dir", lambda: tmp_path
        )
        log_file = tmp_path / f"audit_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.jsonl"
        monkeypatch.setattr(
            audit, "_log_file", lambda: log_file
        )

        result = audit.log_compliance_event(
            event_type="monitoring",
            skill_name="concentration_monitor",
            data_files=[{"name": "test.csv", "path": "/tmp/test.csv", "date": "2026-05-15"}],
            sql_or_formula="calculators.concentration.v1",
            thresholds={"threshold_entity": 10.0},
            result_summary={"breach_count": 2},
            confirmed_by="test_user",
        )

        assert result.ok is True
        assert result.event_id != ""

        # Read back the file
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        event = json.loads(lines[0])
        assert event["event_type"] == "monitoring"
        assert event["skill_name"] == "concentration_monitor"
        assert event["confirmed_by"] == "test_user"

    def test_required_fields_present(self, tmp_path, monkeypatch):
        """Audit log entries contain all required fields."""
        import tools.compliance_audit as audit

        log_file = tmp_path / "audit_test.jsonl"
        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        monkeypatch.setattr(audit, "_log_file", lambda: log_file)

        audit.log_compliance_event(
            event_type="report",
            skill_name="nav_report",
            data_files=[{"name": "nav.csv", "path": "/tmp/nav.csv", "date": "2026-06-01"}],
            sql_or_formula="calculators.nav_metrics.v1",
            thresholds={"return_days": 365},
            result_summary={"products_count": 5},
            confirmed_by="analyst",
        )

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[0])

        required_fields = [
            "event_type", "skill_name", "data_files", "sql_or_formula",
            "thresholds", "result_summary", "confirmed_by", "timestamp", "prev_hash",
        ]
        for field_name in required_fields:
            assert field_name in event, f"Missing required field: {field_name}"

    def test_data_files_have_fingerprint(self, tmp_path, monkeypatch):
        """Data files in audit log include MD5 fingerprint."""
        import tools.compliance_audit as audit

        log_file = tmp_path / "audit_fp.jsonl"
        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        monkeypatch.setattr(audit, "_log_file", lambda: log_file)

        # Create a real file so fingerprint is computed
        test_file = tmp_path / "data.csv"
        test_file.write_text("col1,col2\n1,2\n")

        audit.log_compliance_event(
            event_type="query",
            skill_name="test_skill",
            data_files=[{"name": "data.csv", "path": str(test_file), "date": "2026-06-10"}],
            sql_or_formula="SELECT 1",
            thresholds={},
            result_summary={"rows": 1},
        )

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[0])
        assert len(event["data_files"]) == 1
        assert "fingerprint" in event["data_files"][0]
        # Should be a valid MD5 hex (32 chars), not MISSING
        assert len(event["data_files"][0]["fingerprint"]) == 32

    def test_hash_chain_verification(self, tmp_path, monkeypatch):
        """Hash chain is valid after writing multiple events."""
        import tools.compliance_audit as audit
        from datetime import datetime

        date_str = datetime.now().strftime("%Y%m%d")
        log_file = tmp_path / f"audit_{date_str}.jsonl"
        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        monkeypatch.setattr(audit, "_log_file", lambda: log_file)

        # Write 3 events
        for i in range(3):
            result = audit.log_compliance_event(
                event_type="monitoring",
                skill_name=f"skill_{i}",
                data_files=[],
                sql_or_formula=f"formula_{i}",
                thresholds={"threshold": i},
                result_summary={"count": i},
                confirmed_by="tester",
            )
            assert result.ok is True

        # Verify the chain
        ok, msg = audit.verify_chain(date_str)
        assert ok is True
        assert "3" in msg  # should mention 3 records

    def test_hash_chain_detects_tampering(self, tmp_path, monkeypatch):
        """Tampered log file should fail hash chain verification."""
        import tools.compliance_audit as audit
        from datetime import datetime

        date_str = datetime.now().strftime("%Y%m%d")
        log_file = tmp_path / f"audit_{date_str}.jsonl"
        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        monkeypatch.setattr(audit, "_log_file", lambda: log_file)

        # Write 3 events
        for i in range(3):
            audit.log_compliance_event(
                event_type="monitoring",
                skill_name=f"skill_{i}",
                data_files=[],
                sql_or_formula=f"formula_{i}",
                thresholds={},
                result_summary={"count": i},
            )

        # Tamper with the second line (change skill_name)
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        event = json.loads(lines[1])
        event["skill_name"] = "TAMPERED"
        lines[1] = json.dumps(event, ensure_ascii=False)
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify should fail
        ok, msg = audit.verify_chain(date_str)
        assert ok is False
        assert "不匹配" in msg or "断裂" in msg

    def test_rejects_large_result_summary(self, tmp_path, monkeypatch):
        """log_compliance_event rejects result_summary with >10 item lists."""
        import tools.compliance_audit as audit

        log_file = tmp_path / "audit_reject.jsonl"
        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        monkeypatch.setattr(audit, "_log_file", lambda: log_file)

        result = audit.log_compliance_event(
            event_type="monitoring",
            skill_name="test",
            data_files=[],
            sql_or_formula="test",
            thresholds={},
            result_summary={"rows": list(range(20))},  # >10 items
        )
        assert result.ok is False
        assert "禁止" in result.error

    def test_read_audit_log_empty(self, tmp_path, monkeypatch):
        """read_audit_log returns empty list for nonexistent date."""
        import tools.compliance_audit as audit

        monkeypatch.setattr(audit, "_audit_dir", lambda: tmp_path)
        events = audit.read_audit_log("19000101")
        assert events == []

    def test_missing_file_fingerprint(self):
        """_file_fingerprint returns 'MISSING' for nonexistent file."""
        from tools.compliance_audit import _file_fingerprint

        assert _file_fingerprint("/nonexistent/path/file.csv") == "MISSING"


# ═══════════════════════════════════════════════════════════════
#  5. entity_manager.py tests
# ═══════════════════════════════════════════════════════════════

class TestEntityManager:
    """Tests for tools/entity_manager.py."""

    def test_create_group(self, empty_groups_file):
        """Creating a new group succeeds and persists."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(empty_groups_file)
        assert mgr.create_group("测试系", ["成员A", "成员B"]) is True

        # Verify persistence
        mgr2 = EntityManager(empty_groups_file)
        assert "测试系" in mgr2.list_groups()
        assert mgr2.get_members("测试系") == ["成员A", "成员B"]

    def test_create_group_duplicate(self, empty_groups_file):
        """Creating a group that already exists returns False."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(empty_groups_file)
        mgr.create_group("测试系")
        assert mgr.create_group("测试系") is False

    def test_add_member(self, groups_file):
        """Adding a new member to an existing group succeeds."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.add_member("象屿系", "象屿地产") is True
        assert "象屿地产" in mgr.get_members("象屿系")
        assert mgr.get_group("象屿地产") == "象屿系"

    def test_add_member_duplicate(self, groups_file):
        """Adding a member that already exists returns False."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.add_member("象屿系", "象屿集团") is False

    def test_add_member_creates_group(self, empty_groups_file):
        """Adding a member to a nonexistent group auto-creates it."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(empty_groups_file)
        assert mgr.add_member("新集团系", "新成员") is True
        assert "新集团系" in mgr.list_groups()
        assert mgr.get_members("新集团系") == ["新成员"]

    def test_remove_member(self, groups_file):
        """Removing a member from a group succeeds."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.remove_member("象屿系", "象屿股份") is True
        assert "象屿股份" not in mgr.get_members("象屿系")
        assert mgr.get_group("象屿股份") == ""

    def test_remove_member_not_found(self, groups_file):
        """Removing a nonexistent member returns False."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.remove_member("象屿系", "不存在的成员") is False

    def test_remove_member_no_group(self, groups_file):
        """Removing from a nonexistent group returns False."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.remove_member("不存在系", "任意成员") is False

    def test_delete_group(self, groups_file):
        """Deleting a group removes it entirely."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.delete_group("建发系") is True
        assert "建发系" not in mgr.list_groups()
        assert mgr.get_group("建发集团") == ""

    def test_delete_group_not_found(self, groups_file):
        """Deleting a nonexistent group returns False."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.delete_group("不存在系") is False

    def test_list_groups(self, groups_file):
        """list_groups returns all groups with members."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        groups = mgr.list_groups()
        assert "象屿系" in groups
        assert "建发系" in groups
        assert "象屿集团" in groups["象屿系"]
        assert "象屿股份" in groups["象屿系"]
        assert "建发集团" in groups["建发系"]

    def test_get_group_mapping(self, groups_file):
        """get_group_mapping returns the full entity-to-group mapping."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        mapping = mgr.get_group_mapping()
        assert mapping["象屿集团"] == "象屿系"
        assert mapping["象屿股份"] == "象屿系"
        assert mapping["建发集团"] == "建发系"

    def test_get_group_unknown_entity(self, groups_file):
        """get_group returns empty string for unknown entity."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(groups_file)
        assert mgr.get_group("未知公司") == ""

    def test_nonexistent_groups_file(self, tmp_path):
        """EntityManager handles missing groups.yaml gracefully."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(str(tmp_path / "nonexistent.yaml"))
        assert mgr.list_groups() == {}
        assert mgr.get_group("any") == ""

    def test_persistence_across_operations(self, empty_groups_file):
        """Multiple operations persist correctly to disk."""
        from tools.entity_manager import EntityManager

        mgr = EntityManager(empty_groups_file)
        mgr.create_group("A系", ["成员1"])
        mgr.add_member("A系", "成员2")
        mgr.create_group("B系", ["成员3"])
        mgr.remove_member("A系", "成员1")

        # Reload and verify
        mgr2 = EntityManager(empty_groups_file)
        assert mgr2.get_members("A系") == ["成员2"]
        assert mgr2.get_members("B系") == ["成员3"]
        assert mgr2.get_group("成员1") == ""
        assert mgr2.get_group("成员2") == "A系"
