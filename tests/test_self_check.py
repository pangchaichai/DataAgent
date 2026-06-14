"""
tests/test_self_check.py — SelfChecker 单元测试（ETCLOVG V 层）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agent.self_check import SelfChecker


class TestSelfCheckerEntityConcentration:
    """entity_concentration 计算器的自检规则测试"""

    def test_no_warnings_for_valid_data(self):
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "象屿集团", "concentration_pct": 8.5,
                 "market_value": 1234567.0, "threshold_pct": 10.0},
            ]
        }
        assert checker.check("entity_concentration", result) == []

    def test_negative_concentration_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "某主体", "concentration_pct": -1.0,
                 "market_value": 100000.0, "threshold_pct": 10.0},
            ]
        }
        warnings = checker.check("entity_concentration", result)
        assert len(warnings) == 1
        assert "concentration_pct" in warnings[0]
        assert "⚠️" in warnings[0]

    def test_concentration_over_100_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "某主体", "concentration_pct": 120.0,
                 "market_value": 100000.0, "threshold_pct": 10.0},
            ]
        }
        warnings = checker.check("entity_concentration", result)
        assert any("concentration_pct" in w for w in warnings)

    def test_negative_market_value_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "测试主体", "concentration_pct": 5.0,
                 "market_value": -500.0, "threshold_pct": 10.0},
            ]
        }
        warnings = checker.check("entity_concentration", result)
        assert any("market_value" in w for w in warnings)

    def test_threshold_over_100_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "主体X", "concentration_pct": 5.0,
                 "market_value": 100.0, "threshold_pct": 150.0},
            ]
        }
        warnings = checker.check("entity_concentration", result)
        assert any("threshold_pct" in w for w in warnings)

    def test_empty_breaches_no_warnings(self):
        checker = SelfChecker()
        result = {"breaches": []}
        assert checker.check("entity_concentration", result) == []

    def test_missing_field_skipped(self):
        """缺少字段的行不应触发警告（不是计算错误）"""
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "主体Y"},  # 缺 concentration_pct 等
            ]
        }
        assert checker.check("entity_concentration", result) == []

    def test_entity_name_in_warning(self):
        """警告信息中应包含主体名"""
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "象屿集团", "concentration_pct": -0.1,
                 "market_value": 100.0, "threshold_pct": 10.0},
            ]
        }
        warnings = checker.check("entity_concentration", result)
        assert any("象屿集团" in w for w in warnings)


class TestSelfCheckerNavMetrics:
    """nav_metrics 计算器的自检规则测试"""

    def test_valid_nav_no_warnings(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product": "产品A", "return_7d": 0.5, "return_1m": 1.2,
                 "return_ytd": 5.0, "unit_nav": 1.05},
            ]
        }
        assert checker.check("nav_metrics", result) == []

    def test_extreme_7d_return_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product": "产品A", "return_7d": 25.0},
            ]
        }
        warnings = checker.check("nav_metrics", result)
        assert any("return_7d" in w for w in warnings)

    def test_extreme_monthly_return_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product": "产品B", "return_1m": -60.0},
            ]
        }
        warnings = checker.check("nav_metrics", result)
        assert any("return_1m" in w for w in warnings)

    def test_extreme_ytd_return_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product": "产品C", "return_ytd": 90.0},
            ]
        }
        warnings = checker.check("nav_metrics", result)
        assert any("return_ytd" in w for w in warnings)

    def test_low_unit_nav_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product_name": "基金D", "unit_nav": 0.3},
            ]
        }
        warnings = checker.check("nav_metrics", result)
        assert any("unit_nav" in w for w in warnings)

    def test_high_unit_nav_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product_name": "基金E", "unit_nav": 10.0},
            ]
        }
        warnings = checker.check("nav_metrics", result)
        assert any("unit_nav" in w for w in warnings)

    def test_boundary_values_no_warnings(self):
        """边界值本身不触发警告（严格 < / >）"""
        checker = SelfChecker()
        result = {
            "metrics": [
                {"product": "产品X", "return_7d": -20.0, "return_7d_max": 20.0,
                 "unit_nav": 0.5},
            ]
        }
        assert checker.check("nav_metrics", result) == []


class TestSelfCheckerAssetStructure:
    """asset_structure 计算器的自检规则测试"""

    def test_valid_structure(self):
        checker = SelfChecker()
        result = {
            "structure": [
                {"product": "产品A", "ratio_pct": 45.0, "market_value": 1e6},
                {"product": "产品A", "ratio_pct": 55.0, "market_value": 1.2e6},
            ]
        }
        assert checker.check("asset_structure", result) == []

    def test_negative_ratio_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "structure": [
                {"product": "产品A", "ratio_pct": -5.0, "market_value": 1e5},
            ]
        }
        warnings = checker.check("asset_structure", result)
        assert any("ratio_pct" in w for w in warnings)

    def test_negative_market_value_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "structure": [
                {"product": "产品B", "ratio_pct": 50.0, "market_value": -100.0},
            ]
        }
        warnings = checker.check("asset_structure", result)
        assert any("market_value" in w for w in warnings)


class TestSelfCheckerCreditDistribution:
    """credit_distribution 计算器的自检规则测试"""

    def test_valid_distribution(self):
        checker = SelfChecker()
        result = {
            "distribution": [
                {"ratio_pct": 30.0, "market_value": 5e5},
                {"ratio_pct": 70.0, "market_value": 1.2e6},
            ]
        }
        assert checker.check("credit_distribution", result) == []

    def test_ratio_over_100_triggers_warning(self):
        checker = SelfChecker()
        result = {
            "distribution": [
                {"ratio_pct": 110.0, "market_value": 1e6},
            ]
        }
        warnings = checker.check("credit_distribution", result)
        assert any("ratio_pct" in w for w in warnings)


class TestSelfCheckerUnknownCalculator:
    """未知计算器名称应返回空列表"""

    def test_unknown_calculator_no_crash(self):
        checker = SelfChecker()
        result = {"data": [{"value": 999}]}
        assert checker.check("unknown_calculator", result) == []

    def test_empty_result_no_crash(self):
        checker = SelfChecker()
        assert checker.check("entity_concentration", {}) == []

    def test_non_numeric_field_skipped(self):
        """非数值字段应被跳过，不触发警告也不抛异常"""
        checker = SelfChecker()
        result = {
            "breaches": [
                {"entity_or_bond": "主体Z", "concentration_pct": "N/A",
                 "market_value": 1000.0, "threshold_pct": 10.0},
            ]
        }
        assert checker.check("entity_concentration", result) == []
