---
name: client_meeting_report
description: |
  谈参要点（客户业务合作情况）报告生成器。
  根据客户名称和时间区间，生成两部分内容：
  1. 某行准入及投放情况（逐年评级/限额/用信描述）
  2. 某某理财准入及持仓情况（集团关系树 + 子公司横向对比透视表）
  触发词：谈参要点、拜访材料、客户合作情况、准入投放、业务合作报告
calc_type: exploratory
required_table_types:
  - bank_credit
data_sources:
  - 某行信用数据表（CSV，含客户名称/年份/主体评级/风险限额/用信情况描述）
  - 某某理财信用数据表（可选，含历史年末评级和限额）
  - 持仓表（可选，含半穿透/全穿透持仓）
---

## 适用场景
准备对外拜访某客户前，生成完整的业务合作情况报告，包含银行侧授信历史和理财侧准入持仓情况。

## 必填输入
- `客户名称`：需要分析的企业名称（如"象屿集团"）
- `时间区间`：格式"起始年-结束年"（如"2023-2026"）

## 执行步骤

### Step 1：确认输入
确认用户已提供 `客户名称` 和 `时间区间`，若缺失则用 ask_user 询问。

### Step 2：解析时间区间
从 `时间区间` 解析 start_year 和 end_year。若未提供 current_date，使用系统当前日期。

### Step 3：第一节 — 某行准入及投放情况
检查是否已上传某行信用数据表（含客户名称、年份、主体评级、风险限额、用信情况描述列）。
若未上传，提示用户上传后继续。

执行 SQL：
```sql
SELECT 年份, 主体评级, 风险限额, 用信情况描述
FROM {bank_credit_table}
WHERE 客户名称 = '{客户名称}'
  AND 年份 >= {start_year}
  AND 年份 <= {end_year}
ORDER BY 年份 ASC
LIMIT 20
```

按以下模板输出：
> 经查询，"{客户名称}"在 {year1} 年主体评级为 {rating1}、风险限额为 {limit1}、用信情况描述为"{desc1}"，在 {year2} 年…

若无数据，输出：> 未找到与之匹配的数据。

### Step 4：第二节 — 集团关系树
1. 先用 profile_table 查询 groups.yaml 中是否有该集团成员配置（通过 entity_manager）。
2. 若 groups.yaml 中有，直接使用成员列表，以 ├─ └─ 树状结构输出。
3. 若无配置，调用 web_search 搜索"{客户名称} 集团 子公司"，将结果展示给用户并用 ask_user 确认是否采用。
4. 输出格式示例：
   象屿集团 集团关系树：
   ├─ 象屿集团（集团总公司）
      ├─ 象屿股份
      └─ 象屿金象控股

### Step 5：第三节 — 子公司主体信用及持仓总览（透视表）
获取子公司列表（来自 Step 4），对每个子公司分别查询：

**历史年末数据**（若已上传理财信用数据表）：
```sql
SELECT 主体名称, 内部评级, 理财限额
FROM {credit_table}
WHERE 主体名称 = '{subsidiary}'
  AND 年份 = {year}
LIMIT 1
```

**当前日期数据**（若已上传主体评级表和持仓表）：
```sql
SELECT 内部评级, 理财限额, 已占用限额, 剩余可用限额, 品种信用政策
FROM {rating_entity_table}
WHERE 主体名称 = '{subsidiary}'
LIMIT 1
```

```sql
SELECT SUM(资产市值_半穿透) AS 半穿透持仓, SUM(资产市值_穿透后) AS 全穿透持仓
FROM {holding_table}
WHERE 限额占用方主体 = '{subsidiary}'
LIMIT 1
```

将所有查询结果组装为以子公司为列的 Markdown 透视表：
| 指标 | {sub1} | {sub2} | … | 合计 |
|------|--------|--------|---|------|
| {year}年末级别 | … |
| {year}年末限额 | … |
| {current_date}存续债余额 | … |
| {current_date}级别 | … |
| {current_date}限额 | … |
| {current_date}持仓-半穿透 | … |
| {current_date}持仓-全穿透 | … |
| {current_date}剩余可用限额 | … |

数值型指标合计列求和；评级/政策类填 /。

### Step 6：request_confirmation
展示完整报告给用户确认后输出最终版本。

## 注意事项
- 若某子公司在某表中找不到，对应格填"-"，不终止流程
- 剩余可用限额 = 理财限额 - 半穿透持仓（若评级表中无该字段时使用此公式）
- 本 Skill 为探索式（exploratory），所有 SQL 由 Agent 根据实际列名生成