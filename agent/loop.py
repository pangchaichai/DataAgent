"""
agent/loop.py — Agent 核心循环（Phase R1：重构为真正 tool-calling Agent）

职责：
  1. 组装 messages（系统提示+schema+skills+对话历史+用户）
  2. 调用 LLM chat()（with tools），模型自行决定调用哪个工具
  3. 流式输出文本 + tool_start/tool_end 事件
  4. 执行工具调用、把结果追加回 messages
  5. ask_user / request_confirmation 产出暂停信号，等待用户回应后续跑
  6. 区分 A 类探索式（run_sql）和 B 类合规固化（run_calculator）

关键变化：
  - v1.0：关键词→单条 SQL→表格 的直线流水线
  - v1.5：标准 Agent 循环，messages 驱动，模型自主选择工具
"""

import json
import time
from collections.abc import Generator

from agent.context import build_schema_context
from agent.llm_client import LLMClient
from agent.skill_loader import SkillLoader
from tools.data_loader import get_loaded_tables
from tools.error_translator import translate as translate_error
from tools.query_runner import execute_query
from tools.runtime_logger import get_logger as _get_logger

# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

MAX_TURNS = 15          # 单个请求最大 tool-calling 轮数
MAX_TOOL_RETRY = 3      # run_sql 最大自愈重试次数


# ═══════════════════════════════════════════════════════════════
#  SSE 事件辅助
# ═══════════════════════════════════════════════════════════════

def _sse_event(event_type: str, data) -> dict:
    return {"type": event_type, "data": data}


def _text(text: str) -> dict:
    return _sse_event("text", text)


def _table(data: dict) -> dict:
    return _sse_event("table", data)


def _error(msg: str) -> dict:
    return _sse_event("error", {"message": translate_error(msg), "detail": msg})


def _tool_start(tool_name: str, label: str = "", tool_id: str = "") -> dict:
    return _sse_event("tool_start", {
        "tool": tool_name,
        "label": label or tool_name,
        "id": tool_id or tool_name,
    })


def _tool_end(tool_name: str, success: bool, summary: str = "",
              sql: str = "", tool_id: str = "") -> dict:
    return _sse_event("tool_end", {
        "success": success,
        "summary": summary,
        "sql": sql,
        "id": tool_id or tool_name,
    })


def _thinking(text: str) -> dict:
    return _sse_event("thinking", text)


def _ask(data: dict) -> dict:
    return _sse_event("ask", data)


def _confirm(data: dict) -> dict:
    return _sse_event("confirm", data)


def _stream_end() -> dict:
    return _sse_event("stream_end", None)


# ═══════════════════════════════════════════════════════════════
#  错误分类（保留 v1.0 自愈逻辑，用于 run_sql 失败时）
# ═══════════════════════════════════════════════════════════════

def categorize_tool_error(error_msg: str) -> str:
    """
    区分错误类型：
      'syntax'   → SQL 语法错误，可自动重试
      'semantic' → 字段/表名/语义错误，浮现给用户确认
      'empty'    → 结果为空
      'anomaly'  → 结果异常，强制人工介入
    """
    msg = error_msg.lower()

    for p in ['syntax error', 'parse error', 'parser error',
              'unexpected token', 'unexpected character', 'catalog error']:
        if p in msg:
            return 'syntax'

    if 'binder error' in msg:
        if any(k in msg for k in ['column', 'table', 'does not exist', 'no such']):
            return 'semantic'
        return 'syntax'

    for p in ['no rows', 'empty result', '0 rows']:
        if p in msg:
            return 'empty'

    for p in ['no such column', 'column', 'no such table',
              'not loaded', 'referenced table', 'not found']:
        if p in msg:
            return 'semantic'

    return 'anomaly'


# ═══════════════════════════════════════════════════════════════
#  Agent 核心循环（v1.5：tool-calling）
# ═══════════════════════════════════════════════════════════════

