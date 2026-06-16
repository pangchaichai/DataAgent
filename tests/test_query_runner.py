"""
tests/test_query_runner.py -- SQLGuard + execute_query + apply_field_map

This is the SQL security boundary. Every blocked pattern must have a test
so regressions are caught before they reach production.
"""

import duckdb
import pytest

from tools.query_runner import (
    BLOCKED_COMMANDS,
    BLOCKED_FUNCTIONS,
    MAX_LIMIT,
    QueryResult,
    SQLGuard,
    apply_field_map,
    execute_query,
)


# ================================================================
#  Fixtures
# ================================================================

@pytest.fixture
def guard():
    return SQLGuard()


@pytest.fixture
def conn():
    """In-memory DuckDB with a sample table for validation."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE test_holding (id INT, name VARCHAR, value DOUBLE)")
    c.execute("INSERT INTO test_holding VALUES (1, 'bond_a', 100.5)")
    c.execute("INSERT INTO test_holding VALUES (2, 'bond_b', 200.0)")
    c.execute("INSERT INTO test_holding VALUES (3, 'bond_c', 300.75)")
    yield c
    c.close()


@pytest.fixture
def multi_table_conn():
    """DuckDB connection with two tables for JOIN tests."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE holding (id INT, entity VARCHAR, mv DOUBLE)")
    c.execute("INSERT INTO holding VALUES (1, 'A Corp', 1000.0)")
    c.execute("CREATE TABLE rating (entity VARCHAR, grade VARCHAR)")
    c.execute("INSERT INTO rating VALUES ('A Corp', 'AAA')")
    yield c
    c.close()


# ================================================================
#  SQLGuard.validate -- reject dangerous statements
# ================================================================

class TestSQLGuardRejectDDL:
    """DML / DDL statements must be rejected.

    These are caught by _check_select_only (rule 2) because they don't
    start with SELECT/WITH. The error message is 'only SELECT is allowed'.
    """

    def test_reject_drop_table(self, guard, conn):
        ok, msg = guard.validate("DROP TABLE test_holding", conn)
        assert not ok
        assert "SELECT" in msg.upper()  # "only SELECT is allowed"

    def test_reject_delete_from(self, guard, conn):
        ok, msg = guard.validate("DELETE FROM test_holding WHERE id = 1", conn)
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_insert_into(self, guard, conn):
        ok, msg = guard.validate(
            "INSERT INTO test_holding VALUES (4, 'x', 0)", conn
        )
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_update_set(self, guard, conn):
        ok, msg = guard.validate(
            "UPDATE test_holding SET value = 0 WHERE id = 1", conn
        )
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_create_table(self, guard, conn):
        ok, msg = guard.validate("CREATE TABLE evil (x INT)", conn)
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_truncate(self, guard, conn):
        ok, msg = guard.validate("TRUNCATE TABLE test_holding", conn)
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_alter_table(self, guard, conn):
        ok, msg = guard.validate(
            "ALTER TABLE test_holding ADD COLUMN extra INT", conn
        )
        assert not ok
        assert "SELECT" in msg.upper()

    def test_reject_grant(self, guard, conn):
        ok, msg = guard.validate("GRANT ALL ON test_holding TO public", conn)
        assert not ok
        assert "SELECT" in msg.upper()


class TestSQLGuardRejectDangerousFunctions:
    """DuckDB file-access functions must be blocked."""

    def test_reject_read_csv_auto(self, guard, conn):
        sql = "SELECT * FROM read_csv_auto('/etc/passwd') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        # May be caught by table-check (empty table name) or function-check
        assert "not loaded" in msg.lower() or "read_csv_auto" in msg.lower()

    def test_reject_read_csv(self, guard, conn):
        sql = "SELECT * FROM read_csv('/tmp/data.csv') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok

    def test_reject_read_parquet(self, guard, conn):
        sql = "SELECT * FROM read_parquet('data.parquet') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        # May be caught by table-check or function-check depending on parse
        assert "not loaded" in msg.lower() or "read_parquet" in msg.lower()

    def test_reject_read_json(self, guard, conn):
        sql = "SELECT * FROM read_json('data.json') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok

    def test_reject_read_json_auto(self, guard, conn):
        sql = "SELECT * FROM read_json_auto('data.json') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok


