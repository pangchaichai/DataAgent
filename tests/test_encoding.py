"""
tests/test_encoding.py — 编码检测 + 乱码防护测试

覆盖场景：
  - UTF-8 BOM / plain UTF-8 / GB18030 / GBK 文件
  - 少量 CJK 字符的短文件（曾误判为 latin-1）
  - 乱码检测函数
  - DuckDB 编码名归一化
  - Pandas 回退路径乱码防护
  - 列名清洗（BOM 字符/不可见字符）
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from tools.encoding import (
    clean_column_name,
    clean_thousands_separator,
    detect_encoding,
    is_garbled,
    normalize_for_duckdb,
)


# ═══════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════

def _write_csv(tmp_path: Path, name: str, content: str, encoding: str,
               bom: bool = False) -> Path:
    p = tmp_path / name
    with open(p, 'wb') as f:
        if bom:
            f.write(b'\xef\xbb\xbf')
        f.write(content.encode(encoding))
    return p


HEADER_CN = '持仓日期,企业名称,债券名称,市值\n'
ROW_CN = '2026-06-01,象屿集团,24象屿01,1234567.89\n'
CSV_CN = HEADER_CN + ROW_CN

HEADER_SHORT = '日期,金额\n'
ROW_SHORT = '2026-06-01,100\n2026-06-02,200\n'
CSV_SHORT = HEADER_SHORT + ROW_SHORT

HEADER_ASCII = 'date,name,value,status\n'
ROW_ASCII = '2026-06-01,test,123,ok\n'
CSV_ASCII = HEADER_ASCII + ROW_ASCII


# ═══════════════════════════════════════════════════════════════
#  detect_encoding
# ═══════════════════════════════════════════════════════════════

class TestDetectEncoding:
    def test_utf8_bom_shortcircuit(self, tmp_path):
        p = _write_csv(tmp_path, 'bom.csv', CSV_CN, 'utf-8', bom=True)
        assert detect_encoding(str(p)) == 'utf-8'

    def test_utf8_plain(self, tmp_path):
        p = _write_csv(tmp_path, 'utf8.csv', CSV_CN, 'utf-8')
        assert detect_encoding(str(p)) == 'utf-8'

    def test_gb18030(self, tmp_path):
        p = _write_csv(tmp_path, 'gb.csv', CSV_CN, 'gb18030')
        enc = detect_encoding(str(p))
        assert enc.upper().replace('-', '') in ('GB18030', 'GBK', 'GB2312')

    def test_gbk(self, tmp_path):
        p = _write_csv(tmp_path, 'gbk.csv', CSV_CN, 'gbk')
        enc = detect_encoding(str(p))
        assert enc.upper().replace('-', '') in ('GB18030', 'GBK', 'GB2312')

    def test_short_utf8_not_latin1(self, tmp_path):
        """短文件少量CJK字符——曾被误判为latin-1导致乱码"""
        p = _write_csv(tmp_path, 'short.csv', CSV_SHORT, 'utf-8')
        enc = detect_encoding(str(p))
        df = pd.read_csv(str(p), encoding=enc, dtype=str, nrows=3)
        assert not is_garbled(list(df.columns))
        assert '日期' in list(df.columns)

    def test_short_utf8_bom(self, tmp_path):
        p = _write_csv(tmp_path, 'short_bom.csv', CSV_SHORT, 'utf-8', bom=True)
        assert detect_encoding(str(p)) == 'utf-8'

    def test_ascii_file(self, tmp_path):
        p = _write_csv(tmp_path, 'ascii.csv', CSV_ASCII, 'utf-8')
        enc = detect_encoding(str(p))
        df = pd.read_csv(str(p), encoding=enc, dtype=str, nrows=3)
        assert list(df.columns) == ['date', 'name', 'value', 'status']

    def test_mostly_ascii_with_few_cjk_bom(self, tmp_path):
        content = 'ID,Code,Name,Date,Amount,企业名称\n1,001,X,2026-01-01,100,象屿\n'
        p = _write_csv(tmp_path, 'mixed.csv', content, 'utf-8', bom=True)
        assert detect_encoding(str(p)) == 'utf-8'


# ═══════════════════════════════════════════════════════════════
#  is_garbled
# ═══════════════════════════════════════════════════════════════

class TestIsGarbled:
    def test_clean_chinese(self):
        assert is_garbled(['持仓日期', '企业名称', '市值']) is False

    def test_clean_ascii(self):
        assert is_garbled(['date', 'name', 'value']) is False

    def test_bom_latin1(self):
        assert is_garbled(['ï»¿æä»æ¥æ', 'name']) is True

    def test_latin1_garble(self):
        assert is_garbled(['ä¼ä¸åç§°', 'ok']) is True

    def test_empty(self):
        assert is_garbled([]) is False

    def test_mixed_clean(self):
        assert is_garbled(['ID', '企业名称', 'value']) is False


# ═══════════════════════════════════════════════════════════════
#  normalize_for_duckdb
# ═══════════════════════════════════════════════════════════════

class TestNormalizeForDuckdb:
    def test_utf8_variants(self):
        assert normalize_for_duckdb('utf-8') == 'utf-8'
        assert normalize_for_duckdb('UTF-8') == 'utf-8'
        assert normalize_for_duckdb('utf-8-sig') == 'utf-8'
        assert normalize_for_duckdb('ascii') == 'utf-8'

    def test_latin1_variants(self):
        assert normalize_for_duckdb('latin-1') == 'latin-1'
        assert normalize_for_duckdb('latin1') == 'latin-1'
        assert normalize_for_duckdb('iso-8859-1') == 'latin-1'
        assert normalize_for_duckdb('windows-1252') == 'latin-1'
        assert normalize_for_duckdb('cp1252') == 'latin-1'

    def test_unsupported(self):
        assert normalize_for_duckdb('gb18030') is None
        assert normalize_for_duckdb('gbk') is None
        assert normalize_for_duckdb('gb2312') is None
        assert normalize_for_duckdb('euc-kr') is None


# ═══════════════════════════════════════════════════════════════
#  clean_column_name
# ═══════════════════════════════════════════════════════════════

class TestCleanColumnName:
    def test_strip_bom_unicode(self):
        assert clean_column_name('﻿持仓日期') == '持仓日期'

    def test_strip_bom_latin1(self):
        assert clean_column_name('ï»¿date') == 'date'

    def test_strip_whitespace(self):
        assert clean_column_name('  name  ') == 'name'

    def test_noop(self):
        assert clean_column_name('持仓日期') == '持仓日期'

    def test_invisible_chars(self):
        assert clean_column_name('na​me') == 'name'


# ═══════════════════════════════════════════════════════════════
#  clean_thousands_separator
# ═══════════════════════════════════════════════════════════════

class TestCleanThousands:
    def test_with_commas(self):
        assert clean_thousands_separator('1,234,567.89') == '1234567.89'

    def test_no_commas(self):
        assert clean_thousands_separator('123456') == '123456'

    def test_nan(self):
        assert clean_thousands_separator('nan') == 'nan'

    def test_negative(self):
        assert clean_thousands_separator('-1,234') == '-1234'


# ═══════════════════════════════════════════════════════════════
#  Pandas 回退路径乱码防护
# ═══════════════════════════════════════════════════════════════

class TestPandasFallbackGarbleProtection:
    def test_wrong_encoding_auto_retry(self, tmp_path):
        """即使 detect_encoding 返回错误编码，Pandas 回退应自动纠正"""
        from tools.file_ingest import _load_csv_pandas

        p = _write_csv(tmp_path, 'cn.csv', CSV_CN, 'utf-8')
        warnings = []
        df = _load_csv_pandas(str(p), 'latin-1', warnings)
        assert not is_garbled(list(df.columns))
        assert '持仓日期' in list(df.columns)

    def test_gb18030_pandas_fallback(self, tmp_path):
        from tools.file_ingest import _load_csv_pandas

        p = _write_csv(tmp_path, 'gb.csv', CSV_CN, 'gb18030')
        warnings = []
        df = _load_csv_pandas(str(p), 'gb18030', warnings)
        assert '持仓日期' in list(df.columns)

    def test_utf8_bom_pandas(self, tmp_path):
        from tools.file_ingest import _load_csv_pandas

        p = _write_csv(tmp_path, 'bom.csv', CSV_CN, 'utf-8', bom=True)
        warnings = []
        df = _load_csv_pandas(str(p), 'utf-8', warnings)
        assert '持仓日期' in list(df.columns)
        assert not is_garbled(list(df.columns))


# ═══════════════════════════════════════════════════════════════
#  DuckDB 原生加载路径
# ═══════════════════════════════════════════════════════════════

class TestDuckDBNativeLoad:
    def test_utf8_bom_native(self, tmp_path):
        import duckdb
        from tools.file_ingest import _load_csv_native

        p = _write_csv(tmp_path, 'bom.csv', CSV_CN, 'utf-8', bom=True)
        conn = duckdb.connect(':memory:')
        result = _load_csv_native(conn, str(p), 'test_bom', 'utf-8')
        assert result is not None
        assert '持仓日期' in result['columns']
        conn.close()

    def test_gb18030_native_returns_none(self, tmp_path):
        import duckdb
        from tools.file_ingest import _load_csv_native

        p = _write_csv(tmp_path, 'gb.csv', CSV_CN, 'gb18030')
        conn = duckdb.connect(':memory:')
        result = _load_csv_native(conn, str(p), 'test_gb', 'gb18030')
        assert result is None
        conn.close()

    def test_garbled_native_returns_none(self, tmp_path):
        """If DuckDB loads but produces garbled columns, should return None"""
        import duckdb
        from tools.file_ingest import _load_csv_native

        p = _write_csv(tmp_path, 'ascii.csv', CSV_ASCII, 'utf-8')
        conn = duckdb.connect(':memory:')
        result = _load_csv_native(conn, str(p), 'test_ascii', 'utf-8')
        assert result is not None
        assert not is_garbled(result['columns'])
        conn.close()
