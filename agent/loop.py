"""
agent/loop.py — Agent 核心循环（Phase 1 最简版）

职责：
  1. 接收用户消息，编排完整的 Agent 对话流程
  2. 构建上下文 → 意图识别 → SQL 生成 → 执行 → 结果返回
  3. 错误分类自愈：syntax 自动重试，semantic/empty/anomaly 浮现给用户
  4. 以 Generator 方式产出 SSE 事件（供 Flask 路由流式输出）

Phase 1 限制：
  - 只支持 run_sql 工具（探索式查询）
  - 固化计算（calculators）识别但不执行（Phase 3 完整实现）
  - 人工确认节点暂不实现（Phase 2 加）
  - 意图识别用关键词匹配（Phase 4 改 LLM 分类）
"""

from typing import Generator

from tools.data_loader import get_connection, get_loaded_tables
from tools.query_runner import execute_query, QueryResult
from tools.error_translator import translate as translate_error
from agent.llm_client import LLMClient
from agent.skill_loader import SkillLoader
from agent.context import build_schema_context


# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

MAX_TURNS = 15
MAX_TOOL_RETRY = 3


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


def _tool_start(tool_name: str, label: str = "") -> dict:
    return _sse_event("tool_start", {"tool": tool_name, "label": label or tool_name})


def _tool_end(success: bool, summary: str = "", sql: str = "") -> dict:
    return _sse_event("tool_end", {"success": success, "summary": summary, "sql": sql})


def _stream_end() -> dict:
    return _sse_event("stream_end", None)


# ═══════════════════════════════════════════════════════════════
#  错误分类
# ═══════════════════════════════════════════════════════════════

def categorize_tool_error(error_msg: str) -> str:
    """
    区分错误类型（P1-5）：
      'syntax'   → SQL 语法错误，可自动重试
      'semantic' → 字段/表名/语义错误，浮现给用户确认
      'empty'    → 结果为空，询问用户
      'anomaly'  → 结果异常，强制人工介入
    """
    msg = error_msg.lower()

    for p in ['syntax error', 'parse error', 'parser error',
              'unexpected token', 'unexpected character',
              'catalog error']:
        if p in msg:
            return 'syntax'

    # DuckDB Binder Error 通常是语义错误（列/表不存在），只有明确语法问题时重试
    if 'binder error' in msg:
        if any(k in msg for k in ['column', 'table', 'does not exist', 'no such']):
            return 'semantic'
        return 'syntax'  # 其他 binder 错误归为语法

    for p in ['no rows', 'empty result', '0 rows']:
        if p in msg:
            return 'empty'

    for p in ['no such column', 'column', 'no such table',
              'not loaded', 'referenced table', 'not found']:
        if p in msg:
            return 'semantic'

    return 'anomaly'


# ═══════════════════════════════════════════════════════════════
#  Agent 核心循环
# ═══════════════════════════════════════════════════════════════

