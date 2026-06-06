"""
tests/test_web_search.py — 联网搜索单元测试（I-6，mock HTTP）
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Mock 搜索测试
# ═══════════════════════════════════════════════════════════════

class TestWebSearch:
    def _mock_ddgs(self, results: list[dict]):
        """创建 DDGS mock，返回指定结果"""
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text = MagicMock(return_value=results)
        mock_ddgs.news = MagicMock(return_value=results)
        return mock_ddgs

    def _patch_ddgs(self, mock_results):
        """Patch DDGS inside duckduckgo_search module (it's imported lazily)."""
        return patch("duckduckgo_search.DDGS", return_value=self._mock_ddgs(mock_results))

    def test_general_search_success(self):
        from tools.web_search import search
        mock_results = [
            {"title": "测试标题1", "href": "https://example.com/1", "body": "摘要内容1"},
            {"title": "测试标题2", "href": "https://example.com/2", "body": "摘要内容2"},
        ]
        with self._patch_ddgs(mock_results):
            resp = search("测试查询", search_type="general", max_results=5)
        assert resp.ok
        assert resp.total == 2
        assert resp.results[0].title == "测试标题1"
        assert resp.results[0].url == "https://example.com/1"

    def test_news_search_success(self):
        from tools.web_search import search
        mock_results = [
            {"title": "新闻标题", "url": "https://news.com", "body": "新闻摘要", "date": "2026-06-01"},
        ]
        with self._patch_ddgs(mock_results):
            resp = search("查询新闻", search_type="news")
        assert resp.ok
        assert resp.search_type == "news"

    def test_empty_query_returns_error(self):
        from tools.web_search import search
        resp = search("")
        assert not resp.ok
        assert "不能为空" in resp.error

    def test_max_results_clamped(self):
        from tools.web_search import search
        mock_results = [{"title": f"t{i}", "href": "x", "body": ""} for i in range(15)]
        with self._patch_ddgs(mock_results):
            resp = search("test", max_results=15)
        assert resp.ok

    def test_ddgs_exception_returns_error(self):
        from tools.web_search import search
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(side_effect=Exception("网络错误"))
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
            resp = search("test query")
        assert not resp.ok
        assert "搜索失败" in resp.error

    def test_snippet_truncated_to_400_chars(self):
        from tools.web_search import search
        long_body = "x" * 600
        mock_results = [{"title": "t", "href": "u", "body": long_body}]
        with self._patch_ddgs(mock_results):
            resp = search("test")
        assert resp.ok
        assert len(resp.results[0].snippet) <= 400
