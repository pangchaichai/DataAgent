"""
tools/web_search.py — 联网搜索工具（I-6）

使用 DuckDuckGo Search API（duckduckgo-search 库）。
仅用于投研类搜索（新闻、政策、一般信息），不外发用户数据。

注意：实际数值不得通过外部搜索获取，只用于定性信息/公开信息查询。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published: str = ""
    source: str = ""


@dataclass
class SearchResponse:
    ok: bool
    query: str = ""
    search_type: str = ""
    results: list[SearchResult] = field(default_factory=list)
    total: int = 0
    error: str = ""


SearchType = Literal["news", "general", "policy"]


def search(
    query: str,
    search_type: SearchType = "general",
    max_results: int = 5,
    region: str = "cn-zh",
) -> SearchResponse:
    """
    执行联网搜索。

    参数:
      query:       搜索关键词（不含敏感数据）
      search_type: 'news'（最近新闻）/ 'general'（通用）/ 'policy'（政策法规）
      max_results: 返回条数上限（1-10）
      region:      地区语言（默认中文）

    合规约束：
      - 搜索词不得包含完整产品名称 / 持仓金额 / 内部口径信息
      - 只用于定性背景查询（宏观/政策/公开评级/公开新闻）
    """
    if not query or not query.strip():
        return SearchResponse(ok=False, query=query, error="搜索词不能为空")

    max_results = max(1, min(10, max_results))

    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return SearchResponse(ok=False, query=query, error="duckduckgo-search 未安装")

    try:
        results: list[SearchResult] = []
        with DDGS() as ddgs:
            if search_type == "news":
                raw = ddgs.news(query, region=region, max_results=max_results)
            else:
                raw = ddgs.text(query, region=region, max_results=max_results)

        for item in (raw or []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", item.get("href", "")),
                snippet=item.get("body", item.get("snippet", ""))[:400],
                published=item.get("date", item.get("published", "")),
                source=item.get("source", ""),
            ))

        return SearchResponse(
            ok=True, query=query, search_type=search_type,
            results=results, total=len(results),
        )

    except Exception as e:
        return SearchResponse(ok=False, query=query, error=f"搜索失败：{str(e)[:200]}")
