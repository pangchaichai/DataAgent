# DataAgent 数据字典（语义层）

> 本目录是系统的「语义地基」，解决异构 CSV 字段名不统一、主体名称写法不一致、跨表 JOIN 键对不齐三大根本问题。
> 所有 LLM SQL 生成、固化计算函数、SQLGuard 白名单均从此处取字段定义。

---

## 目录结构

```
data_dictionary/
├── README.md                  ← 本文件，字典使用说明
├── holding_dict.yaml          ← 持仓表字段语义字典
├── nav_dict.yaml              ← 净值表字段语义字典
├── rating_entity_dict.yaml    ← 主体评级表字段语义字典
├── rating_bond_dict.yaml      ← 债券评级表字段语义字典
└── entity_alias.yaml          ← 主体别名/归一表（实体归一用）
```

---

## 字典文件格式规范

每个 YAML 文件描述一种数据类型，包含：
- `table_type`：数据类型标识（与 Skill 的 required_table_types 对应）
- `join_keys`：与其他表的关联键定义
- `fields`：字段定义列表（每个字段含语义名、物理列名候选、计算口径说明）

示例（持仓表核心字段）：

```yaml
table_type: holding
join_keys:
  to_nav: {semantic: "产品名称", physical_candidates: ["产品名称", "理财产品名称", "基金名称"]}
  to_rating_entity: {semantic: "限额占用主体", physical_candidates: ["限额占用方主体", "发行人名称", "主体名称"]}
  to_rating_bond: {semantic: "资产代码", physical_candidates: ["资产代码", "债券代码", "证券代码"]}

fields:
  - semantic: "穿透后市值"          # 业务语义名（LLM和计算函数使用此名）
    physical_candidates:            # 各系统导出的可能列名（加载时自动匹配）
      - "资产市值_穿透后"
      - "穿透后市值(元)"
      - "全穿透市值"
    dtype: float
    requires_cleaning: thousands_separator  # 含千分位需清洗
    note: "合规集中度计算优先使用全穿透口径，待C-01确认后固化"
    quote_in_sql: true              # DuckDB SQL中需用双引号包裹
```

---

## 字典加载机制

DataAgent 启动时，`data_loader.py` 加载 CSV 后，自动：
1. 读取对应类型的字典文件
2. 遍历 `physical_candidates` 寻找实际列名匹配
3. 建立「语义名 → 实际列名」映射表，存入 session
4. 不能匹配的字段：显式提示用户，而非静默跳过

LLM 生成 SQL 时，system prompt 中注入的是**语义名和实际列名的映射关系**，而非原始列名，大幅提升 SQL 稳定性。
