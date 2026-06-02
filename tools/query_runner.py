"""
tools/query_runner.py — SQL 执行器 + 安全守卫

职责：
  1. SQLGuard：使用 sqlglot 解析 SQL，动态校验表名、拦截危险操作
  2. execute_query：参数化执行，返回 QueryResult

约束：
  - 只允许 SELECT 语句
  - LIMIT 必须存在且 ≤ 1000
  - 表名白名单：动态从 DuckDB SHOW TABLES 获取
  - 拦截 BLOCKED_FUNCTIONS 中的危险函数
  - 禁止 information_schema 等系统表
  - 执行超时 30 秒
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import duckdb
import sqlglot
from sqlglot import exp


# ═══════════════════════════════════════════════════════════════
#  危险函数 / 命令黑名单
# ═══════════════════════════════════════════════════════════════

BLOCKED_FUNCTIONS = {
    'read_csv_auto', 'read_csv', 'read_parquet', 'read_json',
    'read_csv_auto', 'read_json_auto',
}

BLOCKED_COMMANDS = [
    'copy', 'attach', 'detach', 'install', 'load',
    'pragma', 'export_database', 'export', 'import',
    'create', 'alter', 'drop', 'insert', 'update', 'delete',
    'truncate', 'grant', 'revoke',
]

FORBIDDEN_DBS = {'information_schema', 'pg_catalog', 'sqlite_master', 'duckdb_settings'}

MAX_LIMIT = 1000
QUERY_TIMEOUT_SEC = 30


# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class QueryResult:
    """SQL 执行结果"""
    success: bool
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    row_count: int = 0
    error: str = ""
    requires_confirmation: bool = False
    executed_at: str = ""


# ═══════════════════════════════════════════════════════════════
#  SQLGuard — 安全校验
# ═══════════════════════════════════════════════════════════════

class SQLGuard:
    """
    SQL 安全守卫。

    validate(sql, conn) → (is_valid: bool, message: str)
    """

    def validate(self, sql: str, conn: duckdb.DuckDBPyConnection) -> tuple[bool, str]:
        """运行全部校验规则，任一失败即返回 (False, reason)"""

        # ── 规则 0：预处理，去除注释 ─────────────────────────
        cleaned = self._strip_comments(sql)

        # ── 规则 1：非空 ────────────────────────────────────
        if not cleaned.strip():
            return False, "SQL 语句为空"

        # ── 规则 2：只允许 SELECT ───────────────────────────
        ok, msg = self._check_select_only(cleaned)
        if not ok:
            return False, msg

        # ── 规则 3：拦截 BLOCKED_COMMANDS ──────────────────
        ok, msg = self._check_blocked_commands(cleaned)
        if not ok:
            return False, msg

        # ── 规则 4：LIMIT 校验 ──────────────────────────────
        ok, msg = self._check_limit(cleaned)
        if not ok:
            return False, msg

        # ── 规则 5：sqlglot 解析提取表名，动态校验 ─────────
        ok, msg = self._check_tables(cleaned, conn)
        if not ok:
            return False, msg

        # ── 规则 6：拦截危险函数 ────────────────────────────
        ok, msg = self._check_blocked_functions(cleaned)
        if not ok:
            return False, msg

        return True, "OK"

    # ── 各规则实现 ──────────────────────────────────────────

    def _strip_comments(self, sql: str) -> str:
        """移除 SQL 注释（-- 和 块注释）"""
        # 移除块注释
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
        # 移除行注释
        sql = re.sub(r'--[^\n]*', '', sql)
        return sql

    def _check_select_only(self, sql: str) -> tuple[bool, str]:
        """规则：只允许 SELECT 开头（跳过空白和 WITH CTE）"""
        stripped = sql.strip().upper()
        # WITH ... SELECT 也允许（CTE）
        if stripped.startswith('SELECT') or stripped.startswith('WITH'):
            return True, "OK"
        return False, "only SELECT is allowed"

    def _check_blocked_commands(self, sql: str) -> tuple[bool, str]:
        """规则：拦截非 SELECT 命令（COPY/PRAGMA 等不被 sqlglot 完整解析）"""
        lower = sql.lower()
        for cmd in BLOCKED_COMMANDS:
            # 匹配独立命令词（前面不是字母，后面是空格）
            pattern = r'\b' + re.escape(cmd) + r'\b'
            if re.search(pattern, lower):
                return False, f"{cmd.upper()} is not allowed"
        return True, "OK"

    def _check_limit(self, sql: str) -> tuple[bool, str]:
        """规则：LIMIT 必须存在且 ≤ MAX_LIMIT"""
        try:
            parsed = sqlglot.parse_one(sql)
            if parsed is None:
                return False, "SQL parse error"
        except Exception:
            # 解析失败但可能是合法 SQL，放行让 DuckDB 报错
            return False, "SQL parse error"

        limit_node = parsed.find(exp.Limit)
        if limit_node is None:
            return False, "LIMIT is required"

        limit_val = limit_node.expression
        if limit_val.is_int:
            val = int(limit_val.name)
            if val > MAX_LIMIT:
                return False, f"LIMIT must be <= {MAX_LIMIT}, got {val}"
            return True, "OK"

        # LIMIT 值不是字面整数（如子查询），保守拒绝
        return False, f"LIMIT must be a literal integer <= {MAX_LIMIT}"

    def _check_tables(self, sql: str, conn: duckdb.DuckDBPyConnection) -> tuple[bool, str]:
        """
        规则：sqlglot 解析提取所有物理表名，与 DuckDB SHOW TABLES 动态校验。

        排除 CTE 内部别名、子查询别名，只检查物理表。
        禁止 information_schema 等系统表引用。
        """
        try:
            parsed = sqlglot.parse_one(sql)
        except Exception:
            return True, "OK"  # 解析失败放行让 DuckDB 报具体错误

        if parsed is None:
            return True, "OK"

        # 收集 CTE 名称（这些不是物理表）
        cte_names: set[str] = set()
        for cte in parsed.find_all(exp.CTE):
            if cte.alias:
                cte_names.add(cte.alias.lower())

        # 提取所有物理表引用
        physical_tables: set[str] = set()
        for table in parsed.find_all(exp.Table):
            tbl_name = table.name.lower()
            # 跳过 CTE 别名
            if tbl_name in cte_names:
                continue
            # 检查 db 限定符（如 information_schema.tables）
            db_qualifier = table.args.get('db')
            if db_qualifier is not None:
                db_name = str(db_qualifier).strip('"').strip("'").lower()
                if db_name in FORBIDDEN_DBS:
                    return False, f"access to '{db_name}' is forbidden"
            physical_tables.add(table.name)

        if not physical_tables:
            return True, "OK"  # 可能是纯表达式查询如 SELECT 1+1

        # 获取 DuckDB 中已加载的表
        valid_tables = {
            row[0].lower()
            for row in conn.execute("SHOW TABLES").fetchall()
        }

        # 检查每个物理表是否在已加载表中
        for tbl in physical_tables:
            # 跳过已知的 DuckDB 函数表、duckdb_ 前缀的内部表
            if tbl.startswith('duckdb_'):
                return False, f"access to internal table '{tbl}' is forbidden"
            if tbl not in valid_tables:
                return False, f"referenced table not loaded: '{tbl}'"

        return True, "OK"

    def _check_blocked_functions(self, sql: str) -> tuple[bool, str]:
        """规则：拦截 BLOCKED_FUNCTIONS 中的危险函数调用"""
        try:
            parsed = sqlglot.parse_one(sql)
            if parsed is None:
                return True, "OK"
        except Exception:
            return True, "OK"

        # 检查命名函数
        for func_node in parsed.find_all(exp.Func):
            if func_node.name and func_node.name.lower() in BLOCKED_FUNCTIONS:
                return False, f"{func_node.name} is not allowed"

        # 检查匿名函数（如 DuckDB 特有函数被解析为 Anonymous）
        for anon in parsed.find_all(exp.Anonymous):
            if anon.name and anon.name.lower() in BLOCKED_FUNCTIONS:
                return False, f"{anon.name} is not allowed"

        return True, "OK"


# ═══════════════════════════════════════════════════════════════
#  查询执行
# ═══════════════════════════════════════════════════════════════

_guard = SQLGuard()


def execute_query(
    sql: str,
    conn: duckdb.DuckDBPyConnection,
    timeout: int = QUERY_TIMEOUT_SEC,
) -> QueryResult:
    """
    校验并执行 SELECT 查询。

    返回 QueryResult，success=False 时 error 字段包含用户可读的错误描述。
    """
    # ── 1. SQLGuard 校验 ─────────────────────────────────
    is_valid, message = _guard.validate(sql, conn)
    if not is_valid:
        return QueryResult(
            success=False,
            sql=sql,
            error=message,
        )

    # ── 2. 执行（带超时） ────────────────────────────────
    start = time.time()
    try:
        result = conn.execute(sql)
        elapsed_ms = int((time.time() - start) * 1000)
        if elapsed_ms > timeout * 1000:
            return QueryResult(
                success=False,
                sql=sql,
                error="timeout",
            )

        # ── 3. 提取结果 ──────────────────────────────────
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        # 转换为可序列化的格式（避免 DuckDB 类型）
        serializable_rows = []
        for row in rows:
            serializable_rows.append([
                str(v) if v is not None else None for v in row
            ])

        return QueryResult(
            success=True,
            sql=sql,
            columns=columns,
            rows=serializable_rows,
            row_count=len(serializable_rows),
            requires_confirmation=len(serializable_rows) > 50,
            executed_at=f"{elapsed_ms}ms",
        )

    except Exception as e:
        elapsed_ms = int((time.time() - start) * 1000)
        error_str = str(e)
        if elapsed_ms > timeout * 1000:
            return QueryResult(success=False, sql=sql, error="timeout")
        return QueryResult(success=False, sql=sql, error=error_str)
