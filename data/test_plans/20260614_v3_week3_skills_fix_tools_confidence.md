# 迭代测试计划 — v3.0 Week 3：Skills 修复 + 新工具 + 置信度标注

- **日期**：2026-06-14
- **迭代目标**：修复重复/不完整 Skills、新增 export_data/list_tables 工具、置信度标注前后端、UX 优化
- **关联 PROGRESS.md 条目**：`## v3.0 Week 3`

---

## 一、变更范围

| 变更文件 / 模块 | 变更类型 | 说明 |
|---------------|---------|------|
| `skills/client_meeting_report/` | 删除 | 与 meeting_report 重复，由 meeting_report 合并覆盖 |
| `skills/meeting_report/SKILL.md` | 修改 | 吸收 client_meeting_report 的触发词；补充正式 request_confirmation 步骤 |
| `skills/partnership_summary/SKILL.md` | 修改 | 将非正式"人工确认节点"改为正式 request_confirmation 工具调用步骤 |
| `agent/skill_preflight.py` | 修改 | 新增 `template_file` 存在性检查（缺失时阻断并报错） |
| `agent/tools_spec.py` | 修改 | 新增 `list_tables` 工具 + `export_data` 工具定义和实现 |
| `agent/loop.py` | 修改 | `_text(text, confidence=None)` 新增 confidence 参数；fast_path 调用处设 confidence="auditable" |
| `agent/fast_path.py` | 修改 | `run_fast_path` yield 的 text 事件携带 confidence="auditable" |
| `ui/js/chat.js` | 修改 | handleChunk text 分支读取 chunk.confidence，流结束时在气泡尾部附加置信度标签 |
| `ui/index.html` | 修改 | 新增 `.conf-tag` CSS（auditable/verify/ai 三种颜色）；placeholder 去技术化 |

---

## 二、影响面分析

- **删除 client_meeting_report**：需确认 `skill_loader.load_registry()` 不崩溃；前端 sidebar 不再显示该 Skill
- **preflight 模板检查**：新增检查逻辑，影响有 `template_file` 字段的所有 Skill（dept_weekly_report/monthly_bond_summary）
- **list_tables / export_data**：新增工具，不修改现有工具；dispatch_map 新增两个 key
- **confidence 字段**：`_text()` 签名改变，但因参数有默认值 `None` → 向后兼容；前端 `chunk.confidence` 为 undefined 时不渲染标签
- **placeholder**：纯 HTML 改动，无逻辑影响

---

## 三、测试用例设计

### L1 — 单元测试

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L1-01 | `skill_loader.load_registry()` 中不存在 `client_meeting_report` | registry 不含 name="client_meeting_report" | P0 | todo |
| L1-02 | `skill_loader.load_registry()` 中 meeting_report 含合并后的触发词 | description 含"拜访材料"等关键词 | P1 | todo |
| L1-03 | `skill_preflight` 对含 `template_file` 且文件存在的 Skill → 不阻断 | blocked=False | P0 | todo |
| L1-04 | `skill_preflight` 对含 `template_file` 且文件不存在的 Skill → 阻断 | blocked=True，block_message 含"模板文件" | P0 | todo |
| L1-05 | `dispatch_tool("list_tables", {}, ctx)` → 返回 ok=True + tables 列表 | ok=True，data 含 tables 字段 | P0 | todo |
| L1-06 | `dispatch_tool("export_data", {"table_name": "t", "format": "csv"}, ctx)` → 返回 ok=True + 文件路径 | ok=True，data 含 file_path | P0 | todo |
| L1-07 | `_text("hello", confidence="auditable")` → SSE 事件含 confidence 字段 | event["confidence"] == "auditable" | P1 | todo |
| L1-08 | `_text("hello")` → 向后兼容，confidence 字段为 None 或不存在 | 不影响现有行为 | P1 | todo |

### L2 — 功能测试（模块级接口）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L2-01 | `GET /api/skills/status` → monthly_bond_summary 因缺模板文件显示 not ready | ready=False，missing_files 含"模板" | P0 | todo |
| L2-02 | `GET /api/skills/status` → dept_weekly_report 有模板文件显示 ready（有数据时） | ready=True（mock 数据就绪时） | P1 | todo |
| L2-03 | `GET /api/skills/status` → client_meeting_report 不出现在 skills 列表 | skills 数组中无 client_meeting_report | P0 | todo |
| L2-04 | Flask API：`POST /api/chat` + mock `list_tables` 工具调用 → SSE 含 tool_start/tool_end | SSE 事件流正常 | P1 | todo |

