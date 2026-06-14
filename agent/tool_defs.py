"""
agent/tool_defs.py — 工具定义层

TOOL_DEFINITIONS: OpenAI function-calling 格式的工具描述列表
ToolResult:       标准化工具返回格式
ToolContext:      工具调用上下文（上下文数据类）

本文件是纯数据/结构定义，不含任何业务逻辑。
"""

from dataclasses import dataclass, field
from typing import Any

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
