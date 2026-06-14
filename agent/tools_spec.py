"""
agent/tools_spec.py — Agent 工具定义与分发表

定义 5 个工具（profile_table / run_sql / run_calculator / ask_user / request_confirmation）
及 dispatch_tool 分发函数。

设计原则：
- 工具只读/受控，写操作一律禁止
- run_calculator 的口径字段只能来自 config.yaml，不接受 LLM 传值
- ask_user / request_confirmation 产出暂停信号，由 loop 处理
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ═══════════════════════════════════════════════════════════════
#  Tool Definitions (OpenAI function-calling format)
# ═══════════════════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "profile_table",
            "description": (
                "剖析一张已加载的数据表：返回列名、推断类型、关键文本列的样本去重值、空值率。"
                "当你不确定某列含义或口径时，先调用它，而不是猜或要求用户标注。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要剖析的已加载表名",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，只剖析这些列；不传则全部列",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "对已加载表执行只读 SELECT（探索式 A 类查询）。"
                "禁止用于合规/报告口径（集中度、净值指标、资产结构、评级分布等）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "要执行的 SELECT 语句"},
                    "purpose": {
                        "type": "string",
                        "description": "一句话说明这条查询要回答什么",
                    },
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_calculator",
            "description": (
                "调用固化口径计算（合规/报告 B 类）。结果口径正确、可审计。"
                "凡涉及集中度、净值指标、资产结构、评级分布、运作报告、参谈要点等"
                "合规或报告数字，必须用本工具，禁止自己写 SQL。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "calculator": {
                        "type": "string",
                        "enum": [
                            "entity_concentration",
                            "nav_metrics",
                            "asset_structure",
                            "credit_distribution",
                            "position_diff",
                            "leverage",
                            "liquidity",
                        ],
                        "description": "要调用的固化计算器名称",
                    },
                    "holding_table": {
                        "type": "string",
                        "description": "持仓表名（可选，未指定则自动选最新持有表）",
                    },
                    "holding_table_t1": {
                        "type": "string",
                        "description": "前期持仓表名（position_diff 专用）",
                    },
                    "holding_table_t2": {
                        "type": "string",
                        "description": "后期持仓表名（position_diff 专用）",
                    },
                    "nav_table": {
                        "type": "string",
                        "description": "净值表名（leverage 专用，未指定则自动选最新净值表）",
                    },
                    "product_filter": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，只计算指定产品",
                    },
                    "group_name": {
                        "type": "string",
                        "description": "可选，按集团系过滤/合并",
                    },
                },
                "required": ["calculator"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "当存在影响结果正确性的歧义（如口径=穿透后/半穿透、是否集团合并、"
                "指哪个产品）时，向用户提出【一个】关键选择题。不要用它问无关紧要的问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "向用户提出的选择题"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "供用户选择的选项列表",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_confirmation",
            "description": (
                "在生成对外报告 / 落库合规结论前，把关键数值与口径交用户确认。"
                "用户确认后才会继续生成最终输出。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "确认事项标题"},
                    "summary": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "关键数值摘要 [{label, value}, ...]",
                    },
                    "sql_or_formula": {
                        "type": "string",
                        "description": "使用的 SQL 或固化公式版本号",
                    },
                },
                "required": ["title", "summary"],
            },
        },
    },
    # ── propose_dict_entry（R4）──
    {
        "type": "function",
        "function": {
            "name": "propose_dict_entry",
            "description": (
                "将字段语义映射提案写入草稿目录。仅用于用户确认后保存映射。"
                "草稿保存在 data_dictionary/drafts/ 下，不进入正式映射。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_type": {"type": "string", "description": "表类型"},
                    "semantic_name": {"type": "string", "description": "语义字段名"},
                    "physical_column": {"type": "string", "description": "实际列名"},
                },
                "required": ["table_type", "semantic_name", "physical_column"],
            },
        },
    },
    # ── confirm_dict（R4）──
    {
        "type": "function",
        "function": {
            "name": "confirm_dict",
            "description": (
                "将 drafts/ 中的草稿合并进正式数据字典。此操作不可逆，"
                "必须先经过 request_confirmation 获得用户明确同意。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_type": {"type": "string", "description": "要合并的表类型"},
                },
                "required": ["table_type"],
            },
        },
    },
    # ── render_chart（I-3）──
    {
        "type": "function",
        "function": {
            "name": "render_chart",
            "description": (
                "将固化计算结果可视化为 ECharts 图表。"
                "支持饼图（资产结构/评级分布）、柱状图（集中度对比）、"
                "折线图（净值走势）、瀑布图（规模变动）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["pie", "bar", "line", "waterfall"],
                        "description": "图表类型",
                    },
                    "data": {
                        "type": "object",
                        "description": "图表数据（来自 run_calculator 结果，如 structure/distribution/breaches）",
                    },
                    "title": {
                        "type": "string",
                        "description": "图表标题",
                    },
                    "options": {
                        "type": "object",
                        "description": "可选，局部覆盖 ECharts option 配置",
                    },
                },
                "required": ["chart_type", "data"],
            },
        },
    },
    # ── generate_report（I-2）──
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": (
                "根据固化计算结果生成结构化报告（Markdown + Word 导出）。"
                "数字来自 run_calculator，不经 LLM 生成。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["concentration", "nav", "asset_structure", "custom"],
                        "description": "报告类型",
                    },
                    "data": {
                        "type": "object",
                        "description": "传入模板的数据字典（来自 run_calculator 结果）",
                    },
                    "title": {
                        "type": "string",
                        "description": "报告标题",
                    },
                    "export_word": {
                        "type": "boolean",
                        "description": "是否同时导出 Word 文件（默认 true）",
                    },
                },
                "required": ["report_type", "data"],
            },
        },
    },
    # ── read_document（I-6）──
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "读取已上传的 Word/PDF/TXT 文档，提取文本内容和表格。"
                "用于理解参谈材料、政策文件等非结构化文档。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径（来自上传后的 file_path）",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最大提取字符数，默认 10000",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    # ── web_search（I-6）──
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索公开信息（新闻/政策/一般查询）。"
                "仅用于定性背景查询，不得用于获取实际数值或内部口径。"
                "合规约束：搜索词不得包含产品名称、持仓金额等敏感信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词（不含敏感数据）",
                    },
                    "search_type": {
                        "type": "string",
                        "enum": ["news", "general", "policy"],
                        "description": "搜索类型：news=最近新闻，general=通用，policy=政策法规",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回条数（1-10，默认5）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": (
                "列出当前会话中已加载的所有数据表及其元数据（表名、行数、列数、类型、日期）。"
                "在不确定有哪些可用数据时先调用此工具，避免引用不存在的表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_data",
            "description": (
                "将指定数据表导出为 CSV 文件，返回下载路径供用户下载。"
                "适用于用户需要将查询结果或分析数据导出到本地的场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要导出的表名（必须是已加载的表）",
                    },
                    "filename": {
                        "type": "string",
                        "description": "导出文件名（不含扩展名，如 holding_export）。留空则自动生成。",
                    },
                    "sql": {
                        "type": "string",
                        "description": "可选：导出前执行的过滤 SQL（SELECT 语句），结果写入 CSV。留空则导出全表。",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════
#  ToolResult — 标准化工具返回格式
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolResult:
    """标准化工具返回格式（ETCLOVG V 层）"""
    ok: bool
    data: Any = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
#  参数校验（ETCLOVG T 层）
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  执行超时保护（ETCLOVG E 层）
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  ToolContext
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolContext:
    """工具分发所需的上下文"""
    config: dict = field(default_factory=dict)
    calculation_config: dict = field(default_factory=dict)
    _conn: object | None = None

    @property
    def duckdb_conn(self):
        """Lazy-load DuckDB connection"""
        if self._conn is None:
            from tools.data_loader import get_connection
            self._conn = get_connection()
        return self._conn


# ═══════════════════════════════════════════════════════════════
#  Dispatch
# ═══════════════════════════════════════════════════════════════

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
    from tools.query_runner import execute_query

    sql = args.get("sql", "")
    if not sql.strip():
        return {"ok": False, "error": "SQL 为空"}

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
    from calculators.concentration import calc_entity_concentration
    from tools.entity_manager import EntityManager

    c = cfg.get("concentration", {})
    em = EntityManager()

    entity_alias = _load_entity_alias()

    results = calc_entity_concentration(
        conn=conn,
        holding_table=holding_table,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        threshold_pct=c.get("threshold_entity", 10.0),
        use_group_merge=c.get("use_group_merge", True),
        group_mapping=em.get_group_mapping(),
        entity_alias=entity_alias,
        product_filter=args.get("product_filter"),
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
    from calculators.nav_metrics import calc_nav_metrics

    nav_table = args.get("holding_table", "") or _auto_select_table("nav")

    results = calc_nav_metrics(
        conn=conn,
        nav_table=nav_table,
        valuation_date=args.get("valuation_date", ""),
        product_filter=args.get("product_filter"),
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

    c = cfg.get("concentration", {})
    results = calc_asset_structure(
        conn=conn,
        holding_table=holding_table,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        group_by_product=args.get("group_by_product", True),
        category_field=args.get("category_field", "G06一级分类"),
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
    from calculators.credit_distribution import calc_credit_distribution

    c = cfg.get("concentration", {})
    results = calc_credit_distribution(
        conn=conn,
        holding_table=holding_table,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        rating_field=args.get("rating_field", "外部评级"),
        product_filter=args.get("product_filter"),
        exclude_null=args.get("exclude_null", True),
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
    from calculators.position_diff import calc_position_diff

    c = cfg.get("concentration", {})
    table_t1 = args.get("holding_table_t1", "") or _auto_select_table("holding")
    table_t2 = args.get("holding_table_t2", "") or _auto_select_table("holding")

    if table_t1 == table_t2:
        return {"ok": False, "error": "前后两期持仓表相同，无法计算差异，请指定 holding_table_t1 和 holding_table_t2"}

    results = calc_position_diff(
        conn=conn,
        table_t1=table_t1,
        table_t2=table_t2,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        date_t1=args.get("date_t1", ""),
        date_t2=args.get("date_t2", ""),
        product_filter=args.get("product_filter"),
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
    from calculators.leverage import calc_leverage

    c = cfg.get("concentration", {})
    nav_table = args.get("nav_table", "") or _auto_select_table("nav")

    results = calc_leverage(
        conn=conn,
        holding_table=holding_table,
        nav_table=nav_table,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        threshold=cfg.get("leverage", {}).get("threshold", 2.0),
        product_filter=args.get("product_filter"),
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
    from calculators.liquidity import calc_liquidity

    c = cfg.get("concentration", {})
    results = calc_liquidity(
        conn=conn,
        holding_table=holding_table,
        market_value_field=c.get("market_value_field", "穿透后市值"),
        category_field=args.get("category_field", "G06一级分类"),
        threshold_liquid_pct=cfg.get("liquidity", {}).get("threshold_liquid_pct", 20.0),
        product_filter=args.get("product_filter"),
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
