#!/usr/bin/env python3
"""
模拟 meeting_report Skill 全流程：
  1. 加载三张测试 CSV 到 DuckDB
  2. 执行 Skill 中定义的 SQL 查询
  3. 渲染 Jinja2 模板
  4. 输出 Markdown 报告到 data/outputs/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

os.chdir(ROOT)

from datetime import datetime  # noqa: E402

# ─── 1. 初始化 DuckDB（内存模式） ─────────────────────────────
from tools.data_loader import init_duckdb_connection, load_file  # noqa: E402

conn = init_duckdb_connection()
print("✅ DuckDB 初始化完成")

# ─── 2. 加载三张测试表 ───────────────────────────────────────
uploads = ROOT / "data" / "uploads"

r_entity = load_file(
    str(uploads / "test_rating_entity_20260609.csv"),
    "rating_entity_20260609",
    date_tag="20260609",
    table_type="rating_entity",
)
print(f"✅ 主体评级表：{r_entity.row_count} 行，表名={r_entity.table_name}")

r_holding = load_file(
    str(uploads / "test_holding_20260609.csv"),
    "holding_20260609",
    date_tag="20260609",
    table_type="holding",
)
print(f"✅ 持仓表：{r_holding.row_count} 行，表名={r_holding.table_name}")

r_bond = load_file(
    str(uploads / "test_rating_bond_20260609.csv"),
    "rating_bond_20260609",
    date_tag="20260609",
    table_type="rating_bond",
)
print(f"✅ 债券评级表：{r_bond.row_count} 行，表名={r_bond.table_name}")

# ─── 3. 定义集团成员（模拟 groups.yaml） ─────────────────────
GROUP_NAME = "象屿系"
GROUP_MEMBERS = [
    "象屿集团有限公司",
    "象屿股份有限公司",
    "厦门象屿供应链管理股份有限公司",
    "象屿金象控股集团有限公司",
    "厦门象屿农产品集团有限公司",
]
DATA_DATE = "2026-06-09"
GENERATE_TIME = datetime.now().strftime("%Y-%m-%d %H:%M")

print(f"\n📊 开始生成 [{GROUP_NAME}] 参谈要点报告...")
print(f"   集团成员：{len(GROUP_MEMBERS)} 家")

# ─── 4. Step 2：查询各主体评级和限额 ─────────────────────────
members_str = ", ".join(f"'{m}'" for m in GROUP_MEMBERS)

rating_sql = f"""
SELECT
    "主体名称",
    "内部评级结果",
    "预警等级",
    TRY_CAST("理财限额" AS DOUBLE) AS 理财限额,
    TRY_CAST("已占用限额" AS DOUBLE) AS 已占用限额,
    TRY_CAST("剩余可用限额" AS DOUBLE) AS 剩余可用限额,
    "品种（信用政策）",
    "评级有效期"
FROM rating_entity_20260609
WHERE "主体名称" IN ({members_str})
ORDER BY TRY_CAST("理财限额" AS DOUBLE) DESC
LIMIT 50
"""
rating_rows = conn.execute(rating_sql).fetchdf()
print(f"\n[主体评级查询] {len(rating_rows)} 条记录")

# ─── 5. Step 3：查询各主体持仓汇总 ───────────────────────────
holding_sql = f"""
SELECT
    "限额占用方主体",
    ROUND(SUM(CAST("资产市值_穿透后" AS DOUBLE)), 0) AS 全穿透持仓合计,
    ROUND(SUM(CAST("资产市值_半穿透" AS DOUBLE)), 0) AS 半穿透持仓合计,
    ROUND(SUM(CASE WHEN CAST("剩余期限" AS DOUBLE) <= 1
              THEN CAST("资产市值_穿透后" AS DOUBLE) ELSE 0 END), 0) AS 一年以内,
    ROUND(SUM(CASE WHEN CAST("剩余期限" AS DOUBLE) > 1
                   AND CAST("剩余期限" AS DOUBLE) <= 2
              THEN CAST("资产市值_穿透后" AS DOUBLE) ELSE 0 END), 0) AS 一至二年,
    ROUND(SUM(CASE WHEN CAST("剩余期限" AS DOUBLE) > 2
              THEN CAST("资产市值_穿透后" AS DOUBLE) ELSE 0 END), 0) AS 二年以上,
    COUNT(DISTINCT "资产代码") AS 持仓品种数
