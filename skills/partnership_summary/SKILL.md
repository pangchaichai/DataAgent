---
name: partnership_summary
description: |
  按投资部门维度，生成与某个合作主体（发债主体/交易对手）的合作业务情况简报。
  内容包括：各类资产持仓金额、内外部评级结果、限额占用情况。
  触发词：合作简报、合作情况、业务往来、合作主体、部门合作、投资合作
required_table_types:
  - holding              # 必须：持仓数据
  - rating_entity        # 必须：主体评级和限额数据
optional_table_types:
  - rating_bond          # 可选：债券评级明细
---

## 适用场景
投资经理或部门负责人需要了解本部门（或全公司）与某个具体合作主体的全面业务往来情况，
用于业务拜访准备、信用审查、或日常监控。

## 前提条件
已加载：持仓数据表 + 主体评级数据表（含限额信息）

## 执行步骤

### Step 1：确认查询参数
从用户指令中提取：
- `target_entity`：目标合作主体名称（必填）
- `dept_scope`：查询范围，"某个部门名称" 或 "全公司"（默认全公司）
- 当前用户部门：从 config.yaml 用户档案获取

### Step 2：按资产大类统计持仓
```sql
SELECT
  G06一级分类 AS 资产类型,
  COUNT(DISTINCT 资产代码) AS 持仓品种数,
  ROUND(SUM("资产市值_穿透后") / 10000, 2) AS "持仓金额(万元)",
  ROUND(SUM("资产市值_穿透后") / 10000 /
        (SELECT SUM("资产市值_穿透后") / 10000
         FROM holding_table
         WHERE 限额占用方主体 LIKE '%{target_entity}%') * 100, 2) AS "占比(%)"
FROM holding_table
WHERE 限额占用方主体 LIKE '%{target_entity}%'
-- 若指定部门，需关联部门过滤（通过产品名称匹配用户档案中的部门产品清单）
GROUP BY G06一级分类
ORDER BY "持仓金额(万元)" DESC
LIMIT 50
```

### Step 3：查询主体评级和限额
```sql
SELECT
  主体名称, 内部评级结果, 预警等级,
  ROUND(理财限额 / 10000, 0) AS "理财限额(万元)",
  ROUND(已占用限额 / 10000, 0) AS "已占用(万元)",
  ROUND(剩余可用限额 / 10000, 0) AS "剩余可用(万元)",
  "品种（信用政策）",
  评级有效期
FROM rating_entity_table
WHERE 主体名称 LIKE '%{target_entity}%'
LIMIT 10
```

### Step 4：人工确认（request_confirmation）
将持仓统计表和评级限额结果展示给用户，使用 `request_confirmation` 工具请求确认：
- 展示：主体名称、总持仓金额、限额占用率
- 确认提示："是否生成完整文字简报（数值已确认，文字由企业内网 LLM 生成）"
- 用户拒绝时：直接输出数值表格，不生成文字简报

### Step 5：生成简报（用户确认后）
将以上数据交给企业内网 LLM 生成文字简报（数值由代码算，文字由 LLM 写）。

## 输出格式（参考，模板后续补充）
```
【合作业务情况简报】
主体：{target_entity}  查询范围：{dept_scope}  数据日期：{data_date}

一、当前业务合作情况
{asset_type_table}  ← 资产类型分类统计表格

二、主体评级及限额情况
内部评级：{internal_rating}  |  外部评级：{external_rating}
理财限额：{limit}万元  |  已占用：{used}万元  |  剩余可用：{available}万元

三、综合情况说明
{llm_generated_summary}  ← 企业内网 LLM 生成
```

## 注意事项
- 主体名称支持模糊匹配（LIKE），用户无需输入完整名称
- 若部门范围为"全公司"，不做产品过滤
- 若部门范围为特定部门，通过 config.yaml 的用户档案筛选该部门管理的产品列表
