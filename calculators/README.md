# DataAgent 固化计算模块（calculators/）

> **核心原则**：合规指标和固定报告的数值，必须从这里调用，不允许 LLM 现编 SQL。
>
> 探索式临时查询 → LLM 生成 SQL（允许灵活）
> 合规监控 + 运作报告 + 参谈要点 → calculators/ 中的固化函数（禁止 LLM 生成 SQL）

---

## 为什么要固化

DuckDB 执行 SQL 只保证「算术精确」，不保证「口径正确」。
如果让 LLM 每次现编集中度 SQL，它可能：
- 把「穿透后市值」取成「半穿透市值」
- 漏掉集团合并逻辑
- 忘记排除现金/存款类资产

这些错误会产生「精确的错误数字」——比 AI 估算更危险，因为看起来权威。

固化计算函数的特点：
- 口径由合规部门和业务方确认后写死
- 有单元测试覆盖
- 参数化暴露（阈值、口径开关），不暴露计算逻辑给 LLM

---

## 模块结构

```
calculators/
├── README.md                   ← 本文件
├── concentration.py            ← 集中度计算（主体/单券，支持集团合并）
├── nav_metrics.py              ← 净值和收益率指标计算
├── asset_structure.py          ← 资产结构分布计算
├── credit_distribution.py      ← 信用评级分布计算
└── _base.py                    ← 基础工具（字段映射、口径开关读取）
```

---

## 口径开关说明

口径开关通过 config.yaml 的 `calculation_config` 区块配置，不改代码：

```yaml
calculation_config:
  concentration:
    market_value_field: "穿透后市值"   # C-01确认后改为实际口径
    use_group_merge: true              # true=集团合并口径
    exclude_asset_types: []            # 排除的资产大类（如现金）
  nav:
    return_annualization_days: 365
```