FROM holding_20260609
WHERE "限额占用方主体" IN ({members_str})
GROUP BY "限额占用方主体"
LIMIT 50
"""
holding_rows = conn.execute(holding_sql).fetchdf()
print(f"[持仓汇总查询] {len(holding_rows)} 条记录")

# ─── 6. Step 4：在存续债明细 ──────────────────────────────────
bond_sql = f"""
SELECT
    "债券名称",
    "债券代码",
    TRY_CAST("持仓金额" AS DOUBLE) AS 持仓金额,
    "内部评级结果",
    "外部评级",
    "到期日",
    "限额占用主体"
FROM rating_bond_20260609
WHERE "限额占用主体" IN ({members_str})
ORDER BY TRY_CAST("持仓金额" AS DOUBLE) DESC
LIMIT 30
"""
bond_rows = conn.execute(bond_sql).fetchdf()
print(f"[存续债明细查询] {len(bond_rows)} 条记录")

# ─── 7. 组装模板数据 ─────────────────────────────────────────
def fmt(val, decimals=0):
    """格式化数值为万元字符串"""
    try:
        v = float(val)
        if decimals == 0:
            return f"{int(v):,}"
        return f"{v:,.{decimals}f}"
    except Exception:
        return str(val)

holding_map = {row["限额占用方主体"]: dict(row) for _, row in holding_rows.iterrows()}

entity_rows = []
for _, row in rating_rows.iterrows():
    name = row["主体名称"]
    h = holding_map.get(name, {})
    available = float(row["剩余可用限额"]) if row["剩余可用限额"] else 0
    entity_rows.append({
        "name": name,
        "rating": row["内部评级结果"],
        "warning": row["预警等级"],
        "total_limit": fmt(row["理财限额"]),
        "used": fmt(row["已占用限额"]),
        "available": available,
        "available_str": fmt(available),
        "holding_total": fmt(h.get("全穿透持仓合计", 0)) if h else "-",
        "within_1y": fmt(h.get("一年以内", 0)) if h else "-",
        "y1_2": fmt(h.get("一至二年", 0)) if h else "-",
        "over_2y": fmt(h.get("二年以上", 0)) if h else "-",
        "policy": row["品种（信用政策）"],
        "expire": str(row["评级有效期"])[:10],
    })

# 合计行
total_limit = sum(float(r["理财限额"]) for _, r in rating_rows.iterrows())
total_used = sum(float(r["已占用限额"]) for _, r in rating_rows.iterrows())
total_avail = sum(float(r["剩余可用限额"]) for _, r in rating_rows.iterrows())
total_holding = holding_rows["全穿透持仓合计"].sum() if len(holding_rows) else 0
total_1y = holding_rows["一年以内"].sum() if len(holding_rows) else 0
total_1_2y = holding_rows["一至二年"].sum() if len(holding_rows) else 0
total_2y = holding_rows["二年以上"].sum() if len(holding_rows) else 0

total = {
    "total_limit": fmt(total_limit),
    "used": fmt(total_used),
    "available": total_avail,
    "available_str": fmt(total_avail),
    "holding_total": fmt(total_holding),
    "within_1y": fmt(total_1y),
    "y1_2": fmt(total_1_2y),
    "over_2y": fmt(total_2y),
    "used_pct": f"{total_used/total_limit*100:.1f}",
}

bond_holdings = []
for _, row in bond_rows.iterrows():
    bond_holdings.append({
        "name": row["债券名称"],
        "code": str(row["债券代码"]),
        "amount": fmt(row["持仓金额"]),
        "internal_rating": row["内部评级结果"],
        "external_rating": row["外部评级"],
        "maturity": str(row["到期日"])[:10],
        "issuer": row["限额占用主体"],
    })

# 综合分析文字（模拟 LLM 输出，实际生产走企业内网 LLM）
comprehensive_analysis = f"""象屿系是厦门国有控股企业，主业涵盖大宗商品供应链管理、地产开发及金融服务。整体信用资质较好，集团总公司及核心子公司（象屿集团、象屿股份）内部评级均维持 **AA**，处于可准入范围。

