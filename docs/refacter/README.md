# DataAgent 方向转变与重构方案（Phase R）

> 本目录是一组**可执行驱动文档**。给开发用 Claude Code 的开场指令：
> 「阅读 `docs/refactor/README.md`，然后按 `PROGRESS-refactor.md` 的勾选项，从 Step R1 开始逐步执行。每完成一个 Step 更新 PROGRESS-refactor.md。」

---

## 0. 这份方案要解决什么

试用反馈两个核心问题：
1. **Agent 机械死板**：每次分析都要用户详细标注字段、说明处理逻辑，门槛高，相对传统报表无优势。
2. **UI 不够高效、智能、美观。**

经核对仓库当前代码（`master` / commit 69a91a0，对应 CLAUDE.md v1.3），根因定位如下：

| 现象 | 根因（代码证据） |
|------|------------------|
| 机械死板 | `agent/loop.py` 是「关键词→单条 SQL→表格」的**直线流水线**，不是 tool-calling Agent。LLM 全程拿不到工具定义、不迭代、不追问；固化计算类 Skill 直接 `return` 拒绝（`loop.py:138-149`）。`MAX_TURNS=15` 是摆设。 |
| 要求用户详细标注 | SQL 质量强依赖**手工维护的** `data_dictionary/*.yaml` + `entity_alias.yaml`；无字典时 `field_map` 为空，LLM 只见原始列名（`data_loader.py:175-177`）。没有澄清机制，用户被迫每次过度说明来补偿。 |
| UI 原型级 | `ui/index.html` 仅基础聊天，无质量/确认/健康卡片。 |

**结论**：CC4.6 的 v1.4 方案（schema_discovery / memory / 质量诊断 / UI）是有价值的外围增量，但它明确「不触碰 loop.py」，因此**没有触及"机械死板"的根因**。本方案把优先级重排，**先把内核改成真正的 Agent，再做外围与美化**，并对 memory 做合规收窄。

---

## 1. 目标形态（一句话）

> 让没有数据分析经验的业务人员，像身边坐着一位分析师：Agent **自己剖析数据、提出字段假设、对歧义只问一个关键问题、调用固化口径算数、把结果交人工确认**——而不是要求用户预先把一切标注清楚。

---

## 2. 设计原则（不可违背）

1. **第一性约束不变**：数字正确性、可追溯性 > 灵活性。探索式(A 类)允许 LLM 生成 SQL；合规/报告(B 类)**必须**走 `calculators/` 固化函数，**严禁** LLM 生成 SQL。
2. **把"理解数据"的负担从用户移回 Agent**：Agent 用工具自己剖析，而不是要求用户标注。
3. **复用既有资产**：`calculators/`、`query_runner` 的 SQLGuard、`data_dictionary/`、`entity_manager`、`error_translator`、`compliance_audit` **不重写**，只被新 loop 编排调用。
4. **离线底线**：内网+数据合规环境，前端资源必须**全本地**，禁止任何 CDN（含 Tailwind Play CDN）。
5. **向后兼容**：保留现有 SSE chunk 类型（text/tool_start/tool_end/table/chart/error/stream_end），新增类型为增量。
6. **小步快跑**：每个 Step 独立可验收、可回滚；不破坏已通过的 57+72 单测。

---

## 3. 阶段总览（执行顺序 = 优先级）

| Step | 文档 | 内容 | 为什么这个顺序 | 依赖 |
|------|------|------|----------------|------|
| **R1** | `01-agent-core-refactor.md` | 把 loop 改成真 tool-calling Agent（含 `profile_table` / `ask_user` / 接 `calculators`） | **治本**，直接解决"机械死板" | 无 |
| **R2** | `02-data-quality-diagnosis.md` | 上传即输出数据质量报告 | 服务"口径正确"，性价比最高，减少用户标注 | 无（可与 R1 并行） |
| **R3** | `03-ui-rebuild.md` | UI 重建（全本地资源 + 确认/质量/思考卡片） | 承载 R1/R2 的透明度 | R1 的新 chunk 类型 |
| **R4** | `04-schema-inline-inference.md` | 未知表**内联**推断字段语义（非独立草稿确认流） | 进一步降门槛 | R1 |
| **R5** | `05-memory-scoped.md` | 收窄版跨会话记忆（仅口径纠正、显式建议、不自动注入 SQL） | 锦上添花，有合规边界 | R1 |

R1+R2+R3 完成即可让你重新试用并感到质变；R4/R5 为增强。

---

## 4. 与现有文档的关系

- `CLAUDE.md`（v1.3）仍是**架构与约束的权威参考**，本方案不改写它。
- 本目录文档在 Phase R 范围内**优先级高于** CC4.6 的 v1.4 草稿（你上传的 `*-v2` 附件）。冲突时以本目录为准。
- **UI 设计**以本目录 `ui-design.md`（合并版）为唯一权威，**CC4.6 的 `ui-design-v2.md` / `index-v2.html` 已被取代，可忽略**。配套 `ui-mockup.svg`（效果图）、`index-preview.html`（可点击原型）。
- 本目录完整文件清单：`README.md`、`01~05` 五个 Step、`PROGRESS-refactor.md`、`ui-design.md`、`ui-mockup.svg`、`index-preview.html`。
- Phase R 收尾后，可把生效内容回灌成 `CLAUDE.md v1.5`（见 PROGRESS-refactor 末尾「收尾」）。

---

## 5. 给执行者的硬性护栏（每个 Step 都适用）

- **动手前先读**对应 Step 文档的「前置阅读」清单，核对真实函数签名，**不要凭记忆编签名**。
- **不要修改**：`calculators/*.py` 内部口径、`query_runner.py` 的 SQLGuard 规则、`data_dictionary/*.yaml` 内容、`compliance_audit.py`。
- **每个 .py 文件 ≤ 300 行**，超了就拆模块（沿用 CLAUDE.md 规范）。
- **每个新函数配单测**，放到对应 `tests/`，并保证旧单测全绿后再提交。
- **每个 Step 独立 commit**，提交信息写清 `Step Rx: ...`。
- 合规/报告类一旦让 LLM 生成 SQL，即为**严重违规**，必须拦回。
