"""
tests/test_calculators.py — 固化计算模块单元测试

覆盖：concentration.py / nav_metrics.py / asset_structure.py /
       credit_distribution.py / position_diff.py / leverage.py / liquidity.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import pytest

from calculators.concentration import ConcentrationResult, calc_entity_concentration


@pytest.fixture
def conn():
    """创建测试用 DuckDB 连接 + 持仓表"""
    con = duckdb.connect(':memory:')
    con.execute("""
        CREATE TABLE test_holding AS SELECT * FROM (VALUES
            ('产品1', '象屿集团', 5000000.0, 10000000.0),
            ('产品1', '象屿集团', 3000000.0, 10000000.0),
            ('产品1', '建发集团', 2000000.0, 10000000.0),
            ('产品2', '象屿集团', 8000000.0, 20000000.0),
            ('产品2', '建发集团', 6000000.0, 20000000.0),
            ('产品2', '国贸控股', 2000000.0, 20000000.0),
        ) AS t("产品名称", "限额占用方主体", "资产市值_穿透后（元）", "总市值")
    """)
    yield con
    con.close()


@pytest.fixture
def entity_alias():
    return {
        '厦门象屿集团有限公司': '象屿集团',
        '象屿股份': '象屿集团',
        '象屿': '象屿集团',
    }


@pytest.fixture
def group_mapping():
    return {
        '象屿集团': '象屿系',
        '建发集团': '建发系',
    }


class TestEntityConcentration:
    """主体集中度计算测试"""

    def test_basic_calculation(self, conn, entity_alias):
        """基础计算：无集团合并，无产品过滤"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias=entity_alias,
        )
        # 产品1: 象屿=80%, 建发=20% → 象屿超标
        # 产品2: 象屿=40%, 建发=30%, 国贸=10% → 象屿/建发超标
        assert len(results) >= 2
        names = {(r.product_name, r.entity_or_bond) for r in results}
        assert ('产品1', '象屿集团') in names
        assert ('产品2', '象屿集团') in names

    def test_group_merge(self, conn, entity_alias, group_mapping):
        """集团合并：象屿系 = 象屿集团合并"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=True,
            group_mapping=group_mapping,
            entity_alias=entity_alias,
        )
        # 产品1: 象屿系=80%, 建发系=20% → 都超标
        assert len(results) >= 2
        names = {(r.product_name, r.entity_or_bond) for r in results}
        assert ('产品1', '象屿系') in names

    def test_concentration_value(self, conn, entity_alias):
        """集中度数值精确性"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=50.0,  # 阈值抬高，让所有结果都能返回
            use_group_merge=False,
            group_mapping={},
            entity_alias=entity_alias,
        )
        # 产品1 象屿 = 5M+3M = 8M / 30M? 不，total_nav 是用 SUM(市值字段) 分产品计算的
        # 找到产品1象屿
        p1_xiangyu = [r for r in results if r.product_name == '产品1' and r.entity_or_bond == '象屿集团']
        assert len(p1_xiangyu) > 0
        # 集中度 = 8M / (5M+3M+2M) = 8M / 10M = 80%
        assert p1_xiangyu[0].concentration_pct == 80.0

    def test_threshold_respected(self, conn, entity_alias):
        """阈值生效：低于阈值的不应出现在结果中"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=90.0,  # 极高阈值
            use_group_merge=False,
            group_mapping={},
            entity_alias=entity_alias,
        )
        # 没有主体集中度超过 90%
        assert len(results) == 0

    def test_product_filter(self, conn, entity_alias, group_mapping):
        """产品过滤：只计算指定产品"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=True,
            group_mapping=group_mapping,
            entity_alias=entity_alias,
            product_filter=['产品1'],
        )
        # 只包含产品1
        products = {r.product_name for r in results}
        assert products == {'产品1'}

    def test_result_dataclass(self, conn, entity_alias):
        """返回的 ConcentrationResult 应包含所有必要字段"""
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias=entity_alias,
        )
        for r in results:
            assert isinstance(r, ConcentrationResult)
            assert r.concentration_pct > 0
            assert r.market_value > 0
            assert r.total_nav > 0
            assert r.is_breach is True
            assert r.market_value_field == '资产市值_穿透后（元）'

    def test_zero_total_skip(self, conn):
        """总市值为 0 的产品应被跳过"""
        conn.execute("INSERT INTO test_holding VALUES ('产品3', '主体X', 0.0, 0.0)")
        results = calc_entity_concentration(
            conn=conn,
            holding_table='test_holding',
            market_value_field='资产市值_穿透后（元）',
            threshold_pct=10.0,
            use_group_merge=False,
            group_mapping={},
            entity_alias={},
            product_filter=['产品3'],
        )
        # 产品3 总市值=0，应被跳过
        assert len(results) == 0
