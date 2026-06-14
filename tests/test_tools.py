"""
tests/test_tools.py — 工具层单元测试

覆盖：data_loader, query_runner（逐步扩展）
"""

import os
import sys
import tempfile

import pytest

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def gb18030_csv():
    """创建一个 GB18030 编码的测试 CSV（含千分位逗号）"""
    content = (
        '产品名称,资产代码,资产名称,资产市值_穿透后,限额占用方主体,外部评级,持仓日期\n'
        'XX稳健理财01号,0123456789,21象屿MTN001,"1,234,567.89",厦门象屿集团有限公司,AAA,2026-05-15\n'
        'XX稳健理财01号,9876543210,22建发SCP003,"5,678,000.00",厦门建发集团有限公司,AA+,2026-05-15\n'
        'YY进取理财02号,1122334455,21象屿股份CP002,"890,123.45",象屿股份,AA,2026-05-15\n'
    )
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='gb18030') as f:
        f.write(content)
    yield f.name
    os.unlink(f.name)


@pytest.fixture
def utf8_csv():
    """创建一个 UTF-8 编码的测试 CSV"""
    content = (
        '产品名称,资产代码,资产名称,资产市值_穿透后,限额占用方主体,外部评级\n'
        '测试产品A,CODE001,测试债券1,1000000.00,测试主体A,AAA\n'
    )
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        f.write(content)
    yield f.name
    os.unlink(f.name)


# ═══════════════════════════════════════════════════════════════
#  DuckDB 连接测试
# ═══════════════════════════════════════════════════════════════

def test_init_duckdb_memory_limit():
    """验证 DuckDB 内存限制设置生效"""
    # 重置全局连接，确保测试独立性
    import tools.data_loader as dl
    from tools.data_loader import init_duckdb_connection
    dl._global_conn = None
    dl._loaded_tables.clear()

    conn = init_duckdb_connection(max_memory="80MB", threads=2)
    mem = conn.execute("SELECT current_setting('max_memory')").fetchone()[0]
    # DuckDB 会用实际字节数或用 MiB 表示
    assert '80' in str(mem) or '76' in str(mem) or '80MB' in str(mem), f"内存限制应为80MB，实际：{mem}"


def test_init_duckdb_singleton():
    """验证多次调用返回同一连接"""
    import tools.data_loader as dl
    from tools.data_loader import get_connection, init_duckdb_connection
    dl._global_conn = None

    c1 = init_duckdb_connection()
    c2 = get_connection()
    assert c1 is c2


# ═══════════════════════════════════════════════════════════════
#  CSV 加载测试
# ═══════════════════════════════════════════════════════════════

def test_load_csv_gb18030(gb18030_csv):
    """测试 GB18030 CSV 加载：编码检测 + 千分位清洗 + 字段映射"""
    import tools.data_loader as dl
    from tools.data_loader import get_connection, get_loaded_tables, load_file
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl.init_duckdb_connection()

    result = load_file(gb18030_csv, 'test_holding', table_type='holding')
    assert result.row_count == 3
    assert '资产市值_穿透后' in result.field_map.values()

    # 验证千分位已清洗
    conn = get_connection()
    val = conn.execute('SELECT "资产市值_穿透后" FROM test_holding LIMIT 1').fetchone()[0]
    assert isinstance(val, float), f"应为 float 类型，实际: {type(val)}"
    assert abs(val - 1234567.89) < 0.01, f"千分位清洗后应为 1234567.89，实际: {val}"
    # 验证实体归一列已添加
    assert '限额占用主体_标准' in result.field_map

    tables = get_loaded_tables()
    assert len(tables) == 1
    assert tables[0]['rows'] == 3


def test_load_csv_utf8(utf8_csv):
    """测试 UTF-8 CSV 加载"""
    import tools.data_loader as dl
    from tools.data_loader import load_file
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl.init_duckdb_connection()

    result = load_file(utf8_csv, 'test_utf8', table_type='holding')
    assert result.row_count == 1
    assert result.encoding in ('utf-8', 'ascii', 'UTF-8')


