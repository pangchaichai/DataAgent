"""
agent/fast_path.py — 确定性快速路径

对 calc_type=fixed 的 Skill，直接调用固化计算，完全跳过 LLM。
响应时间从 3-5s 降至 <0.5s，同时保证零 LLM SQL 的合规约束。

集成方式：在 loop.py 的 preflight 之后、Tool-calling 循环之前，
调用 can_fast_path() 判断，然后 yield from run_fast_path(...)。
"""

import time
from collections.abc import Generator

from tools.error_translator import translate as translate_error

# fixed_calculator 路径 → run_calculator 的 calculator 参数名
_CALC_NAME_MAP: dict[str, str] = {
    "calculators.concentration.calc_entity_concentration": "entity_concentration",
    "calculators.nav_metrics.calc_nav_metrics": "nav_metrics",
    "calculators.asset_structure.calc_asset_structure": "asset_structure",
    "calculators.credit_distribution.calc_credit_distribution": "credit_distribution",
    "calculators.leverage.calc_leverage": "leverage",
    "calculators.liquidity.calc_liquidity": "liquidity",
    "calculators.position_diff.calc_position_diff": "position_diff",
}

_CALC_LABELS: dict[str, str] = {
    "entity_concentration": "运行集中度固化计算",
    "nav_metrics": "运行净值指标计算",
    "asset_structure": "运行资产结构分析",
    "credit_distribution": "运行信用评级分布计算",
    "leverage": "运行杠杆率计算",
    "liquidity": "运行流动性分析",
    "position_diff": "运行持仓变动对比",
}


def can_fast_path(skill_info) -> bool:
    """判断该 Skill 是否满足快速路径条件。"""
    if skill_info.calc_type != "fixed":
        return False
    # 多计算器路径（fund_nav_report 等复合报告）
    if skill_info.fixed_calculators:
        return all(c in _CALC_NAME_MAP for c in skill_info.fixed_calculators)
    # 单计算器路径（现有路径）
    return bool(skill_info.fixed_calculator) and skill_info.fixed_calculator in _CALC_NAME_MAP


