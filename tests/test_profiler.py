"""
tests/test_profiler.py — 数据剖析器单元测试
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestProfiler:
    """profile_table 功能测试"""

    @pytest.fixture
    def conn(self):
        """创建含测试数据的 DuckDB 内存连接"""
        import duckdb
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_table AS SELECT * FROM (VALUES
                ('产品A', '象屿集团', 1234567.89, 'AAA'),
                ('产品B', '建发集团', 2345678.90, 'AA+'),
                ('产品B', NULL, NULL, NULL),
                ('产品C', '象屿集团', 3456789.01, 'AAA'),
                ('产品A', '国贸集团', 4567890.12, 'AA'),
            ) AS t("产品名称", "限额占用主体", "穿透后市值", "外部评级")
        """)
        return con

    def test_profile_unknown_table(self, conn):
        """剖析应返回表名和行数"""
        from tools.profiler import profile_table
        result = profile_table(conn, "test_table")
        assert result["table"] == "test_table"
        assert result["row_count"] == 5
        assert len(result["columns"]) >= 3

    def test_profile_null_rate(self, conn):
        """空值率应正确计算"""
        from tools.profiler import profile_table
        result = profile_table(conn, "test_table")
        col_map = {c["name"]: c for c in result["columns"]}
        # 限额占用主体列：5行中1行为NULL
        entity_col = col_map.get("限额占用主体")
        assert entity_col is not None
        assert entity_col["null_rate"] == 0.2  # 1/5

    def test_profile_samples_dedup(self, conn):
        """文本列样本应去重"""
        from tools.profiler import profile_table
        result = profile_table(conn, "test_table")
        col_map = {c["name"]: c for c in result["columns"]}
        product_col = col_map.get("产品名称")
        assert product_col is not None
        samples = product_col.get("samples", [])
        # 3种产品，每条去重
        assert len(samples) == 3
        assert set(samples) == {"产品A", "产品B", "产品C"}

    def test_profile_numeric_min_max(self, conn):
        """数值列应有 min/max"""
        from tools.profiler import profile_table
        result = profile_table(conn, "test_table")
        col_map = {c["name"]: c for c in result["columns"]}
        mv_col = col_map.get("穿透后市值")
        assert mv_col is not None
        assert mv_col["min"] == pytest.approx(1234567.89, rel=0.01)
        assert mv_col["max"] == pytest.approx(4567890.12, rel=0.01)

    def test_profile_specific_columns(self, conn):
        """指定 columns 参数应只剖析指定列"""
        from tools.profiler import profile_table
        result = profile_table(conn, "test_table", columns=["产品名称"])
        assert len(result["columns"]) == 1
        assert result["columns"][0]["name"] == "产品名称"