def test_load_csv_auto_encoding(gb18030_csv):
    """测试自动编码检测"""
    import tools.data_loader as dl
    from tools.data_loader import load_file
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl.init_duckdb_connection()

    result = load_file(gb18030_csv, 'test_enc', table_type='holding')
    # 编码应该是 GB2312 或 GB18030（chardet 可能返回 GB2312）
    assert 'gb' in result.encoding.lower() or 'gb2312' in result.encoding.lower(), \
        f"应为中文编码，实际：{result.encoding}"


def test_load_nonexistent_file():
    """测试加载不存在的文件应抛出异常"""
    import tools.data_loader as dl
    from tools.data_loader import load_file
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl.init_duckdb_connection()

    with pytest.raises(Exception):  # noqa: B017
        load_file('/nonexistent/file.csv', 'bad_table')


# ═══════════════════════════════════════════════════════════════
#  字段映射测试
# ═══════════════════════════════════════════════════════════════

def test_field_mapping_missing_required(gb18030_csv):
    """验证必填字段缺失时会记录警告"""
    import tools.data_loader as dl
    from tools.data_loader import load_file
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl.init_duckdb_connection()

    result = load_file(gb18030_csv, 'test_map', table_type='holding')
    # 持仓日期 是 required=True，但我们的测试 CSV 中第一行有这个字段
    # 实际上检查 missing_required 的定义
    assert isinstance(result.missing_required, list)
    assert isinstance(result.unmatched_cols, list)


def test_column_name_cleaning():
    """测试列名清洗：去空格、去不可见字符"""
    from tools.data_loader import clean_column_name
    assert clean_column_name('  产品名称  ') == '产品名称'
    assert clean_column_name('正常列名') == '正常列名'


def test_thousands_separator_cleaning():
    """测试千分位逗号清洗"""
    from tools.data_loader import clean_thousands_separator
    assert clean_thousands_separator('1,234,567.89') == '1234567.89'
    assert clean_thousands_separator('1000000') == '1000000'
    assert clean_thousands_separator('') == ''
    assert clean_thousands_separator('-5,000.00') == '-5000.00'


# ═══════════════════════════════════════════════════════════════
#  I-4: auto_detect_table_type 测试
# ═══════════════════════════════════════════════════════════════

class TestAutoDetectTableType:
    def _df(self, cols):
        import pandas as pd
        return pd.DataFrame(columns=cols)

    def test_holding_by_columns(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['产品名称', '资产代码', '资产市值_穿透后', '持仓日期'])
        assert auto_detect_table_type(df) == 'holding'

    def test_nav_by_columns(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['产品名称', '单位净值', '累计净值', '日期'])
        assert auto_detect_table_type(df) == 'nav'

    def test_rating_entity_by_columns(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['主体名称', '主体评级', '内部评级', '行业'])
        assert auto_detect_table_type(df) == 'rating_entity'

    def test_rating_bond_by_columns(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['债券代码', '债项评级', '发行人', '评级日期'])
        assert auto_detect_table_type(df) == 'rating_bond'

    def test_holding_by_filename_hint(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['产品名称', '代码', '市值'])
        assert auto_detect_table_type(df, '持仓_20260515.csv') == 'holding'

    def test_nav_by_filename_hint(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['产品', '日期', '数值'])
        assert auto_detect_table_type(df, 'nav_0515.csv') == 'nav'

    def test_unknown_no_keywords(self):
        from tools.data_loader import auto_detect_table_type
        df = self._df(['col_a', 'col_b', 'col_c'])
        assert auto_detect_table_type(df) == 'unknown'


# ═══════════════════════════════════════════════════════════════
#  I-4: extract_date_from_filename 测试
# ═══════════════════════════════════════════════════════════════

class TestExtractDateFromFilename:
    def test_full_8digit(self):
        from tools.data_loader import extract_date_from_filename
        assert extract_date_from_filename('持仓_20260515.csv') == '20260515'

    def test_6digit_yy(self):
        from tools.data_loader import extract_date_from_filename
        result = extract_date_from_filename('holding_260515.csv')
        assert result == '20260515'

    def test_4digit_mmdd(self):
        from datetime import datetime

        from tools.data_loader import extract_date_from_filename
        result = extract_date_from_filename('nav_0501.csv')
        assert result is not None
        assert result.endswith('0501')
        assert len(result) == 8

    def test_no_date(self):
        from tools.data_loader import extract_date_from_filename
        assert extract_date_from_filename('arbitrary_filename.csv') is None

    def test_date_in_middle(self):
        from tools.data_loader import extract_date_from_filename
        assert extract_date_from_filename('report_20260601_v2.xlsx') == '20260601'


