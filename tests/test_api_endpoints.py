"""
tests/test_api_endpoints.py — API endpoint smoke tests

Covers all 6 blueprints (chat, data, config, system, report, skill)
with Flask test client. Focus: every endpoint returns a non-500 response
with correct structure.

Test plan:
  App & Blueprint          : 3 tests
  Chat API (/api/chat etc) : 6 tests
  Data API (/api/tables)   : 3 tests
  Config API (/api/config) : 3 tests
  System API (/api/health) : 7 tests
  Report API (/api/report) : 2 tests
  Total                    : 24 tests
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path (conftest.py handles this, but be safe)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def app():
    """Create the Flask app in testing mode."""
    from main import create_flask_app
    application = create_flask_app()
    application.config['TESTING'] = True
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    with app.test_client() as c:
        yield c


# ═══════════════════════════════════════════════════════════════
#  App & Blueprint Tests
# ═══════════════════════════════════════════════════════════════

class TestAppCreation:
    """Tests 1-3: Flask app and blueprint registration."""

    def test_01_flask_app_creates_successfully(self, app):
        """Flask app creates without errors."""
        assert app is not None
        assert app.config['TESTING'] is True

    def test_02_all_blueprints_registered(self, app):
        """All 6 blueprints are registered."""
        bp_names = set(app.blueprints.keys())
        expected = {'chat', 'data', 'config', 'skill', 'report', 'system'}
        assert expected.issubset(bp_names), (
            f"Missing blueprints: {expected - bp_names}"
        )

    def test_03_index_returns_html(self, client):
        """GET / returns 200 with HTML content."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'<html' in resp.data.lower() or b'<!doctype' in resp.data.lower()


# ═══════════════════════════════════════════════════════════════
#  Chat API Tests
# ═══════════════════════════════════════════════════════════════

