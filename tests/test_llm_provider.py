"""
tests/test_llm_provider.py — LLM provider 配置 + 连通性检测测试

覆盖：
- LM Studio provider 配置解析
- test_connection() mock 单测
- list_providers() 格式
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def client_with_lmstudio(tmp_path):
    """带 lmstudio 配置的 LLMClient"""
    import yaml

    from agent.llm_client import LLMClient

    cfg = {
        "llm": {
            "sql_gen": {"primary": "lmstudio", "fallback": "deepseek",
                        "external_allowed": True, "tool_mode": "native",
                        "timeout": 60, "max_tokens": 2000},
            "report_text": {"provider": "deepseek", "fallback": "none"},
            "enterprise_internal": {"url": "", "model": "", "api_key": ""},
            "deepseek": {"url": "https://api.deepseek.com/v1",
                         "model": "deepseek-chat", "api_key": "你的DeepSeek_API_Key"},
            "lmstudio": {"url": "http://localhost:1234/v1",
                         "model": "qwen/qwen3-8b", "api_key": "lm-studio",
                         "timeout": 120},
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg), encoding="utf-8")
    return LLMClient(str(cfg_file))


# ═══════════════════════════════════════════════════════════════
#  Provider 配置解析
# ═══════════════════════════════════════════════════════════════

class TestLMStudioProviderConfig:

    def test_lmstudio_in_providers(self, client_with_lmstudio):
        """lmstudio 应出现在 providers 字典中"""
        assert 'lmstudio' in client_with_lmstudio.providers

    def test_lmstudio_url_correct(self, client_with_lmstudio):
        """lmstudio provider URL 应正确"""
        cfg = client_with_lmstudio.providers['lmstudio']
        assert cfg.get('url') == 'http://localhost:1234/v1'

    def test_lmstudio_model_correct(self, client_with_lmstudio):
        """lmstudio model 应正确"""
        cfg = client_with_lmstudio.providers['lmstudio']
        assert cfg.get('model') == 'qwen/qwen3-8b'

    def test_lmstudio_key_not_rejected(self, client_with_lmstudio):
        """lm-studio 占位符 key 不在 _PLACEHOLDER_KEYS 中（LM Studio 不校验 key）"""
        placeholder_keys = client_with_lmstudio._PLACEHOLDER_KEYS
        assert 'lm-studio' not in placeholder_keys

    def test_primary_is_lmstudio(self, client_with_lmstudio):
        """sql_gen.primary 应为 lmstudio"""
        assert client_with_lmstudio.sql_gen_cfg.get('primary') == 'lmstudio'


# ═══════════════════════════════════════════════════════════════
#  test_connection()
# ═══════════════════════════════════════════════════════════════

class TestConnectionCheck:

    def test_connection_success(self, client_with_lmstudio, monkeypatch):
        """LM Studio 正常运行时应返回 ok=True 和模型列表"""
        import requests

        class MockResp:
            status_code = 200
            def json(self):
                return {"data": [{"id": "qwen/qwen3-8b"}, {"id": "llama3"}]}

        monkeypatch.setattr(requests, 'get', lambda *a, **kw: MockResp())
        result = client_with_lmstudio.test_connection('lmstudio')
        assert result['ok'] is True
        assert 'qwen/qwen3-8b' in result['models']
        assert result['configured_model'] == 'qwen/qwen3-8b'

    def test_connection_refused(self, client_with_lmstudio, monkeypatch):
        """LM Studio 未启动时应返回 ok=False 含提示"""
        import requests

        def mock_get(*a, **kw):
            raise requests.ConnectionError("Connection refused")

        monkeypatch.setattr(requests, 'get', mock_get)
        result = client_with_lmstudio.test_connection('lmstudio')
        assert result['ok'] is False
        assert '连接' in result['error'] or 'localhost' in result['error']

    def test_connection_timeout(self, client_with_lmstudio, monkeypatch):
        """连接超时应返回 ok=False"""
        import requests

        def mock_get(*a, **kw):
            raise requests.Timeout("Timeout")

        monkeypatch.setattr(requests, 'get', mock_get)
        result = client_with_lmstudio.test_connection('lmstudio')
        assert result['ok'] is False
        assert '超时' in result['error']

    def test_connection_unknown_provider(self, client_with_lmstudio):
        """未配置的 provider 应返回 ok=False 含提示"""
        result = client_with_lmstudio.test_connection('unknown_provider')
        assert result['ok'] is False
        assert 'unknown_provider' in result['error']

    def test_connection_http_error(self, client_with_lmstudio, monkeypatch):
        """HTTP 4xx 应返回 ok=False"""
        import requests

        class MockResp:
            status_code = 404
            def json(self): return {}

        monkeypatch.setattr(requests, 'get', lambda *a, **kw: MockResp())
        result = client_with_lmstudio.test_connection('lmstudio')
        assert result['ok'] is False


# ═══════════════════════════════════════════════════════════════
#  list_providers()
# ═══════════════════════════════════════════════════════════════

class TestListProviders:

    def test_list_includes_lmstudio(self, client_with_lmstudio):
        """list_providers 应包含 lmstudio"""
        providers = client_with_lmstudio.list_providers()
        names = [p['name'] for p in providers]
        assert 'lmstudio' in names

    def test_lmstudio_is_local(self, client_with_lmstudio):
        """lmstudio provider 的 is_local 应为 True"""
        providers = client_with_lmstudio.list_providers()
        lm = next((p for p in providers if p['name'] == 'lmstudio'), None)
        assert lm is not None
        assert lm['is_local'] is True

    def test_deepseek_not_local(self, client_with_lmstudio):
        """deepseek provider 的 is_local 应为 False"""
        providers = client_with_lmstudio.list_providers()
        ds = next((p for p in providers if p['name'] == 'deepseek'), None)
        assert ds is not None
        assert ds['is_local'] is False

    def test_primary_marked_correctly(self, client_with_lmstudio):
        """当前 primary provider 的 is_primary 应为 True"""
        providers = client_with_lmstudio.list_providers()
        primaries = [p for p in providers if p['is_primary']]
        assert len(primaries) == 1
        assert primaries[0]['name'] == 'lmstudio'

    def test_unconfigured_provider_excluded(self, client_with_lmstudio):
        """没有 url 的 enterprise_internal 应被排除"""
        providers = client_with_lmstudio.list_providers()
        names = [p['name'] for p in providers]
        assert 'enterprise_internal' not in names
