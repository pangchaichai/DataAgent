"""
tests/test_column_resolution.py — 字段映射解析回归测试

覆盖：
  1. calculators/columns.py resolve_columns() 基础功能
  2. 每个计算器使用非默认列名（模拟物理列名不同于语义名）的场景
  3. tool_dispatch 层的 _resolve_cols_for_table / _resolve_mv_field
  4. 向后兼容（cols=None 时行为不变）
  5. 错误处理（必需列缺失时的 ColumnResolutionError）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import pytest


# ═══════════════════════════════════════════════════════════════
#  resolve_columns 基础测试
# ═══════════════════════════════════════════════════════════════

class TestResolveColumns:

    def test_none_field_map_returns_identity(self):
        from calculators.columns import resolve_columns
        result = resolve_columns(None, ["产品名称", "资产代码"])
        assert result == {"产品名称": "产品名称", "资产代码": "资产代码"}

    def test_basic_mapping(self):
        from calculators.columns import resolve_columns
        field_map = {"产品名称": "产品简称", "资产代码": "债券代码"}
        result = resolve_columns(field_map, ["产品名称", "资产代码"])
        assert result == {"产品名称": "产品简称", "资产代码": "债券代码"}

    def test_missing_required_raises(self):
        from calculators.columns import ColumnResolutionError, resolve_columns
        field_map = {"产品名称": "产品简称"}
        with pytest.raises(ColumnResolutionError, match="资产代码"):
            resolve_columns(field_map, ["产品名称", "资产代码"])

    def test_optional_fallback_to_semantic(self):
        from calculators.columns import resolve_columns
        field_map = {"产品名称": "产品简称"}
        result = resolve_columns(
            field_map,
            required=["产品名称"],
            optional=["外部评级"],
        )
        assert result["产品名称"] == "产品简称"
        assert result["外部评级"] == "外部评级"

    def test_optional_uses_mapping_when_available(self):
        from calculators.columns import resolve_columns
        field_map = {"产品名称": "产品简称", "外部评级": "债项外部评级"}
        result = resolve_columns(
            field_map,
            required=["产品名称"],
            optional=["外部评级"],
        )
        assert result["外部评级"] == "债项外部评级"

    def test_empty_field_map_raises_for_required(self):
        from calculators.columns import ColumnResolutionError, resolve_columns
        with pytest.raises(ColumnResolutionError):
            resolve_columns({}, ["产品名称"])

    def test_constants_are_strings(self):
        from calculators.columns import (
            COL_ASSET_CODE,
            COL_ENTITY,
            COL_MV_PENETRATED,
            COL_PRODUCT_NAME,
        )
        assert isinstance(COL_PRODUCT_NAME, str)
        assert isinstance(COL_ASSET_CODE, str)
        assert isinstance(COL_ENTITY, str)
        assert isinstance(COL_MV_PENETRATED, str)


# ═══════════════════════════════════════════════════════════════
#  concentration.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestConcentrationWithCols:

    @pytest.fixture
    def conn_alt_cols(self):
        """表列名使用非默认物理列名"""
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品A', '象屿集团', 5000000.0),
                ('产品A', '象屿集团', 3000000.0),
                ('产品A', '建发集团', 2000000.0),
                ('产品B', '象屿集团', 8000000.0),
                ('产品B', '建发集团', 6000000.0)
            ) AS t("产品简称", "限额占用方", "资产市值_穿透后")
        """)
        yield con
        con.close()

    def test_with_alt_column_names(self, conn_alt_cols):
        from calculators.concentration import calc_entity_concentration
        cols = {
            "产品名称": "产品简称",
            "限额占用主体": "限额占用方",
        }
        results = calc_entity_concentration(
            conn=conn_alt_cols,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias={},
            cols=cols,
        )
        assert len(results) >= 2
        products = {r.product_name for r in results}
        assert '产品A' in products

    def test_backward_compat_no_cols(self):
        """cols=None 使用默认语义名——与原有测试行为相同"""
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品1', '象屿集团', 5000000.0)
            ) AS t("产品名称", "限额占用方主体", "穿透后市值")
        """)
        from calculators.concentration import calc_entity_concentration
        results = calc_entity_concentration(
            conn=con,
            holding_table='test_holding',
            market_value_field='穿透后市值',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias={},
        )
        assert len(results) >= 1
        con.close()


# ═══════════════════════════════════════════════════════════════
#  nav_metrics.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestNavMetricsWithCols:

    @pytest.fixture
    def nav_conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_nav AS SELECT * FROM (VALUES
                ('产品A', '2026-05-14', 1.0523, 500000000.0, 498000000.0,
                 3.25, 3.10, 3.50, 4.20, 2.80, 5.60)
            ) AS t("基金简称", "数据日期", "单位净值/万份收益(公布)",
                   "产品总资产(公布)", "产品净资产(公布)", "七日年化收益率(公布)%",
                   "近1月年化收益率(%)", "近3月年化收益率(%)", "近1年收益率(%)",
                   "今年以来收益率(%)", "成立以来收益率(%)")
        """)
        yield con
        con.close()

    def test_with_alt_product_and_date(self, nav_conn_alt):
        from calculators.nav_metrics import calc_nav_metrics
        cols = {
            "产品名称": "基金简称",
            "估值日期": "数据日期",
        }
        results = calc_nav_metrics(nav_conn_alt, 'test_nav', cols=cols)
        assert len(results) == 1
        assert results[0].product_name == '产品A'
        assert results[0].unit_nav == 1.0523

    def test_backward_compat(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_nav AS SELECT * FROM (VALUES
                ('产品1', '2026-05-14', 1.05, 500000000.0, 498000000.0,
                 3.25, 3.10, 3.50, 4.20, 2.80, 5.60)
            ) AS t("产品简称", "估值日期", "单位净值/万份收益(公布)",
                   "产品总资产(公布)", "产品净资产(公布)", "七日年化收益率(公布)%",
                   "近1月年化收益率(%)", "近3月年化收益率(%)", "近1年收益率(%)",
                   "今年以来收益率(%)", "成立以来收益率(%)")
        """)
        from calculators.nav_metrics import calc_nav_metrics
        results = calc_nav_metrics(con, 'test_nav')
        assert len(results) == 1
        con.close()


# ═══════════════════════════════════════════════════════════════
#  asset_structure.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestAssetStructureWithCols:

    @pytest.fixture
    def conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品A', '债券', 'c01', 5000000.0),
                ('产品A', '债券', 'c02', 3000000.0),
                ('产品A', '公募基金', 'c03', 2000000.0)
            ) AS t("理财产品名称", "一级资产类别", "证券代码", "全穿透市值")
        """)
        yield con
        con.close()

    def test_with_alt_columns(self, conn_alt):
        from calculators.asset_structure import calc_asset_structure
        cols = {
            "产品名称": "理财产品名称",
            "资产代码": "证券代码",
            "G06一级分类": "一级资产类别",
        }
        results = calc_asset_structure(
            conn_alt, 'test_holding', '全穿透市值',
            category_field="G06一级分类", cols=cols,
        )
        assert len(results) == 2
        bond = [r for r in results if r.category == '债券'][0]
        assert bond.ratio_pct == 80.0

    def test_top_n_with_alt_columns(self, conn_alt):
        from calculators.asset_structure import calc_top_n_holdings
        cols = {
            "产品名称": "理财产品名称",
            "资产名称": "资产名称",
            "资产代码": "证券代码",
            "外部评级": "外部评级",
            "G06一级分类": "一级资产类别",
        }
        results = calc_top_n_holdings(
            conn_alt, 'test_holding', '全穿透市值', n=2, cols=cols,
        )
        assert len(results) == 2
        assert results[0]['value'] >= results[1]['value']