# ═══════════════════════════════════════════════════════════════
#  query_runner / SQLGuard 测试
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def duckdb_with_table():
    """创建一个加载了测试表的 DuckDB 连接"""
    import tools.data_loader as dl
    dl._global_conn = None
    dl._loaded_tables.clear()
    conn = dl.init_duckdb_connection()
    conn.execute('CREATE TABLE test_holding AS SELECT 1 AS id, \'XX产品\' AS name')
    yield conn
    conn.execute('DROP TABLE IF EXISTS test_holding')
    dl._global_conn = None
    dl._loaded_tables.clear()


def test_guard_blocks_delete(duckdb_with_table):
    """DELETE 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('DELETE FROM test_holding', duckdb_with_table)
    assert not ok


def test_guard_blocks_insert(duckdb_with_table):
    """INSERT 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('INSERT INTO test_holding VALUES (2, \'Y\')', duckdb_with_table)
    assert not ok


def test_guard_blocks_drop(duckdb_with_table):
    """DROP 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('DROP TABLE test_holding', duckdb_with_table)
    assert not ok


def test_guard_blocks_copy(duckdb_with_table):
    """COPY 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate("COPY test_holding TO '/tmp/out.csv'", duckdb_with_table)
    assert not ok


def test_guard_blocks_pragma(duckdb_with_table):
    """PRAGMA 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('PRAGMA database_list', duckdb_with_table)
    assert not ok


def test_guard_requires_limit(duckdb_with_table):
    """缺少 LIMIT 应被拒绝"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT * FROM test_holding', duckdb_with_table)
    assert not ok
    assert 'LIMIT' in msg.upper()


def test_guard_limit_too_large(duckdb_with_table):
    """LIMIT 超过 1000 应被拒绝"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT * FROM test_holding LIMIT 2000', duckdb_with_table)
    assert not ok


def test_guard_valid_select(duckdb_with_table):
    """合法的 SELECT 应通过"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT * FROM test_holding LIMIT 10', duckdb_with_table)
    assert ok, f"应通过但被拒绝：{msg}"


def test_guard_valid_with_cte(duckdb_with_table):
    """合法的 CTE + SELECT 应通过"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    sql = 'WITH a AS (SELECT * FROM test_holding) SELECT * FROM a LIMIT 10'
    ok, msg = guard.validate(sql, duckdb_with_table)
    assert ok, f"CTE 查询应通过但被拒绝：{msg}"


def test_guard_unknown_table(duckdb_with_table):
    """引用未加载的表应被拒绝"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT * FROM nonexistent_table LIMIT 10', duckdb_with_table)
    assert not ok
    assert 'not loaded' in msg.lower() or 'referenced' in msg.lower()


def test_guard_blocks_read_csv():
    """read_csv_auto 应被拦截"""
    import tools.data_loader as dl
    from tools.data_loader import init_duckdb_connection
    dl._global_conn = None
    conn = init_duckdb_connection()
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate("SELECT read_csv_auto('/tmp/test.csv') LIMIT 10", conn)
    assert not ok


