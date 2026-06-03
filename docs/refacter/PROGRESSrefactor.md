# Phase R 重构进度（每完成一项就勾选 + 记录）

> 开发用 Claude Code：每次会话先读 `docs/refactor/README.md` 与本文件，
> 从第一个未完成的 Step 开始，做完一个 Step 提交一次并更新本文件。

基准：master commit 69a91a0（CLAUDE.md v1.3，Phase 1/2 落地 + Phase 3 待联试）。
执行分支：`claude/relaxed-keller-TJBYu`。

---

## Step R1 — Agent 内核重构（治本，最高优先） ✅ 完成（2026-06-03）
> 文档：`01-agent-core-refactor.md`
- [x] `agent/tools_spec.py`（TOOL_DEFINITIONS + dispatch）— 5 工具定义 + ToolContext + 分发表
- [x] `agent/llm_client.py` 新增 `chat()` + `ChatResult`（**native 模式**，DeepSeek/Qwen3-32B 均原生支持；react 兜底已实现可后置）
- [x] `tools/profiler.py` + `tests/test_profiler.py` — 5/5 单测通过
- [x] `agent/loop.py` 重写为 tool-calling 循环（保持 `run_agent_loop` 对外签名，新增 `session_messages`/`pending` 参数）
- [x] `run_calculator` 接入 calculators（口径取自 config，B 类强制 confirm + 审计）
- [x] `_session` 增 `messages`/`pending`；`main.py` 加 `/api/confirm`
- [x] `prompts/system_prompt.txt` 改写（6 条行为准则）
- [x] `config.yaml` / `config.example.yaml` 加 `llm.sql_gen.tool_mode: native`
- [x] `tests/test_agent.py` 新增 5 项；82/82 旧+新单测全绿
- [ ] 手动端到端 3 场景通过；内存 < 200MB（待 R3 UI 后就绪后联调）

## Step R2 — 数据质量诊断（可与 R1 并行） ☐
> 文档：`02-data-quality-diagnosis.md`
- [ ] `tools/quality.py` + `QualityReport`
- [ ] `data_loader.load_file` 末尾计算 + `LoadResult.quality_report`
- [ ] `/api/upload` 返回 `quality_report`
- [ ] loop 上下文注入 critical 摘要
- [ ] 质量单测 3 项；旧测试绿

## Step R3 — UI 重建（全本地资源） ☐
> 文档：`03-ui-rebuild.md` + 权威设计 `ui-design.md`；参照 `index-preview.html` / `ui-mockup.svg`
- [ ] `ui/index.html` 重建 + `ui/static/` 本地资源（零 CDN）
- [ ] **侧边栏「最近会话」分区 + 回放**；会话落盘 `data/sessions/{id}.jsonl`
- [ ] `/api/health` `/api/skills` `/api/confirm` `/api/sessions` `/api/sessions/<id>`
- [ ] `requirements-*.txt` 加 `psutil`
- [ ] P0 验收清单全过（含断网可打开 + 会话回放）

## Step R4 — 未知表内联推断 ☐
> 文档：`04-schema-inline-inference.md`
- [ ] profiler `sanitize` 选项
- [ ] `propose_dict_entry` / `confirm_dict` 工具
- [ ] `data_dictionary/drafts/`
- [ ] 单测 5 项；旧测试绿

## Step R5 — 收窄版记忆（增强，最后） ☐
> 文档：`05-memory-scoped.md`
- [ ] `agent/memory.py`（仅 schema_correction，不自动注入）
- [ ] **用户开关 `memory.enabled`（默认 OFF）+ no-op 短路 + UI 开关/清空**
- [ ] `/api/memory/stats`
- [ ] `requirements-*.txt` 加 `rank_bm25`
- [ ] 单测 4 项；旧测试绿

---

## 收尾（R1–R3 完成即可让用户重新试用；全部完成后）
- [ ] 把 Phase R 生效内容回灌为 `CLAUDE.md v1.5`（更新架构图：新增"Agent 工具编排"与"剖析/质量"层）
- [ ] 更新主 `PROGRESS.md`，把 Phase R 标记完成
- [ ] 在 Windows 环境跑 Phase 5（PyWebView/打包），验证 psutil/rank_bm25 打包正常

---

## 决策记录（与 CC4.6 v1.4 的分歧，便于回溯）
- R1 优先于 UI/memory：v1.4 明确"不触碰 loop.py"，未解决"机械死板"根因；本方案先治本。
- R4 用"内联推断+即用即纠"替代 v1.4 的"独立草稿确认流"：后者新增门槛，与降门槛目标相悖。
- R5 收窄 memory：禁止自动记忆/注入 SQL 与业务规则，避免"精确的错误"与审计缺口。
- UI 全本地资源：拒绝 v1.4 `ui-design-v2.md` 的 Tailwind Play CDN，守内网离线底线。
- tool_mode 锁定 native：经核实 DeepSeek（V3.2/deepseek-chat）与 Qwen3-32B 均原生支持 function-calling；react 兜底仅在 Qwen3 vLLM 解析不稳时再补。
- 记忆能力分两层：会话内多轮（R1，内核不可关）/ 跨会话持久（R5，用户开关，默认 OFF，仅本机、不外发）。
- UI 设计合并为单一权威 `ui-design.md`（取代 ui-design-v2.md）；侧边栏新增「最近会话」可调取历史；附可点击原型 index-preview.html。