def run_agent_loop(
    user_message: str,
    llm_client: LLMClient,
    skill_loader: SkillLoader,
    turn_count: int = 0,
) -> Generator[dict, None, None]:
    """
    Agent 主循环（Phase 1 最简版）。

    Yields SSE 事件字典，Flask 路由逐条推送给前端。
    """
    if turn_count >= MAX_TURNS:
        yield _error("对话轮数已达上限，请开启新对话继续。")
        yield _stream_end()
        return

    tables = get_loaded_tables()
    if not tables:
        yield _text("请先上传数据文件（CSV/Excel），然后我就可以帮你分析了。")
        yield _stream_end()
        return

    # ── 1. 构建上下文 ───────────────────────────────────────
    schema_ctx = build_schema_context()

    # ── 2. 意图识别 ─────────────────────────────────────────
    registry = skill_loader.load_registry()
    skill_name = skill_loader.detect_relevant_skill(user_message, registry)

    if skill_name:
        skill_info = next((s for s in registry if s.name == skill_name), None)
        if skill_info:
            desc_short = skill_info.description.split('\n')[0][:60]
            yield _text(f"🔍 检测到意图：{desc_short}...\n\n")
            if skill_info.calc_type == 'fixed':
                yield _text(
                    f"⚠️「{skill_info.name}」属于合规/报告类操作，使用固化计算。\n"
                    f"（固化计算执行功能在 Phase 3 实现）"
                )
                yield _stream_end()
                return

    # ── 3. SQL 生成 + 执行循环（含自愈重试）───────────────
    yield _tool_start("run_sql", "生成 SQL 查询")

    last_error = ""
    sql_text = ""

    for retry in range(MAX_TOOL_RETRY + 1):
        if retry == 0:
            prompt = _build_sql_prompt(user_message, schema_ctx)
        else:
            prompt = _build_retry_prompt(user_message, schema_ctx, last_error)

        sql_text, llm_resp = llm_client.generate_sql(prompt, schema_context="")

        if not llm_resp.success or not sql_text:
            yield _tool_end(False, f"SQL 生成失败：{translate_error(llm_resp.error)}")
            yield _error(llm_resp.error)
            yield _stream_end()
            return

        yield _text(f"\n```sql\n{sql_text}\n```\n\n")

        conn = get_connection()
        result: QueryResult = execute_query(sql_text, conn)

        if result.success:
            yield _tool_end(True, f"查询完成，返回 {result.row_count} 行", sql=sql_text)

            if result.row_count == 0:
                yield _text("查询结果为空。请检查筛选条件是否正确，或确认数据表中存在符合条件的记录。")

            yield _table({
                "title": "查询结果",
                "columns": result.columns,
                "rows": result.rows,
                "sql": sql_text,
            })
            yield _stream_end()
            return

        # 失败 → 分类处理
        error_type = categorize_tool_error(result.error)

        if error_type == 'syntax' and retry < MAX_TOOL_RETRY:
            last_error = result.error
            yield _text(f"（SQL 语法有误，正在自动修正... 第 {retry + 1}/{MAX_TOOL_RETRY} 次重试）\n")
            continue

        elif error_type == 'semantic' and retry < MAX_TOOL_RETRY:
            # 语义错误（如列名不存在），让 LLM 修正后重试
            last_error = result.error
            yield _text(f"（列名或表名有误，正在根据反馈修正... 第 {retry + 1}/{MAX_TOOL_RETRY} 次重试）\n")
            continue

        elif error_type == 'empty':
            yield _tool_end(True, "查询结果为空", sql=sql_text)
            yield _text("查询结果为空，可能筛选条件过严或数据表中暂无匹配数据。建议调整查询条件后重试。")
            yield _stream_end()
            return

        else:
            yield _tool_end(False, f"结果异常，需要人工确认：{translate_error(result.error)}", sql=sql_text)
            yield _error(result.error)
            yield _stream_end()
            return

    yield _tool_end(False, f"经过 {MAX_TOOL_RETRY} 次重试后仍失败", sql=sql_text)
    yield _error(f"SQL 语法修正失败，已达最大重试次数。请重新描述你的需求。")
    yield _stream_end()


# ═══════════════════════════════════════════════════════════════
#  Prompt 构建
# ═══════════════════════════════════════════════════════════════

def _build_sql_prompt(user_message: str, schema_ctx: str) -> str:
    return (
        f"{schema_ctx}\n\n"
        f"用户问题：{user_message}\n\n"
        f"★ 严格规则：\n"
        f"1. SELECT 和 WHERE 中的列名必须使用上面「语义字段映射」中列出的「实际列名」，不得自己编造\n"
        f"2. 列名用双引号包裹\n"
        f"3. 必须在末尾加上 LIMIT，不超过 100\n"
        f"4. 只返回 SQL，不要有任何解释文字"
    )


def _build_retry_prompt(user_message: str, schema_ctx: str, last_error: str) -> str:
    return (
        f"{schema_ctx}\n\n"
        f"用户问题：{user_message}\n\n"
        f"上次 SQL 执行报错：{last_error}\n"
        f"请根据错误信息修正 SQL。记住：\n"
        f"1. 列名必须严格使用上面的「实际列名」，不能自己编造或简化\n"
        f"2. 列名用双引号包裹\n"
        f"3. 末尾加 LIMIT 100\n"
        f"4. 只返回 SQL"
    )