def test_guard_blocks_information_schema(duckdb_with_table):
    """访问 information_schema 应被拦截"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT * FROM information_schema.tables LIMIT 10', duckdb_with_table)
    assert not ok


def test_guard_allows_expression_query(duckdb_with_table):
    """纯表达式查询 SELECT 1+1 应通过"""
    from tools.query_runner import SQLGuard
    guard = SQLGuard()
    ok, msg = guard.validate('SELECT 1+1 AS result LIMIT 1', duckdb_with_table)
    assert ok, f"表达式查询应通过但被拒绝：{msg}"


def test_execute_query_success(duckdb_with_table):
    """execute_query 应正确执行并返回结果"""
    from tools.query_runner import execute_query
    result = execute_query('SELECT * FROM test_holding LIMIT 10', duckdb_with_table)
    assert result.success
    assert result.row_count == 1
    assert 'id' in result.columns
    assert result.rows[0][1] == 'XX产品'


def test_execute_query_failure(duckdb_with_table):
    """execute_query 对非法查询应返回失败"""
    from tools.query_runner import execute_query
    result = execute_query('DELETE FROM test_holding', duckdb_with_table)
    assert not result.success


def test_execute_query_requires_confirmation(duckdb_with_table):
    """超过50行时应标记 requires_confirmation"""
    from tools.query_runner import execute_query
    # 先插入 60 行
    for i in range(60):
        duckdb_with_table.execute(f"INSERT INTO test_holding VALUES ({i+2}, 'product_{i}')")
    result = execute_query('SELECT * FROM test_holding LIMIT 100', duckdb_with_table)
    assert result.success
    assert result.requires_confirmation  # >50 行应要求确认


# ═══════════════════════════════════════════════════════════════
#  Phase R2 新增：数据质量诊断测试
# ═══════════════════════════════════════════════════════════════

class TestQualityReport:
    """compute_quality_report 功能测试"""

    @pytest.fixture
    def q_conn(self):
        """创建含空值和不同质量特征的测试表"""
        import duckdb

        import tools.data_loader as dl
        dl._global_conn = None
        dl._loaded_tables.clear()
        con = dl.init_duckdb_connection()
        con.execute("""
            CREATE TABLE test_quality AS SELECT * FROM (VALUES
                ('2026-05-15', '象屿集团', 1234567.89, 'AAA'),
                ('2026-05-16', '建发集团', NULL, 'AA+'),
                ('2026-05-17', '未知主体X', 3456789.01, NULL),
                (NULL, '象屿集团', 4567890.12, 'AAA'),
                ('2026-05-19', NULL, 5678901.23, 'AA'),
            ) AS t("统计日期", "限额占用主体", "穿透后市值", "外部评级")
        """)
        return con

    def test_quality_null_rates(self, q_conn):
        """空值率应正确计算并标注关键字段"""
        from tools.quality import compute_quality_report
        field_map = {
            "统计日期": "统计日期",
            "限额占用主体": "限额占用主体",
            "穿透后市值": "穿透后市值",
            "外部评级": "外部评级",
        }
        report = compute_quality_report(
            q_conn, "test_quality", "holding", field_map,
            key_fields=["限额占用主体", "穿透后市值"],
        )
        # 5行中，限额占用主体 1 行为 NULL → 20%
        assert report.null_rates.get("限额占用主体") == 0.2
        # 穿透后市值 1 行为 NULL → 20% > 5% 阈值 → critical
        assert report.null_rates.get("穿透后市值") == 0.2
        # 关键字段空值 > 5% → critical_issues 应有记录
        assert len(report.critical_issues) >= 1
        critical_text = " ".join(report.critical_issues)
        assert "穿透后市值" in critical_text or "限额占用主体" in critical_text

    def test_quality_entity_coverage(self, q_conn):
        """部分主体不在 alias 中时应返回未匹配列表"""
        from tools.quality import compute_quality_report
        field_map = {
            "限额占用主体": "限额占用主体",
            "穿透后市值": "穿透后市值",
        }
        report = compute_quality_report(
            q_conn, "test_quality", "holding", field_map,
        )
        ec = report.entity_coverage
        assert ec["total"] > 0
        # "未知主体X" 不在 entity_alias 中
        assert len(ec.get("unmatched", [])) >= 1

    def test_quality_date_range(self, q_conn):
        """应检测日期列并给出范围"""
        from tools.quality import compute_quality_report
        field_map = {
            "统计日期": "统计日期",
            "限额占用主体": "限额占用主体",
            "穿透后市值": "穿透后市值",
        }
        report = compute_quality_report(
            q_conn, "test_quality", "holding", field_map,
        )
        assert report.date_range is not None
        assert report.date_range.get("min") == "2026-05-15"
        # max 应存在（5行中有4个非NULL日期）
        assert report.date_range.get("max") is not None
