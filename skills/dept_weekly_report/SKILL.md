---
name: dept_weekly_report
description: |
  生成某个投资部门的周度投资情况报告，按部门维度汇总本周持仓变化、收益表现、资产结构等。
  支持手动触发和每周定时自动生成两种方式。
  触发词：周报、每周报告、部门周报、本周情况、周度统计
required_table_types:
  - holding              # 必须：本期持仓数据
  - nav                  # 建议：净值数据
optional_table_types:
  - rating_entity        # 可选：评级数据
template_file: template.md.j2
---

## 适用场景
每周生成投资部门维度的工作简报，汇总本周持仓状况、收益表现、资产结构分布等。
报告内容和格式以后续提供的周报模板为准，当前先按标准结构生成。

## 前提条件
已加载本期持仓数据表，且已在 config.yaml 中配置当前用户的部门信息。

## 执行步骤

### Step 1：确定部门范围
- 从 config.yaml 读取 `user_profile.department`
- 从 config.yaml 读取 `user_profile.managed_products`（该部门管理的产品列表）
- 若用户在指令中指定了其他部门，以指令为准

### Step 2：部门持仓汇总
```sql
SELECT
  G06一级分类 AS 资产类型,
  COUNT(DISTINCT 资产代码) AS 品种数,
  COUNT(DISTINCT 产品名称) AS 涉及产品数,
  ROUND(SUM("资产市值_穿透后") / 10000, 2) AS "合计市值(万元)"
FROM holding_table
WHERE 产品名称 IN ({dept_products_list})  -- 替换为部门产品列表
GROUP BY G06一级分类
ORDER BY "合计市值(万元)" DESC
LIMIT 30
```

### Step 3：评级分布统计
```sql
SELECT
  CASE
    WHEN 外部评级 = 'AAA' THEN 'AAA'
    WHEN 外部评级 = 'AA+' THEN 'AA+'
    WHEN 外部评级 = 'AA' THEN 'AA'
    WHEN 外部评级 IS NULL OR 外部评级 = '' THEN '无评级'
    ELSE 'AA-及以下'
  END AS 评级区间,
  ROUND(SUM("资产市值_穿透后") / 10000, 2) AS "市值(万元)",
  COUNT(DISTINCT 资产代码) AS 品种数
FROM holding_table
WHERE 产品名称 IN ({dept_products_list})
GROUP BY 评级区间
ORDER BY "市值(万元)" DESC
LIMIT 10
```

### Step 4：各产品净值表现（如已加载净值表）
```sql
SELECT
  产品名称,
  单位净值,
  "当前周期年化收益率(%)",
  "本季度最大回撤(%)"
FROM nav_table
WHERE 产品名称 IN ({dept_products_list})
ORDER BY "当前周期年化收益率(%)" DESC
LIMIT 20
```

### Step 5：生成报告文字
将数值统计结果交给企业内网 LLM，生成周报文字说明段落。

## 人工确认节点
定时任务自动生成：直接输出，保存到 data/outputs/ 目录，并通过 chat 通知用户
用户手动触发：展示数值汇总后询问确认，再生成完整报告

## 输出路径
`data/outputs/周报_{部门名称}_{年份}第{周次}周.md`

## 注意事项
- 周报模板样式待业务人员后续提供，提供后更新 template.md.j2
- 当前按标准结构输出，格式确认后可一键切换为正式模板
- 若某产品本期无持仓数据，在报告中注明"本期无持仓"
