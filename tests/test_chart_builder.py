"""
tests/test_chart_builder.py — 图表构建器单元测试（I-3）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.chart_builder import build_chart, _deep_merge


class TestBuildPieChart:
    def test_basic_items_format(self):
        result = build_chart("pie", {
            "items": [{"name": "AAA", "value": 60.0}, {"name": "AA+", "value": 40.0}]
        }, title="评级分布")
        assert result.ok
        assert result.chart_type == "pie"
        series = result.option["series"][0]
        assert series["type"] == "pie"
        assert len(series["data"]) == 2
        names = [d["name"] for d in series["data"]]
        assert "AAA" in names

    def test_credit_distribution_format(self):
        result = build_chart("pie", {
            "distribution": [
                {"rating": "AAA", "ratio_pct": 55.0, "market_value": 1e6},
                {"rating": "AA+", "ratio_pct": 45.0, "market_value": 8e5},
            ]
        }, title="信用分布")
        assert result.ok
        series = result.option["series"][0]
        names = [d["name"] for d in series["data"]]
        assert "AAA" in names

    def test_asset_structure_format(self):
        result = build_chart("pie", {
            "structure": [
                {"category": "债券", "ratio_pct": 70.0, "market_value": 7e6},
                {"category": "现金", "ratio_pct": 30.0, "market_value": 3e6},
            ]
        }, title="资产结构")
        assert result.ok
        names = [d["name"] for d in result.option["series"][0]["data"]]
        assert "债券" in names

    def test_pie_no_valid_data_raises_error(self):
        result = build_chart("pie", {"unknown_key": []})
        assert not result.ok
        assert "格式错误" in result.error or "字段" in result.error

    def test_title_in_option(self):
        result = build_chart("pie", {"items": [{"name": "A", "value": 100}]}, title="测试标题")
        assert result.ok
        assert result.option["title"]["text"] == "测试标题"


class TestBuildBarChart:
    def test_explicit_categories_format(self):
        result = build_chart("bar", {
            "categories": ["主体A", "主体B", "主体C"],
            "series": [{"name": "集中度%", "values": [8.5, 12.1, 5.3]}],
        }, title="主体集中度")
        assert result.ok
        assert result.chart_type == "bar"
        xaxis = result.option["xAxis"]
        assert "主体A" in xaxis["data"]

    def test_breaches_format(self):
        result = build_chart("bar", {
            "breaches": [
                {"entity_or_bond": "象屿集团", "concentration_pct": 11.2},
                {"entity_or_bond": "建发集团", "concentration_pct": 8.5},
            ]
        }, title="超标情况")
        assert result.ok
        cats = result.option["xAxis"]["data"]
        assert "象屿集团" in cats

    def test_bar_no_valid_data_error(self):
        result = build_chart("bar", {"unknown": []})
        assert not result.ok

    def test_multiple_series(self):
        result = build_chart("bar", {
            "categories": ["产品A", "产品B"],
            "series": [
                {"name": "债券", "values": [60.0, 55.0]},
                {"name": "现金", "values": [40.0, 45.0]},
            ],
        }, title="对比")
        assert result.ok
        assert len(result.option["series"]) == 2


class TestBuildLineChart:
    def test_basic_line(self):
        result = build_chart("line", {
            "categories": ["2026-01", "2026-02", "2026-03"],
            "series": [{"name": "产品A", "values": [1.0, 1.05, 1.03]}],
        }, title="净值走势")
        assert result.ok
        assert result.chart_type == "line"
        assert result.option["series"][0]["type"] == "line"
        assert result.option["xAxis"]["data"] == ["2026-01", "2026-02", "2026-03"]

    def test_multiple_series(self):
        result = build_chart("line", {
            "categories": ["Jan", "Feb"],
            "series": [
                {"name": "产品A", "values": [1.0, 1.1]},
                {"name": "产品B", "values": [1.0, 0.95]},
            ],
        }, title="对比")
        assert result.ok
        assert len(result.option["series"]) == 2

    def test_empty_series(self):
        result = build_chart("line", {"categories": [], "series": []}, title="空")
        assert result.ok  # 空数据也应成功，由前端处理空图表


class TestBuildWaterfallChart:
    def test_basic_waterfall(self):
        result = build_chart("waterfall", {
            "categories": ["期初", "收益", "赎回", "期末"],
            "values": [100, 20, -15, 105],
        }, title="规模变动")
        assert result.ok
        assert result.chart_type == "waterfall"
        # 应有两个 series（辅助 + 实际）
        assert len(result.option["series"]) == 2

    def test_all_positive_values(self):
        result = build_chart("waterfall", {
            "categories": ["A", "B", "C"],
            "values": [50, 30, 20],
        }, title="增长")
        assert result.ok


class TestUnknownChartType:
    def test_unknown_type_returns_error(self):
        result = build_chart("heatmap", {"data": []}, title="热力图")
        assert not result.ok
        assert "heatmap" in result.error or "不支持" in result.error


class TestOptionsOverride:
    def test_deep_merge_override(self):
        base = {"title": {"text": "原标题", "left": "center"}, "series": []}
        override = {"title": {"text": "新标题"}}
        merged = _deep_merge(base, override)
        assert merged["title"]["text"] == "新标题"
        assert merged["title"]["left"] == "center"  # 保留未覆盖的键

    def test_options_applied_to_chart(self):
        result = build_chart(
            "pie",
            {"items": [{"name": "A", "value": 100}]},
            title="测试",
            options={"backgroundColor": "#f0f0f0"},
        )
        assert result.ok
        assert result.option.get("backgroundColor") == "#f0f0f0"

    def test_nested_override(self):
        result = build_chart(
            "line",
            {"categories": ["A"], "series": [{"name": "s", "values": [1]}]},
            title="测试",
            options={"xAxis": {"axisLabel": {"rotate": 45}}},
        )
        assert result.ok
        assert result.option["xAxis"]["type"] == "category"  # 保留原有值
        assert result.option["xAxis"]["axisLabel"]["rotate"] == 45  # 覆盖值生效
