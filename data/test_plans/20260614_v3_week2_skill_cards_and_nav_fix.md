# 迭代测试计划 — v3.0 Week 2：Skill 卡片 + fund_nav_report 合规修复

- **日期**：2026-06-14
- **迭代目标**：在侧边栏新增 Skill 卡片（含就绪状态+一键执行），修复 fund_nav_report 违规使用 LLM SQL 的合规问题
- **预计完成**：2026-06-21
- **关联 PROGRESS.md 条目**：`## v3.0 Week 2 — Skill 卡片 + fund_nav_report 合规修复`

---

## 一、变更范围

| 变更文件 / 模块 | 变更类型 | 说明 |
|---------------|---------|------|
| `api/skill_api.py` | 修改（新增端点）| 新增 `GET /api/skills/status` 批量 preflight；新增 `POST /api/skills/<name>/execute` |
| `ui/js/sidebar.js` | 修改 | `loadSkills()` 改为渲染 Skill 卡片（描述+就绪状态+执行按钮）；表名点击 → `openProfile()` |
| `ui/js/chat.js` | 修改 | 新增 `executeSkill(skillName)` 函数，复用 SSE 事件流 |
| `skills/fund_nav_report/SKILL.md` | 修改 | `calc_type` 改为 `fixed`，新增 `fixed_calculator` 字段串联 3 个 calculator |

## 二、影响面分析

- **上游依赖**：
  - `sidebar.js` 的 Skill 列表 → 影响前端整体布局
  - `executeSkill()` → 复用 `sendMessage()` 的 SSE 流程，若 SSE 有改动会连带影响
- **下游依赖**：
  - `GET /api/skills/status` → 调用 `skill_preflight.run_preflight()`（已测）
  - `POST /api/skills/<name>/execute` → 调用 `agent/loop.py` 的 `run_agent_loop()`
  - `fund_nav_report` calc_type 变更 → 触发 `fast_path.can_fast_path()` → 调用 nav_metrics + asset_structure + credit_distribution
- **共享状态**：
  - `/api/skills/status` 返回的数据缓存（30s TTL）存在 `session_store._skill_status_cache`
  - SSE 流的 `_stream_queues` 不受影响（复用已有机制）
- **前端 SSE 流**：`executeSkill()` 复用 `handleChunk()` 事件处理，SSE 事件结构不变

## 三、测试用例设计

### L1 — 单元测试

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L1-01 | `can_fast_path()` 对 fund_nav_report（calc_type=fixed）返回 True | 快速路径命中 | P0 | todo |
| L1-02 | `can_fast_path()` 对 fund_nav_report（calc_type 原值 exploratory）返回 False | 路径不命中 | P0 | todo |
| L1-03 | `/api/skills/status` 的缓存逻辑：首次调用写入缓存，30s 内第二次调用读缓存 | 两次结果一致，第二次无 preflight 调用 | P1 | todo |
| L1-04 | `run_preflight()` 对 fund_nav_report（无 required_files）返回 ready=True | 无依赖声明时不阻断 | P1 | todo |
| L1-05 | fund_nav_report 三个 calculator 的计算结果格式化：nav_metrics / asset_structure / credit_distribution 各自有输出 | 各模块输出非空，无 KeyError | P0 | todo |

### L2 — 功能测试（模块级接口）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L2-01 | `GET /api/skills/status` — 有 3 个 Skill 已加载时 | 返回 JSON，包含 `skills` 数组，每项有 `name / description / ready / missing_files` 字段 | P0 | todo |
| L2-02 | `GET /api/skills/status` — Skill 缺数据时（concentration_monitor 无持仓表）| `ready: false`，`missing_files: ["持仓表"]` | P0 | todo |
| L2-03 | `GET /api/skills/status` — Skill 数据就绪时 | `ready: true`，`missing_files: []` | P0 | todo |
| L2-04 | `POST /api/skills/<name>/execute` — 有效 Skill 名 + 有数据 | 返回 SSE 流，第一个 event 为 `tool_start` 或 `text` | P0 | todo |
| L2-05 | `POST /api/skills/<name>/execute` — 无效 Skill 名 | 返回 HTTP 404，JSON 含 `error` 字段 | P1 | todo |
| L2-06 | `POST /api/skills/<name>/execute` — Skill 存在但无数据 | SSE 流返回 `text` 事件，内容含"缺少"或"请先上传" | P1 | todo |

### L3 — 集成测试（多模块协作）