# ═══════════════════════════════════════════════════════════════
#  NavMetrics 测试
# ═══════════════════════════════════════════════════════════════

class TestNavMetrics:
    @pytest.fixture
    def nav_conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_nav AS SELECT * FROM (VALUES
                ('产品1', '2026-05-14', 1.0523, 500000000.0, 498000000.0, 3.25, 3.10, 3.50, 4.20, 2.80, 5.60),
                ('产品2', '2026-05-14', 1.0815, 800000000.0, 796000000.0, 2.85, 2.90, 3.10, 3.80, 2.50, 4.90),
            ) AS t("产品简称", "估值日期", "单位净值/万份收益(公布)",
                   "产品总资产(公布)", "产品净资产(公布)", "七日年化收益率(公布)%",
                   "近1月年化收益率(%)", "近3月年化收益率(%)", "近1年收益率(%)",
                   "今年以来收益率(%)", "成立以来收益率(%)")
        """)
        yield con
        con.close()

    def test_basic_nav_calc(self, nav_conn):
        from calculators.nav_metrics import calc_nav_metrics
        results = calc_nav_metrics(nav_conn, 'test_nav')
        assert len(results) == 2
        assert results[0].unit_nav == 1.0523

    def test_product_filter(self, nav_conn):
        from calculators.nav_metrics import calc_nav_metrics
        results = calc_nav_metrics(nav_conn, 'test_nav', product_filter=['产品1'])
        assert len(results) == 1


# ═══════════════════════════════════════════════════════════════
#  AssetStructure 测试
# ═══════════════════════════════════════════════════════════════

class TestAssetStructure:
    @pytest.fixture
    def conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品1', '债券', 'code001', 5000000.0),
                ('产品1', '债券', 'code002', 3000000.0),
                ('产品1', '同业存单', 'code003', 2000000.0),
                ('产品2', '债券', 'code004', 8000000.0),
                ('产品2', '公募基金', 'code005', 2000000.0),
            ) AS t("产品名称", "G06一级分类", "资产代码", "资产市值_穿透后（元）")
        """)
        yield con
        con.close()

    def test_by_product(self, conn):
        from calculators.asset_structure import calc_asset_structure
        results = calc_asset_structure(conn, 'test_holding', '资产市值_穿透后（元）')
        ratios = {(r.product_name, r.category): r.ratio_pct for r in results}
        assert ratios[('产品1', '债券')] == 80.0

    def test_global(self, conn):
        from calculators.asset_structure import calc_asset_structure
        results = calc_asset_structure(conn, 'test_holding', '资产市值_穿透后（元）', group_by_product=False)
        total = sum(r.ratio_pct for r in results)
        assert abs(total - 100.0) < 0.1

    def test_top_n(self, conn):
        from calculators.asset_structure import calc_top_n_holdings
        results = calc_top_n_holdings(conn, 'test_holding', '资产市值_穿透后（元）', n=3)
        assert len(results) == 3
        assert results[0]['value'] >= results[1]['value']


# ═══════════════════════════════════════════════════════════════
#  CreditDistribution 测试
# ═══════════════════════════════════════════════════════════════

