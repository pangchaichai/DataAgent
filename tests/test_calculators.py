"""
tests/test_calculators.py — 固化计算模块单元测试

覆盖：concentration.py（主体/单券集中度）
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