**风险关注点：**
- 厦门象屿供应链管理股份有限公司及象屿金象控股集团有限公司预警等级已升至"关注"，剩余可用限额压缩明显（分别剩余 {fmt(1400)} 万、{fmt(1100)} 万），续作时需重点核查最新财务数据；
- 集团系整体剩余可用限额 **{fmt(total_avail)} 万**，占批复总限额比例约 {total_avail/total_limit*100:.1f}%，整体占用率偏高，新增投放空间有限；
- 集团内部债务规模持续扩张，需关注供应链业务中应收账款周转及短期流动性压力。

**正面因素：**
- 象屿系为厦门市国资委直属国企，隐性信用支撑较强；
- 集团整体外部评级与内部评级保持一致，信用稳定性较好；
- 存续债到期结构较均衡，1 年内到期占全穿透持仓 {total_1y/total_holding*100:.1f}%，流动性风险可控。"""

meeting_suggestions = f"""1. **准入额度使用已趋饱和**：集团系批复总限额 {fmt(total_limit)} 万，当前已用 {fmt(total_used)} 万（占用率 {total_used/total_limit*100:.1f}%），建议向客户说明整体准入空间有限，新增申请需提前申请额度调整。

2. **关注类主体处理**：象屿供应链、象屿金象两家子公司已列入"关注"名单，现有持仓可维持但不宜新增，拜访中可了解其当前财务状况及展期计划，为年底评级审查收集资料。

3. **到期续作窗口**：24象屿MTN001（{fmt(23500)}万，12月到期）、24象屿股份MTN001（{fmt(24200)}万，11月到期）将在近半年集中到期，拜访时可提前沟通续发意向及利率区间。

4. **集团整体深化合作**：象屿农产品子公司剩余可用限额相对充裕（{fmt(5200)}万），可探讨绿色农业供应链债券等新品种投资机会，配合集团业务扩张节奏。

5. **建议拜访路径**：集团财务部 → 各子公司分管副总，重点收集 2025 年报及 2026Q1 财务数据，作为半年度评级复审依据。"""

# ─── 8. 渲染 Jinja2 模板 ──────────────────────────────────────
from jinja2 import Environment, FileSystemLoader  # noqa: E402

template_dir = ROOT / "skills" / "meeting_report"
env = Environment(loader=FileSystemLoader(str(template_dir)))
tmpl = env.get_template("template.md.j2")

report_md = tmpl.render(
    group_name=GROUP_NAME,
    data_date=DATA_DATE,
    generate_time=GENERATE_TIME,
    entity_rows=entity_rows,
    total=total,
    bond_holdings=bond_holdings,
    comprehensive_analysis=comprehensive_analysis,
    meeting_suggestions=meeting_suggestions,
)

# ─── 9. 写入输出文件 ─────────────────────────────────────────
output_dir = ROOT / "data" / "outputs"
output_dir.mkdir(parents=True, exist_ok=True)
output_path = output_dir / f"参谈要点_{GROUP_NAME}_{DATA_DATE.replace('-','')}.md"
output_path.write_text(report_md, encoding="utf-8")

print(f"\n{'='*60}")
print(f"✅ 报告生成完成：{output_path}")
print(f"   集团成员：{len(entity_rows)} 家")
print(f"   存续债：{len(bond_holdings)} 只")
print(f"   报告大小：{len(report_md)} 字符")
print('='*60)
print("\n📄 报告预览（前 30 行）：\n")
for _i, line in enumerate(report_md.split('\n')[:30]):
    print(line)