class TestSQLGuardRejectCommands:
    """DuckDB-specific commands (COPY, ATTACH, etc.) must be blocked.

    Standalone commands are caught by _check_select_only first. We verify
    they're also caught by _check_blocked_commands when embedded inside
    a SELECT (e.g. in a subquery context or via word-boundary matching).
    """

    def test_reject_attach(self, guard, conn):
        ok, msg = guard.validate("ATTACH ':memory:' AS evil", conn)
        assert not ok  # caught by select-only check

    def test_reject_install(self, guard, conn):
        ok, msg = guard.validate("INSTALL httpfs", conn)
        assert not ok

    def test_reject_load(self, guard, conn):
        ok, msg = guard.validate("LOAD httpfs", conn)
        assert not ok

    def test_reject_copy(self, guard, conn):
        ok, msg = guard.validate(
            "COPY test_holding TO '/tmp/out.csv'", conn
        )
        assert not ok

    def test_reject_pragma(self, guard, conn):
        ok, msg = guard.validate("PRAGMA database_list", conn)
        assert not ok

    def test_reject_export_database(self, guard, conn):
        ok, msg = guard.validate("EXPORT DATABASE '/tmp/dump'", conn)
        assert not ok

    def test_blocked_commands_in_select_context(self, guard, conn):
        """Commands embedded in a SELECT-like wrapper are caught by
        _check_blocked_commands via word-boundary regex."""
        # 'copy' as a word inside a SELECT statement
        sql = "SELECT copy FROM test_holding LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        assert "COPY" in msg.upper()


class TestSQLGuardRejectSystemTables:
    """Access to information_schema and similar catalogs is forbidden."""

    def test_reject_information_schema_tables(self, guard, conn):
        sql = "SELECT * FROM information_schema.tables LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        assert "information_schema" in msg.lower()

    def test_reject_information_schema_columns(self, guard, conn):
        sql = "SELECT * FROM information_schema.columns LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok

    def test_reject_pg_catalog(self, guard, conn):
        sql = "SELECT * FROM pg_catalog.pg_tables LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        assert "pg_catalog" in msg.lower()

    def test_reject_duckdb_internal_tables(self, guard, conn):
        sql = "SELECT * FROM duckdb_tables LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        assert "duckdb_" in msg.lower()


# ================================================================
#  SQLGuard.validate -- LIMIT enforcement
# ================================================================

class TestSQLGuardLimit:
    """LIMIT must be present and <= MAX_LIMIT (1000)."""

    def test_reject_select_without_limit(self, guard, conn):
        ok, msg = guard.validate("SELECT * FROM test_holding", conn)
        assert not ok
        assert "LIMIT" in msg.upper()

    def test_reject_limit_exceeding_max(self, guard, conn):
        sql = f"SELECT * FROM test_holding LIMIT {MAX_LIMIT + 1}"
        ok, msg = guard.validate(sql, conn)
        assert not ok
        assert str(MAX_LIMIT) in msg

    def test_accept_limit_at_max(self, guard, conn):
        sql = f"SELECT * FROM test_holding LIMIT {MAX_LIMIT}"
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_accept_limit_small(self, guard, conn):
        ok, msg = guard.validate("SELECT * FROM test_holding LIMIT 10", conn)
        assert ok
        assert msg == "OK"

    def test_accept_limit_one(self, guard, conn):
        ok, msg = guard.validate("SELECT * FROM test_holding LIMIT 1", conn)
        assert ok


# ================================================================
#  SQLGuard.validate -- valid queries accepted
# ================================================================

class TestSQLGuardAcceptValid:
    """Legitimate queries should pass validation."""

    def test_simple_select_with_limit(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT id, name FROM test_holding LIMIT 50", conn
        )
        assert ok
        assert msg == "OK"

    def test_select_with_where(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT * FROM test_holding WHERE value > 100 LIMIT 10", conn
        )
        assert ok

    def test_select_with_aggregation(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT name, SUM(value) FROM test_holding GROUP BY name LIMIT 10",
            conn,
        )
        assert ok

    def test_select_with_order_by(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT * FROM test_holding ORDER BY value DESC LIMIT 10", conn
        )
        assert ok

    def test_cte_with_limit(self, guard, conn):
        sql = """
        WITH ranked AS (
            SELECT id, name, value,
                   ROW_NUMBER() OVER (ORDER BY value DESC) AS rn
            FROM test_holding
        )
        SELECT * FROM ranked WHERE rn <= 5 LIMIT 100
        """
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_cte_name_not_treated_as_physical_table(self, guard, conn):
        """CTE alias 'tmp' should not be checked against loaded tables."""
        sql = """
        WITH tmp AS (
            SELECT * FROM test_holding
        )
        SELECT * FROM tmp LIMIT 10
        """
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_select_with_join(self, guard, multi_table_conn):
        sql = """
        SELECT h.entity, r.grade, h.mv
        FROM holding h
        JOIN rating r ON h.entity = r.entity
        LIMIT 50
        """
        ok, msg = guard.validate(sql, multi_table_conn)
        assert ok

    def test_select_with_left_join(self, guard, multi_table_conn):
        sql = """
        SELECT h.entity, r.grade
        FROM holding h
        LEFT JOIN rating r ON h.entity = r.entity
        LIMIT 100
        """
        ok, msg = guard.validate(sql, multi_table_conn)
        assert ok

    def test_subquery(self, guard, conn):
        sql = """
        SELECT * FROM (
            SELECT id, value FROM test_holding WHERE value > 100
        ) sub
        LIMIT 10
        """
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_select_count(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT COUNT(*) FROM test_holding LIMIT 1", conn
        )
        assert ok