class TestCreditDistribution:
    @pytest.fixture
    def conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品1', 'code001', 'AAA', 5000000.0),
                ('产品1', 'code002', 'AA+', 3000000.0),
                ('产品1', 'code003', 'AA+', 2000000.0),
                ('产品2', 'code004', 'AAA', 8000000.0),
                ('产品2', 'code005', 'AA', 2000000.0),
            ) AS t("产品名称", "资产代码", "外部评级", "资产市值_穿透后（元）")
        """)
        yield con
        con.close()

    def test_external_rating(self, conn):
        from calculators.credit_distribution import calc_credit_distribution
        results = calc_credit_distribution(conn, 'test_holding', '资产市值_穿透后（元）')
        assert len(results) >= 3
        aaa = [r for r in results if r.rating == 'AAA'][0]
        assert aaa.ratio_pct > 50

    def test_product_filter(self, conn):
        from calculators.credit_distribution import calc_credit_distribution
        results = calc_credit_distribution(
            conn, 'test_holding', '资产市值_穿透后（元）', product_filter=['产品2'])
        total = sum(r.ratio_pct for r in results)
        assert abs(total - 100.0) < 0.1

    def test_rating_migration(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE rate_now AS SELECT * FROM (VALUES
                ('主体A', 'AAA'), ('主体B', 'AA'), ('主体C', 'AA+')
            ) AS t("企业名称", "内部评级结果")
        """)
        con.execute("""
            CREATE TABLE rate_prev AS SELECT * FROM (VALUES
                ('主体A', 'AAA'), ('主体B', 'AA+'), ('主体D', 'AA')
            ) AS t("企业名称", "内部评级结果")
        """)
        from calculators.credit_distribution import calc_rating_migration
        results = calc_rating_migration(con, 'rate_now', 'rate_prev')
        assert len(results) >= 2
        con.close()


# ═══════════════════════════════════════════════════════════════
#  PositionDiff 测试
# ═══════════════════════════════════════════════════════════════