# ═══════════════════════════════════════════════════════════════
#  credit_distribution.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestCreditDistributionWithCols:

    @pytest.fixture
    def conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品A', 'c01', 'AAA', 5000000.0),
                ('产品A', 'c02', 'AA+', 3000000.0),
                ('产品A', 'c03', 'AA+', 2000000.0)
            ) AS t("产品简称", "债券代码", "债项外部评级", "资产市值_穿透后")
        """)
        yield con
        con.close()

    def test_with_alt_columns(self, conn_alt):
        from calculators.credit_distribution import calc_credit_distribution
        cols = {
            "产品名称": "产品简称",
            "资产代码": "债券代码",
            "外部评级": "债项外部评级",
        }
        results = calc_credit_distribution(
            conn_alt, 'test_holding', '资产市值_穿透后',
            rating_field="外部评级", cols=cols,
        )
        assert len(results) >= 2
        aaa = [r for r in results if r.rating == 'AAA'][0]
        assert aaa.ratio_pct == 50.0


# ═══════════════════════════════════════════════════════════════
#  position_diff.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestPositionDiffWithCols:

    @pytest.fixture
    def conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE hold_t1 AS SELECT * FROM (VALUES
                ('产品A', 'c01', '债券A', 5000000.0),
                ('产品A', 'c02', '债券B', 3000000.0)
            ) AS t("产品简称", "证券代码", "证券简称", "市值_穿透")
        """)
        con.execute("""
            CREATE TABLE hold_t2 AS SELECT * FROM (VALUES
                ('产品A', 'c01', '债券A', 7000000.0),
                ('产品A', 'c03', '债券C', 4000000.0)
            ) AS t("产品简称", "证券代码", "证券简称", "市值_穿透")
        """)
        yield con
        con.close()

    def test_with_alt_columns(self, conn_alt):
        from calculators.position_diff import calc_position_diff
        cols = {
            "产品名称": "产品简称",
            "资产代码": "证券代码",
            "资产名称": "证券简称",
        }
        results = calc_position_diff(
            conn_alt, 'hold_t1', 'hold_t2', '市值_穿透', cols=cols,
        )
        changes = {r.change_type for r in results}
        assert '加仓' in changes
        assert '清仓' in changes
        assert '新建仓' in changes