| 测试 ID | 测试场景 | 预期结果 | 优先级 | 状态 |
|--------|---------|---------|-------|------|
| L3-01 | `POST /api/skills/concentration_monitor/execute` → `loop.py` → `fast_path` → SSE 事件 | 全流程：执行端点 → can_fast_path()=True → run_fast_path() → SSE text 事件含集中度数据；LLM 调用次数为 0 | P0 | todo |
| L3-02 | `POST /api/skills/fund_nav_report/execute` → `loop.py` → `fast_path`（修复后）| calc_type=fixed 后：can_fast_path()=True → run_fast_path() 调用 nav_metrics；LLM 调用次数为 0 | P0 | todo |
| L3-03 | `GET /api/skills/status` → `skill_preflight.run_preflight()` → 结果汇总 | 批量调用所有已注册 Skill 的 preflight，超时不崩溃（30s 上限）| P1 | todo |
| L3-04 | `executeSkill()` 前端函数 → `POST /api/skills/<name>/execute` → SSE 流 → `handleChunk()` 处理 | 前端收到 SSE 事件后猫头鹰状态更新，消息气泡显示结果 | P1 | todo |
| L3-05 | 侧边栏 Skill 卡片"就绪"状态与 `/api/skills/status` 数据一致 | 卡片绿色="就绪"时，API 返回 `ready:true`；卡片红色="缺数据"时，API 返回 `ready:false` | P1 | todo |
| L3-06 | 表名点击 → `openProfile(tableName)` → 发送 `profile_table` 消息 | 点击侧边栏表名后，聊天窗口显示该表的结构剖析结果 | P2 | todo |

### L4 — UAT 验收场景（业务用户手动执行，Windows 环境）

| 场景 ID | 用户角色 | 操作步骤 | 预期结果 | 验收标准 | 状态 |
|--------|---------|---------|---------|---------|------|
| U4-01 | 投资经理 | 1. 启动应用 2. 查看侧边栏 Skill 区块 | 每个 Skill 显示卡片样式：标题+描述（1-2行）+就绪状态标签+执行按钮 | 卡片布局清晰，业务用户能看懂描述 | 待验收 |
| U4-02 | 投资经理 | 1. 未上传任何数据 2. 点击"集中度监控"执行按钮 | 卡片标签显示"缺数据"（红色/橙色），点击后聊天窗口出现"请先上传持仓数据"提示 | 提示语友好，不报技术错误 | 待验收 |
| U4-03 | 投资经理 | 1. 上传持仓 CSV 2. 等待数据加载完成 3. 查看侧边栏"集中度监控"卡片 | 卡片标签从"缺数据"变为"就绪"（绿色） | 状态自动刷新（或页面刷新后更新） | 待验收 |
| U4-04 | 投资经理 | 1. 有持仓数据 2. 点击"集中度监控"执行按钮 | 猫头鹰动画出现，数秒后返回主体集中度报告，有无超标告警 | 报告中的数字与 Excel 手算一致（误差 < 0.1%） | 待验收 |
| U4-05 | 投资经理 | 1. 有净值数据 2. 点击"净值报告"执行按钮 | 返回含净值指标、资产结构、信用评级的格式化报告 | 报告数字来自固化 calculator，非 AI 生成（可在报告末尾标注"数据来源：本地计算"） | 待验收 |
| U4-06 | 投资经理 | 点击侧边栏"已加载数据表"中的某个表名 | 聊天窗口自动显示该表的字段结构剖析（表名、行数、列名列表、样本数据） | 信息一目了然，投资经理能判断这张表是什么 | 待验收 |

---

## 四、执行结果（编码完成后填写）

- **测试运行日期**：（待填写）
- **pytest 结果**：（待填写）
- **覆盖率变化**：（待填写）

### 新建测试文件

- `tests/test_skill_api.py`：覆盖 L1-01~L1-04、L2-01~L2-06

### L1~L3 用例执行摘要

| 测试 ID | 实际结果 | 备注 |
|--------|---------|------|
| L1-01 | 待执行 | |
| L1-02 | 待执行 | |
| L1-03 | 待执行 | |
| L1-04 | 待执行 | |
| L1-05 | 待执行 | |
| L2-01 | 待执行 | |
| L2-02 | 待执行 | |
| L2-03 | 待执行 | |
| L2-04 | 待执行 | |
| L2-05 | 待执行 | |
| L2-06 | 待执行 | |
| L3-01 | 待执行 | |
| L3-02 | 待执行 | |
| L3-03 | 待执行 | |
| L3-04 | 待执行 | |
| L3-05 | 待执行 | |
| L3-06 | 待执行 | |

### 已知问题 / 遗留项

（编码后填写）

### UAT 状态

- [ ] U4-01 — 待业务方验收（Skill 卡片外观）
- [ ] U4-02 — 待业务方验收（缺数据时友好提示）
- [ ] U4-03 — 待业务方验收（状态自动刷新）
- [ ] U4-04 — 待业务方验收（集中度监控完整流程）
- [ ] U4-05 — 待业务方验收（fund_nav_report 合规修复后数值验证）
- [ ] U4-06 — 待业务方验收（表名点击查看结构）

---

## 附：回归测试清单

执行本次迭代后，以下已有测试必须全部通过（无回归）：

```bash
# 快速路径（Week 1 完成）
pytest tests/test_fast_path.py -v

# Skill 预检（Skill v3 完成）
pytest tests/test_skill_preflight.py -v

# Agent 循环（核心）
pytest tests/test_agent.py -v

# 计算器（合规关键）
pytest tests/test_calculators.py -v

# 全量回归
pytest tests/ -v --tb=short
```