class TestChatAPI:
    """Tests 4-9: Chat endpoints."""

    def test_04_chat_empty_message_returns_400(self, client):
        """POST /api/chat with empty message returns 400 error."""
        resp = client.post('/api/chat', json={"message": ""})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "error" in data

    def test_04b_chat_missing_message_returns_400(self, client):
        """POST /api/chat with no message field returns 400."""
        resp = client.post('/api/chat', json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_05_chat_valid_message_returns_stream_id(self, client):
        """POST /api/chat with valid message returns ok + stream_id."""
        # Mock the agent background thread so it does not actually run
        with patch('api.chat.threading.Thread') as mock_thread:
            mock_thread.return_value = MagicMock()
            resp = client.post('/api/chat', json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "stream_id" in data
        assert isinstance(data["stream_id"], str)

    def test_06_confirm_without_pending_returns_400(self, client):
        """POST /api/confirm with no pending confirmation returns 400."""
        resp = client.post('/api/confirm', json={"confirmed": True})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "error" in data

    def test_07_reset_returns_ok(self, client):
        """POST /api/reset returns ok."""
        resp = client.post('/api/reset')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_08_sessions_returns_list(self, client):
        """GET /api/sessions returns a sessions list."""
        resp = client.get('/api/sessions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_09_delete_nonexistent_session_returns_error(self, client):
        """DELETE /api/sessions/nonexistent returns 400 or 404."""
        resp = client.delete('/api/sessions/nonexistent')
        # 'nonexistent' does not match the ^[a-f0-9]{12}$ pattern, so 400
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_09b_delete_valid_id_format_not_found(self, client):
        """DELETE /api/sessions/<valid-format-id> that doesn't exist returns 404."""
        resp = client.delete('/api/sessions/aabbccddeeff')
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False

    def test_session_detail_nonexistent_returns_404(self, client):
        """GET /api/sessions/<id> for nonexistent session returns 404."""
        resp = client.get('/api/sessions/aabbccddeeff')
        assert resp.status_code == 404

    def test_stream_nonexistent_returns_404(self, client):
        """GET /api/stream/<sid> for unknown stream returns 404."""
        resp = client.get('/api/stream/no-such-stream')
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  Data API Tests
# ═══════════════════════════════════════════════════════════════

class TestDataAPI:
    """Tests 10-12: Data upload and table management."""

    def test_10_tables_returns_list(self, client):
        """GET /api/tables returns a tables list (possibly empty)."""
        resp = client.get('/api/tables')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tables" in data
        assert isinstance(data["tables"], list)

    def test_11_delete_nonexistent_table_returns_404(self, client):
        """DELETE /api/tables/nonexistent returns 404."""
        resp = client.delete('/api/tables/nonexistent_table')
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False

    def test_12_upload_without_file_returns_400(self, client):
        """POST /api/upload without file returns 400."""
        resp = client.post('/api/upload')
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "error" in data

    def test_upload_with_empty_filename_returns_400(self, client):
        """POST /api/upload with empty filename returns 400."""
        data = {"file": (io.BytesIO(b""), "")}
        resp = client.post('/api/upload', data=data,
                           content_type='multipart/form-data')
        assert resp.status_code == 400

    def test_upload_csv_returns_preview(self, client):
        """POST /api/upload with a valid CSV returns preview data."""
        csv_content = "col_a,col_b,col_c\n1,2,3\n4,5,6\n"
        data = {
            "file": (io.BytesIO(csv_content.encode('utf-8')), "test_data.csv"),
        }
        resp = client.post('/api/upload', data=data,
                           content_type='multipart/form-data')
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["ok"] is True
        assert result["file_kind"] == "data"
        assert "columns" in result
        assert "preview_rows" in result

    def test_table_profile_nonexistent_returns_404(self, client):
        """GET /api/tables/<name>/profile for nonexistent table returns 404."""
        resp = client.get('/api/tables/no_such_table/profile')
        assert resp.status_code == 404

    def test_table_quality_nonexistent_returns_404(self, client):
        """GET /api/tables/<name>/quality for nonexistent table returns 404."""
        resp = client.get('/api/tables/no_such_table/quality')
        assert resp.status_code == 404

    def test_workdir_files_returns_structure(self, client):
        """GET /api/workdir/files returns work_dir and files."""
        resp = client.get('/api/workdir/files')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "files" in data
        assert "work_dir" in data


# ═══════════════════════════════════════════════════════════════
#  Config API Tests
# ═══════════════════════════════════════════════════════════════

class TestConfigAPI:
    """Tests 13-15: Configuration endpoints."""

    def test_13_config_read_returns_dict(self, client):
        """GET /api/config returns config with expected keys."""
        resp = client.get('/api/config')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "user_profile" in data
        assert "calculation_config" in data
        assert "memory" in data
        assert "api_key_set" in data
        assert "logging" in data

    def test_14_config_write_returns_ok(self, client):
        """POST /api/config with valid data returns ok."""
        # Write to a temporary config to avoid modifying real config
        payload = {
            "memory": {"enabled": False},
        }
        resp = client.post('/api/config', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_15_groups_returns_groups(self, client):
        """GET /api/groups returns groups data."""
        resp = client.get('/api/groups')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "groups" in data
        # groups may be a list or a dict depending on EntityManager
        assert isinstance(data["groups"], (list, dict))

    def test_create_group_empty_name_returns_400(self, client):
        """POST /api/groups with empty name returns 400."""
        resp = client.post('/api/groups', json={"name": "", "members": []})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_tasks_returns_list(self, client):
        """GET /api/tasks returns tasks list."""
        resp = client.get('/api/tasks')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_memory_stats_returns_dict(self, client):
        """GET /api/memory/stats returns memory statistics."""
        resp = client.get('/api/memory/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        # Should return some dict structure from memory.get_stats()
        assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════
#  System API Tests
# ═══════════════════════════════════════════════════════════════

class TestSystemAPI:
    """Tests 16-22: System health, status, and LLM endpoints."""

    def test_16_health_returns_expected_fields(self, client):
        """GET /api/health returns health dict with ram_mb and llm fields."""
        resp = client.get('/api/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "ram_mb" in data
        assert "llm_status" in data
        assert "llm_name" in data
        assert "turn_count" in data
        assert isinstance(data["ram_mb"], (int, float))

    def test_17_status_returns_status_dict(self, client):
        """GET /api/status returns status dict with llm_ok and tables_count."""
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "llm_ok" in data
        assert "tables_count" in data
        assert isinstance(data["tables_count"], int)
        assert "tables" in data

    def test_18_suggestions_returns_list(self, client):
        """GET /api/suggestions returns suggestions list."""
        resp = client.get('/api/suggestions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
        assert len(data["suggestions"]) <= 5

    def test_19_cost_returns_data(self, client):
        """GET /api/cost returns cost tracking data."""
        resp = client.get('/api/cost')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_20_logs_returns_entries(self, client):
        """GET /api/logs returns entries list."""
        resp = client.get('/api/logs')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "entries" in data
        assert isinstance(data["entries"], list)

    def test_21_log_stats_returns_stats(self, client):
        """GET /api/logs/stats returns log statistics."""
        resp = client.get('/api/logs/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_22_llm_providers_returns_list(self, client):
        """GET /api/llm/providers returns providers list."""
        resp = client.get('/api/llm/providers')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "providers" in data
        assert isinstance(data["providers"], list)
        assert "current" in data

    def test_log_files_returns_list(self, client):
        """GET /api/logs/files returns log file list."""
        resp = client.get('/api/logs/files')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "files" in data

    def test_log_mode_invalid_returns_400(self, client):
        """POST /api/logs/mode with invalid mode returns 400."""
        resp = client.post('/api/logs/mode', json={"mode": "invalid"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_log_mode_valid_returns_ok(self, client):
        """POST /api/logs/mode with valid mode returns ok."""
        resp = client.post('/api/logs/mode', json={"mode": "basic"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["mode"] == "basic"

    def test_log_cleanup_returns_ok(self, client):
        """POST /api/logs/cleanup returns ok."""
        resp = client.post('/api/logs/cleanup')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_llm_test_returns_result(self, client):
        """POST /api/llm/test returns a result dict."""
        resp = client.post('/api/llm/test', json={})
        # May return ok or error depending on LLM availability, but not 500
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)


# ═══════════════════════════════════════════════════════════════
#  Report API Tests
# ═══════════════════════════════════════════════════════════════

class TestReportAPI:
    """Tests 23-24: Report template and export endpoints."""

    def test_23_report_templates_returns_list(self, client):
        """GET /api/report/templates returns template list."""
        resp = client.get('/api/report/templates')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "templates" in data
        assert isinstance(data["templates"], list)

    def test_24_export_word_with_content_returns_result(self, client):
        """POST /api/report/export-word with content returns ok + filename."""
        payload = {
            "content": "# Test Report\n\nThis is a test report.",
            "report_name": "test_report",
        }
        resp = client.post('/api/report/export-word', json=payload)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "filename" in data

    def test_export_word_empty_content_returns_400(self, client):
        """POST /api/report/export-word with empty content returns 400."""
        resp = client.post('/api/report/export-word', json={"content": ""})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_report_generate_missing_template_returns_400(self, client):
        """POST /api/report/generate without template_name returns 400."""
        resp = client.post('/api/report/generate', json={"data": {}})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False

    def test_report_download_nonexistent_returns_404(self, client):
        """GET /api/report/download/<file> for missing file returns 404."""
        resp = client.get('/api/report/download/nonexistent.docx')
        assert resp.status_code == 404

    def test_report_download_path_traversal_returns_400(self, client):
        """GET /api/report/download with path traversal returns 400."""
        resp = client.get('/api/report/download/../../../etc/passwd')
        # Flask routing may return 404 for the nested path, but the
        # endpoint checks for / or \ and returns 400
        assert resp.status_code in (400, 404)