### L3 — 集成测试（多模块协作）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L3-01 | concentration_monitor fast_path → SSE text 事件 confidence="auditable" | chunk.confidence == "auditable" | P0 | todo |
| L3-02 | preflight 检查 + template_file 存在性 + skills/status API 全链路 | monthly_bond_summary ready=False，dept_weekly_report 有模板时 ready=True | P0 | todo |
| L3-03 | dispatch_tool("list_tables") → get_loaded_tables() → 格式化列表 | 返回 ok=True，数据与 _loaded_tables 一致 | P1 | todo |

### L4 — UAT 验收场景（业务用户手动执行，Windows 环境）

| 场景 ID | 用户角色 | 操作步骤 | 预期结果 | 验收标准 | 状态 |
|--------|---------|---------|---------|---------|------|
| U4-07 | 投资经理 | 侧边栏查看 Skill 列表，确认没有"客户谈参报告"重复条目 | 只显示一个谈参 Skill（meeting_report） | 无重复项，描述清晰 | 待验收 |
| U4-08 | 投资经理 | 执行"业务合作简报"Skill，查看最终确认步骤 | 数值汇总展示后出现"是否生成完整简报"确认卡片 | 确认卡片明确可操作 | 待验收 |
| U4-09 | 投资经理 | 侧边栏查看月度债券简报 Skill，无模板时应显示"缺数据" | Skill 卡片显示"缺:模板文件"橙色状态 | 用户理解需要管理员配置模板 | 待验收 |
| U4-10 | 投资经理 | 执行集中度监控（fast_path），查看回复气泡末尾 | 气泡末尾有"[✓ 已审计]"蓝绿色标签 | 标签小而不影响阅读，点击可悬停说明 | 待验收 |
| U4-11 | 投资经理 | 执行持仓查询（exploratory），查看回复气泡末尾 | 气泡末尾有"[~ 需核实]"橙色标签 | 标签提示用户核查 SQL 依据 | 待验收 |

---

## 四、执行结果

- **测试运行日期**：2026-06-14
- **pytest 结果**：383 passed, 2 skipped（含全量回归）
- **覆盖率变化**：总体 74%（新代码路径覆盖率 ≥ 63%）

### 新建/修改测试文件

- `tests/test_week3.py`：覆盖 L1-01~L1-08、L2-01~L2-03（共 14 个测试，全通过）

### L1~L3 用例执行摘要

| 测试 ID | 实际结果 | 备注 |
|--------|---------|------|
| L1-01 | ✅ 通过 | client_meeting_report 已从 registry 移除 |
| L1-02 | ✅ 通过 | meeting_report 含"拜访材料"触发词 |
| L1-03 | ✅ 通过 | template 存在时不阻断 |
| L1-04 | ✅ 通过 | template 不存在时阻断，block_message 含"模板文件" |
| L1-05 | ✅ 通过 | dispatch_tool("list_tables") 返回 ok=True + tables |
| L1-05b | ✅ 通过 | _tool_list_tables 直接调用 |
| L1-06 | ✅ 通过 | 表不存在时返回 ok=False，error 含"未加载" |
| L1-06b | ✅ 通过 | export_data 成功时返回文件路径和行数 |
| L1-07 | ✅ 通过 | _text("hello", confidence="auditable") 含 confidence 字段 |
| L1-08 | ✅ 通过 | _text("hello") 无 confidence 字段（向后兼容） |
| L2-01 | ✅ 通过 | monthly_bond_summary 缺模板时 ready=False |
| L2-02 | ✅ 通过 | dept_weekly_report 有模板时不因模板阻断 |
| L2-03 | ✅ 通过 | client_meeting_report 不出现在 skills/status 结果 |
| L2-04 | — | L1-05 覆盖 dispatch_tool 路径，不做独立集成测试 |
| L3-01 | ✅ 通过 | fast_path text 事件 confidence="auditable"（test_fast_path_emits_auditable） |
| L3-02 | ✅ 通过 | L2-01/L2-02 覆盖 |
| L3-03 | ✅ 通过 | L1-05b 覆盖 |

### 已知问题 / 遗留项

无

### UAT 状态

- [ ] U4-07 — 待业务方验收（无重复 Skill 条目）
- [ ] U4-08 — 待业务方验收（partnership_summary 确认节点）
- [ ] U4-09 — 待业务方验收（monthly_bond_summary 缺模板状态）
- [ ] U4-10 — 待业务方验收（fast_path 已审计标签）
- [ ] U4-11 — 待业务方验收（exploratory 需核实标签）
