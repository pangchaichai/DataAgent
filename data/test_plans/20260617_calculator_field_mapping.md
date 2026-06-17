# 迭代测试计划：计算器字段映射参数化（Path B）

**迭代名称**：calculator_field_mapping_parameterization
**日期**：2026-06-17
**变更范围**：calculators/ 全部 7 个模块 + agent/tool_dispatch.py + tools/data_loader.py

---

## 变更分析

### 问题描述
所有 7 个固化计算器（B 类）的 SQL 中硬编码了语义列名（如 `产品名称`、`限额占用方主体`），
当用户上传的数据源物理列名不同时（如 `产品简称`、`限额占用方`），计算器 SQL 直接报列名不存在错误。
而 A 类探索式查询（run_sql）通过 `apply_field_map()` 正确处理了这个问题。

### 修复方案（Path B：全参数化）
1. 新建 `calculators/columns.py` — 语义列名常量 + `resolve_columns()` 函数
2. 所有计算器函数新增 `cols=None` 参数，SQL 使用 `cols` 字典获取物理列名
3. `agent/tool_dispatch.py` 新增 `_resolve_cols_for_table()` 和 `_resolve_mv_field()`
4. `tools/data_loader.py` 新增 `get_field_map_for_table()` 接口

### 向后兼容设计
- `cols=None` 默认值 → 使用语义名本身（与修改前行为完全一致）
- 所有既有测试无需修改即可通过

---

## L1 单元测试

### resolve_columns 基础（7 个测试）
- [x] None field_map 返回语义名自身
- [x] 正常映射返回物理列名
- [x] 必需列缺失抛 ColumnResolutionError
- [x] 可选列缺失回退到语义名
- [x] 可选列有映射时使用映射
- [x] 空 field_map 对必需列抛异常
- [x] 常量都是字符串类型

### 每个计算器的列名映射测试（9 个测试）
- [x] concentration: 非默认列名（产品简称 + 限额占用方）正确计算
- [x] concentration: cols=None 向后兼容
- [x] nav_metrics: 非默认列名（基金简称 + 数据日期）正确计算
- [x] nav_metrics: cols=None 向后兼容
- [x] asset_structure: 非默认列名正确计算
- [x] asset_structure: top_n_holdings 非默认列名
- [x] credit_distribution: 非默认列名正确计算
- [x] position_diff: 非默认列名正确识别加仓/清仓/新建仓
- [x] leverage: 非默认产品名列正确计算
- [x] liquidity: 非默认列名正确计算

### tool_dispatch 解析层（5 个测试）
- [x] 无已加载表时返回 None
- [x] 无已加载表时市值字段直接透传
- [x] mock field_map 正确映射
- [x] mock field_map 市值字段正确翻译
- [x] 未映射列回退到语义名

### 端到端集成（4 个测试）
- [x] 真实投资团队格式：集中度计算正确（50%/30%/20%）
- [x] 真实投资团队格式：资产结构占比和为 100%
- [x] 真实投资团队格式：评级分布占比正确
- [x] 真实投资团队格式：流动性分层正确

---

## L2 功能测试

### 既有计算器测试全量通过（30 个测试）
- [x] test_calculators.py 全部 30 个测试 PASSED

### 全量回归（601 个测试）
- [x] tests/ 全量 601 passed, 2 skipped, 0 failed

---

## L3 集成测试

- [x] tool_dispatch 层通过 monkeypatch 验证字段映射传导链路
- [x] 计算器在收到 cols 参数后生成正确的 SQL（AS 别名保证下游 DataFrame 列名不变）

---

## 执行结果

| 层级 | 测试数 | 通过 | 失败 | 跳过 |
|------|--------|------|------|------|
| L1（新增） | 26 | 26 | 0 | 0 |
| L2（既有回归） | 575 | 575 | 0 | 2(skip) |
| L3（集成） | 含在 L1 中 | — | — | — |
| **合计** | **601** | **601** | **0** | **2** |
