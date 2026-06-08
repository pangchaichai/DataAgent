"""
agent/self_check.py — Agent 结果自检（ETCLOVG V 层验证）

对 run_calculator 的数值结果做合理性校验，防止计算异常被直接展示给用户。
校验失败时返回 warnings 列表，不阻断结果，但在 UI 上显著提示。

设计原则：
- 只校验「物理上不可能」或「极大概率是计算错误」的值
- 不校验「业务上是否合理」（那是用户的判断）
- 宁可漏报，不要误报（阈值设保守）
"""

from dataclasses import dataclass


@dataclass
class CheckRule:
    field: str
    min_val: float | None
    max_val: float | None
    message: str


class SelfChecker:
    """对 run_calculator 结果执行数值合理性校验"""

    RULES: dict[str, list[CheckRule]] = {
        "entity_concentration": [
            CheckRule("concentration_pct", 0.0, 100.0, "集中度应在 0-100%"),
            CheckRule("market_value", 0.0, None, "市值不应为负"),
            CheckRule("threshold_pct", 0.0, 100.0, "阈值应在 0-100%"),
        ],
        "nav_metrics": [
            CheckRule("return_7d", -20.0, 20.0, "7日收益率超出 ±20%，请确认数据单位"),
            CheckRule("return_1m", -50.0, 50.0, "月收益率超出 ±50%，请确认数据单位"),
            CheckRule("return_ytd", -80.0, 80.0, "年初至今收益率超出 ±80%，请确认数据单位"),
            CheckRule("unit_nav", 0.5, 5.0, "单位净值超出 0.5-5.0 范围，请确认"),
        ],
        "asset_structure": [
            CheckRule("ratio_pct", 0.0, 100.0, "资产占比应在 0-100%"),
            CheckRule("market_value", 0.0, None, "资产市值不应为负"),
        ],
        "credit_distribution": [
            CheckRule("ratio_pct", 0.0, 100.0, "评级占比应在 0-100%"),
            CheckRule("market_value", 0.0, None, "持仓市值不应为负"),
        ],
        "position_diff": [
            CheckRule("mv_t1", 0.0, None, "前期市值不应为负"),
            CheckRule("mv_t2", 0.0, None, "后期市值不应为负"),
        ],
        "leverage": [
            CheckRule("leverage_ratio", 0.0, 50.0, "杠杆率超出 0-50x 范围，请确认数据"),
            CheckRule("total_assets", 0.0, None, "总资产不应为负"),
            CheckRule("net_asset_value", 0.0, None, "净资产值不应为负"),
        ],
        "liquidity": [
            CheckRule("liquid_ratio_pct", 0.0, 100.0, "流动性占比应在 0-100%"),
            CheckRule("high_liquidity_ratio_pct", 0.0, 100.0, "高流动性占比应在 0-100%"),
            CheckRule("total_assets", 0.0, None, "总资产不应为负"),
        ],
    }

    def check(self, calculator: str, result: dict) -> list[str]:
        """
        对 dispatch_tool 返回的 result dict 做合理性校验。

        参数:
            calculator: 计算器名称（如 "entity_concentration"）
            result:     dispatch_tool 返回的 result dict

        返回: warnings 列表，空列表表示无异常
        """
        warnings = []
        rules = self.RULES.get(calculator, [])
        if not rules:
            return warnings

        rows = self._extract_rows(calculator, result)
        for row in rows:
            for rule in rules:
                val = row.get(rule.field)
                if val is None:
                    continue
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    continue
                if rule.min_val is not None and fval < rule.min_val:
                    warnings.append(
                        f"⚠️ {rule.message}：{rule.field}={fval}"
                        + (f"（{row.get('entity_or_bond') or row.get('product') or ''}）" if any(
                            row.get(k) for k in ('entity_or_bond', 'product', 'product_name')
                        ) else "")
                    )
                if rule.max_val is not None and fval > rule.max_val:
                    warnings.append(
                        f"⚠️ {rule.message}：{rule.field}={fval}"
                        + (f"（{row.get('entity_or_bond') or row.get('product') or row.get('product_name') or ''}）" if any(
                            row.get(k) for k in ('entity_or_bond', 'product', 'product_name')
                        ) else "")
                    )
        return warnings

    @staticmethod
    def _extract_rows(calculator: str, result: dict) -> list[dict]:
        """从不同计算器的返回结构中提取数据行列表"""
        if calculator == "entity_concentration":
            return result.get("breaches", [])
        elif calculator == "nav_metrics":
            return result.get("metrics", [])
        elif calculator == "asset_structure":
            return result.get("structure", [])
        elif calculator == "credit_distribution":
            return result.get("distribution", [])
        elif calculator == "position_diff":
            return result.get("changes", [])
        elif calculator == "leverage":
            return result.get("results", [])
        elif calculator == "liquidity":
            return result.get("results", [])
        return []
