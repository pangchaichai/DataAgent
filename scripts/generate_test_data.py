"""
scripts/generate_test_data.py — 从样例文件结构生成 UAT + 性能压力测试数据

用法:
    python scripts/generate_test_data.py          # 生成全部
    python scripts/generate_test_data.py --uat     # 仅 UAT 数据
    python scripts/generate_test_data.py --perf    # 仅性能数据

UAT 数据: data/test_data/uat/ — 小文件(50-200行)，真实列名和文件名
性能数据: data/test_data/perf/ — 大文件(>10MB)，模拟115万行场景
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UAT_DIR = PROJECT_ROOT / "data" / "test_data" / "uat"
PERF_DIR = PROJECT_ROOT / "data" / "test_data" / "perf"

random.seed(42)

# ── 共享假数据池 ──────────────────────────────────────────────

PRODUCT_NAMES = [
    "稳健增值1号", "稳健增值2号", "现金管理3号", "固收精选A",
    "固收精选B", "短债优选1期", "信用增利2期", "多策略灵活5号",
    "同业存单指数", "货币增强7号", "纯债增强A", "混合偏债1号",
    "目标收益6号", "现金宝", "稳利增长3期", "活期通",
]
PRODUCT_CODES = [f"P{i:06d}" for i in range(len(PRODUCT_NAMES))]

ENTITY_NAMES = [
    "中国建设银行股份有限公司", "中国工商银行股份有限公司",
    "中国农业银行股份有限公司", "中国银行股份有限公司",
    "招商银行股份有限公司", "兴业银行股份有限公司",
    "浦发银行股份有限公司", "平安银行股份有限公司",
    "中信证券股份有限公司", "华泰证券股份有限公司",
    "国泰君安证券股份有限公司", "广发证券股份有限公司",
    "万科企业股份有限公司", "保利发展控股集团股份有限公司",
    "中国中铁股份有限公司", "中国交通建设集团有限公司",
    "华能国际电力股份有限公司", "国家电网有限公司",
    "中国石油天然气股份有限公司", "中国海洋石油集团有限公司",
]

BOND_CODES = [f"{random.randint(100000, 999999):06d}.IB" for _ in range(200)]
BOND_NAMES = [
    f"{random.choice(['24', '25', '26'])}{random.choice(ENTITY_NAMES)[:4]}"
    f"{random.choice(['SCP', 'CP', 'MTN', 'PPN'])}{random.randint(1,9):03d}"
    for _ in range(200)
]

RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "BBB+", "BBB"]
INTERNAL_RATINGS = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
COMPANY_TYPES = ["中央国有企业", "地方国有企业", "民营企业", "外资企业", "合资企业"]
PROVINCES = ["北京市", "上海市", "广东省", "浙江省", "江苏省", "山东省", "四川省", "湖北省"]
CITIES = ["北京市", "上海市", "广州市", "杭州市", "南京市", "济南市", "成都市", "武汉市"]
INDUSTRIES = ["金融", "房地产", "能源", "基础设施", "制造业", "科技", "医药", "消费"]
DEPARTMENTS = ["固收投资一部", "固收投资二部", "混合投资部", "现金管理部", "量化投资部"]
MANAGERS = ["张三", "李四", "王五", "赵六", "陈七", "周八"]
BOND_TYPES = ["企业债务融资工具", "金融债", "国债", "政策性金融债", "资产支持证券", "同业存单"]
BOND_SUBTYPES = ["超短期融资债券", "短期融资债券", "中期票据", "定向工具", "永续债"]
CURRENCIES = ["CNY"]


def _rand_date(start_year=2025, end_year=2026):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _rand_market_value():
    return round(random.uniform(1_000_000, 500_000_000), 2)


def _fmt_thousands(v):
    return f"{v:,.2f}"


# ═══════════════════════════════════════════════════════════════
#  14 种文件类型的列定义和数据生成器
# ═══════════════════════════════════════════════════════════════

def gen_holding(n_rows):
    """持仓产品管理 — 61 列 (holding)"""
    cols = [
        "持仓日期", "资产代码", "资产名称", "产品名称", "主投部门名称",
        "主投经理姓名", "穿透类型（账户类别）", "资管计划账户名称",
        "资产市值_穿透后（元）", "限额占用主体", "发行人", "外部评级",
        "内部评级", "公司属性", "是否上市", "币种", "起息日", "到期日",
        "票面利率", "面值", "剩余期限（年）", "估价收益率（到期）",
        "行权剩余期限（年）", "估价收益率（行权）", "同期限国开债收益率",
        "信用利差", "担保人", "担保方式", "担保人外部评级", "担保人内部评级",
        "中债隐含评级", "G06一级分类", "G06二级分类", "债券类型",
        "内部债项级别", "债项展望", "行业分类", "所属省", "所属市",
        "城投平台级别", "YY行业", "YY省份", "YY城市", "YY区", "YY行政级别",
        "公募/私募", "是否永续", "是否次级", "是否为ESG债券", "持仓数量",
        "券面总额(元)", "评级主体", "最新买入时间", "投资目的", "策略",
        "特殊条款", "CRMW", "重要性标签", "资产五级分类", "实际融资人",
        "非标持仓金额(亿)",
    ]
    rows = []
    d = "2026-06-16"
    for i in range(n_rows):
        entity = random.choice(ENTITY_NAMES)
        prov = random.choice(PROVINCES)
        rows.append({
            "持仓日期": d, "资产代码": BOND_CODES[i % len(BOND_CODES)],
            "资产名称": BOND_NAMES[i % len(BOND_NAMES)],
            "产品名称": random.choice(PRODUCT_NAMES),
            "主投部门名称": random.choice(DEPARTMENTS),
            "主投经理姓名": random.choice(MANAGERS),
            "穿透类型（账户类别）": random.choice(["直投", "委外共管", "通道"]),
            "资管计划账户名称": "",
            "资产市值_穿透后（元）": _fmt_thousands(_rand_market_value()),
            "限额占用主体": entity, "发行人": entity,
            "外部评级": random.choice(RATINGS),
            "内部评级": random.choice(INTERNAL_RATINGS),
            "公司属性": random.choice(COMPANY_TYPES),
            "是否上市": random.choice(["是", "否"]),
            "币种": "CNY",
            "起息日": str(_rand_date(2024, 2025)),
            "到期日": str(_rand_date(2026, 2028)),
            "票面利率": round(random.uniform(1.5, 5.0), 2),
            "面值": "100.00",
            "剩余期限（年）": round(random.uniform(0.1, 5.0), 4),
            "估价收益率（到期）": round(random.uniform(1.0, 4.5), 4),
            "行权剩余期限（年）": round(random.uniform(0.1, 5.0), 4),
            "估价收益率（行权）": round(random.uniform(1.0, 4.5), 4),
            "同期限国开债收益率": round(random.uniform(1.5, 3.0), 4),
            "信用利差": round(random.uniform(0.1, 2.0), 4),
            "担保人": "", "担保方式": "", "担保人外部评级": "",
            "担保人内部评级": "", "中债隐含评级": random.choice(RATINGS),
            "G06一级分类": random.choice(["债券", "同业存单", "基金"]),
            "G06二级分类": random.choice(BOND_TYPES),
            "债券类型": random.choice(BOND_SUBTYPES),
            "内部债项级别": random.choice(["4", "5", "6"]),
            "债项展望": random.choice(["稳定", "正面", "负面"]),
            "行业分类": random.choice(INDUSTRIES),
            "所属省": prov, "所属市": random.choice(CITIES),
            "城投平台级别": "",
            "YY行业": random.choice(INDUSTRIES),
            "YY省份": prov, "YY城市": random.choice(CITIES),
            "YY区": "", "YY行政级别": "",
            "公募/私募": random.choice(["公募", "私募"]),
            "是否永续": random.choice(["是", "否"]),
            "是否次级": "否", "是否为ESG债券": "否",
            "持仓数量": _fmt_thousands(random.randint(10000, 1000000)),
            "券面总额(元)": _fmt_thousands(random.randint(1000000, 100000000)),
            "评级主体": entity,
            "最新买入时间": str(_rand_date(2025, 2026)),
            "投资目的": random.choice(["FVTPL", "AC", "FVOCI"]),
            "策略": "", "特殊条款": "", "CRMW": "",
            "重要性标签": random.choice(["重点", "普通", ""]),
            "资产五级分类": random.choice(["正常", "关注", ""]),
            "实际融资人": "", "非标持仓金额(亿)": "",
        })
    return pd.DataFrame(rows, columns=cols)


def gen_holding_detail(n_rows):
    """底层资产持仓及债券信息表 — 66 列 (holding_detail)"""
    cols = [
        "持仓日期", "穿透类型（1通道 2委外共管 3直投 4委外非共管）",
        "债券类型", "g06一级分类", "g06二级分类", "资产代码", "资产简称",
        "资产名称", "持仓数量", "券面总额，最新", "资产市值_穿透后",
        "剩余期限（年）", "行权剩余期限（年）", "估价收益率（到期）",
        "估价收益率（行权）", "票面利率", "币种", "起息日", "到期日",
        "限额占用方主体", "发行人", "公司属性", "外部主体评级",
        "产品代码", "产品简称", "产品名称", "产品类型", "运作类型", "投资类型",
        "设立日期", "到期日期", "产品状态", "委托人", "管理人",
        "产品标签", "资产组合类别", "资管计划账户名称",
        "主投部门代码", "主投部门名称", "主投经理代码", "主投经理姓名",
        "G06三级分类", "中债隐含评级", "YY行业", "YY省份", "YY城市",
        "YY区", "YY行政级别", "城投平台级别", "是否永续", "是否次级",
        "是否为ESG债券", "是否上市", "所属省", "所属市", "企业性质",
        "行业分组", "内部评级", "评级展望", "面值",
        "同期限国开债收益率", "信用利差", "担保方式", "担保人",
        "担保人外部评级", "担保人内部评级",
    ]
    rows = []
    d = "2026-06-16"
    for i in range(n_rows):
        entity = random.choice(ENTITY_NAMES)
        product = random.choice(PRODUCT_NAMES)
        rows.append({
            "持仓日期": d, "穿透类型（1通道 2委外共管 3直投 4委外非共管）": random.choice(["1", "2", "3", "4"]),
            "债券类型": random.choice(BOND_SUBTYPES),
            "g06一级分类": random.choice(["债券", "同业存单"]),
            "g06二级分类": random.choice(BOND_TYPES),
            "资产代码": BOND_CODES[i % len(BOND_CODES)],
            "资产简称": BOND_NAMES[i % len(BOND_NAMES)][:10],
            "资产名称": BOND_NAMES[i % len(BOND_NAMES)],
            "持仓数量": random.randint(10000, 500000),
            "券面总额，最新": _fmt_thousands(random.randint(1000000, 50000000)),
            "资产市值_穿透后": _fmt_thousands(_rand_market_value()),
            "剩余期限（年）": round(random.uniform(0.1, 5.0), 4),
            "行权剩余期限（年）": round(random.uniform(0.1, 5.0), 4),
            "估价收益率（到期）": round(random.uniform(1.0, 4.5), 4),
            "估价收益率（行权）": round(random.uniform(1.0, 4.5), 4),
            "票面利率": round(random.uniform(1.5, 5.0), 2),
            "币种": "CNY",
            "起息日": str(_rand_date(2024, 2025)),
            "到期日": str(_rand_date(2026, 2028)),
            "限额占用方主体": entity, "发行人": entity,
            "公司属性": random.choice(COMPANY_TYPES),
            "外部主体评级": random.choice(RATINGS),
            "产品代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "产品简称": product[:6], "产品名称": product,
            "产品类型": random.choice(["固定收益类", "混合类", "现金管理"]),
            "运作类型": random.choice(["封闭式", "开放式"]),
            "投资类型": random.choice(["主动管理", "被动管理"]),
            "设立日期": str(_rand_date(2020, 2024)),
            "到期日期": str(_rand_date(2026, 2030)),
            "产品状态": "运行中", "委托人": "某银行",
            "管理人": "某资管公司",
            "产品标签": random.choice(["固收", "短债", "现金", "混合"]),
            "资产组合类别": "债券",
            "资管计划账户名称": "",
            "主投部门代码": f"D{random.randint(1,5):03d}",
            "主投部门名称": random.choice(DEPARTMENTS),
            "主投经理代码": f"M{random.randint(1,20):03d}",
            "主投经理姓名": random.choice(MANAGERS),
            "G06三级分类": "",
            "中债隐含评级": random.choice(RATINGS),
            "YY行业": random.choice(INDUSTRIES),
            "YY省份": random.choice(PROVINCES),
            "YY城市": random.choice(CITIES),
            "YY区": "", "YY行政级别": "",
            "城投平台级别": "",
            "是否永续": random.choice(["是", "否"]),
            "是否次级": "否", "是否为ESG债券": "否",
            "是否上市": random.choice(["是", "否"]),
            "所属省": random.choice(PROVINCES),
            "所属市": random.choice(CITIES),
            "企业性质": random.choice(COMPANY_TYPES),
            "行业分组": random.choice(INDUSTRIES),
            "内部评级": random.choice(INTERNAL_RATINGS),
            "评级展望": random.choice(["稳定", "正面", "负面"]),
            "面值": 100.00,
            "同期限国开债收益率": round(random.uniform(1.5, 3.0), 4),
            "信用利差": round(random.uniform(0.1, 2.0), 4),
            "担保方式": "", "担保人": "",
            "担保人外部评级": "", "担保人内部评级": "",
        })
    return pd.DataFrame(rows, columns=cols)


def gen_nav(n_rows):
    """净值结果管理 — 43 列 (nav)"""
    cols = [
        "核对状态", "核对结果", "净值核对处理人", "托管对账结果",
        "内部对账结果", "资管下发状态", "信披下发状态", "清盘下发状态",
        "产品代码", "产品简称", "款型代码", "款型简称", "产品类型",
        "估值日期", "公布日期", "单位净值", "累计净值", "日涨跌幅%",
        "年化收益率%", "产品规模(万元)", "存续份额(万份)",
        "当日申购(万元)", "当日赎回(万份)", "成立日期", "到期日期",
        "运作类型", "投资类型", "管理人", "托管人", "投资经理",
        "主投部门", "产品状态", "业绩比较基准", "七日年化%",
        "每万份收益", "偏离度%", "预警线", "止损线", "杠杆率%",
        "久期", "持仓集中度%", "净资产(万元)", "总资产(万元)",
    ]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        nav_val = round(random.uniform(0.95, 1.15), 4)
        rows.append({
            "核对状态": random.choice(["已核对", "待核对"]),
            "核对结果": random.choice(["一致", "差异"]),
            "净值核对处理人": random.choice(MANAGERS),
            "托管对账结果": "一致", "内部对账结果": "一致",
            "资管下发状态": "已下发", "信披下发状态": "已下发",
            "清盘下发状态": "未下发",
            "产品代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "产品简称": product[:6], "款型代码": f"K{random.randint(1,99):03d}",
            "款型简称": product[:4], "产品类型": random.choice(["固定收益类", "混合类"]),
            "估值日期": "2026-06-15", "公布日期": "2026-06-16",
            "单位净值": nav_val,
            "累计净值": round(nav_val + random.uniform(0, 0.3), 4),
            "日涨跌幅%": round(random.uniform(-0.5, 0.5), 4),
            "年化收益率%": round(random.uniform(1.0, 8.0), 2),
            "产品规模(万元)": _fmt_thousands(random.uniform(1000, 500000)),
            "存续份额(万份)": _fmt_thousands(random.uniform(1000, 500000)),
            "当日申购(万元)": _fmt_thousands(random.uniform(0, 50000)),
            "当日赎回(万份)": _fmt_thousands(random.uniform(0, 30000)),
            "成立日期": str(_rand_date(2020, 2024)),
            "到期日期": str(_rand_date(2026, 2030)),
            "运作类型": random.choice(["封闭式", "开放式"]),
            "投资类型": "主动管理", "管理人": "某资管公司",
            "托管人": random.choice(["中国建设银行", "中国工商银行", "招商银行"]),
            "投资经理": random.choice(MANAGERS),
            "主投部门": random.choice(DEPARTMENTS),
            "产品状态": "运行中",
            "业绩比较基准": f"一年期定期存款利率+{random.randint(50,200)}bp",
            "七日年化%": round(random.uniform(1.5, 4.0), 4),
            "每万份收益": round(random.uniform(0.3, 1.2), 4),
            "偏离度%": round(random.uniform(-0.1, 0.1), 4),
            "预警线": 0.95, "止损线": 0.90,
            "杠杆率%": round(random.uniform(100, 140), 2),
            "久期": round(random.uniform(0.5, 3.0), 2),
            "持仓集中度%": round(random.uniform(5, 50), 2),
            "净资产(万元)": _fmt_thousands(random.uniform(1000, 500000)),
            "总资产(万元)": _fmt_thousands(random.uniform(1000, 600000)),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_rating_entity(n_rows):
    """主体评级结果 — 39 列 (rating_entity)"""
    cols = [
        "企业名称", "企业性质", "行业分组", "研究部行业", "评级模型",
        "所在省份", "内部评级结果", "预警等级", "预警日期", "评级类型",
        "评级生效日", "评级到期日", "内部评级日期", "主体所属名单",
        "外部评级", "外部评级机构", "外部评级日期", "外部展望",
        "中债隐含评级", "城投平台级别", "上市公司", "担保人",
        "担保方式", "担保人评级", "YY行业", "YY省份", "YY城市",
        "YY区", "YY行政级别", "备注", "最近更新时间",
        "评级分析师", "评级审批人", "关联集团", "集团评级",
        "是否重点关注", "特殊标记", "已投余额(亿)", "风险敞口(亿)",
    ]
    rows = []
    for i in range(n_rows):
        entity = ENTITY_NAMES[i % len(ENTITY_NAMES)]
        rows.append({
            "企业名称": entity,
            "企业性质": random.choice(COMPANY_TYPES),
            "行业分组": random.choice(INDUSTRIES),
            "研究部行业": random.choice(INDUSTRIES),
            "评级模型": random.choice(["信用评分模型V3", "定性评估"]),
            "所在省份": random.choice(PROVINCES),
            "内部评级结果": random.choice(INTERNAL_RATINGS),
            "预警等级": random.choice(["正常", "关注", "预警"]),
            "预警日期": str(_rand_date(2025, 2026)),
            "评级类型": "跟踪评级",
            "评级生效日": str(_rand_date(2025, 2026)),
            "评级到期日": str(_rand_date(2026, 2027)),
            "内部评级日期": str(_rand_date(2025, 2026)),
            "主体所属名单": random.choice(["白名单", "灰名单", "观察名单"]),
            "外部评级": random.choice(RATINGS),
            "外部评级机构": random.choice(["中诚信", "联合资信", "大公国际"]),
            "外部评级日期": str(_rand_date(2025, 2026)),
            "外部展望": random.choice(["稳定", "正面", "负面"]),
            "中债隐含评级": random.choice(RATINGS),
            "城投平台级别": "",
            "上市公司": random.choice(["是", "否"]),
            "担保人": "", "担保方式": "", "担保人评级": "",
            "YY行业": random.choice(INDUSTRIES),
            "YY省份": random.choice(PROVINCES),
            "YY城市": random.choice(CITIES),
            "YY区": "", "YY行政级别": "",
            "备注": "", "最近更新时间": "2026-06-16 09:11:00",
            "评级分析师": random.choice(MANAGERS),
            "评级审批人": random.choice(MANAGERS),
            "关联集团": "", "集团评级": "",
            "是否重点关注": random.choice(["是", "否"]),
            "特殊标记": "",
            "已投余额(亿)": round(random.uniform(0, 50), 2),
            "风险敞口(亿)": round(random.uniform(0, 30), 2),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_rating_bond(n_rows):
    """投资债券评级结果 — 42 列 (rating_bond)"""
    cols = [
        "序号", "债券代码", "债券简称", "评级主体", "债券类型",
        "起息日", "到期日", "债券是否到期", "发行截止日",
        "内部评级结果", "所属部门库", "评级展望", "评级有效期",
        "评级是否到期", "评级到期日", "外部评级", "外部评级机构",
        "外部评级日期", "中债隐含评级", "票面利率", "发行规模(亿)",
        "剩余期限(年)", "是否永续", "是否次级", "担保方式", "担保人",
        "担保人评级", "行业分组", "企业性质", "所在省份",
        "城投平台级别", "YY行业", "YY省份", "YY城市",
        "已投余额(亿)", "持仓市值(亿)", "利差(bp)",
        "估价收益率", "关联集团", "最近更新时间",
        "评级分析师", "备注",
    ]
    rows = []
    for i in range(n_rows):
        entity = random.choice(ENTITY_NAMES)
        rows.append({
            "序号": i + 1,
            "债券代码": BOND_CODES[i % len(BOND_CODES)],
            "债券简称": BOND_NAMES[i % len(BOND_NAMES)][:10],
            "评级主体": entity,
            "债券类型": random.choice(BOND_SUBTYPES),
            "起息日": str(_rand_date(2024, 2025)),
            "到期日": str(_rand_date(2026, 2028)),
            "债券是否到期": "否",
            "发行截止日": str(_rand_date(2024, 2025)),
            "内部评级结果": random.choice(INTERNAL_RATINGS),
            "所属部门库": random.choice(DEPARTMENTS),
            "评级展望": random.choice(["稳定", "正面", "负面"]),
            "评级有效期": "1年",
            "评级是否到期": "否",
            "评级到期日": str(_rand_date(2026, 2027)),
            "外部评级": random.choice(RATINGS),
            "外部评级机构": random.choice(["中诚信", "联合资信"]),
            "外部评级日期": str(_rand_date(2025, 2026)),
            "中债隐含评级": random.choice(RATINGS),
            "票面利率": round(random.uniform(1.5, 5.0), 2),
            "发行规模(亿)": round(random.uniform(1, 100), 2),
            "剩余期限(年)": round(random.uniform(0.1, 5.0), 2),
            "是否永续": random.choice(["是", "否"]),
            "是否次级": "否",
            "担保方式": "", "担保人": "", "担保人评级": "",
            "行业分组": random.choice(INDUSTRIES),
            "企业性质": random.choice(COMPANY_TYPES),
            "所在省份": random.choice(PROVINCES),
            "城投平台级别": "",
            "YY行业": random.choice(INDUSTRIES),
            "YY省份": random.choice(PROVINCES),
            "YY城市": random.choice(CITIES),
            "已投余额(亿)": round(random.uniform(0, 20), 2),
            "持仓市值(亿)": round(random.uniform(0, 20), 2),
            "利差(bp)": round(random.uniform(10, 200), 0),
            "估价收益率": round(random.uniform(1.0, 4.5), 4),
            "关联集团": "", "最近更新时间": "2026-06-16 09:12:00",
            "评级分析师": random.choice(MANAGERS),
            "备注": "",
        })
    return pd.DataFrame(rows, columns=cols)


def gen_monitoring(n_rows):
    """监控值查询 — 18 列 (monitoring)"""
    cols = [
        "监控日期", "监控类型", "指标类型", "组合/组合包代码",
        "组合/组合包名称", "投资经理", "投资部门", "募集方式",
        "开放类型", "组合类型", "收益类型", "预警线", "禁止线",
        "实际值", "连续违规天数", "状态", "违规说明", "处置措施",
    ]
    monitor_types = ["集中度", "杠杆率", "久期", "流动性", "信用评级"]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        actual = round(random.uniform(0, 100), 2)
        warn = round(random.uniform(60, 80), 2)
        forbid = round(random.uniform(80, 100), 2)
        rows.append({
            "监控日期": "2026-06-22",
            "监控类型": random.choice(monitor_types),
            "指标类型": random.choice(["比例", "绝对值"]),
            "组合/组合包代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "组合/组合包名称": product,
            "投资经理": random.choice(MANAGERS),
            "投资部门": random.choice(DEPARTMENTS),
            "募集方式": random.choice(["公募", "私募"]),
            "开放类型": random.choice(["封闭式", "开放式"]),
            "组合类型": random.choice(["固定收益类", "混合类"]),
            "收益类型": random.choice(["净值型", "预期收益型"]),
            "预警线": warn, "禁止线": forbid,
            "实际值": actual,
            "连续违规天数": random.randint(0, 5) if actual > warn else 0,
            "状态": "违规" if actual > forbid else ("预警" if actual > warn else "正常"),
            "违规说明": "", "处置措施": "",
        })
    return pd.DataFrame(rows, columns=cols)


def gen_valuation(n_rows):
    """估值表查询 — 12 列 (valuation)"""
    cols = [
        "资产名称", "总资产_成本", "总资产_市值", "净资产_成本",
        "净资产_市值", "单位净值_成本", "单位净值_市值",
        "净值波动%_较上一日", "净值波动%_较上月", "净值波动%_较年初",
        "偏离金额", "偏离度",
    ]
    rows = []
    for i in range(n_rows):
        cost = _rand_market_value()
        market = cost * random.uniform(0.95, 1.05)
        rows.append({
            "资产名称": random.choice(PRODUCT_NAMES),
            "总资产_成本": _fmt_thousands(cost),
            "总资产_市值": _fmt_thousands(market),
            "净资产_成本": _fmt_thousands(cost * 0.95),
            "净资产_市值": _fmt_thousands(market * 0.95),
            "单位净值_成本": round(random.uniform(0.95, 1.10), 4),
            "单位净值_市值": round(random.uniform(0.95, 1.10), 4),
            "净值波动%_较上一日": round(random.uniform(-0.5, 0.5), 4),
            "净值波动%_较上月": round(random.uniform(-2.0, 2.0), 4),
            "净值波动%_较年初": round(random.uniform(-5.0, 5.0), 4),
            "偏离金额": round(random.uniform(-10000, 10000), 2),
            "偏离度": round(random.uniform(-0.25, 0.25), 4),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_subscription(n_rows):
    """申赎数据 — 12 列 (subscription)"""
    cols = [
        "产品代码", "产品名称", "募集类型", "开放类型",
        "主投资部门", "主投资经理", "上日净资产", "上日净值",
        "当日申购资金", "当日赎回份额", "估算净申购资金", "占净资产比例",
    ]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        net_asset = random.uniform(10000000, 500000000)
        purchase = random.uniform(0, net_asset * 0.1)
        redeem = random.uniform(0, net_asset * 0.08)
        rows.append({
            "产品代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "产品名称": product,
            "募集类型": random.choice(["公募", "私募"]),
            "开放类型": random.choice(["开放式", "封闭式"]),
            "主投资部门": random.choice(DEPARTMENTS),
            "主投资经理": random.choice(MANAGERS),
            "上日净资产": _fmt_thousands(net_asset),
            "上日净值": round(random.uniform(0.95, 1.15), 4),
            "当日申购资金": _fmt_thousands(purchase),
            "当日赎回份额": _fmt_thousands(redeem),
            "估算净申购资金": _fmt_thousands(purchase - redeem),
            "占净资产比例": round((purchase - redeem) / net_asset * 100, 4),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_asset_position(n_rows):
    """实时资产头寸查询 — 7 列 (asset_position)"""
    cols = [
        "组合名称", "证券账户/通道代码", "资产类型", "资产二级类型",
        "资产代码", "资产名称", "实际持仓",
    ]
    asset_types = ["债券", "同业存单", "基金", "现金"]
    rows = []
    for i in range(n_rows):
        rows.append({
            "组合名称": random.choice(PRODUCT_NAMES),
            "证券账户/通道代码": f"A{random.randint(10000, 99999)}",
            "资产类型": random.choice(asset_types),
            "资产二级类型": random.choice(BOND_SUBTYPES),
            "资产代码": BOND_CODES[i % len(BOND_CODES)],
            "资产名称": BOND_NAMES[i % len(BOND_NAMES)],
            "实际持仓": _fmt_thousands(random.randint(10000, 5000000)),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_cashflow_gap(n_rows):
    """现金流缺口分析 — 8 列 (cashflow_gap)"""
    cols = [
        "日期", "组合代码", "资金账户", "现金流类型",
        "资产标的", "现金流", "币种", "是否移植交易系统",
    ]
    cf_types = ["到期还本", "付息", "回购到期", "申购", "赎回", "买入", "卖出"]
    rows = []
    for i in range(n_rows):
        rows.append({
            "日期": str(_rand_date(2026, 2026)),
            "组合代码": random.choice(PRODUCT_CODES),
            "资金账户": f"ACCT{random.randint(1000, 9999)}",
            "现金流类型": random.choice(cf_types),
            "资产标的": random.choice(BOND_NAMES[:50]),
            "现金流": _fmt_thousands(random.uniform(-50000000, 50000000)),
            "币种": "CNY",
            "是否移植交易系统": random.choice(["是", "否"]),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_bond_pledge(n_rows):
    """债券质押查询 — 26 列 (bond_pledge)"""
    cols = [
        "组合代码", "业务类型", "债券一级分类", "债券二级分类",
        "查询日", "二级分类", "三级分类", "资产代码", "债券简称",
        "企业性质", "是否次级债", "质押融资金额（元）", "质押利率（%）",
        "质押期限（天）", "质押起始日", "质押到期日", "折扣比例",
        "券面总额(元)", "市值(元)", "回购方", "交易市场",
        "清算速度", "交易状态", "录入时间", "备注", "操作人",
    ]
    rows = []
    for i in range(n_rows):
        rows.append({
            "组合代码": random.choice(PRODUCT_CODES),
            "业务类型": "质押式回购",
            "债券一级分类": random.choice(["利率债", "信用债"]),
            "债券二级分类": random.choice(BOND_TYPES),
            "查询日": "2026-06-16",
            "二级分类": random.choice(BOND_TYPES),
            "三级分类": random.choice(BOND_SUBTYPES),
            "资产代码": BOND_CODES[i % len(BOND_CODES)],
            "债券简称": BOND_NAMES[i % len(BOND_NAMES)][:10],
            "企业性质": random.choice(COMPANY_TYPES),
            "是否次级债": "否",
            "质押融资金额（元）": _fmt_thousands(random.uniform(1000000, 100000000)),
            "质押利率（%）": round(random.uniform(1.0, 3.5), 4),
            "质押期限（天）": random.randint(1, 91),
            "质押起始日": str(_rand_date(2026, 2026)),
            "质押到期日": str(_rand_date(2026, 2026)),
            "折扣比例": round(random.uniform(0.85, 0.98), 4),
            "券面总额(元)": _fmt_thousands(random.randint(1000000, 100000000)),
            "市值(元)": _fmt_thousands(random.uniform(1000000, 100000000)),
            "回购方": random.choice(ENTITY_NAMES[:10]),
            "交易市场": random.choice(["银行间", "交易所"]),
            "清算速度": random.choice(["T+0", "T+1"]),
            "交易状态": "已成交",
            "录入时间": "2026-06-16 10:30:00",
            "备注": "", "操作人": random.choice(MANAGERS),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_account_flow(n_rows):
    """账户流水 — 15 列 (account_flow)"""
    cols = [
        "记账日期", "记账编号", "产品代码", "产品名称",
        "账户名称", "账户号", "期初", "借方发生额", "贷方发生额",
        "余额", "摘要", "对方账户名", "对方账户", "类型", "创建时间",
    ]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        balance = random.uniform(100000, 50000000)
        debit = random.uniform(0, 10000000)
        credit = random.uniform(0, 10000000)
        rows.append({
            "记账日期": "2026-06-16",
            "记账编号": f"JZ{random.randint(100000, 999999)}",
            "产品代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "产品名称": product,
            "账户名称": f"{product}专用账户",
            "账户号": f"{random.randint(10000000000, 99999999999)}",
            "期初": _fmt_thousands(balance),
            "借方发生额": _fmt_thousands(debit),
            "贷方发生额": _fmt_thousands(credit),
            "余额": _fmt_thousands(balance + credit - debit),
            "摘要": random.choice(["债券买入", "利息收入", "回购到期", "申购款", "赎回款"]),
            "对方账户名": random.choice(ENTITY_NAMES[:5]),
            "对方账户": f"{random.randint(10000000000, 99999999999)}",
            "类型": random.choice(["转入", "转出"]),
            "创建时间": "2026-06-16 15:30:00",
        })
    return pd.DataFrame(rows, columns=cols)


def gen_repo_trade(n_rows):
    """质押式回购投资交易查询 — 25 列 (repo_trade)"""
    cols = [
        "有效状态", "有效时间", "成交编号", "业务编号", "组合代码",
        "组合名称", "交易方向", "券面总额（万元）", "本方交易员",
        "本金金额（元）", "到期结算金额（元）", "回购利率(%)",
        "交易对手", "交易日期", "起息日", "到期日", "回购天数",
        "清算速度", "交易市场", "交易状态", "录入时间",
        "审批状态", "审批人", "备注", "操作人",
    ]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        principal = random.uniform(1000000, 500000000)
        rate = round(random.uniform(1.0, 3.5), 4)
        days = random.randint(1, 91)
        interest = principal * rate / 100 * days / 365
        rows.append({
            "有效状态": random.choice(["有效", "无效"]),
            "有效时间": "2026-06-16 09:30:00",
            "成交编号": f"CJ{random.randint(100000, 999999)}",
            "业务编号": f"YW{random.randint(100000, 999999)}",
            "组合代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "组合名称": product,
            "交易方向": random.choice(["正回购", "逆回购"]),
            "券面总额（万元）": _fmt_thousands(principal / 10000),
            "本方交易员": random.choice(MANAGERS),
            "本金金额（元）": _fmt_thousands(principal),
            "到期结算金额（元）": _fmt_thousands(principal + interest),
            "回购利率(%)": rate,
            "交易对手": random.choice(ENTITY_NAMES[:10]),
            "交易日期": str(_rand_date(2026, 2026)),
            "起息日": str(_rand_date(2026, 2026)),
            "到期日": str(_rand_date(2026, 2026)),
            "回购天数": days,
            "清算速度": random.choice(["T+0", "T+1"]),
            "交易市场": random.choice(["银行间", "交易所"]),
            "交易状态": "已成交",
            "录入时间": "2026-06-16 10:00:00",
            "审批状态": "已审批",
            "审批人": random.choice(MANAGERS),
            "备注": "", "操作人": random.choice(MANAGERS),
        })
    return pd.DataFrame(rows, columns=cols)


def gen_fund_position(n_rows):
    """组合资金账户头寸 — 8 列 (fund_position)"""
    cols = [
        "日期", "组合代码", "组合名称", "账号",
        "账户名称", "余额", "当日发生额", "币种",
    ]
    rows = []
    for i in range(n_rows):
        product = random.choice(PRODUCT_NAMES)
        rows.append({
            "日期": "2026-06-16",
            "组合代码": PRODUCT_CODES[PRODUCT_NAMES.index(product)],
            "组合名称": product,
            "账号": f"{random.randint(10000000000, 99999999999)}",
            "账户名称": f"{product}资金账户",
            "余额": _fmt_thousands(random.uniform(100000, 100000000)),
            "当日发生额": _fmt_thousands(random.uniform(-10000000, 10000000)),
            "币种": "CNY",
        })
    return pd.DataFrame(rows, columns=cols)


# ═══════════════════════════════════════════════════════════════
#  文件名映射(与 config auto_load file_rules 一致)
# ═══════════════════════════════════════════════════════════════

FILE_SPECS = [
    # (filename_pattern, gen_func, uat_rows, perf_rows, is_xls, table_type)
    # perf_rows: 足够触发 >10MB 阈值或压力测试，同时生成时间可控
    ("持仓产品管理-2026-06-16.xls", gen_holding, 150, 15_000, True, "holding"),
    ("底层资产持仓及债券信息表0616.xlsx", gen_holding_detail, 120, 10_000, False, "holding_detail"),
    ("净值结果管理2026-06-15-2026-06-15.xlsx", gen_nav, 50, 2_000, False, "nav"),
    ("评级结果202606160911.xls", gen_rating_entity, 80, 3_000, True, "rating_entity"),
    ("投资债券评级结果202606160912.xls", gen_rating_bond, 100, 5_000, True, "rating_bond"),
    ("监控值查询 - 2026-06-22T084857.169.xlsx", gen_monitoring, 80, 2_000, False, "monitoring"),
    ("估值表查询(2026-06-16).xlsx", gen_valuation, 50, 1_000, False, "valuation"),
    ("申赎数据0615.xlsx", gen_subscription, 50, 1_000, False, "subscription"),
    ("实时资产头寸查询(2026-06-16).xlsx", gen_asset_position, 100, 5_000, False, "asset_position"),
    ("现金流缺口分析(2026-06-16).xlsx", gen_cashflow_gap, 80, 5_000, False, "cashflow_gap"),
    ("债券质押查询(2026-06-16).xlsx", gen_bond_pledge, 60, 3_000, False, "bond_pledge"),
    ("账户流水(2026-06-16).xlsx", gen_account_flow, 100, 10_000, False, "account_flow"),
    ("质押式回购投资交易查询(2026-06-16).xlsx", gen_repo_trade, 200, 30_000, False, "repo_trade"),
    ("组合资金账户头寸(2026-06-16).xlsx", gen_fund_position, 40, 1_000, False, "fund_position"),
]

# 性能测试：大持仓文件用多 sheet (7 sheet × 50K = 350K rows)
PERF_MULTI_SHEET_HOLDING = True
PERF_HOLDING_SHEETS = 3
PERF_HOLDING_ROWS_PER_SHEET = 5_000


def _to_native(val):
    """Convert numpy/pandas types to Python native for xlwt compatibility."""
    if pd.isna(val):
        return ""
    import numpy as np
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
        return bool(val)
    return val


def _df_to_xls(df, filepath):
    """pandas DataFrame → .xls via xlwt (pandas 2.x dropped xlwt support)"""
    import xlwt
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    for c_idx, col in enumerate(df.columns):
        ws.write(0, c_idx, col)
    for r_idx in range(len(df)):
        for c_idx in range(len(df.columns)):
            ws.write(r_idx + 1, c_idx, _to_native(df.iloc[r_idx, c_idx]))
    wb.save(str(filepath))


def generate_uat():
    UAT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[UAT] 输出目录: {UAT_DIR}")
    for filename, gen_func, n_rows, _, is_xls, ttype in FILE_SPECS:
        fp = UAT_DIR / filename
        df = gen_func(n_rows)
        if is_xls:
            _df_to_xls(df, fp)
        else:
            df.to_excel(str(fp), index=False, engine="openpyxl")
        size_kb = os.path.getsize(fp) / 1024
        print(f"  [{ttype}] {filename}: {n_rows} rows, {size_kb:.0f} KB")
    print(f"[UAT] 完成: {len(FILE_SPECS)} 个文件\n")


def generate_perf():
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[PERF] 输出目录: {PERF_DIR}")

    for filename, gen_func, _, n_rows, is_xls, ttype in FILE_SPECS:
        fp = PERF_DIR / filename

        if ttype == "holding" and PERF_MULTI_SHEET_HOLDING:
            _write_multi_sheet_xls(fp, gen_func, ttype)
            continue

        # 对大行数，分 chunk 写入以控制内存
        if n_rows > 20_000:
            _write_chunked(fp, gen_func, n_rows, is_xls, ttype)
        else:
            df = gen_func(n_rows)
            if is_xls:
                _df_to_xls(df, fp)
            else:
                df.to_excel(str(fp), index=False, engine="openpyxl")
            del df
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            print(f"  [{ttype}] {filename}: {n_rows} rows, {size_mb:.1f} MB")

    print(f"[PERF] 完成: {len(FILE_SPECS)} 个文件\n")


def _write_multi_sheet_xls(fp, gen_func, ttype):
    """写多 sheet 的 XLS 文件 (模拟 持仓产品管理 大文件)"""
    import xlwt
    wb = xlwt.Workbook()
    total_rows = 0
    for s in range(PERF_HOLDING_SHEETS):
        sheet_name = f"Sheet{s+1}"
        ws = wb.add_sheet(sheet_name)
        df = gen_func(PERF_HOLDING_ROWS_PER_SHEET)
        for c_idx, col in enumerate(df.columns):
            ws.write(0, c_idx, col)
        for r_idx in range(len(df)):
            for c_idx, col in enumerate(df.columns):
                ws.write(r_idx + 1, c_idx, _to_native(df.iloc[r_idx, c_idx]))
            if r_idx % 10000 == 0 and r_idx > 0:
                sys.stdout.write(f"\r  [holding] Sheet{s+1}: {r_idx}/{PERF_HOLDING_ROWS_PER_SHEET}")
                sys.stdout.flush()
        total_rows += len(df)
        del df
        print(f"\r  [holding] Sheet{s+1}: {PERF_HOLDING_ROWS_PER_SHEET} rows done")
    wb.save(str(fp))
    size_mb = os.path.getsize(fp) / (1024 * 1024)
    print(f"  [{ttype}] {fp.name}: {total_rows} rows ({PERF_HOLDING_SHEETS} sheets), {size_mb:.1f} MB")


def _write_chunked(fp, gen_func, n_rows, is_xls, ttype):
    """分 chunk 生成大 XLSX，减少内存峰值"""
    chunk_size = 10_000
    engine = "xlwt" if is_xls else "openpyxl"

    if is_xls:
        import xlwt
        wb = xlwt.Workbook()
        ws = wb.add_sheet("Sheet1")
        header_written = False
        row_offset = 0
        for start in range(0, n_rows, chunk_size):
            actual = min(chunk_size, n_rows - start)
            df = gen_func(actual)
            if not header_written:
                for c_idx, col in enumerate(df.columns):
                    ws.write(0, c_idx, col)
                header_written = True
                row_offset = 1
            for r_idx in range(len(df)):
                for c_idx in range(len(df.columns)):
                    ws.write(row_offset, c_idx, _to_native(df.iloc[r_idx, c_idx]))
                row_offset += 1
            del df
            sys.stdout.write(f"\r  [{ttype}] {start + actual}/{n_rows}")
            sys.stdout.flush()
        wb.save(str(fp))
    else:
        # openpyxl: collect chunks (memory trade-off for simplicity)
        chunks = []
        for start in range(0, n_rows, chunk_size):
            actual = min(chunk_size, n_rows - start)
            chunks.append(gen_func(actual))
            sys.stdout.write(f"\r  [{ttype}] generating {start + actual}/{n_rows}")
            sys.stdout.flush()
        df = pd.concat(chunks, ignore_index=True)
        del chunks
        df.to_excel(str(fp), index=False, engine="openpyxl")
        del df
    size_mb = os.path.getsize(fp) / (1024 * 1024)
    print(f"\r  [{ttype}] {fp.name}: {n_rows} rows, {size_mb:.1f} MB")


# ═══════════════════════════════════════════════════════════════
#  CSV 性能测试文件（直接 CSV 生成，无需 Excel 开销）
# ═══════════════════════════════════════════════════════════════

def generate_perf_csv():
    """生成 CSV 格式的性能测试文件，用于测试 native CSV load 路径"""
    csv_dir = PERF_DIR / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    print(f"[PERF-CSV] 输出目录: {csv_dir}")

    specs = [
        ("持仓产品管理-2026-06-16.csv", gen_holding, 50_000, "holding"),
        ("质押式回购投资交易查询(2026-06-16).csv", gen_repo_trade, 50_000, "repo_trade"),
        ("底层资产持仓及债券信息表0616.csv", gen_holding_detail, 30_000, "holding_detail"),
    ]
    for filename, gen_func, n_rows, ttype in specs:
        fp = csv_dir / filename
        chunk_size = 20_000
        header_written = False
        for start in range(0, n_rows, chunk_size):
            actual = min(chunk_size, n_rows - start)
            df = gen_func(actual)
            df.to_csv(str(fp), index=False, mode="a",
                      header=not header_written, encoding="utf-8")
            header_written = True
            del df
            sys.stdout.write(f"\r  [{ttype}] {start + actual}/{n_rows}")
            sys.stdout.flush()
        size_mb = os.path.getsize(fp) / (1024 * 1024)
        print(f"\r  [{ttype}] {filename}: {n_rows} rows, {size_mb:.1f} MB")

    # GB18030 编码文件
    fp = csv_dir / "持仓产品管理-2026-06-16-gb18030.csv"
    df = gen_holding(50_000)
    df.to_csv(str(fp), index=False, encoding="gb18030")
    size_mb = os.path.getsize(fp) / (1024 * 1024)
    print(f"  [holding-gb18030] {fp.name}: 50000 rows, {size_mb:.1f} MB")
    del df

    print(f"[PERF-CSV] 完成\n")


def main():
    parser = argparse.ArgumentParser(description="生成 DataAgent 测试数据")
    parser.add_argument("--uat", action="store_true", help="仅生成 UAT 数据")
    parser.add_argument("--perf", action="store_true", help="仅生成性能数据")
    parser.add_argument("--perf-csv", action="store_true", help="仅生成 CSV 性能数据")
    args = parser.parse_args()

    if not (args.uat or args.perf or args.perf_csv):
        args.uat = args.perf = args.perf_csv = True

    if args.uat:
        generate_uat()
    if args.perf:
        generate_perf()
    if args.perf_csv:
        generate_perf_csv()


if __name__ == "__main__":
    main()