# ================================================================
#  SQLGuard.validate -- table existence check
# ================================================================

class TestSQLGuardTableCheck:
    """References to nonexistent tables must be rejected."""

    def test_reject_unknown_table(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT * FROM nonexistent_table LIMIT 10", conn
        )
        assert not ok
        assert "not loaded" in msg.lower() or "nonexistent_table" in msg.lower()

    def test_reject_unknown_table_in_join(self, guard, conn):
        ok, msg = guard.validate(
            "SELECT * FROM test_holding h JOIN ghost g ON h.id = g.id LIMIT 10",
            conn,
        )
        assert not ok
        assert "ghost" in msg.lower()


# ================================================================
#  SQLGuard.validate -- comment stripping
# ================================================================

class TestSQLGuardComments:
    """SQL comments should be stripped before validation."""

    def test_line_comment_stripped(self, guard, conn):
        sql = "-- just a comment\nSELECT * FROM test_holding LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_block_comment_stripped(self, guard, conn):
        sql = "/* block */ SELECT * FROM test_holding LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert ok

    def test_empty_after_comments(self, guard, conn):
        ok, msg = guard.validate("-- only a comment\n", conn)
        assert not ok
        assert "empty" in msg.lower() or "SQL" in msg


# ================================================================
#  SQLGuard.validate -- edge cases
# ================================================================

class TestSQLGuardEdgeCases:
    """Edge cases and bypass attempts."""

    def test_empty_sql(self, guard, conn):
        ok, msg = guard.validate("", conn)
        assert not ok

    def test_whitespace_only(self, guard, conn):
        ok, msg = guard.validate("   \n\t  ", conn)
        assert not ok

    def test_blocked_keyword_inside_string_literal(self, guard, conn):
        """'drop' inside a WHERE string should still be caught by word-boundary
        regex because the regex operates on the raw SQL text. This is
        conservative -- better to over-block than under-block."""
        sql = "SELECT * FROM test_holding WHERE name = 'drop' LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        # The regex \bdrop\b matches the word even inside a string literal.
        # This is the expected conservative behavior.
        assert not ok

    def test_case_insensitive_command_blocking(self, guard, conn):
        ok, msg = guard.validate("DROP TABLE test_holding", conn)
        assert not ok
        ok2, msg2 = guard.validate("drop table test_holding", conn)
        assert not ok2


# ================================================================
#  apply_field_map
# ================================================================

class TestApplyFieldMap:
    """Field-map substitution for semantic -> physical column names."""

    def test_basic_substitution(self):
        sql = "SELECT name FROM test_holding LIMIT 10"
        mapped = apply_field_map(sql, {"name": "real_name"})
        assert '"real_name"' in mapped
        assert "name" not in mapped.split('"real_name"')[0].split("SELECT")[1]

    def test_empty_field_map_no_change(self):
        sql = "SELECT id, name FROM t LIMIT 10"
        result = apply_field_map(sql, {})
        # With an empty map the SQL should remain functionally equivalent
        assert "id" in result
        assert "name" in result

    def test_none_field_map_no_change(self):
        sql = "SELECT id FROM t LIMIT 10"
        result = apply_field_map(sql, None)
        assert "id" in result

    def test_literal_string_not_substituted(self):
        """String literals like 'name' should not be replaced."""
        sql = "SELECT * FROM t WHERE col = 'name' LIMIT 10"
        result = apply_field_map(sql, {"name": "replaced"})
        # The string literal 'name' should stay, only column refs change
        assert "'name'" in result or "'replaced'" not in result

    def test_multiple_columns_mapped(self):
        sql = "SELECT foo, bar FROM t LIMIT 10"
        result = apply_field_map(sql, {"foo": "col_a", "bar": "col_b"})
        assert '"col_a"' in result
        assert '"col_b"' in result

    def test_chinese_column_names(self):
        """Chinese semantic names should map correctly."""
        sql = "SELECT name FROM t LIMIT 10"
        result = apply_field_map(sql, {"name": "asset_code"})
        assert '"asset_code"' in result

    def test_unmapped_columns_unchanged(self):
        sql = "SELECT id, name FROM t LIMIT 10"
        result = apply_field_map(sql, {"name": "real_name"})
        # 'id' is not in the map, so it should remain
        assert "id" in result

    def test_invalid_sql_returns_original(self):
        bad_sql = "NOT VALID SQL {{{{"
        result = apply_field_map(bad_sql, {"x": "y"})
        assert result == bad_sql