# ═══════════════════════════════════════════════════════════════
#  leverage.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestLeverageWithCols:

    @pytest.fixture
    def conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品A', 5000000.0),
                ('产品A', 3000000.0)
            ) AS t("理财产品名称", "市值_穿透")
        """)
        con.execute("""
            CREATE TABLE test_nav AS SELECT * FROM (VALUES
                ('产品A', 1.05, 7000000.0)
            ) AS t("理财产品名称", "单位净值", "基金份额")
        """)
        yield con
        con.close()

    def test_with_alt_product_column(self, conn_alt):
        from calculators.leverage import calc_leverage
        cols = {"产品名称": "理财产品名称"}
        results = calc_leverage(
            conn_alt, 'test_holding', 'test_nav', '市值_穿透', cols=cols,
        )
        assert len(results) == 1
        assert results[0].product_name == '产品A'
        assert abs(results[0].total_assets - 8000000.0) < 1


# ═══════════════════════════════════════════════════════════════
#  liquidity.py 带 cols 参数测试
# ═══════════════════════════════════════════════════════════════

class TestLiquidityWithCols:

    @pytest.fixture
    def conn_alt(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品A', '利率债',  'c01', 4000000.0),
                ('产品A', '信用债',  'c02', 3000000.0),
                ('产品A', '股票',    'c03', 2000000.0),
                ('产品A', '私募基金','c04', 1000000.0)
            ) AS t("理财产品名称", "一级资产类别", "证券代码", "市值_穿透")
        """)
        yield con
        con.close()

    def test_with_alt_columns(self, conn_alt):
        from calculators.liquidity import calc_liquidity
        cols = {
            "产品名称": "理财产品名称",
            "资产代码": "证券代码",
            "G06一级分类": "一级资产类别",
        }
        results = calc_liquidity(
            conn_alt, 'test_holding', '市值_穿透',
            category_field="G06一级分类", cols=cols,
        )
        assert len(results) == 1
        assert abs(results[0].liquid_ratio_pct - 70.0) < 0.1


# ═══════════════════════════════════════════════════════════════
#  tool_dispatch 层集成测试
# ═══════════════════════════════════════════════════════════════

class TestToolDispatchResolution:

    def test_resolve_cols_returns_none_without_loaded_tables(self):
        from agent.tool_dispatch import _resolve_cols_for_table
        result = _resolve_cols_for_table("nonexistent_table", ["产品名称"])
        assert result is None

    def test_resolve_mv_field_passthrough_without_loaded_tables(self):
        from agent.tool_dispatch import _resolve_mv_field
        result = _resolve_mv_field("nonexistent_table", "穿透后市值")
        assert result == "穿透后市值"

    def test_resolve_cols_with_mock_field_map(self, monkeypatch):
        import tools.data_loader as dl
        monkeypatch.setattr(
            dl, 'get_field_map_for_table',
            lambda name: {"产品名称": "产品简称", "资产代码": "证券代码"},
        )
        from agent.tool_dispatch import _resolve_cols_for_table
        result = _resolve_cols_for_table("test_table", ["产品名称", "资产代码"])
        assert result == {"产品名称": "产品简称", "资产代码": "证券代码"}

    def test_resolve_mv_field_with_mapping(self, monkeypatch):
        import tools.data_loader as dl
        monkeypatch.setattr(
            dl, 'get_field_map_for_table',
            lambda name: {"穿透后市值": "资产市值_穿透后（元）"},
        )
        from agent.tool_dispatch import _resolve_mv_field
        result = _resolve_mv_field("test_table", "穿透后市值")
        assert result == "资产市值_穿透后（元）"

    def test_resolve_cols_unmapped_fallback_to_semantic(self, monkeypatch):
        import tools.data_loader as dl
        monkeypatch.setattr(
            dl, 'get_field_map_for_table',
            lambda name: {"产品名称": "产品简称"},
        )
        from agent.tool_dispatch import _resolve_cols_for_table
        result = _resolve_cols_for_table("test_table", ["产品名称", "未映射的列"])
        assert result["产品名称"] == "产品简称"
        assert result["未映射的列"] == "未映射的列"