def run_agent_loop(
    user_message: str,
    llm_client: LLMClient,
    skill_loader: SkillLoader,
    turn_count: int = 0,
    session_messages: list[dict] = None,
    pending: dict = None,
) -> Generator[dict, None, None]:
    """
    Agent 主循环（v1.5 tool-calling 重构版）。

    参数:
      user_message:     用户输入文本
      llm_client:       LLMClient 实例（需支持 chat() with tools）
      skill_loader:     SkillLoader 实例
      turn_count:       累计对话轮数（用于上限校验）
      session_messages: 会话消息历史；None = 新会话
      pending:          暂停状态；非 None = 续跑（用户回答了 ask/confirm）

    Yields SSE 事件字典。
    """
    # ── 加载 ToolContext ────────────────────────────────────
    from pathlib import Path

    import yaml

    from agent.tools_spec import TOOL_DEFINITIONS, ToolContext, dispatch_tool

    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    tool_ctx = ToolContext(
        config=config,
        calculation_config=config.get("calculation_config", {}),
    )

    # ── 基础校验 ──────────────────────────────────────────
    if turn_count >= MAX_TURNS:
        yield _error("对话轮数已达上限，请开启新对话继续。")
        yield _stream_end()
        return

    tables = get_loaded_tables()
    if not tables:
        yield _text("请先上传数据文件（CSV/Excel），然后我就可以帮你分析了。")
        yield _stream_end()
        return

    # ── 构建 schema + skills 上下文 ──────────────────────────
    schema_ctx = build_schema_context()
    registry = skill_loader.load_registry()
    skills_desc = _build_skills_registry_text(registry)

    # ── 组装 messages ────────────────────────────────────
    if session_messages is None:
        session_messages = []

    if not session_messages:
        # 首条消息：加入 system prompt
        system_prompt = _build_system_prompt(schema_ctx, skills_desc)
        session_messages.append({"role": "system", "content": system_prompt})

    # 处理暂停续跑
    if pending:
        pending_type = pending.get("type", "")
        tool_call_id = pending.get("tool_call_id", "")

        if pending_type == "ask":
            # 用户回答了 ask_user 的选择题
            session_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": user_message,
            })
        elif pending_type == "confirm":
            # 来自 /api/confirm 的结果
            confirmed = pending.get("confirmed", False)
            session_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps({"confirmed": confirmed}, ensure_ascii=False),
            })
        # pending 已处理，不加新的 user message
    else:
        # 普通新消息
        session_messages.append({"role": "user", "content": user_message})

    # ── 场景化工具过滤（ETCLOVG T 层）────────────────────────
    # 在新消息上检测匹配的 Skill；续跑时沿用 pending 的上下文
    if not pending:
        matched_skill_name = skill_loader.detect_relevant_skill(user_message, registry)
        matched_skill_info = next(
            (s for s in registry if s.name == matched_skill_name), None
        ) if matched_skill_name else None
    else:
        matched_skill_info = None  # 续跑阶段不重新过滤
    active_tools = _filter_tools_for_context(TOOL_DEFINITIONS, matched_skill_info)

    # ── Tool-calling 循环 ──────────────────────────────────
    _logger = _get_logger()
    for turn in range(MAX_TURNS):
        _llm_t0 = time.perf_counter()
        try:
            result = llm_client.chat(session_messages, tools=active_tools)
        except Exception as e:
            _logger.log_exception('llm', 'LLM 调用异常', e)
            yield _error(f"LLM 调用失败：{str(e)}")
            yield _stream_end()
            return
        _llm_ms = (time.perf_counter() - _llm_t0) * 1000
        _logger.log_llm_call('chat', getattr(llm_client, '_model', 'unknown'),
                             result.success, duration_ms=_llm_ms)

        if not result.success:
            _logger.warning('llm', 'LLM 返回失败', {'error': result.error[:200]})
            yield _error(result.error)
            yield _stream_end()
            return

        # 流式输出文本内容
        if result.text:
            yield _text(result.text)

        # 无 tool_calls → 最终回答
        if not result.tool_calls:
            assistant_msg = {"role": "assistant", "content": result.text}
            session_messages.append(assistant_msg)
            yield _stream_end()
            return

        # 有 tool_calls → 添加 assistant 消息（含 tool_calls）
        assistant_msg = {
            "role": "assistant",
            "content": result.text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in result.tool_calls
            ],
        }
        session_messages.append(assistant_msg)

        # 执行每个工具调用
        for tc in result.tool_calls:
            tool_name = tc["name"]
            tool_args = tc["arguments"]
            tool_id = tc["id"]

            # 构建可读标签
            label = _tool_label(tool_name, tool_args)
            yield _tool_start(tool_name, label, tool_id)

            # 执行工具
            _tool_t0 = time.perf_counter()
            if tool_name == "run_sql":
                tool_result = _execute_with_retry(tool_args, tool_ctx, tool_id)
            else:
                tool_result = dispatch_tool(tool_name, tool_args, tool_ctx)
            _tool_ms = (time.perf_counter() - _tool_t0) * 1000
            _logger.log_tool_call(
                tool_name, tool_args,
                ok=tool_result.get("ok", False),
                duration_ms=_tool_ms,
                error=tool_result.get("error", ""),
            )

            # 检查暂停信号
            if tool_result.get("__pause__"):
                pause_type = tool_result["__pause_type__"]
                del tool_result["__pause__"]
                del tool_result["__pause_type__"]

                yield _tool_end(tool_name, True, "等待用户回应", tool_id=tool_id)

                if pause_type == "ask":
                    yield _ask({
                        "question": tool_result.get("question", ""),
                        "options": tool_result.get("options", []),
                    })
                elif pause_type == "confirm":
                    yield _confirm({
                        "title": tool_result.get("title", ""),
                        "summary": tool_result.get("summary", []),
                        "sql_or_formula": tool_result.get("sql_or_formula", ""),
                    })

                # 保存暂停状态到 _session（由 main.py 读取）
                pending_state = {
                    "type": pause_type,
                    "tool_call_id": tool_id,
                }
                if pause_type == "confirm":
                    pending_state["title"] = tool_result.get("title", "")

                yield {"type": "__pending__", "data": pending_state}
                yield _stream_end()
                return

            # 普通结果 → 追加 tool message
            ok = tool_result.get("ok", False)
            summary = _result_summary(tool_name, tool_result)
            sql_display = tool_result.get("sql", "")

            yield _tool_end(tool_name, ok, summary, sql=sql_display, tool_id=tool_id)

            if tool_name == "run_sql" and ok and tool_result.get("columns"):
                yield _table({
                    "title": tool_args.get("purpose", "查询结果"),
                    "columns": tool_result["columns"],
                    "rows": tool_result.get("rows", []),
                    "sql": sql_display,
                })

            if tool_name == "render_chart" and ok and tool_result.get("option"):
                yield _sse_event("chart", {
                    "title": tool_result.get("title", ""),
                    "option": tool_result["option"],
                    "chart_type": tool_result.get("chart_type", ""),
                })

            if tool_name == "generate_report" and ok and tool_result.get("markdown"):
                yield _sse_event("report", {
                    "markdown": tool_result["markdown"],
                    "word_path": tool_result.get("word_path", ""),
                    "word_filename": tool_result.get("word_filename", ""),
                    "report_type": tool_result.get("report_type", ""),
                })

            session_messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "content": json.dumps(tool_result, ensure_ascii=False, default=str),
            })

    # 达到最大轮数
    yield _error(f"已达到最大交互轮数（{MAX_TURNS}），请简化问题或重新描述需求。")
    yield _stream_end()