def run_fast_path(
    skill_info,
    tool_ctx,
    tables: list[dict],
    user_message: str,
) -> Generator[dict, None, None]:
    """
    执行快速路径：跳过 LLM，直接调用固化计算，格式化输出。

    支持单计算器（fixed_calculator）和多计算器（fixed_calculators）。
    Yields 与 loop.py 格式完全一致的 SSE 事件字典。
    """
    from agent.tools_spec import dispatch_tool

    calc_paths = skill_info.fixed_calculators if skill_info.fixed_calculators \
        else [skill_info.fixed_calculator]
    calc_names = [_CALC_NAME_MAP[p] for p in calc_paths]

    t0_total = time.perf_counter()
    all_results: dict[str, dict] = {}

    for calc_name in calc_names:
        tool_id = f"fast_{calc_name}"
        label = _CALC_LABELS.get(calc_name, f"运行固化计算（{calc_name}）")

        yield {"type": "tool_start", "data": {
            "tool": "run_calculator",
            "label": label,
            "id": tool_id,
        }}

        t0 = time.perf_counter()
        args = _build_calc_args(calc_name, tables, skill_info)
        result = dispatch_tool("run_calculator", args, tool_ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        success = result.get("ok", False)
        yield {"type": "tool_end", "data": {
            "success": success,
            "summary": _brief_summary(calc_name, result) if success else "",
            "sql": "",
            "id": tool_id,
        }}

        if not success:
            raw_err = result.get("error", "计算失败")
            yield {"type": "error", "data": {
                "message": translate_error(raw_err),
                "detail": raw_err,
            }}
            _log_trace(skill_info.name, calc_name, user_message, False, elapsed_ms,
                       error=raw_err)
            yield {"type": "stream_end", "data": None}
            return

        all_results[calc_name] = result

    total_ms = (time.perf_counter() - t0_total) * 1000

    if len(calc_names) == 1:
        text = _format_result(calc_names[0], all_results[calc_names[0]], tables)
    else:
        text = _format_multi_result(calc_names, all_results, tables)

    yield {"type": "text", "data": text, "confidence": "auditable"}

    _log_trace(skill_info.name, "+".join(calc_names), user_message, True, total_ms)
    yield {"type": "stream_end", "data": None}


# ── 参数构建 ─────────────────────────────────────────────────────

def _build_calc_args(calc_name: str, tables: list[dict], skill_info) -> dict:
    """组装 run_calculator 调用参数，不依赖 LLM。"""
    args: dict = {"calculator": calc_name}

    default_args: dict = skill_info.metadata.get("default_args", {})

    holding = _latest_of_type(tables, "holding")
    if holding:
        args["holding_table"] = holding["name"]

    # nav_metrics 需要净值表（tools_spec 内部用 holding_table 字段读取 nav）
    if calc_name == "nav_metrics":
        nav = _latest_of_type(tables, "nav")
        if nav:
            args["holding_table"] = nav["name"]

    if default_args:
        args.update({k: v for k, v in default_args.items() if k not in args})

    return args


def _latest_of_type(tables: list[dict], table_type: str) -> dict | None:
    matches = [t for t in tables if t.get("type") == table_type]
    if not matches:
        return None
    return max(matches, key=lambda t: t.get("date_tag") or "")


# ── 结果格式化 ───────────────────────────────────────────────────

def _brief_summary(calc_name: str, result: dict) -> str:
    if calc_name == "entity_concentration":
        n = result.get("breach_count", 0)
        return f"发现 {n} 条超标" if n else "无超标"
    return "计算完成"


def _format_result(calc_name: str, result: dict, tables: list[dict]) -> str:
    if calc_name == "entity_concentration":
        return _fmt_entity_concentration(result, tables)
    if calc_name == "nav_metrics":
        return _fmt_nav_metrics(result)
    if calc_name == "asset_structure":
        return _fmt_asset_structure(result)
    if calc_name == "credit_distribution":
        return _fmt_credit_distribution(result)
    return f"计算完成（{calc_name}）。"


def _format_multi_result(
    calc_names: list[str], all_results: dict[str, dict], tables: list[dict],
) -> str:
    """多计算器结果合并输出（fund_nav_report 等复合报告）。"""
    parts = [_format_result(n, all_results[n], tables) for n in calc_names]
    return "\n\n---\n\n".join(parts)


def _fmt_entity_concentration(result: dict, tables: list[dict]) -> str:
    breaches = result.get("breaches", [])
    holding_table = result.get("holding_table", "")
    mv_field = result.get("market_value_field") or "穿透后市值"
    threshold = result.get("threshold_pct", 10.0)
    if threshold is None:
        threshold = 10.0
    use_group = result.get("use_group_merge", True)

    date_tag = next(
        (t.get("date_tag", "") for t in tables if t.get("name") == holding_table),
        "",
    )
    口径说明 = f"{'集团合并口径，' if use_group else ''}穿透市值字段：{mv_field}"

    if not breaches:
        return (
            f"✅ {date_tag} 数据检查完成，当前无集中度超标情况\n"
            f"（{口径说明}，阈值 {threshold}%）"
        )

    lines = [
        f"【集中度超标提示】 数据日期：{date_tag}  {口径说明}，阈值 {threshold}%",
        f"\n共发现 **{len(breaches)}** 条超标记录\n",
        "─" * 44,
    ]
    for b in breaches:
        lines.append(
            f"**产品**：{b['product']}\n"
            f"  超标主体：{b['entity_or_bond']}\n"
            f"  当前集中度：**{b['concentration_pct']}%**  |  监控阈值：{b['threshold_pct']}%\n"
            f"  持仓市值：{b['market_value']:,.2f}"
        )
        lines.append("─" * 44)

    return "\n".join(lines)


def _fmt_nav_metrics(result: dict) -> str:
    metrics = result.get("metrics", [])
    if not metrics:
        return "净值数据为空，请确认净值表已加载。"
    lines = ["**净值指标**\n"]
    header = "| 产品 | 估值日期 | 单位净值 | 近7日年化 | 近1月年化 | 今年以来 |"
    sep =    "|------|---------|---------|---------|---------|---------|"
    lines += [header, sep]
    for m in metrics:
        def _pct(v): return f"{v:.2f}%" if v is not None else "—"
        lines.append(
            f"| {m['product']} | {m['nav_date']} | {m['unit_nav']:.4f}"
            f" | {_pct(m['return_7d'])} | {_pct(m['return_1m'])} | {_pct(m['return_ytd'])} |"
        )
    return "\n".join(lines)


def _fmt_asset_structure(result: dict) -> str:
    items = result.get("structure", [])
    if not items:
        return "资产结构数据为空，请确认持仓表已加载。"
    lines = ["**资产结构**\n"]
    header = "| 资产类别 | 产品 | 市值（元）| 占比 | 品种数 |"
    sep =    "|---------|-----|---------|-----|------|"
    lines += [header, sep]
    for s in items:
        lines.append(
            f"| {s['category']} | {s['product']} | {s['market_value']:,.2f}"
            f" | {s['ratio_pct']:.2f}% | {s['security_count']} |"
        )
    return "\n".join(lines)


def _fmt_credit_distribution(result: dict) -> str:
    items = result.get("distribution", [])
    if not items:
        return "信用评级数据为空，请确认持仓表已加载。"
    lines = ["**信用评级分布**\n"]
    header = "| 评级 | 市值（元）| 占比 | 品种数 |"
    sep =    "|-----|---------|-----|------|"
    lines += [header, sep]
    for d in items:
        lines.append(
            f"| {d['rating']} | {d['market_value']:,.2f}"
            f" | {d['ratio_pct']:.2f}% | {d['security_count']} |"
        )
    return "\n".join(lines)


# ── 追踪日志 ─────────────────────────────────────────────────────

def _log_trace(
    skill_name: str,
    calc_name: str,
    user_message: str,
    success: bool,
    duration_ms: float,
    error: str = "",
) -> None:
    try:
        from agent.execution_tracker import get_tracker
        get_tracker().record(
            skill_name=skill_name,
            calc_name=calc_name,
            user_message=user_message,
            success=success,
            duration_ms=duration_ms,
            fast_path=True,
            error=error,
        )
    except Exception:
        pass