class TestPositionDiff:
    @pytest.fixture
    def conn(self):
        con = duckdb.connect(':memory:')
        # 前期持仓
        con.execute("""
            CREATE TABLE hold_t1 AS SELECT * FROM (VALUES
                ('产品1', 'code001', '债券A', 5000000.0),
                ('产品1', 'code002', '债券B', 3000000.0),
                ('产品1', 'code003', '债券C', 2000000.0),
            ) AS t("产品名称", "资产代码", "资产名称", "市值")
        """)
        # 后期持仓：code001增仓, code002减仓, code003清仓, code004新建
        con.execute("""
            CREATE TABLE hold_t2 AS SELECT * FROM (VALUES
                ('产品1', 'code001', '债券A', 7000000.0),
                ('产品1', 'code002', '债券B', 1000000.0),
                ('产品1', 'code004', '债券D', 4000000.0),
            ) AS t("产品名称", "资产代码", "资产名称", "市值")
        """)
        yield con
        con.close()

    def test_new_position(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值')
        new_pos = [r for r in results if r.change_type == "新建仓"]
        assert any(r.asset_code == 'code004' for r in new_pos)

    def test_exit_position(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值')
        exits = [r for r in results if r.change_type == "清仓"]
        assert any(r.asset_code == 'code003' for r in exits)

    def test_increase_position(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值')
        inc = [r for r in results if r.change_type == "加仓" and r.asset_code == 'code001']
        assert len(inc) == 1
        assert inc[0].mv_delta == 2000000.0

    def test_decrease_position(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值')
        dec = [r for r in results if r.change_type == "减仓" and r.asset_code == 'code002']
        assert len(dec) == 1
        assert dec[0].mv_delta == -2000000.0

    def test_sorted_by_abs_delta(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值')
        abs_deltas = [abs(r.mv_delta) for r in results]
        assert abs_deltas == sorted(abs_deltas, reverse=True)

    def test_date_labels(self, conn):
        from calculators.position_diff import calc_position_diff
        results = calc_position_diff(conn, 'hold_t1', 'hold_t2', '市值',
                                     date_t1='20260501', date_t2='20260515')
        assert all(r.date_t1 == '20260501' for r in results)
        assert all(r.date_t2 == '20260515' for r in results)


# ═══════════════════════════════════════════════════════════════
#  Leverage 测试
# ═══════════════════════════════════════════════════════════════

class TestLeverage:
    @pytest.fixture
    def conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品1', 5000000.0),
                ('产品1', 3000000.0),
                ('产品2', 8000000.0),
            ) AS t("产品名称", "市值")
        """)
        # NAV: 产品1 = 1.05 × 7000000份 = 7350000, 产品2 = 1.0 × 6000000份 = 6000000
        con.execute("""
            CREATE TABLE test_nav AS SELECT * FROM (VALUES
                ('产品1', 1.05, 7000000.0),
                ('产品2', 1.0, 6000000.0),
            ) AS t("产品名称", "单位净值", "基金份额")
        """)
        yield con
        con.close()

    def test_leverage_ratio_calc(self, conn):
        from calculators.leverage import calc_leverage
        results = calc_leverage(conn, 'test_holding', 'test_nav', '市值')
        p1 = [r for r in results if r.product_name == '产品1'][0]
        # total = 8M, nav = 7.35M → ratio ≈ 1.0884
        assert abs(p1.total_assets - 8000000.0) < 1
        assert abs(p1.net_asset_value - 7350000.0) < 1
        assert abs(p1.leverage_ratio - 8000000.0 / 7350000.0) < 0.001

    def test_breach_detection(self, conn):
        from calculators.leverage import calc_leverage
        # 产品2: 8M / 6M ≈ 1.33, threshold=1.2 → 超标
        results = calc_leverage(conn, 'test_holding', 'test_nav', '市值', threshold=1.2)
        p2 = [r for r in results if r.product_name == '产品2'][0]
        assert p2.is_breach

    def test_no_breach_high_threshold(self, conn):
        from calculators.leverage import calc_leverage
        results = calc_leverage(conn, 'test_holding', 'test_nav', '市值', threshold=5.0)
        assert all(not r.is_breach for r in results)

    def test_sorted_by_leverage_desc(self, conn):
        from calculators.leverage import calc_leverage
        results = calc_leverage(conn, 'test_holding', 'test_nav', '市值')
        ratios = [r.leverage_ratio for r in results]
        assert ratios == sorted(ratios, reverse=True)


# ═══════════════════════════════════════════════════════════════
#  Liquidity 测试
# ═══════════════════════════════════════════════════════════════

class TestLiquidity:
    @pytest.fixture
    def conn(self):
        con = duckdb.connect(':memory:')
        con.execute("""
            CREATE TABLE test_holding AS SELECT * FROM (VALUES
                ('产品1', '利率债',  'c01', 4000000.0),
                ('产品1', '信用债',  'c02', 3000000.0),
                ('产品1', '股票',    'c03', 2000000.0),
                ('产品1', '私募基金','c04', 1000000.0),
            ) AS t("产品名称", "G06一级分类", "资产代码", "市值")
        """)
        yield con
        con.close()

    def test_liquid_ratio(self, conn):
        from calculators.liquidity import calc_liquidity
        results = calc_liquidity(conn, 'test_holding', '市值')
        assert len(results) == 1
        r = results[0]
        # 利率债(1层)=40%, 信用债(2层)=30% → liquid=70%
        assert abs(r.liquid_ratio_pct - 70.0) < 0.1

    def test_illiquid_ratio(self, conn):
        from calculators.liquidity import calc_liquidity
        results = calc_liquidity(conn, 'test_holding', '市值')
        r = results[0]
        # 股票(3层)=20%, 私募基金(4层)=10% → illiquid=30%
        assert abs(r.illiquid_ratio_pct - 30.0) < 0.1

    def test_breach_detection(self, conn):
        from calculators.liquidity import calc_liquidity
        # threshold=80% → liquid=70% < 80% → 超标
        results = calc_liquidity(conn, 'test_holding', '市值', threshold_liquid_pct=80.0)
        assert results[0].is_breach

    def test_no_breach(self, conn):
        from calculators.liquidity import calc_liquidity
        results = calc_liquidity(conn, 'test_holding', '市值', threshold_liquid_pct=50.0)
        assert not results[0].is_breach

    def test_bands_sorted_by_tier(self, conn):
        from calculators.liquidity import calc_liquidity
        results = calc_liquidity(conn, 'test_holding', '市值')
        bands = results[0].bands
        tiers = [b.tier for b in bands]
        assert tiers == sorted(tiers)