# ═══════════════════════════════════════════════════════════════
#  端到端集成：模拟真实数据源场景
# ═══════════════════════════════════════════════════════════════

class TestEndToEndFieldMapping:
    """
    模拟真实场景：投资团队上传的 CSV 使用 "资产市值_穿透后（元）" 列名，
    config.yaml 中配置 market_value_field 为语义名 "穿透后市值"，
    字典映射 {"穿透后市值": "资产市值_穿透后（元）"}。
    验证整个链路是否正确传导。
    """

    @pytest.fixture
    def realistic_conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE holding_20260515 AS SELECT * FROM (VALUES
                ('象屿稳健1号', '象屿集团有限公司', 'c01', '债券A',
                 50000000.0, '利率债', 'AAA'),
                ('象屿稳健1号', '建发集团有限公司', 'c02', '债券B',
                 30000000.0, '信用债', 'AA+'),
                ('象屿稳健1号', '国贸控股集团', 'c03', '债券C',
                 20000000.0, '公募基金', 'AA')
            ) AS t("产品简称", "限额占用方", "债券代码", "证券简称",
                   "资产市值_穿透后（元）", "一级资产类别", "债项外部评级")
        """)
        yield con
        con.close()

    def test_concentration_realistic(self, realistic_conn):
        """集中度计算：用投资团队格式的数据"""
        from calculators.concentration import calc_entity_concentration
        cols = {
            "产品名称": "产品简称",
            "限额占用主体": "限额占用方",
        }
        results = calc_entity_concentration(
            conn=realistic_conn,
            holding_table='holding_20260515',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias={},
            cols=cols,
        )
        assert len(results) >= 2
        xiangyu = [r for r in results if r.entity_or_bond == '象屿集团有限公司']
        assert len(xiangyu) == 1
        assert xiangyu[0].concentration_pct == 50.0

    def test_asset_structure_realistic(self, realistic_conn):
        from calculators.asset_structure import calc_asset_structure
        cols = {
            "产品名称": "产品简称",
            "资产代码": "债券代码",
            "G06一级分类": "一级资产类别",
        }
        results = calc_asset_structure(
            realistic_conn, 'holding_20260515', '资产市值_穿透后（元）',
            category_field="G06一级分类", cols=cols,
        )
        assert len(results) == 3
        total_ratio = sum(r.ratio_pct for r in results)
        assert abs(total_ratio - 100.0) < 0.1

    def test_credit_distribution_realistic(self, realistic_conn):
        from calculators.credit_distribution import calc_credit_distribution
        cols = {
            "产品名称": "产品简称",
            "资产代码": "债券代码",
            "外部评级": "债项外部评级",
        }
        results = calc_credit_distribution(
            realistic_conn, 'holding_20260515', '资产市值_穿透后（元）',
            rating_field="外部评级", cols=cols,
        )
        assert len(results) == 3
        aaa = [r for r in results if r.rating == 'AAA'][0]
        assert aaa.ratio_pct == 50.0

    def test_liquidity_realistic(self, realistic_conn):
        from calculators.liquidity import calc_liquidity
        cols = {
            "产品名称": "产品简称",
            "资产代码": "债券代码",
            "G06一级分类": "一级资产类别",
        }
        results = calc_liquidity(
            realistic_conn, 'holding_20260515', '资产市值_穿透后（元）',
            category_field="G06一级分类", cols=cols,
        )
        assert len(results) == 1
        r = results[0]
        # 利率债(50M,T1) + 信用债(30M,T2) + 公募基金(20M,T1) = 100M/100M = 100% liquid
        assert abs(r.liquid_ratio_pct - 100.0) < 0.1
        # 高流动性(T1): 利率债+公募基金 = 70M/100M = 70%
        assert abs(r.high_liquidity_ratio_pct - 70.0) < 0.1
