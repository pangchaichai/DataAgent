# Step R4：未知表「内联推断」字段语义（非独立草稿确认流）

> 与 CC4.6 的 `schema_discovery` 目标一致（让未知表也能用），但**形式不同**：
> 不做"上传→生成草稿 YAML→用户逐字段确认→才可查"的前置表单，而是
> **Agent 在对话里临时推断、即用即纠、确认后再固化**。前者新增门槛，后者降低门槛。

依赖 R1（Agent 循环 + `profile_table`）。

---

## 前置阅读

- R1 的 `tools/profiler.py` 与 loop
- `tools/data_loader.py` 的字典映射逻辑、`DICT_TABLE_MAP`
- `data_dictionary/holding_dict.yaml`（字典 YAML 结构样例）

---

## 机制

1. 上传未知类型表（`table_type='unknown'` 或无对应 `*_dict.yaml`）：**照常入库**，不阻断、不弹草稿。
2. 用户就该表提问时，loop 中 Agent 调 `profile_table` → 基于列名+样本形成**字段语义假设**（哪列是日期、市值、主体、产品…）。
3. Agent **直接用假设回答**，并在答复中**显式声明假设**：
   > "这张表没有预设字典，我推断'持仓市值'对应列 `mkt_val_pen`。如不对请指正。"
4. 用户纠正（"市值应该用 `mkt_val_full`"）→ Agent 记住本会话；并可调用新工具 `propose_dict_entry` 把该映射**追加为草稿**。
5. 仅当用户明确说"保存为字典/以后都这样"时，才 `confirm_dict` 落到 `data_dictionary/`（写盘需人工确认节点）。

> 核心差别：**先能用，错了再固化**；确认是可选的收尾，不是使用的前置。

---

## 新增工具（挂到 R1 的 tools_spec）

- `propose_dict_entry(table_type, semantic_name, physical_column)`：写入 `data_dictionary/drafts/{table_type}_draft.yaml`（草稿，不进正式映射）。
- `confirm_dict(table_type)`：把草稿合并进正式 `{table_type}_dict.yaml`——**必须经 `request_confirmation`**（写盘是不可逆动作）。

合规边界：
- **B 类（合规/报告）禁止使用"推断字段"**。固化计算只认正式字典里的物理列；未确认字典的表不能跑 `run_calculator`，Agent 须提示"该口径需先确认字段映射"。
- 推断只服务 A 类探索式查询。

---

## 外发安全

若 `external_allowed=true` 且 primary 为外网：`profile_table` 回流给 LLM 的样本需走脱敏（主体/产品→占位、数值→量级、日期→格式）。在 `profiler.py` 增加 `sanitize=True` 选项，由 loop 根据 provider 是否外网决定。`external_allowed=false` 时不脱敏（仅内网）。

---

## 验收（`tests/test_intelligence.py` 或 `test_profiler.py`）

- `test_infer_unknown_table_inline()`：未知表提问 → 事件流含字段假设说明，且能返回结果。
- `test_proposed_dict_is_draft_only()`：`propose_dict_entry` 只写 drafts/，不改正式字典。
- `test_confirm_dict_requires_confirmation()`：`confirm_dict` 必经确认节点。
- `test_calculator_rejects_inferred_table()`：未确认字典的表跑 B 类被拒。
- `test_sanitize_sample_when_external()`：外网场景样本被脱敏。

---

## 交付物

- [ ] profiler 增 `sanitize` 选项
- [ ] `propose_dict_entry` / `confirm_dict` 工具 + 分发
- [ ] `data_dictionary/drafts/` 目录
- [ ] 单测 5 项；旧测试绿
- [ ] 更新 PROGRESS-refactor.md
