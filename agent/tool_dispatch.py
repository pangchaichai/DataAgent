"""
agent/tool_dispatch.py — 工具分发层

包含：
  dispatch_tool     — 工具名 → 实现函数的路由分发
  _tool_*           — 每个工具的具体实现函数
  _validate_*       — 工具参数 Schema 校验（ETCLOVG T 层）
  _with_timeout     — 执行超时保护（ETCLOVG E 层）
"""

from dataclasses import field  # noqa: F401 (used in _validate_tool_args field_name loop)
from pathlib import Path

import yaml

from agent.tool_defs import TOOL_DEFINITIONS, ToolContext  # noqa: F401


def _get_tool_schema(name: str) -> dict:
    """从 TOOL_DEFINITIONS 中取出指定工具的 parameters schema"""
    for t in TOOL_DEFINITIONS:
        if t["function"]["name"] == name:
            return t["function"].get("parameters", {})
    return {}


def _validate_tool_args(name: str, args: dict) -> tuple[bool, str]:
    """
    校验工具入参是否满足 schema 要求。
    返回 (ok, error_message)。
    """
    schema = _get_tool_schema(name)
    if not schema:
        return True, ""  # 无 schema 可校验，放行

    required = schema.get("required", [])
    for field_name in required:
        if field_name not in args or args[field_name] is None:
            return False, f"缺少必填参数：{field_name}"

    # 枚举值校验
    props = schema.get("properties", {})
    for field_name, prop_schema in props.items():
        if field_name not in args:
            continue
        if "enum" in prop_schema:
            if args[field_name] not in prop_schema["enum"]:
                allowed = ", ".join(prop_schema["enum"])
                return False, (
                    f"参数 {field_name}={args[field_name]!r} 不在允许值中"
                    f"（允许：{allowed}）"
                )

    return True, ""


_TOOL_TIMEOUTS: dict[str, int] = {
    "profile_table": 30,
    "run_sql": 30,
    "run_calculator": 60,
    "ask_user": 5,
    "request_confirmation": 5,
    "propose_dict_entry": 10,
    "confirm_dict": 10,
    "generate_report": 30,
    "render_chart": 10,
    "read_document": 30,
    "web_search": 20,
}