# ═══════════════════════════════════════════════════════════════
#  SQL 执行 + 自愈重试（run_sql 工具专用）
# ═══════════════════════════════════════════════════════════════

def _execute_with_retry(args: dict, tool_ctx, tool_id: str) -> dict:
    """
    执行 run_sql 工具，失败时尝试自动修正（最多 MAX_TOOL_RETRY 次）。
    仅对 syntax 类型错误自动重试，semantic/empty/anomaly 直接返回。
    """

    sql = args.get("sql", "")
    if not sql.strip():
        return {"ok": False, "error": "SQL 为空"}

    conn = tool_ctx.duckdb_conn

    for retry in range(MAX_TOOL_RETRY + 1):
        result = execute_query(sql, conn)

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

        error_type = categorize_tool_error(result.error)

        if error_type == 'syntax' and retry < MAX_TOOL_RETRY:
            # 尝试让 LLM 修正（作为 tool 消息返回错误，下一轮 chat 会处理）
            return {
                "ok": False,
                "error": result.error,
                "error_type": "syntax",
                "retry_hint": (
                    f"SQL 语法错误（第{retry + 1}次尝试）。"
                    f"请检查：1) 表名/列名是否与 schema 中完全一致 "
                    f"2) 中文列名是否用双引号包裹 3) 是否漏了 LIMIT"
                ),
                "sql": sql,
            }
        elif error_type == 'semantic' and retry < MAX_TOOL_RETRY:
            return {
                "ok": False,
                "error": result.error,
                "error_type": "semantic",
                "retry_hint": "列名或表名不存在，请检查 schema 并修正。",
                "sql": sql,
            }
        else:
            return {"ok": False, "error": result.error, "error_type": error_type, "sql": sql}

    return {"ok": False, "error": f"SQL 修正失败（已重试 {MAX_TOOL_RETRY} 次）", "sql": sql}


