# DataAgent Skills 开发指南

> 本文档供管理员和高级业务用户阅读，说明如何通过编写 Skill 文件来扩展 DataAgent 能力，**无需修改任何 Python 代码**。

---

## 一、Skills 工作原理

```
DataAgent 启动
    ↓
扫描 skills/ 目录，加载每个 SKILL.md 的 name + description
    ↓
用户输入消息
    ↓
LLM 判断：当前消息是否匹配某个 Skill？
    ↓ 匹配
加载该 Skill 的完整 SKILL.md 内容到上下文
    ↓
LLM 按照 Skill 中定义的规则生成 SQL / 执行分析 / 生成报告
```

关键点：**LLM 在启动时只知道 Skill 的名称和简短描述，只有在任务相关时才加载完整内容。** 这使得添加再多的 Skill 也不会影响系统启动速度和日常对话性能。

---

## 二、Skill 文件结构

```
skills/
└── your_skill_name/           ← 目录名 = Skill 标识符（小写+下划线）
    ├── SKILL.md               ← 必须，Skill 主文件
    └── template.md.j2         ← 可选，Jinja2 报告模板
```

---

## 三、SKILL.md 完整格式规范

```markdown
---
name: skill_name
description: |
  【必填，1-3句话】
  第一句：本 Skill 做什么
  第二句：适用于哪些业务场景
  触发关键词：列出用户可能说的词语，如"运作报告、净值、收益率"
---

## 适用场景
具体描述什么情况下使用本 Skill，以及不适用的情况。

## 前提条件
使用本 Skill 前，用户需要已加载哪些数据表：
- 数据表1：xxx表（字段：产品名称、净值、日期...）
- 数据表2：xxx表（字段：...）

## 参数
用户需要提供（或从对话中提取）的参数：
- `product_name`：产品名称，从持仓表或净值表的产品名称字段获取
- `period`：报告期间，格式 YYYY-MM-DD 至 YYYY-MM-DD
- （可选）`benchmark`：业绩比较基准，默认值 3.0%

## 数据计算规则
> 以下规则 LLM 必须严格遵守，不得自行推断或估算数值

### 指标1：单位净值
- 数据来源：净值表
- SQL 示例：`SELECT 单位净值 FROM nav_table WHERE 产品名称=? AND 估值日期=? LIMIT 1`

### 指标2：区间年化收益率
- 数据来源：净值表
- 字段：当前周期年化收益率(%)
- SQL 示例：`SELECT "当前周期年化收益率(%)" FROM nav_table WHERE 产品名称=? LIMIT 1`

### 指标3：资产结构占比
- 数据来源：持仓表
- 计算方法：按 G06一级分类 分组，各组市值之和 / 总市值 × 100%
- SQL 示例：
  ```sql
  SELECT G06一级分类,
         SUM("资产市值_穿透后") / SUM(SUM("资产市值_穿透后")) OVER() * 100 AS 占比
  FROM holding_table
  WHERE 产品名称 = ?
  GROUP BY G06一级分类
  ORDER BY 占比 DESC
  LIMIT 100
  ```

### 指标4：信用评级分布
- 数据来源：持仓表
- 字段：外部评级
- 分类：AAA、AA+、AA、AA-及以下、无评级
- 计算：各评级市值 / 总市值

### 指标5：前十大持仓
- 数据来源：持仓表
- 排序字段：资产市值_穿透后
- SQL：按市值降序取前10

## 人工确认节点
在以下步骤后，**必须**展示计算结果供用户确认，用户确认后才能继续：
1. 计算完所有数值指标后（继续生成报告前）

## 报告输出
- 模板文件：`template.md.j2`（见同目录）
- LLM 负责生成的段落：市场环境回顾（Section 2.1）、管理人意见（Section 5）
- LLM 生成文字时，输入为精确数值，输出为文字，**禁止在文字中自行编造数字**
- 输出格式：Markdown 文件，保存至 data/outputs/
```

---

## 四、现有 Skill 示例

### 示例1：持仓查询 Skill（position_query）

这是最简单的 Skill，仅包含查询逻辑，无报告模板：

```markdown
---
name: position_query
description: |
  查询特定产品或主体的当前持仓情况，包括持有债券列表、市值、评级等信息。
  适用场景：用户询问"XX产品持有哪些债券"、"XX主体当前持仓多少"、"查一下XX的持仓"。
  触发词：持仓、持有、债券、查询
---

## 适用场景
用户需要快速查看某个产品或主体的当前持仓明细。

## 前提条件
- 持仓表（含字段：产品名称、资产名称、资产代码、资产市值_穿透后、外部评级、G06一级分类）

## 数据计算规则

### 按产品查询持仓
```sql
SELECT 资产名称, 资产代码, "资产市值_穿透后", 外部评级, G06一级分类
FROM holding_table
WHERE 产品名称 = ?
ORDER BY "资产市值_穿透后" DESC
LIMIT 50
```

### 按主体汇总持仓
```sql
SELECT 产品名称,
       SUM("资产市值_穿透后") AS 总持仓市值,
       COUNT(DISTINCT 资产代码) AS 持仓品种数
FROM holding_table
WHERE 资产名称 LIKE '%?%'  -- 主体名称模糊匹配
GROUP BY 产品名称
```

## 输出格式
以表格形式展示，同时展示汇总信息（总市值、品种数）。
无报告模板，直接在对话中展示表格。
```

---

## 五、新增 Skill 检查清单

在创建新 Skill 前，确认以下几点：

- [ ] `name` 字段是否唯一（不与现有 Skill 重名）
- [ ] `description` 是否清晰描述了触发场景（3句话以内）
- [ ] 数据计算规则中的 SQL 是否可以直接在 DuckDB 中执行
- [ ] SQL 中是否含有 LIMIT
- [ ] 是否明确指定了哪些字段来自哪张表
- [ ] 是否定义了人工确认节点（数值类 Skill 必须有）
- [ ] 如有报告模板，是否区分了"数值填充"和"LLM 生成文字"的段落

---

## 六、常见问题

**Q：我可以在 SKILL.md 中写 Python 代码吗？**
A：可以描述计算逻辑，但不要写真正的 Python 代码。写 SQL 示例或自然语言描述计算步骤，LLM 会据此生成实际执行的 SQL。

**Q：如何删除一个不再需要的 Skill？**
A：直接删除 `skills/xxx/` 目录，重启 DataAgent 即生效。

**Q：多个 Skill 可能都匹配同一个用户请求怎么办？**
A：LLM 会根据 description 的精确程度选择最匹配的 Skill。如果发现路由经常错误，需要优化相关 Skill 的 description，使其更精确区分彼此。

**Q：Skill 更新后需要重启应用吗？**
A：目前需要重启（或使用 `/reload-skills` 命令热重载）。
