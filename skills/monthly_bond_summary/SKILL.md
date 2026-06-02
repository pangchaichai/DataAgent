---
name: monthly_bond_summary
description: |
  生成月度全公司（或指定部门）债券投资情况简报，统计各部门各类型债券持仓情况。
  触发词：月报、月度简报、债券简报、月度债券、本月投资情况、月度统计
required_table_types:
  - holding              # 必须：持仓数据（债券类资产）
optional_table_types:
  - rating_entity        # 可选：主体评级
  - rating_bond          # 可选：债券评级
template_file: template.md.j2
---

## 适用场景
每月生成全公司债券投资情况简报，按部门维度分类汇总各类型债券的持仓规模、评级分布、期限结构等。

## 前提条件
已加载当月最新持仓数据表。

## 执行步骤

### Step 1：筛选债券类资产
```sql
-- 先确认持仓表中债券类资产的分类标识
SELECT DISTINCT G06一级分类 FROM holding_table LIMIT 20
-- 根据结果确定债券类的分类标识（通常包含"债券"或"信用"等关键词）
```

### Step 2：按债券类型分类统计（全公司）
```sql
SELECT
  G06一级分类 AS 债券大类,
  G06二级分类 AS 债券细类,
  COUNT(DISTINCT 资产代码) AS 持仓品种数,
  COUNT(DISTINCT 产品名称) AS 涉及产品数,
  ROUND(SUM("资产市值_穿透后") / 100000000, 4) AS "持仓金额(亿元)"
FROM holding_table
WHERE G06一级分类 LIKE '%债券%'  -- 根据实际数据调整
GROUP BY G06一级分类, G06二级分类
ORDER BY "持仓金额(亿元)" DESC
LIMIT 50
```

### Step 3：期限结构分析
```sql
SELECT
  CASE
    WHEN 剩余期限 <= 1 THEN '1年以内'
    WHEN 剩余期限 <= 3 THEN '1-3年'
    WHEN 剩余期限 <= 5 THEN '3-5年'
    ELSE '5年以上'
  END AS 期限区间,
  COUNT(DISTINCT 资产代码) AS 品种数,
  ROUND(SUM("资产市值_穿透后") / 100000000, 4) AS "金额(亿元)"
FROM holding_table
WHERE G06一级分类 LIKE '%债券%'
GROUP BY 期限区间
ORDER BY "金额(亿元)" DESC
LIMIT 10
```

### Step 4：评级分布
```sql
SELECT
  外部评级, COUNT(DISTINCT 资产代码) AS 品种数,
  ROUND(SUM("资产市值_穿透后") / 100000000, 4) AS "金额(亿元)"
FROM holding_table
WHERE G06一级分类 LIKE '%债券%'
GROUP BY 外部评级
ORDER BY "金额(亿元)" DESC
LIMIT 10
```

## 人工确认节点
展示各维度统计汇总后，用户确认数据正确后生成完整简报。

## 输出路径
`data/outputs/月度债券投资简报_{YYYY年MM月}.md`

## 注意事项
- 债券大类的过滤条件（G06一级分类 LIKE '%债券%'）在实际数据中可能需要调整
- 月度简报模板样式待业务人员后续提供，提供后更新 template.md.j2