# ═══════════════════════════════════════════════════════════════
#  Prompt 构建
# ═══════════════════════════════════════════════════════════════

def _build_system_prompt(schema_ctx: str, skills_desc: str) -> str:
    """构建 system prompt（加载 prompts/system_prompt.txt 模板并填充）"""
    from pathlib import Path
    template_path = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.txt"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        template = "你是 DataAgent，一个专业的金融资管数据分析助手。"

    tables = get_loaded_tables()
    if tables:
        table_summary = "\n".join(
            f"- {t['name']}（{t['rows']}行 × {t['cols']}列，类型：{t['type']}）"
            for t in tables
        )
    else:
        table_summary = "（暂无已加载数据表）"

    return (
        template
        .replace("{loaded_tables_summary}", table_summary)
        .replace("{skills_registry}", skills_desc)
    )


def _build_skills_registry_text(registry) -> str:
    """将 Skill 注册表格式化为 prompt 文本"""
    if not registry:
        return "（暂无可用技能）"
    lines = []
    for s in registry:
        desc_short = s.description.split('\n')[0][:80]
        calc_label = "[固化计算]" if s.calc_type == 'fixed' else "[探索式]"
        lines.append(f"- **{s.name}** {calc_label}: {desc_short}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════

def _tool_label(tool_name: str, args: dict) -> str:
    """为工具调用生成用户可读的标签"""
    if tool_name == "profile_table":
        return f"分析表结构：{args.get('table_name', '?')}"
    elif tool_name == "run_sql":
        purpose = args.get("purpose", "")
        return f"执行查询：{purpose}" if purpose else "执行 SQL 查询"
    elif tool_name == "run_calculator":
        calc_names = {
            "entity_concentration": "主体集中度",
            "nav_metrics": "净值指标",
            "asset_structure": "资产结构",
            "credit_distribution": "评级分布",
        }
        cn = calc_names.get(args.get("calculator", ""), args.get("calculator", ""))
        return f"固化计算：{cn}"
    elif tool_name == "ask_user":
        q = args.get("question", "")
        return f"询问：{q[:40]}..."
    elif tool_name == "request_confirmation":
        return f"请求确认：{args.get('title', '')}"
    return tool_name


def _result_summary(tool_name: str, result: dict) -> str:
    """为工具执行结果生成简短摘要"""
    if not result.get("ok"):
        return result.get("error", "执行失败")[:80]
    if tool_name == "profile_table":
        return f"{result.get('row_count', 0)}行，{len(result.get('columns', []))}列"
    elif tool_name == "run_sql":
        return f"返回 {result.get('row_count', 0)} 行"
    elif tool_name == "run_calculator":
        calc = result.get("calculator", "")
        if calc == "entity_concentration":
            return f"{result.get('breach_count', 0)} 项超标"
        return f"计算完成，{result.get('count', 0)} 条记录"
    return "OK"


def _filter_tools_for_context(tools: list, matched_skill) -> list:
    """
    场景化工具过滤（ETCLOVG T 层）：
    当匹配到 calc_type=fixed 的 Skill 时，从工具列表中移除 run_sql，
    防止 LLM 在合规场景下绕过固化计算器直接生成 SQL。
    """
    if matched_skill and getattr(matched_skill, 'calc_type', '') == "fixed":
        return [t for t in tools if t["function"]["name"] != "run_sql"]
    return tools
