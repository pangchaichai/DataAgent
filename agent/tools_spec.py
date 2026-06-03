"""
agent/tools_spec.py — Agent 工具定义与分发表

定义 5 个工具（profile_table / run_sql / run_calculator / ask_user / request_confirmation）
及 dispatch_tool 分发函数。

设计原则：
- 工具只读/受控，写操作一律禁止
- run_calculator 的口径字段只能来自 config.yaml，不接受 LLM 传值
- ask_user / request_confirmation 产出暂停信号，由 loop 处理
"""

import json
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
                        ],
                        "description": "要调用的固化计算器名称",
                    },
                    "holding_table": {
                        "type": "string",
                        "description": "持仓表名（可选，未指定则自动选最新持有表）",
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
]


# ═══════════════════════════════════════════════════════════════
#  ToolContext
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolContext:
    """工具分发所需的上下文"""
    config: dict = field(default_factory=dict)
    calculation_config: dict = field(default_factory=dict)
    _conn: Optional[object] = None

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
    dispatch_map = {
        "profile_table": _tool_profile_table,
        "run_sql": _tool_run_sql,
        "run_calculator": _tool_run_calculator,
        "ask_user": _tool_ask_user,
        "request_confirmation": _tool_request_confirmation,
    }
    handler = dispatch_map.get(name)
    if handler is None:
        return {"ok": False, "error": f"未知工具：{name}"}
    try:
        return handler(args, ctx)
    except Exception as e:
        return {"ok": False, "error": f"工具执行异常：{str(e)}"}


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
        return _run_entity_concentration(args, cfg, conn, holding_table)
    elif calc_name == "nav_metrics":
        return _run_nav_metrics(args, cfg, conn)
    elif calc_name == "asset_structure":
        return _run_asset_structure(args, cfg, conn, holding_table)
    elif calc_name == "credit_distribution":
        return _run_credit_distribution(args, cfg, conn, holding_table)
    else:
        return {"ok": False, "error": f"未知计算器：{calc_name}"}


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
