# DataAgent 开发进度记录

> 每次完成一个 Step 后在此记录，下次会话开始时让 Claude Code 读取此文件。

---

## 当前阶段：Phase R 收尾完成 → Phase 5（Windows 验证）

## Phase R — Agent 内核重构 ✅ 完成（2026-06-04）
- [x] R1: Agent 内核重构为 tool-calling Agent（5 工具 + function-calling + 暂停续跑）
- [x] R2: 数据质量诊断 — 上传即输出质量报告 + 自适应编码
- [x] R3: UI 重建 — 全本地资源 · 状态透明 · 确认不可忽略
- [x] R4: 未知表内联推断（sanitize + 字典草稿→正式）
- [x] R5: 收窄版跨会话记忆（BM25+SQLite，仅口径纠正，默认关闭）
- [x] R5-r: 测试优化 + 内测反馈修复（10 新 API / 8 缺陷修复 / UI v2.3 / PyWebView 4.4.1）
- [x] 收尾: CLAUDE.md v1.5 回灌 + 编码规范更新

## Phase 0 — 环境搭建 ✅ 已完成
- [x] 虚拟环境创建 + 开发依赖安装
- [x] data/ 目录结构创建
- [x] 冒烟测试通过
- [x] **项目结构调整**：platform/ → platform_adapter/，详见 docs/project-changes.md
- [x] scheduler/task_manager.py 占位桩（Phase 3 完整实现）

## Phase 1 — 核心数据链路 ✅ 已完成（57/57 单测 + 45/45 联调通过）
- [x] Step 1：main.py（随机端口 + 平台适配启动）
- [x] Step 2：ui/index.html（聊天界面 + ECharts后置钩子 + @mention + 文件拖拽）
- [x] Step 3：tools/data_loader.py（chardet + DuckDB + 字典映射 + 实体归一 + 千分位清洗）
- [x] Step 4：tools/query_runner.py（sqlglot SQLGuard + 动态表名 + 危险函数拦截 + CTE支持）
- [x] Step 5：agent/llm_client.py（DeepSeek SQL生成 + report_text + 意图分类 + 流式 + 降级）
- [x] Step 6：agent/skill_loader.py（8 Skill 渐进式加载 + 关键词意图匹配）
- [x] Step 7：agent/loop.py（Agent 主循环 + 错误分类自愈 + SSE 事件流）
- [x] Step 8：前后端联通（/api/chat SSE + /api/upload + /api/tables）
- [x] 联调验证：3条真实查询全部成功（DeepSeek + 283行持仓CSV）

## Phase 2 — 语义层 + 报告生成 ✅ 已完成（2026-06-01，72/72 单测通过）
- [x] tools/entity_normalizer.py（64行，10+别名映射）
- [x] data_dictionary/holding_dict.yaml（12字段，投资团队+研究员）
- [x] data_dictionary/nav_dict.yaml（14字段，投资团队）
- [x] data_dictionary/rating_entity_dict.yaml（19字段，研究员+投资团队）
- [x] data_dictionary/rating_bond_dict.yaml（24字段，研究员+投资团队）
- [x] data_dictionary/monitoring_dict.yaml（15字段，投资团队，外部监控结果校验）
- [x] calculators/concentration.py 单元测试（7/7 通过）
- [x] calculators/nav_metrics.py + 单元测试（2/2 通过）
- [x] calculators/asset_structure.py + 单元测试（3/3 通过）
- [x] calculators/credit_distribution.py + 单元测试（3/3 通过）
- [x] tools/compliance_audit.py（JSONL 审计日志，含 MD5 指纹）
- [ ] skills/fund_nav_report/ 改为调用 calculators（模板待 C-02 确认后实现）

## Phase 3 — 合规监控 + 参谈要点 ✅ 代码完成（待 Windows 联试验收）
- [x] tools/entity_manager.py（集团系 CRUD + 逆向索引 + 持久化）
- [x] scheduler/task_manager.py（完整补跑检测 + 数据时效校验 + 运行记录）
- [x] tools/notify.py（超标告警/数据过期/报告完成/任务失败 业务通知）
- [x] skills/concentration_monitor/（SKILL.md calc_type:fixed + fixed_calculator）
- [x] skills/meeting_report/（SKILL.md + template.md.j2 就绪）
- [ ] Phase 3 验收（等 Windows 3 项修复验证通过后一并验收）

## Phase 4 — 批量报告（进入条件：C-02/03/04 模板已确认）
- [ ] skills/dept_weekly_report/ + template
- [ ] skills/monthly_bond_summary/ + template
- [ ] skills/partnership_summary/
- [ ] 意图路由改 LLM 分类
- [ ] Phase 4 验收

## Phase 5 — Windows + 打包（需切换到 Windows 环境）
- [ ] 切换到 Windows，安装 requirements-prod.txt
- [ ] 验证 PyWebView 原生窗口
- [ ] 验证 Windows toast 通知
- [ ] 记录 WebView2 内存基线（docs/memory_baseline.md）
- [ ] PyInstaller 打包测试
- [ ] 最终验收

---

## 待办：尚未使用的数据文件

> 以下文件已评估但暂未纳入当前开发范围，后续按业务需求补充对应的数据字典和功能。

### 投资团队 (testdata/) — 已评估、V1 暂不覆盖

| 文件 | 类型 | 后续关联功能 |
|------|------|------------|
| `实时资产头寸查询(2026-05-15).csv` | 资产头寸 | 持仓查询增强（5.2），可按证券账户维度分析 |
| `申赎数据0515.csv` | 申购赎回 | 产品流动性分析（需先有业务需求） |
| `组合资金账户头寸(2026-05-15).csv` | 资金头寸 | 现金流/头寸管理（需先有业务需求） |
| `账户流水(2026-05-15).csv` | 账户流水 | 资金变动分析（需先有业务需求） |
| `现金流缺口分析(2026-05-15).csv` | 现金流缺口 | 流动性风险管理（需先有业务需求） |
| `估值表查询(2026-05-15).csv` | 估值数据 | NAV 分析增强版（字段结构与净值表不同） |
| `债券质押查询(2026-05-15).csv` | 质押管理 | 质押品监控（需先有业务需求） |
| `质押式回购投资交易查询(2026-05-15).csv` | 回购交易 | 回购交易分析（需先有业务需求） |

### 研究员 (yanjiu/) — 已评估、V1 暂不覆盖

| 文件 | 类型 | 后续关联功能 |
|------|------|------------|
| `底层资产持仓及债券信息表260507.csv` | 底层持仓明细(66列,9.6MB) | 穿透分析(5.2/5.3)，C-01 穿透口径决策关键数据 |
| `内网信评AI生成谈参要点-1.docx` | 参谈要点参考 | meeting_report Skill 的格式参考（非结构化数据） |

> **备注**：`底层资产持仓及债券信息表260507.csv` 优先级最高——含`穿透类型`字段，是 C-01 口径确认后必须支持的数据源。建议 Phase 3 或 Phase 4 补充 `holding_dict.yaml` 中该表的完整字段映射。