# ================================================================
#  execute_query
# ================================================================

class TestExecuteQuery:
    """Integration tests: guard + actual DuckDB execution."""

    def test_valid_query_returns_results(self, conn):
        result = execute_query(
            "SELECT id, name, value FROM test_holding LIMIT 10", conn
        )
        assert isinstance(result, QueryResult)
        assert result.success is True
        assert result.row_count == 3
        assert result.columns == ["id", "name", "value"]
        assert len(result.rows) == 3
        assert result.error == ""

    def test_result_rows_are_serializable(self, conn):
        result = execute_query(
            "SELECT id, value FROM test_holding LIMIT 10", conn
        )
        assert result.success
        for row in result.rows:
            for cell in row:
                assert cell is None or isinstance(cell, str)

    def test_invalid_table_returns_error(self, conn):
        result = execute_query(
            "SELECT * FROM nonexistent LIMIT 10", conn
        )
        assert result.success is False
        assert result.error != ""

    def test_blocked_statement_returns_error(self, conn):
        result = execute_query("DROP TABLE test_holding", conn)
        assert result.success is False
        assert "SELECT" in result.error.upper()  # "only SELECT is allowed"

    def test_missing_limit_returns_error(self, conn):
        result = execute_query("SELECT * FROM test_holding", conn)
        assert result.success is False
        assert "LIMIT" in result.error.upper()

    def test_sql_with_syntax_error(self, conn):
        result = execute_query(
            "SELECTTTT * FROM test_holding LIMIT 10", conn
        )
        assert result.success is False

    def test_empty_result_set(self, conn):
        result = execute_query(
            "SELECT * FROM test_holding WHERE id > 9999 LIMIT 10", conn
        )
        assert result.success is True
        assert result.row_count == 0
        assert result.rows == []

    def test_requires_confirmation_for_large_results(self, conn):
        """When > 50 rows, requires_confirmation should be True."""
        # Insert enough rows to exceed the 50-row threshold
        for i in range(100):
            conn.execute(
                f"INSERT INTO test_holding VALUES ({i + 100}, 'item_{i}', {i * 1.5})"
            )
        result = execute_query(
            "SELECT * FROM test_holding LIMIT 200", conn
        )
        assert result.success is True
        assert result.row_count > 50
        assert result.requires_confirmation is True

    def test_small_result_no_confirmation(self, conn):
        result = execute_query(
            "SELECT * FROM test_holding LIMIT 10", conn
        )
        assert result.success is True
        assert result.requires_confirmation is False

    def test_executed_at_contains_ms(self, conn):
        result = execute_query(
            "SELECT * FROM test_holding LIMIT 10", conn
        )
        assert result.success is True
        assert result.executed_at.endswith("ms")

    def test_aggregation_query(self, conn):
        result = execute_query(
            "SELECT COUNT(*) AS cnt, SUM(value) AS total FROM test_holding LIMIT 1",
            conn,
        )
        assert result.success is True
        assert result.columns == ["cnt", "total"]
        assert result.row_count == 1


# ================================================================
#  Comprehensive blocked-commands coverage
# ================================================================

class TestAllBlockedCommands:
    """Ensure every entry in BLOCKED_COMMANDS is actually caught."""

    @pytest.mark.parametrize("cmd", BLOCKED_COMMANDS)
    def test_blocked_command(self, guard, conn, cmd):
        # Build a minimal SQL-like string using the blocked command
        sql = f"{cmd} something"
        ok, msg = guard.validate(sql, conn)
        assert not ok, f"Command '{cmd}' should be blocked but was accepted"


class TestAllBlockedFunctions:
    """Ensure every entry in BLOCKED_FUNCTIONS is caught when used in SELECT."""

    @pytest.mark.parametrize("func", BLOCKED_FUNCTIONS)
    def test_blocked_function_in_select(self, guard, conn, func):
        sql = f"SELECT * FROM {func}('/tmp/file') LIMIT 10"
        ok, msg = guard.validate(sql, conn)
        assert not ok, f"Function '{func}' should be blocked but was accepted"