def _with_timeout(
    handler, args: dict, ctx: "ToolContext", timeout_sec: int
) -> dict:
    """在线程池中执行 handler，超时时返回错误 dict（不杀死线程）"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handler, args, ctx)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            return {
                "ok": False,
                "error": f"工具执行超时（>{timeout_sec}s），请稍后重试",
            }
        except Exception as e:
            return {"ok": False, "error": f"工具执行异常：{str(e)}"}


def dispatch_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    """
    根据工具名分发到对应处理函数。

    返回:
      普通工具 → {"ok": True/False, ...}
      ask_user → {"__pause__": True, "__pause_type__": "ask", ...}
      request_confirmation → {"__pause__": True, "__pause_type__": "confirm", ...}

    护栏：
      - run_calculator 口径字段只能来自 ctx.calculation_config，拒绝 LLM 传值
      - run_sql 经过 query_runner.SQLGuard 校验
    """
    # T 层：入参校验
    ok, err = _validate_tool_args(name, args)
    if not ok:
        return {"ok": False, "error": f"参数错误：{err}"}

    dispatch_map = {
        "profile_table": _tool_profile_table,
        "run_sql": _tool_run_sql,
        "run_calculator": _tool_run_calculator,
        "ask_user": _tool_ask_user,
        "request_confirmation": _tool_request_confirmation,
        "propose_dict_entry": _tool_propose_dict_entry,
        "confirm_dict": _tool_confirm_dict,
        "generate_report": _tool_generate_report,
        "render_chart": _tool_render_chart,
        "read_document": _tool_read_document,
        "web_search": _tool_web_search,
        "list_tables": _tool_list_tables,
        "export_data": _tool_export_data,
    }
    handler = dispatch_map.get(name)
    if handler is None:
        return {"ok": False, "error": f"未知工具：{name}"}

    # 暂停工具直接调用（不走超时保护，它们只返回 pause 信号）
    if name in ("ask_user", "request_confirmation"):
        return handler(args, ctx)

    # E 层：执行超时保护
    timeout_sec = _TOOL_TIMEOUTS.get(name, 30)
    return _with_timeout(handler, args, ctx, timeout_sec)


# ═══════════════════════════════════════════════════════════════
#  Tool implementations
# ═══════════════════════════════════════════════════════════════

def _tool_profile_table(args: dict, ctx: ToolContext) -> dict:
    """剖析已加载的数据表"""
    from tools.profiler import profile_table
    result = profile_table(
        ctx.duckdb_conn,
        args["table_name"],
        columns=args.get("columns"),
    )
    return {"ok": True, **result}


def _tool_run_sql(args: dict, ctx: ToolContext) -> dict:
    """执行只读 SELECT（探索式 A 类），经 SQLGuard 校验"""
    from tools.data_loader import get_all_field_maps
    from tools.query_runner import apply_field_map, execute_query

    sql = args.get("sql", "")
    if not sql.strip():
        return {"ok": False, "error": "SQL 为空"}

    # 执行前将语义列名替换为实际物理列名（Bug 2 修复）
    field_maps = get_all_field_maps()
    if field_maps:
        sql = apply_field_map(sql, field_maps)

    result = execute_query(sql, ctx.duckdb_conn)

    if result.success:
        rows = result.rows[:200]
        return {
            "ok": True,
            "columns": result.columns,
            "rows": rows,
            "row_count": result.row_count,
            "truncated": result.row_count > 200,
            "sql": sql,
        }
    else:
        return {"ok": False, "error": result.error, "sql": sql}


def _tool_run_calculator(args: dict, ctx: ToolContext) -> dict:
    """
    调用固化口径计算（合规/报告 B 类）。

    ★ 关键护栏：market_value_field、threshold、use_group_merge
      只能来自 ctx.calculation_config（config.yaml），拒绝 LLM 传值。
    ★ 字段映射：通过 resolve_columns() 将语义列名翻译为物理列名，
      确保计算器在数据源列名不同时仍能正确执行。
    """
    cfg = ctx.calculation_config
    conn = ctx.duckdb_conn
    calc_name = args.get("calculator", "")

    # 自动选择持仓表
    holding_table = args.get("holding_table", "")
    if not holding_table:
        holding_table = _auto_select_table("holding")

    if calc_name == "entity_concentration":
        result = _run_entity_concentration(args, cfg, conn, holding_table)
    elif calc_name == "nav_metrics":
        result = _run_nav_metrics(args, cfg, conn)
    elif calc_name == "asset_structure":
        result = _run_asset_structure(args, cfg, conn, holding_table)
    elif calc_name == "credit_distribution":
        result = _run_credit_distribution(args, cfg, conn, holding_table)
    elif calc_name == "position_diff":
        result = _run_position_diff(args, cfg, conn)
    elif calc_name == "leverage":
        result = _run_leverage(args, cfg, conn, holding_table)
    elif calc_name == "liquidity":
        result = _run_liquidity(args, cfg, conn, holding_table)
    else:
        return {"ok": False, "error": f"未知计算器：{calc_name}"}

    # V 层：数值合理性自检
    if result.get("ok"):
        from agent.self_check import SelfChecker
        warnings = SelfChecker().check(calc_name, result)
        if warnings:
            result["warnings"] = warnings

    return result


def _run_entity_concentration(args, cfg, conn, holding_table):
    """实体集中度计算（口径全部来自 config）"""
    from calculators.columns import COL_ENTITY, COL_MV_PENETRATED, COL_PRODUCT_NAME
    from calculators.concentration import calc_entity_concentration
    from tools.entity_manager import EntityManager

    c = cfg.get("concentration", {})
    em = EntityManager()

    entity_alias = _load_entity_alias()
    cols = _resolve_cols_for_table(holding_table, [COL_PRODUCT_NAME, COL_ENTITY])
    mv_field = _resolve_mv_field(holding_table, c.get("market_value_field", "穿透后市值"))

    results = calc_entity_concentration(
        conn=conn,
        holding_table=holding_table,
        market_value_field=mv_field,
        threshold_pct=c.get("threshold_entity", 10.0),
        use_group_merge=c.get("use_group_merge", True),
        group_mapping=em.get_group_mapping(),
        entity_alias=entity_alias,
        product_filter=args.get("product_filter"),
        cols=cols,
    )

    breaches = [
        {
            "entity_or_bond": r.entity_or_bond,
            "product": r.product_name,
            "concentration_pct": r.concentration_pct,
            "threshold_pct": r.threshold_pct,
            "market_value": r.market_value,
            "is_breach": r.is_breach,
        }
        for r in results
    ]

    return {
        "ok": True,
        "calculator": "entity_concentration",
        "holding_table": holding_table,
        "market_value_field": c.get("market_value_field"),
        "use_group_merge": c.get("use_group_merge"),
        "breaches": breaches,
        "breach_count": len(breaches),
        "has_breach": len(breaches) > 0,
        "formula_version": "concentration.v1",
    }


def _run_nav_metrics(args, cfg, conn):
    """净值指标计算"""
    from calculators.columns import (
        COL_NAV_DATE,
        COL_NAV_NET_ASSETS,
        COL_NAV_PRODUCT,
        COL_NAV_RETURN_1M,
        COL_NAV_RETURN_1Y,
        COL_NAV_RETURN_3M,
        COL_NAV_RETURN_7D,
        COL_NAV_RETURN_INCEPTION,
        COL_NAV_RETURN_YTD,
        COL_NAV_TOTAL_ASSETS,
        COL_NAV_UNIT,
    )
    from calculators.nav_metrics import calc_nav_metrics

    nav_table = args.get("holding_table", "") or _auto_select_table("nav")
    cols = _resolve_cols_for_table(nav_table, [
        COL_NAV_PRODUCT, COL_NAV_DATE, COL_NAV_UNIT,
        COL_NAV_TOTAL_ASSETS, COL_NAV_NET_ASSETS,
        COL_NAV_RETURN_7D, COL_NAV_RETURN_1M, COL_NAV_RETURN_3M,
        COL_NAV_RETURN_1Y, COL_NAV_RETURN_YTD, COL_NAV_RETURN_INCEPTION,
    ])

    results = calc_nav_metrics(
        conn=conn,
        nav_table=nav_table,
        valuation_date=args.get("valuation_date", ""),
        product_filter=args.get("product_filter"),
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "nav_metrics",
        "nav_table": nav_table,
        "metrics": [
            {
                "product": r.product_name,
                "nav_date": r.nav_date,
                "unit_nav": r.unit_nav,
                "return_7d": r.return_7d,
                "return_1m": r.return_1m,
                "return_ytd": r.return_ytd,
            }
            for r in results
        ],
        "count": len(results),
        "formula_version": "nav_metrics.v1",
    }


def _run_asset_structure(args, cfg, conn, holding_table):
    """资产结构计算"""
    from calculators.asset_structure import calc_asset_structure
    from calculators.columns import COL_ASSET_CODE, COL_G06_L1, COL_PRODUCT_NAME

    c = cfg.get("concentration", {})
    category_field = args.get("category_field", "G06一级分类")
    cols = _resolve_cols_for_table(holding_table, [COL_PRODUCT_NAME, COL_ASSET_CODE, category_field])
    mv_field = _resolve_mv_field(holding_table, c.get("market_value_field", "穿透后市值"))

    results = calc_asset_structure(
        conn=conn,
        holding_table=holding_table,
        market_value_field=mv_field,
        group_by_product=args.get("group_by_product", True),
        category_field=category_field,
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "asset_structure",
        "holding_table": holding_table,
        "structure": [
            {
                "category": r.category,
                "product": r.product_name,
                "market_value": r.market_value,
                "ratio_pct": r.ratio_pct,
                "security_count": r.security_count,
            }
            for r in results
        ],
        "count": len(results),
        "formula_version": "asset_structure.v1",
    }


def _run_credit_distribution(args, cfg, conn, holding_table):
    """信用评级分布计算"""
    from calculators.columns import COL_ASSET_CODE, COL_EXTERNAL_RATING, COL_PRODUCT_NAME
    from calculators.credit_distribution import calc_credit_distribution

    c = cfg.get("concentration", {})
    rating_field = args.get("rating_field", "外部评级")
    cols = _resolve_cols_for_table(holding_table, [COL_PRODUCT_NAME, COL_ASSET_CODE, rating_field])
    mv_field = _resolve_mv_field(holding_table, c.get("market_value_field", "穿透后市值"))

    results = calc_credit_distribution(
        conn=conn,
        holding_table=holding_table,
        market_value_field=mv_field,
        rating_field=rating_field,
        product_filter=args.get("product_filter"),
        exclude_null=args.get("exclude_null", True),
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "credit_distribution",
        "holding_table": holding_table,
        "distribution": [
            {
                "rating": r.rating,
                "rating_type": r.rating_type,
                "market_value": r.market_value,
                "ratio_pct": r.ratio_pct,
                "security_count": r.security_count,
            }
            for r in results
        ],
        "count": len(results),
        "formula_version": "credit_distribution.v1",
    }


def _run_position_diff(args, cfg, conn):
    """跨期持仓差异计算"""
    from calculators.columns import COL_ASSET_CODE, COL_ASSET_NAME, COL_PRODUCT_NAME
    from calculators.position_diff import calc_position_diff

    c = cfg.get("concentration", {})
    table_t1 = args.get("holding_table_t1", "") or _auto_select_table("holding")
    table_t2 = args.get("holding_table_t2", "") or _auto_select_table("holding")

    if table_t1 == table_t2:
        return {"ok": False, "error": "前后两期持仓表相同，无法计算差异，请指定 holding_table_t1 和 holding_table_t2"}

    cols = _resolve_cols_for_table(table_t1, [COL_PRODUCT_NAME, COL_ASSET_CODE, COL_ASSET_NAME])
    mv_field = _resolve_mv_field(table_t1, c.get("market_value_field", "穿透后市值"))

    results = calc_position_diff(
        conn=conn,
        table_t1=table_t1,
        table_t2=table_t2,
        market_value_field=mv_field,
        date_t1=args.get("date_t1", ""),
        date_t2=args.get("date_t2", ""),
        product_filter=args.get("product_filter"),
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "position_diff",
        "table_t1": table_t1,
        "table_t2": table_t2,
        "changes": [
            {
                "asset_code": r.asset_code,
                "asset_name": r.asset_name,
                "product": r.product_name,
                "change_type": r.change_type,
                "mv_t1": r.mv_t1,
                "mv_t2": r.mv_t2,
                "mv_delta": r.mv_delta,
                "mv_delta_pct": r.mv_delta_pct,
            }
            for r in results
        ],
        "count": len(results),
        "formula_version": "position_diff.v1",
    }


def _run_leverage(args, cfg, conn, holding_table):
    """杠杆率计算"""
    from calculators.columns import COL_PRODUCT_NAME
    from calculators.leverage import calc_leverage

    c = cfg.get("concentration", {})
    nav_table = args.get("nav_table", "") or _auto_select_table("nav")
    cols = _resolve_cols_for_table(holding_table, [COL_PRODUCT_NAME])
    mv_field = _resolve_mv_field(holding_table, c.get("market_value_field", "穿透后市值"))

    results = calc_leverage(
        conn=conn,
        holding_table=holding_table,
        nav_table=nav_table,
        market_value_field=mv_field,
        threshold=cfg.get("leverage", {}).get("threshold", 2.0),
        product_filter=args.get("product_filter"),
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "leverage",
        "holding_table": holding_table,
        "nav_table": nav_table,
        "results": [
            {
                "product": r.product_name,
                "total_assets": r.total_assets,
                "net_asset_value": r.net_asset_value,
                "leverage_ratio": r.leverage_ratio,
                "threshold": r.threshold,
                "is_breach": r.is_breach,
            }
            for r in results
        ],
        "breach_count": sum(1 for r in results if r.is_breach),
        "formula_version": "leverage.v1",
    }


def _run_liquidity(args, cfg, conn, holding_table):
    """流动性分析计算"""
    from calculators.columns import COL_ASSET_CODE, COL_PRODUCT_NAME
    from calculators.liquidity import calc_liquidity

    c = cfg.get("concentration", {})
    category_field = args.get("category_field", "G06一级分类")
    cols = _resolve_cols_for_table(holding_table, [COL_PRODUCT_NAME, COL_ASSET_CODE, category_field])
    mv_field = _resolve_mv_field(holding_table, c.get("market_value_field", "穿透后市值"))

    results = calc_liquidity(
        conn=conn,
        holding_table=holding_table,
        market_value_field=mv_field,
        category_field=category_field,
        threshold_liquid_pct=cfg.get("liquidity", {}).get("threshold_liquid_pct", 20.0),
        product_filter=args.get("product_filter"),
        cols=cols,
    )

    return {
        "ok": True,
        "calculator": "liquidity",
        "holding_table": holding_table,
        "results": [
            {
                "product": r.product_name,
                "total_assets": r.total_assets,
                "liquid_ratio_pct": r.liquid_ratio_pct,
                "high_liquidity_ratio_pct": r.high_liquidity_ratio_pct,
                "illiquid_ratio_pct": r.illiquid_ratio_pct,
                "threshold_liquid_pct": r.threshold_liquid_pct,
                "is_breach": r.is_breach,
                "bands": [
                    {
                        "tier": b.tier,
                        "tier_label": b.tier_label,
                        "market_value": b.market_value,
                        "ratio_pct": b.ratio_pct,
                        "security_count": b.security_count,
                    }
                    for b in r.bands
                ],
            }
            for r in results
        ],
        "breach_count": sum(1 for r in results if r.is_breach),
        "formula_version": "liquidity.v1",
    }


def _tool_ask_user(args: dict, ctx: ToolContext) -> dict:
    """向用户提问 — 产出暂停信号"""
    return {
        "__pause__": True,
        "__pause_type__": "ask",
        "question": args.get("question", ""),
        "options": args.get("options", []),
    }


def _tool_request_confirmation(args: dict, ctx: ToolContext) -> dict:
    """请求用户确认 — 产出暂停信号"""
    return {
        "__pause__": True,
        "__pause_type__": "confirm",
        "title": args.get("title", ""),
        "summary": args.get("summary", []),
        "sql_or_formula": args.get("sql_or_formula", ""),
    }


def _tool_propose_dict_entry(args: dict, ctx: ToolContext) -> dict:
    """将字段语义映射提案写入草稿目录"""
    table_type = args.get("table_type", "")
    semantic = args.get("semantic_name", "")
    physical = args.get("physical_column", "")

    drafts_dir = (
        Path(__file__).resolve().parent.parent / "data_dictionary" / "drafts"
    )
    drafts_dir.mkdir(parents=True, exist_ok=True)

    draft_file = drafts_dir / f"{table_type}_draft.yaml"
    entries = {}
    if draft_file.exists():
        with open(draft_file, encoding="utf-8") as f:
            entries = yaml.safe_load(f) or {}

    if "fields" not in entries:
        entries["fields"] = []
    entries["fields"].append({
        "semantic": semantic,
        "physical_candidates": [physical],
        "proposed": True,
    })

    with open(draft_file, "w", encoding="utf-8") as f:
        yaml.dump(entries, f, allow_unicode=True, default_flow_style=False)

    return {
        "ok": True,
        "draft_file": str(draft_file),
        "table_type": table_type,
        "mapping": {semantic: physical},
    }


def _tool_confirm_dict(args: dict, ctx: ToolContext) -> dict:
    """将草稿合并进正式字典（须经确认）"""
    table_type = args.get("table_type", "")
    drafts_dir = (
        Path(__file__).resolve().parent.parent / "data_dictionary" / "drafts"
    )
    draft_file = drafts_dir / f"{table_type}_draft.yaml"

    if not draft_file.exists():
        return {"ok": False, "error": f"没有 {table_type} 的待确认草稿"}

    with open(draft_file, encoding="utf-8") as f:
        draft_entries = yaml.safe_load(f) or {}

    dict_dir = Path(__file__).resolve().parent.parent / "data_dictionary"
    DICT_MAP = {
        "holding": "holding_dict.yaml",
        "nav": "nav_dict.yaml",
        "rating_entity": "rating_entity_dict.yaml",
        "rating_bond": "rating_bond_dict.yaml",
        "monitoring": "monitoring_dict.yaml",
        "weekly_report": "weekly_report_dict.yaml",
    }
    dict_filename = DICT_MAP.get(table_type)
    if not dict_filename:
        return {"ok": False, "error": f"未知表类型：{table_type}"}

    dict_file = dict_dir / dict_filename
    existing = {}
    if dict_file.exists():
        with open(dict_file, encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    # 合并草稿字段
    existing_fields = existing.get("fields", [])
    existing_semantics = {f["semantic"] for f in existing_fields}
    for df in draft_entries.get("fields", []):
        if df["semantic"] not in existing_semantics:
            existing_fields.append({
                "semantic": df["semantic"],
                "physical_candidates": df.get("physical_candidates", []),
            })

    existing["fields"] = existing_fields
    with open(dict_file, "w", encoding="utf-8") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)

    # 删除已合并的草稿
    draft_file.unlink()

    return {
        "ok": True,
        "table_type": table_type,
        "merged_count": len(draft_entries.get("fields", [])),
        "dict_file": str(dict_file),
    }


def _tool_render_chart(args: dict, ctx: ToolContext) -> dict:
    """生成 ECharts option dict，由前端渲染为图表（I-3）"""
    from tools.chart_builder import build_chart

    result = build_chart(
        chart_type=args.get("chart_type", ""),
        data=args.get("data") or {},
        title=args.get("title", ""),
        options=args.get("options"),
    )

    if not result.ok:
        return {"ok": False, "error": result.error}

    return {
        "ok": True,
        "chart_type": result.chart_type,
        "title": result.title,
        "option": result.option,
    }


def _tool_generate_report(args: dict, ctx: ToolContext) -> dict:
    """
    根据固化计算结果生成 Markdown 报告并可选导出 Word。

    report_type → 模板名映射：
      concentration   → concentration_report
      nav             → nav_report
      asset_structure → concentration_report（结构类似，复用）
      custom          → 需要 data["template"] 指定模板名
    """
    from datetime import datetime

    from tools.report_builder import export_word as _export_word
    from tools.report_builder import render_report

    report_type = args.get("report_type", "")
    data = dict(args.get("data") or {})
    title = args.get("title", "")
    should_export = args.get("export_word", True)

    template_map = {
        "concentration": "concentration_report",
        "nav": "nav_report",
        "asset_structure": "concentration_report",
        "custom": data.get("template", ""),
    }
    template_name = template_map.get(report_type, "")
    if not template_name:
        return {"ok": False, "error": f"未知报告类型：{report_type}"}

    if title:
        data.setdefault("title", title)
    else:
        labels = {
            "concentration_report": "主体集中度监控报告",
            "nav_report": "净值运作报告",
        }
        data.setdefault("title", labels.get(template_name, "DataAgent 报告"))

    render_result = render_report(template_name, data)
    if not render_result.ok:
        return {"ok": False, "error": render_result.error}

    result: dict = {
        "ok": True,
        "report_type": report_type,
        "template": template_name,
        "markdown": render_result.markdown,
        "word_path": "",
    }

    if should_export:
        output_dir = Path(__file__).resolve().parent.parent / "data" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        word_filename = f"{template_name}_{ts}.docx"
        word_result = _export_word(render_result.markdown, str(output_dir / word_filename))
        if word_result.ok:
            result["word_path"] = word_result.word_path
            result["word_filename"] = word_filename
        else:
            result["word_export_error"] = word_result.error

    return result


def _tool_read_document(args: dict, ctx: ToolContext) -> dict:
    """读取 Word/PDF/TXT 文档（I-6）"""
    from tools.file_reader import read_document
    file_path = args.get("file_path", "")
    max_chars = int(args.get("max_chars") or 10000)
    result = read_document(file_path, max_chars=max_chars)
    if not result.ok:
        return {"ok": False, "error": result.error}
    return {
        "ok": True,
        "file_type": result.file_type,
        "text": result.text,
        "tables": [{"headers": t.headers, "rows": t.rows} for t in result.tables],
        "page_count": result.page_count,
        "word_count": result.word_count,
        "warnings": result.warnings,
    }


def _tool_web_search(args: dict, ctx: ToolContext) -> dict:
    """联网搜索公开信息（I-6）"""
    from tools.web_search import search
    query = args.get("query", "")
    search_type = args.get("search_type", "general")
    max_results = int(args.get("max_results") or 5)
    resp = search(query, search_type=search_type, max_results=max_results)
    if not resp.ok:
        return {"ok": False, "error": resp.error}
    return {
        "ok": True,
        "query": resp.query,
        "search_type": resp.search_type,
        "total": resp.total,
        "results": [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "published": r.published,
            }
            for r in resp.results
        ],
    }


def _tool_list_tables(args: dict, ctx: ToolContext) -> dict:
    """列出已加载的所有数据表及元数据"""
    from tools.data_loader import get_loaded_tables
    tables = get_loaded_tables()
    return {
        "ok": True,
        "count": len(tables),
        "tables": tables,
    }


def _tool_export_data(args: dict, ctx: ToolContext) -> dict:
    """将数据表（或 SQL 查询结果）导出为 CSV 文件"""
    import csv
    import datetime

    from session_store import BASE_DIR
    from tools.data_loader import get_loaded_tables

    table_name = args.get("table_name", "").strip()
    if not table_name:
        return {"ok": False, "error": "table_name 不能为空"}

    loaded = [t["name"] for t in get_loaded_tables()]
    if table_name not in loaded:
        return {"ok": False, "error": f"表「{table_name}」未加载，已加载表：{loaded}"}

    # 导出不经过 SQLGuard（写文件的受控操作，非 Agent 自由查询）
    sql = (args.get("sql") or "").strip()
    if not sql:
        sql = f'SELECT * FROM "{table_name}" LIMIT 50000'

    try:
        rel = ctx.duckdb_conn.execute(sql)
        columns = [desc[0] for desc in rel.description]
        rows = rel.fetchall()
    except Exception as e:
        return {"ok": False, "error": f"查询失败：{e}"}

    filename = (args.get("filename") or "").strip()
    if not filename:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{table_name}_export_{ts}"
    if not filename.endswith(".csv"):
        filename += ".csv"

    output_dir = BASE_DIR / "data" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / filename

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    return {
        "ok": True,
        "file_path": str(out_path),
        "filename": filename,
        "row_count": len(rows),
        "columns": columns,
        "message": f"已导出 {len(rows)} 行数据到 {filename}",
    }


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _resolve_cols_for_table(table_name: str, semantics: list[str]) -> dict[str, str] | None:
    """
    查找指定表的字段映射，解析语义列名→物理列名。
    表无映射时返回 None（计算器将使用默认语义名）。
    解析失败时不抛异常——让计算器用语义名尝试执行，
    DuckDB 报列名错误后由 Agent 自愈机制处理。
    """
    from tools.data_loader import get_field_map_for_table
    field_map = get_field_map_for_table(table_name)
    if not field_map:
        return None
    cols = {}
    for sem in semantics:
        cols[sem] = field_map.get(sem, sem)
    return cols


def _resolve_mv_field(table_name: str, configured_mv: str) -> str:
    """
    解析市值字段：若 config 中配置的是语义名（如"穿透后市值"），
    通过字段映射翻译为物理列名（如"资产市值_穿透后"）。
    """
    from tools.data_loader import get_field_map_for_table
    field_map = get_field_map_for_table(table_name)
    if field_map and configured_mv in field_map:
        return field_map[configured_mv]
    return configured_mv


def _auto_select_table(table_type: str) -> str:
    """从已加载表中自动选择最新的一张指定类型的表"""
    from tools.data_loader import get_loaded_tables
    tables = get_loaded_tables()
    candidates = [t for t in tables if t.get("type") == table_type]
    if candidates:
        return candidates[0]["name"]
    return ""


def _load_entity_alias() -> dict:
    """加载主体别名映射表"""
    alias_path = (
        Path(__file__).resolve().parent.parent
        / "data_dictionary" / "entity_alias.yaml"
    )
    if not alias_path.exists():
        return {}
    with open(alias_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    mapping = {}
    for entity in raw.get("entities", []):
        canonical = entity["canonical"]
        mapping[canonical] = canonical
        for alias in entity.get("aliases", []):
            mapping[alias] = canonical
    return mapping
