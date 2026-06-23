"""
tests/test_large_data.py — 大数据量适配测试（Phase 0）

覆盖：
  - DuckDB 文件模式持久化 + 元数据恢复
  - DuckDB 原生 CSV 加载
  - Excel 逐Sheet流式加载
  - 日期提取增强（YYYY-MM-DD, ISO timestamp）
  - 版本淘汰
"""

import gc
import json
import os
import sys
import tempfile

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.data_loader as dl


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_data_loader():
    """每个测试前重置 data_loader 全局状态。"""
    old_conn = dl._global_conn
    old_tables = dl._loaded_tables.copy()
    old_path = dl._db_path
    dl._global_conn = None
    dl._loaded_tables.clear()
    dl._db_path = ':memory:'
    yield
    if dl._global_conn is not None and dl._global_conn is not old_conn:
        try:
            dl._global_conn.close()
        except Exception:
            pass
    dl._global_conn = old_conn
    dl._loaded_tables.clear()
    dl._loaded_tables.update(old_tables)
    dl._db_path = old_path


@pytest.fixture
def utf8_csv(tmp_path):
    """UTF-8 CSV with sample data."""
    p = tmp_path / "test_utf8.csv"
    p.write_text(
        "产品名称,资产代码,金额\n"
        "产品A,C001,1000.50\n"
        "产品B,C002,2000.75\n",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def gb18030_csv(tmp_path):
    """GB18030 CSV with sample data."""
    p = tmp_path / "test_gb18030.csv"
    p.write_text(
        "产品名称,资产代码,金额\n"
        "产品A,C001,1000.50\n"
        "产品B,C002,2000.75\n",
        encoding="gb18030",
    )
    return str(p)


@pytest.fixture
def thousands_csv(tmp_path):
    """CSV with thousands separators."""
    p = tmp_path / "test_thousands.csv"
    p.write_text(
        '产品名称,资产代码,资产市值_穿透后\n'
        '产品A,C001,"1,234,567.89"\n'
        '产品B,C002,"5,678,000.00"\n',
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def simple_xlsx(tmp_path):
    """Small Excel file for testing."""
    p = tmp_path / "test_small.xlsx"
    df = pd.DataFrame({
        "产品名称": ["A", "B", "C"],
        "金额": [100, 200, 300],
    })
    df.to_excel(str(p), index=False)
    return str(p)


@pytest.fixture
def multi_sheet_xlsx(tmp_path):
    """Excel file with multiple compatible sheets."""
    p = tmp_path / "test_multi.xlsx"
    with pd.ExcelWriter(str(p)) as writer:
        for i in range(3):
            df = pd.DataFrame({
                "产品名称": [f"产品{i}_{j}" for j in range(5)],
                "金额": [100 * (i + 1) + j for j in range(5)],
            })
            df.to_excel(writer, sheet_name=f"Sheet{i+1}", index=False)
    return str(p)


# ═══════════════════════════════════════════════════════════════
#  日期提取增强测试
# ═══════════════════════════════════════════════════════════════

class TestDateExtraction:
    def test_yyyy_mm_dd(self):
        assert dl.extract_date_from_filename("持仓产品管理-2026-06-16.xls") == "20260616"

    def test_yyyy_mm_dd_in_parens(self):
        assert dl.extract_date_from_filename("估值表查询(2026-06-16).xlsx") == "20260616"

    def test_iso_timestamp(self):
        assert dl.extract_date_from_filename("评级结果2026-06-22T084857.169.xls") == "20260622"

    def test_yyyymmdd_still_works(self):
        assert dl.extract_date_from_filename("holding_20260515.csv") == "20260515"

    def test_yymmdd_still_works(self):
        assert dl.extract_date_from_filename("data_260515.csv") == "20260515"

    def test_mmdd_still_works(self):
        from datetime import datetime
        result = dl.extract_date_from_filename("data_0515.csv")
        assert result == datetime.now().strftime("%Y") + "0515"

    def test_no_date(self):
        assert dl.extract_date_from_filename("readme.txt") is None

    def test_yyyy_mm_dd_priority(self):
        assert dl.extract_date_from_filename("净值结果管理2026-06-15-2026-06-16.xlsx") == "20260615"


# ═══════════════════════════════════════════════════════════════
#  DuckDB 文件模式持久化测试
# ═══════════════════════════════════════════════════════════════

class TestDuckDBFilePersistence:
    def test_file_mode_persist_and_restore(self, tmp_path, utf8_csv):
        """加载数据 → 关闭连接 → 重新打开 → 验证表存在 + 注册表恢复。"""
        db_file = str(tmp_path / "test.duckdb")
        meta_file = tmp_path / "table_metadata.json"

        dl._db_path = db_file
        dl._METADATA_PATH = meta_file
        conn = dl.init_duckdb_connection()

        result = dl.load_file(utf8_csv, "persist_test")
        assert result.row_count == 2
        assert "persist_test" in dl._loaded_tables

        conn.close()
        dl._global_conn = None
        dl._loaded_tables.clear()

        dl._db_path = db_file
        conn2 = dl.init_duckdb_connection()

        assert "persist_test" in dl._loaded_tables
        rows = conn2.execute('SELECT COUNT(*) FROM "persist_test"').fetchone()[0]
        assert rows == 2

        conn2.close()
        dl._global_conn = None

    def test_metadata_json_written(self, tmp_path, utf8_csv):
        """验证 _save_table_metadata 写入 JSON。"""
        db_file = str(tmp_path / "test.duckdb")
        meta_file = tmp_path / "table_metadata.json"

        dl._db_path = db_file
        dl._METADATA_PATH = meta_file
        dl.init_duckdb_connection()
        dl.load_file(utf8_csv, "meta_test")

        assert meta_file.exists()
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        assert "meta_test" in data

        dl._global_conn.close()
        dl._global_conn = None

    def test_memory_mode_no_metadata(self, utf8_csv, tmp_path):
        """内存模式下不写元数据 JSON。"""
        meta_file = tmp_path / "table_metadata.json"
        dl._METADATA_PATH = meta_file
        dl.init_duckdb_connection()
        dl.load_file(utf8_csv, "mem_test")
        assert not meta_file.exists()


# ═══════════════════════════════════════════════════════════════
#  DuckDB 原生 CSV 加载测试
# ═══════════════════════════════════════════════════════════════

class TestNativeCSVLoad:
    def test_native_utf8(self, utf8_csv):
        """UTF-8 CSV 走原生路径成功。"""
        conn = dl.init_duckdb_connection()
        result = dl._load_csv_native(conn, utf8_csv, "native_utf8", "utf-8")
        assert result is not None
        assert result['row_count'] == 2
        assert '产品名称' in result['columns']

    def test_native_gb18030(self, gb18030_csv):
        """GB18030 CSV 走原生路径（DuckDB 可能不支持 → 回退 None）。"""
        conn = dl.init_duckdb_connection()
        result = dl._load_csv_native(conn, gb18030_csv, "native_gb", "gb18030")
        # DuckDB 原生可能不支持 gb18030，此时返回 None 是正确行为
        # 如果返回结果，验证数据正确性
        if result is not None:
            assert result['row_count'] == 2

    def test_load_file_csv_native_path(self, utf8_csv):
        """load_file() 对 UTF-8 CSV 走原生路径。"""
        dl.init_duckdb_connection()
        result = dl.load_file(utf8_csv, "native_full")
        assert result.row_count == 2
        assert result.table_name == "native_full"

    def test_native_column_cleaning(self, tmp_path):
        """原生路径的列名清洗。"""
        p = tmp_path / "space_cols.csv"
        p.write_text("  产品名称 ,金额\nA,100\n", encoding="utf-8")
        conn = dl.init_duckdb_connection()
        result = dl._load_csv_native(conn, str(p), "clean_test", "utf-8")
        assert result is not None
        cols_out = dl._native_clean_columns(conn, "clean_test", result['columns'])
        assert "产品名称" in cols_out

    def test_pandas_fallback_on_native_failure(self, gb18030_csv):
        """原生加载失败时回退到 Pandas。"""
        dl.init_duckdb_connection()
        result = dl.load_file(gb18030_csv, "fallback_test")
        assert result.row_count == 2


# ═══════════════════════════════════════════════════════════════
#  Excel 流式加载测试
# ═══════════════════════════════════════════════════════════════

class TestExcelStreaming:
    def test_streaming_single_sheet(self, simple_xlsx):
        """单Sheet Excel 流式加载。"""
        from tools.excel_preprocessor import preprocess_excel_streaming
        results = list(preprocess_excel_streaming(simple_xlsx))
        assert len(results) == 1
        df, info, compat = results[0]
        assert info.row_count == 3
        assert compat is True

    def test_streaming_multi_sheet(self, multi_sheet_xlsx):
        """多Sheet同构 Excel 逐Sheet产出。"""
        from tools.excel_preprocessor import preprocess_excel_streaming
        results = list(preprocess_excel_streaming(multi_sheet_xlsx))
        assert len(results) == 3
        for _, _, compat in results:
            assert compat is True

    def test_streaming_sheet_select_first(self, multi_sheet_xlsx):
        """sheet_select='first' 只取首Sheet。"""
        from tools.excel_preprocessor import preprocess_excel_streaming
        results = list(preprocess_excel_streaming(multi_sheet_xlsx, sheet_select="first"))
        assert len(results) == 1

    def test_streaming_sheet_select_indices(self, multi_sheet_xlsx):
        """sheet_select=[0, 2] 取指定索引。"""
        from tools.excel_preprocessor import preprocess_excel_streaming
        results = list(preprocess_excel_streaming(multi_sheet_xlsx, sheet_select=[0, 2]))
        assert len(results) == 2

    def test_preprocess_excel_sheet_select_first(self, multi_sheet_xlsx):
        """preprocess_excel() 支持 sheet_select='first'。"""
        from tools.excel_preprocessor import preprocess_excel
        result = preprocess_excel(multi_sheet_xlsx, sheet_select="first")
        assert result.df is not None
        assert len(result.sheet_info) == 1

    def test_load_excel_streaming_integration(self, tmp_path):
        """_load_excel_streaming 端到端：多Sheet合并到一张 DuckDB 表。"""
        p = tmp_path / "big_test.xlsx"
        with pd.ExcelWriter(str(p)) as writer:
            for i in range(3):
                df = pd.DataFrame({
                    "Name": [f"Item{i}_{j}" for j in range(10)],
                    "Value": list(range(10)),
                })
                df.to_excel(writer, sheet_name=f"Sheet{i+1}", index=False)

        dl.init_duckdb_connection()
        conn = dl.get_connection()
        result = dl._load_excel_streaming(
            conn, str(p), "stream_test", None, None,
        )
        assert result.row_count == 30
        assert result.table_name == "stream_test"


# ═══════════════════════════════════════════════════════════════
#  sheet_select 参数透传测试
# ═══════════════════════════════════════════════════════════════

class TestSheetSelectInLoadFile:
    def test_small_excel_sheet_select(self, multi_sheet_xlsx):
        """小文件走 preprocess_excel 路径，sheet_select 透传。"""
        dl.init_duckdb_connection()
        result = dl.load_file(multi_sheet_xlsx, "ss_test", sheet_select="first")
        assert result.row_count == 5


# ═══════════════════════════════════════════════════════════════
#  版本淘汰测试
# ═══════════════════════════════════════════════════════════════

class TestVersionEviction:
    def test_evict_old_versions(self, tmp_path):
        """max_versions=1 时淘汰旧版本。"""
        dl.init_duckdb_connection()

        for tag in ["20260615", "20260616", "20260617"]:
            p = tmp_path / f"test_{tag}.csv"
            p.write_text(
                f"产品名称,日期\nA,{tag}\n", encoding="utf-8",
            )
            dl.load_file(str(p), f"holding_{tag}", date_tag=tag, table_type="holding")

        assert len([t for t in dl._loaded_tables.values()
                    if t.table_type == "holding"]) == 3

        evicted = dl.evict_old_versions("holding", max_versions=1)
        assert len(evicted) == 2
        assert "holding_20260617" in dl._loaded_tables
        assert "holding_20260615" not in dl._loaded_tables
        assert "holding_20260616" not in dl._loaded_tables

    def test_evict_no_date_tag(self):
        """无 date_tag 的表不参与淘汰。"""
        dl.init_duckdb_connection()
        conn = dl.get_connection()
        conn.execute('CREATE TABLE no_date_table AS SELECT 1 AS col')
        dl._loaded_tables["no_date_table"] = dl.LoadResult(
            table_name="no_date_table", file_path="", row_count=1, col_count=1,
            encoding="", date_tag=None, field_map={}, unmatched_cols=[],
            missing_required=[], warnings=[], table_type="holding",
        )
        evicted = dl.evict_old_versions("holding", max_versions=1)
        assert len(evicted) == 0


# ═══════════════════════════════════════════════════════════════
#  LARGE_FILE_THRESHOLD 路由测试
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  自动加载测试（Phase 1）
# ═══════════════════════════════════════════════════════════════

class TestAutoLoad:
    def _make_config(self, work_dir, rules, enabled=True, max_versions=3):
        return {
            "app": {
                "work_dir": str(work_dir),
                "auto_load": {
                    "enabled": enabled,
                    "max_versions": max_versions,
                    "file_rules": rules,
                },
            },
        }

    def test_auto_load_basic(self, tmp_path, monkeypatch):
        """工作目录有匹配文件 → 自动加载。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        f = tmp_path / "持仓产品管理-2026-06-16.csv"
        f.write_text("产品名称,金额\nA,100\n", encoding="utf-8")

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "持仓产品管理-*.csv", "table_type": "holding"},
        ])
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 1
        assert loaded[0]["table_type"] == "holding"
        assert loaded[0]["rows"] == 1

    def test_auto_load_disabled(self, tmp_path, monkeypatch):
        """auto_load.enabled=false → 不加载。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        f = tmp_path / "data.csv"
        f.write_text("A,B\n1,2\n", encoding="utf-8")

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "*.csv", "table_type": "test"},
        ], enabled=False)
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 0

    def test_auto_load_no_match(self, tmp_path, monkeypatch):
        """无匹配文件 → 返回空列表。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        f = tmp_path / "unrelated.txt"
        f.write_text("hello", encoding="utf-8")

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "持仓*.csv", "table_type": "holding"},
        ])
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 0

    def test_auto_load_incremental_skip(self, tmp_path, monkeypatch):
        """已加载且 mtime 未变 → 跳过。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        f = tmp_path / "test_20260616.csv"
        f.write_text("产品名称,金额\nA,100\n", encoding="utf-8")

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "test_*.csv", "table_type": "test_type"},
        ])
        loaded1 = wl.auto_load_workdir(config)
        assert len(loaded1) == 1

        loaded2 = wl.auto_load_workdir(config)
        assert len(loaded2) == 0

    def test_auto_load_version_eviction(self, tmp_path, monkeypatch):
        """max_versions=1 → 旧版本被淘汰。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        for tag in ["20260615", "20260616"]:
            f = tmp_path / f"data_{tag}.csv"
            f.write_text(f"产品名称,金额\nA_{tag},100\n", encoding="utf-8")

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "data_*.csv", "table_type": "evict_type"},
        ], max_versions=1)
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 2

        remaining = [
            t for t in dl._loaded_tables.values()
            if t.table_type == "evict_type"
        ]
        assert len(remaining) == 1
        assert remaining[0].date_tag == "20260616"

    def test_auto_load_empty_workdir(self, tmp_path, monkeypatch):
        """空工作目录 → 不报错，返回空。"""
        import tools.workdir_loader as wl
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        monkeypatch.setattr(wl, "get_work_dir", lambda: empty)

        dl.init_duckdb_connection()
        config = self._make_config(empty, [
            {"pattern": "*.csv", "table_type": "test"},
        ])
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 0

    def test_auto_load_sheet_select_first(self, tmp_path, monkeypatch):
        """sheet_select=first 透传到 load_file。"""
        import tools.workdir_loader as wl
        monkeypatch.setattr(wl, "get_work_dir", lambda: tmp_path)

        p = tmp_path / "估值表查询(2026-06-16).xlsx"
        with pd.ExcelWriter(str(p)) as writer:
            pd.DataFrame({"A": [1, 2]}).to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({"B": [3, 4]}).to_excel(writer, sheet_name="Sheet2", index=False)

        dl.init_duckdb_connection()
        config = self._make_config(tmp_path, [
            {"pattern": "估值表查询(*.xlsx", "table_type": "valuation",
             "sheet_select": "first"},
        ])
        loaded = wl.auto_load_workdir(config)
        assert len(loaded) == 1
        assert loaded[0]["rows"] == 2


# ═══════════════════════════════════════════════════════════════
#  字段映射扩展测试（Phase 2）
# ═══════════════════════════════════════════════════════════════

class TestDictTableMapExtension:
    def test_new_types_in_map(self):
        """8 种新文件类型在 DICT_TABLE_MAP 中。"""
        new_types = [
            "holding_detail", "valuation", "subscription", "asset_position",
            "cashflow_gap", "bond_pledge", "account_flow", "repo_trade",
            "fund_position",
        ]
        for t in new_types:
            assert t in dl.DICT_TABLE_MAP, f"{t} 不在 DICT_TABLE_MAP 中"

    def test_load_new_dictionaries(self):
        """每种新类型的字典都能成功加载。"""
        new_types = [
            "holding_detail", "valuation", "subscription", "asset_position",
            "cashflow_gap", "bond_pledge", "account_flow", "repo_trade",
            "fund_position",
        ]
        for t in new_types:
            d = dl.load_dictionary(t)
            assert d is not None, f"字典 {t} 加载失败"
            assert "fields" in d, f"字典 {t} 缺少 fields"
            assert len(d['fields']) > 0, f"字典 {t} 无字段定义"

    def test_old_types_still_work(self):
        """原有 6 种类型字典不受影响。"""
        old_types = ["holding", "nav", "rating_entity", "rating_bond", "monitoring"]
        for t in old_types:
            d = dl.load_dictionary(t)
            assert d is not None, f"原字典 {t} 加载失败"


class TestSharedSynonyms:
    def test_synonyms_file_loads(self):
        """shared_synonyms.yaml 可正常加载。"""
        syns = dl._load_shared_synonyms()
        assert "product_name" in syns
        assert "entity_name" in syns
        assert "stat_date" in syns

    def test_synonyms_merged_into_holding(self):
        """共享同义词合并到 holding 字典。"""
        d = dl.load_dictionary("holding")
        assert d is not None
        for field_def in d['fields']:
            if field_def['semantic'] == '产品名称':
                candidates = field_def['physical_candidates']
                assert '组合名称' in candidates
                break

    def test_synonyms_merged_into_new_dict(self):
        """共享同义词合并到新字典。"""
        d = dl.load_dictionary("holding_detail")
        assert d is not None
        for field_def in d['fields']:
            if field_def['semantic'] == '限额占用主体':
                candidates = field_def['physical_candidates']
                assert '限额占用主体' in candidates
                assert '主体名称' in candidates
                break

    def test_synonyms_no_duplicates(self):
        """合并后不产生重复候选列名。"""
        d = dl.load_dictionary("valuation")
        assert d is not None
        for field_def in d['fields']:
            candidates = field_def.get('physical_candidates', [])
            assert len(candidates) == len(set(candidates)), (
                f"字段 {field_def['semantic']} 有重复候选: {candidates}"
            )


class TestMappingOnNewTypes:
    def test_holding_detail_mapping(self, tmp_path):
        """holding_detail CSV 映射正确。"""
        p = tmp_path / "detail.csv"
        p.write_text(
            "持仓日期,产品简称,资产代码,资产市值_穿透后\n"
            "2026-06-16,产品A,C001,1000000\n",
            encoding="utf-8",
        )
        dl.init_duckdb_connection()
        result = dl.load_file(str(p), "detail_test", table_type="holding_detail")
        assert result.field_map.get("持仓日期") == "持仓日期"
        assert result.field_map.get("产品名称") == "产品简称"
        assert result.field_map.get("资产代码") == "资产代码"

    def test_subscription_mapping(self, tmp_path):
        """subscription CSV 映射正确。"""
        p = tmp_path / "subs.csv"
        p.write_text(
            "统计日期,产品名称,申购金额,赎回金额\n"
            "2026-06-16,A,1000,500\n",
            encoding="utf-8",
        )
        dl.init_duckdb_connection()
        result = dl.load_file(str(p), "subs_test", table_type="subscription")
        assert result.field_map.get("统计日期") == "统计日期"
        assert result.field_map.get("产品名称") == "产品名称"

    def test_synonym_based_mapping(self, tmp_path):
        """通过共享同义词匹配：'组合名称' → 产品名称。"""
        p = tmp_path / "syn_test.csv"
        p.write_text(
            "统计日期,组合名称,余额\n"
            "2026-06-16,产品A,100000\n",
            encoding="utf-8",
        )
        dl.init_duckdb_connection()
        result = dl.load_file(str(p), "syn_test", table_type="fund_position")
        assert result.field_map.get("产品名称") == "组合名称"


class TestFieldMapConflict:
    def test_conflict_warning(self, tmp_path, capsys):
        """多表同语义名映射到不同物理列时输出警告。"""
        dl.init_duckdb_connection()

        p1 = tmp_path / "t1.csv"
        p1.write_text("产品名称,金额\nA,100\n", encoding="utf-8")
        dl.load_file(str(p1), "t1", table_type="holding")

        p2 = tmp_path / "t2.csv"
        p2.write_text("产品简称,金额\nB,200\n", encoding="utf-8")
        dl.load_file(str(p2), "t2", table_type="holding_detail")

        dl.get_all_field_maps()
        captured = capsys.readouterr()
        if "产品名称" in dl._loaded_tables["t1"].field_map and \
           "产品名称" in dl._loaded_tables["t2"].field_map:
            phys1 = dl._loaded_tables["t1"].field_map["产品名称"]
            phys2 = dl._loaded_tables["t2"].field_map["产品名称"]
            if phys1 != phys2:
                assert "冲突" in captured.out


class TestLargeFileRouting:
    def test_small_file_uses_preprocess(self, simple_xlsx):
        """小文件走 preprocess_excel 路径。"""
        dl.init_duckdb_connection()
        assert os.path.getsize(simple_xlsx) < dl.LARGE_FILE_THRESHOLD
        result = dl.load_file(simple_xlsx, "small_excel_test")
        assert result.row_count == 3

    def test_threshold_constant(self):
        """LARGE_FILE_THRESHOLD 为 10MB。"""
        assert dl.LARGE_FILE_THRESHOLD == 10 * 1024 * 1024
