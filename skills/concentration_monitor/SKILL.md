---
name: concentration_monitor
description: |
  监控理财产品的集中度超标情况（主体集中度或单券集中度）。
  找出超过监管阈值的产品，生成超标提示清单，标注负责投资经理。
  触发词：集中度、超标、超限、监控、合规检查、主体集中度、单券集中度
calc_type: fixed
fixed_calculator: calculators.concentration.calc_entity_concentration
required_table_types:
  - holding
optional_table_types:
  - user_product_mapping
default_args:
  market_value_field: "穿透后市值"
  threshold_entity: 10.0
  threshold_single_bond: 10.0
  use_group_merge: true
---

## 重要：本 Skill 使用固化计算，不允许 LLM 生成 SQL

本 Skill 的数值计算由 `calculators/concentration.py` 中的固化函数完成。
计算口径由 `config.yaml` 的 `calculation_config.concentration` 配置。
**Agent 不得为此 Skill 生成任何 SQL，直接调用固化函数。**

## 适用场景
合规检查：检查当前持仓是否存在主体集中度或单券集中度超标。
定时任务自动触发（每工作日 08:30）或用户手动触发。

## 前提条件
已加载持仓数据表（date_tag 为今日，时效校验通过）。

## 执行流程

### Step 1：数据时效校验（必须通过，否则终止）
检查已加载持仓表的 date_tag 是否为今日（或在允许时差内）。
过期则告警「持仓数据不是今日最新，合规计算已停止。请上传今日数据后重试。」

### Step 2：调用固化计算函数
```python
from calculators.concentration import calc_entity_concentration
results = calc_entity_concentration(
    conn=conn,
    holding_table=session.latest_table('holding'),
    market_value_field=config['calculation_config']['concentration']['market_value_field'],
    threshold_pct=config['calculation_config']['concentration']['threshold_entity'],
    use_group_merge=config['calculation_config']['concentration']['use_group_merge'],
    group_mapping=entity_manager.get_group_mapping(),
    entity_alias=entity_normalizer.alias_to_canonical,
    product_filter=user_profile.managed_products or None,
)
```

### Step 3：匹配投资经理并生成提示清单

将超标结果与 config.yaml 用户档案中的 managed_products 关联，
得出每条超标记录对应的负责投资经理。

### Step 4：写合规审计日志
```python
compliance_audit.log_compliance_event(
    event_type='monitoring',
    skill_name='concentration_monitor',
    data_files=[session.get_file_info('holding')],
    sql_or_formula='calculators.concentration v1.3',
    thresholds={'threshold_entity': threshold_pct, 'use_group_merge': use_group_merge},
    result_summary={'breach_count': len(results)},
    confirmed_by=user_profile.name,
)
```

## 输出格式

```
【集中度超标提示】 数据日期：{data_date}  计算口径：{口径说明}

共发现 {count} 条超标记录

─────────────────────────────
产品：{product_name}  负责经理：{manager_name}
  超标主体：{entity_name}（集团合并后）
  当前集中度：{value}%  |  监控阈值：{threshold}%
─────────────────────────────
```

若无超标：「✅ {data_date} 数据检查完成，当前无集中度超标情况」

## 注意事项
- 口径（穿透vs半穿透、集团合并vs单主体）由 config.yaml 配置，本文件不定义
- 集团合并口径：象屿集团+象屿股份+... 的持仓合并计算，来自 groups.yaml
- 数据时效不合格时，绝不使用旧数据计算（防止输出假合规结果）
