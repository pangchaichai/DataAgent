"""
tests/test_large_data_integration.py — UAT 和性能集成测试

使用 scripts/generate_test_data.py 生成的测试数据验证：
  1. UAT: 14 种文件类型的加载、字段映射、auto_load 匹配
  2. PERF: 大文件流式加载、>10MB 阈值触发、加载耗时基准

运行前提: python scripts/generate_test_data.py (生成测试数据)
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.data_loader as dl

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UAT_DIR = os.path.join(PROJECT_ROOT, "data", "test_data", "uat")
PERF_DIR = os.path.join(PROJECT_ROOT, "data", "test_data", "perf")
PERF_CSV_DIR = os.path.join(PROJECT_ROOT, "data", "test_data", "perf", "csv")


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


def _ensure_conn():
    dl.init_duckdb_connection(max_memory="300MB", threads=2)
    return dl.get_connection()


def _uat_exists():
    return os.path.isdir(UAT_DIR) and len(os.listdir(UAT_DIR)) >= 14


def _perf_exists():
    return os.path.isdir(PERF_DIR) and any(
        f.endswith(('.xls', '.xlsx')) for f in os.listdir(PERF_DIR)
    )


def _perf_csv_exists():
    return os.path.isdir(PERF_CSV_DIR) and any(
        f.endswith('.csv') for f in os.listdir(PERF_CSV_DIR)
    )


skip_no_uat = pytest.mark.skipif(
    not _uat_exists(),
    reason="UAT 测试数据未生成，运行: python scripts/generate_test_data.py --uat"
)
skip_no_perf = pytest.mark.skipif(
    not _perf_exists(),
    reason="性能测试数据未生成，运行: python scripts/generate_test_data.py --perf"
)
skip_no_perf_csv = pytest.mark.skipif(
    not _perf_csv_exists(),
    reason="CSV 性能测试数据未生成，运行: python scripts/generate_test_data.py --perf-csv"
)


# ═══════════════════════════════════════════════════════════════
#  UAT: 14 种文件类型加载测试
# ═══════════════════════════════════════════════════════════════

UAT_FILE_SPECS = [
    # (filename, table_type, expected_rows, expected_date_tag_YYYYMMDD)
    ("持仓产品管理-2026-06-16.xls", "holding", 150, "20260616"),
    ("底层资产持仓及债券信息表0616.xlsx", "holding_detail", 120, None),
    ("净值结果管理2026-06-15-2026-06-15.xlsx", "nav", 50, "20260615"),
    ("评级结果202606160911.xls", "rating_entity", 80, None),
    ("投资债券评级结果202606160912.xls", "rating_bond", 100, None),
    ("监控值查询 - 2026-06-22T084857.169.xlsx", "monitoring", 80, "20260622"),
    ("估值表查询(2026-06-16).xlsx", "valuation", 50, "20260616"),
    ("申赎数据0615.xlsx", "subscription", 50, None),
    ("实时资产头寸查询(2026-06-16).xlsx", "asset_position", 100, "20260616"),
    ("现金流缺口分析(2026-06-16).xlsx", "cashflow_gap", 80, "20260616"),
    ("债券质押查询(2026-06-16).xlsx", "bond_pledge", 60, "20260616"),
    ("账户流水(2026-06-16).xlsx", "account_flow", 100, "20260616"),
    ("质押式回购投资交易查询(2026-06-16).xlsx", "repo_trade", 200, "20260616"),
    ("组合资金账户头寸(2026-06-16).xlsx", "fund_position", 40, "20260616"),
]


class TestUATFileLoading:

    @skip_no_uat
    @pytest.mark.parametrize(
        "filename,expected_type,expected_rows,expected_date",
        UAT_FILE_SPECS,
        ids=[s[1] for s in UAT_FILE_SPECS],
    )
    def test_load_file_type(self, filename, expected_type, expected_rows, expected_date):
        _ensure_conn()
        fp = os.path.join(UAT_DIR, filename)
        result = dl.load_file(fp, filename)
        assert result.row_count == expected_rows, (
            f"{expected_type}: expected {expected_rows} rows, got {result.row_count}"
        )

    @skip_no_uat
    @pytest.mark.parametrize(
        "filename,expected_type,expected_rows,expected_date",
        [s for s in UAT_FILE_SPECS if s[3] is not None],
        ids=[s[1] for s in UAT_FILE_SPECS if s[3] is not None],
    )
    def test_date_extraction(self, filename, expected_type, expected_rows, expected_date):
        extracted = dl.extract_date_from_filename(filename)
        assert extracted == expected_date, (
            f"{expected_type}: expected date '{expected_date}', got '{extracted}'"
        )


class TestUATTableTypes:

    @skip_no_uat
    def test_dict_table_map_covers_all_types(self):
        """DICT_TABLE_MAP 应覆盖所有 14 种文件类型"""
        expected_types = {s[1] for s in UAT_FILE_SPECS}
        actual_types = set(dl.DICT_TABLE_MAP.keys())
        missing = expected_types - actual_types
        assert not missing, f"DICT_TABLE_MAP 缺少类型: {missing}"


class TestUATFieldMapping:

    @skip_no_uat
    def test_holding_field_map(self):
        """持仓表加载后应有字段映射"""
        _ensure_conn()
        fp = os.path.join(UAT_DIR, "持仓产品管理-2026-06-16.xls")
        result = dl.load_file(fp, "holding_test", table_type="holding")
        assert result.field_map, "持仓表应有字段映射"
        assert result.table_type == "holding"

    @skip_no_uat
    def test_holding_detail_field_map(self):
        """底层持仓表加载后应有字段映射"""
        _ensure_conn()
        fp = os.path.join(UAT_DIR, "底层资产持仓及债券信息表0616.xlsx")
        result = dl.load_file(fp, "holding_detail_test", table_type="holding_detail")
        assert result.field_map, "底层持仓表应有字段映射"
        assert result.table_type == "holding_detail"

    @skip_no_uat
    def test_nav_field_map(self):
        """净值表加载后应有字段映射"""
        _ensure_conn()
        fp = os.path.join(UAT_DIR, "净值结果管理2026-06-15-2026-06-15.xlsx")
        result = dl.load_file(fp, "nav_test", table_type="nav")
        assert result.field_map, "净值表应有字段映射"
        assert result.table_type == "nav"

    @skip_no_uat
    def test_monitoring_field_map(self):
        """监控表加载后应有字段映射"""
        _ensure_conn()
        fp = os.path.join(UAT_DIR, "监控值查询 - 2026-06-22T084857.169.xlsx")
        result = dl.load_file(fp, "monitoring_test", table_type="monitoring")
        assert result.field_map, "监控表应有字段映射"
        assert result.table_type == "monitoring"


# ═══════════════════════════════════════════════════════════════
#  UAT: auto_load_workdir 测试
# ═══════════════════════════════════════════════════════════════

class TestUATAutoLoad:

    @skip_no_uat
    def test_auto_load_matches_all_files(self):
        """auto_load_workdir 应匹配 UAT 目录的全部 14 个文件"""
        from unittest.mock import patch
        from pathlib import Path

        from tools.workdir_loader import auto_load_workdir
        _ensure_conn()
        config = {
            "app": {
                "work_dir": UAT_DIR,
                "auto_load": {
                    "enabled": True,
                    "file_rules": [
                        {"pattern": "持仓产品管理*", "table_type": "holding", "sheet_select": "first"},
                        {"pattern": "底层资产持仓*", "table_type": "holding_detail"},
                        {"pattern": "净值结果管理*", "table_type": "nav"},
                        {"pattern": "评级结果*", "table_type": "rating_entity"},
                        {"pattern": "投资债券评级*", "table_type": "rating_bond"},
                        {"pattern": "监控值查询*", "table_type": "monitoring"},
                        {"pattern": "估值表查询*", "table_type": "valuation"},
                        {"pattern": "申赎数据*", "table_type": "subscription"},
                        {"pattern": "实时资产头寸*", "table_type": "asset_position"},
                        {"pattern": "现金流缺口*", "table_type": "cashflow_gap"},
                        {"pattern": "债券质押查询*", "table_type": "bond_pledge"},
                        {"pattern": "账户流水*", "table_type": "account_flow"},
                        {"pattern": "质押式回购*", "table_type": "repo_trade"},
                        {"pattern": "组合资金账户*", "table_type": "fund_position"},
                    ],
                },
            },
        }
        with patch("tools.workdir_loader.get_work_dir", return_value=Path(UAT_DIR)):
            results = auto_load_workdir(config)
        loaded_types = {r["table_type"] for r in results}
        expected_types = {r["table_type"] for r in config["app"]["auto_load"]["file_rules"]}
        missing = expected_types - loaded_types
        assert not missing, f"auto_load 未匹配的文件类型: {missing}"
        assert len(results) == 14, f"应加载 14 个文件, 实际 {len(results)}"


# ═══════════════════════════════════════════════════════════════
#  PERF: 性能/压力测试
# ═══════════════════════════════════════════════════════════════

class TestPerfLargeExcel:

    @skip_no_perf
    def test_large_xls_triggers_streaming(self):
        """>10MB 的 XLS 文件应触发流式加载路径"""
        fp = os.path.join(PERF_DIR, "持仓产品管理-2026-06-16.xls")
        size_mb = os.path.getsize(fp) / (1024 * 1024)
        assert size_mb > 10, f"文件应 >10MB, 实际 {size_mb:.1f}MB"

        _ensure_conn()
        start = time.time()
        result = dl.load_file(fp, "perf_holding", sheet_select="first")
        elapsed = time.time() - start

        assert result.row_count > 0, "加载应成功"
        print(f"\n  [PERF] 大 XLS 加载: {result.row_count} rows, {elapsed:.1f}s")

    @skip_no_perf
    def test_large_xlsx_load_time(self):
        """30K 行回购交易 XLSX 加载耗时基准"""
        fp = os.path.join(PERF_DIR, "质押式回购投资交易查询(2026-06-16).xlsx")
        _ensure_conn()
        start = time.time()
        result = dl.load_file(fp, "perf_repo")
        elapsed = time.time() - start

        assert result.row_count >= 25000, f"应 ≥25K rows, 实际 {result.row_count}"
        print(f"\n  [PERF] 大 XLSX 加载: {result.row_count} rows, {elapsed:.1f}s")

    @skip_no_perf
    def test_multi_sheet_xls_streaming(self):
        """多 sheet XLS 流式加载测试（3 sheets）"""
        fp = os.path.join(PERF_DIR, "持仓产品管理-2026-06-16.xls")
        _ensure_conn()
        start = time.time()
        result = dl.load_file(fp, "perf_holding_all", sheet_select="merge_all")
        elapsed = time.time() - start

        assert result.row_count >= 10000, f"合并多 sheet 应 ≥10K rows, 实际 {result.row_count}"
        print(f"\n  [PERF] 多 sheet 合并: {result.row_count} rows, {elapsed:.1f}s")


class TestPerfNativeCSV:

    @skip_no_perf_csv
    def test_native_csv_large_utf8(self):
        """50K 行 UTF-8 CSV 原生加载"""
        fp = os.path.join(PERF_CSV_DIR, "持仓产品管理-2026-06-16.csv")
        _ensure_conn()
        start = time.time()
        result = dl.load_file(fp, "perf_csv_holding")
        elapsed = time.time() - start

        assert result.row_count >= 40000, f"应 ≥40K rows, 实际 {result.row_count}"
        print(f"\n  [PERF] CSV UTF-8 原生加载: {result.row_count} rows, {elapsed:.1f}s")

    @skip_no_perf_csv
    def test_native_csv_gb18030(self):
        """50K 行 GB18030 CSV 加载"""
        fp = os.path.join(PERF_CSV_DIR, "持仓产品管理-2026-06-16-gb18030.csv")
        _ensure_conn()
        start = time.time()
        result = dl.load_file(fp, "perf_csv_gb18030")
        elapsed = time.time() - start

        assert result.row_count >= 40000, f"应 ≥40K rows, 实际 {result.row_count}"
        print(f"\n  [PERF] CSV GB18030 加载: {result.row_count} rows, {elapsed:.1f}s")

    @skip_no_perf_csv
    def test_csv_load_time_benchmark(self):
        """CSV 加载耗时基准: 3 个大文件串行加载"""
        _ensure_conn()
        total_rows = 0
        start = time.time()
        for fname in [
            "持仓产品管理-2026-06-16.csv",
            "质押式回购投资交易查询(2026-06-16).csv",
            "底层资产持仓及债券信息表0616.csv",
        ]:
            fp = os.path.join(PERF_CSV_DIR, fname)
            if not os.path.exists(fp):
                continue
            tname = fname.replace(".csv", "").replace("(", "").replace(")", "")
            result = dl.load_file(fp, f"bench_{tname[:20]}")
            total_rows += result.row_count
        elapsed = time.time() - start

        assert total_rows > 100000, f"总行数应 >100K, 实际 {total_rows}"
        print(f"\n  [PERF] 3 CSV 串行加载: {total_rows} rows, {elapsed:.1f}s")


# ═══════════════════════════════════════════════════════════════
#  PERF: 版本淘汰测试
# ═══════════════════════════════════════════════════════════════

class TestPerfVersionEviction:

    @skip_no_uat
    def test_evict_keeps_latest(self):
        """加载多个同类型文件后，evict_old_versions 仅保留最新"""
        _ensure_conn()
        fp = os.path.join(UAT_DIR, "持仓产品管理-2026-06-16.xls")
        dl.load_file(fp, "holding_v1", date_tag="20260615", table_type="holding")
        dl.load_file(fp, "holding_v2", date_tag="20260616", table_type="holding")
        dl.load_file(fp, "holding_v3", date_tag="20260614", table_type="holding")

        evicted = dl.evict_old_versions("holding", max_versions=1)
        assert len(evicted) == 2, f"应淘汰 2 个旧版本, 实际淘汰 {len(evicted)}"

        remaining = [t for t in dl._loaded_tables if dl._loaded_tables[t].table_type == "holding"]
        assert len(remaining) == 1, f"应保留 1 个, 实际 {len(remaining)}"


# ═══════════════════════════════════════════════════════════════
#  PERF: 内存占用估算
# ═══════════════════════════════════════════════════════════════

class TestPerfMemory:

    @skip_no_perf_csv
    def test_duckdb_memory_under_limit(self):
        """加载大 CSV 后 DuckDB 内存应在限制范围内"""
        import tracemalloc
        tracemalloc.start()
        _ensure_conn()

        fp = os.path.join(PERF_CSV_DIR, "持仓产品管理-2026-06-16.csv")
        dl.load_file(fp, "mem_test_holding")

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_mb = peak / (1024 * 1024)
        print(f"\n  [PERF] Python 内存峰值: {peak_mb:.1f} MB")
        assert peak_mb < 500, f"Python 内存峰值 {peak_mb:.1f}MB 超过 500MB 限制"
