# DataAgent — Claude Code 项目启动指引

> 首次打开此项目的 Claude Code 必读。
> 本文件说明项目当前状态和重要入口文件。

---

## 项目当前状态

**阶段**：Evolution I-1 ~ I-10 全部完成（2026-06-06）
**分支**：`claude/trusting-goodall-O4ezp`
**测试**：311/327 通过（15 个失败均为可选依赖缺失，核心模块全绿）

### 已完成阶段

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 0 — 环境搭建 | ✅ 完成 | 虚拟环境 + 数据目录 + 冒烟测试通过 |
| Phase R — Agent 内核重构 | ✅ 完成 | Tool-calling Agent / 质量诊断 / UI重建 / 自适应编码 / 跨会话记忆 |
| Phase 1 — 核心数据链路 | ✅ 完成 | 上传→查询→表格展示，57/57 单测通过 |
| Phase 2 — 语义层+报告生成 | ✅ 完成 | 5个计算器 + 4张数据字典 + 合规审计日志 |
| Phase 3 — 合规监控+参谈要点 | ✅ 代码完成 | 待 Windows 联试验收 |
| Evolution I-1~I-10 | ✅ 完成 | 见下方列表 |

### Evolution I-1~I-10 完成内容

| 迭代 | 核心交付物 |
|------|----------|
| I-1/I-1b | pyproject.toml + PreCommit Hook + cost_tracker + hooks系统 + self_check + 场景化工具过滤 |
| I-2 | report_builder（Jinja2+Word导出）+ 3个报告模板 |
| I-3/I-3b | chart_builder（5种图表+自动选型）+ agent/context 三级压缩 |
| I-4 | 上传两阶段确认弹窗（预解析→确认→入库） |
| I-5/I-5b | /api/status + /api/suggestions + LLM providers API + hooks 审计 hash chain |
| I-6 | file_reader（Word/PDF解析）+ web_search（DuckDuckGo） |
| I-7 | main.py 拆分为 Blueprint（api/ 6个模块）+ session_store.py |
| I-8 | agent/planner + agent/executor + plan/plan_step/plan_done SSE 事件 |
| I-9 | calculators: position_diff + leverage + liquidity |
| I-10 | 前端 JS 模块化：内联 1280 行 → 9个独立 ui/js/*.js 文件 |

---

## 文件清单（读哪些文件、用来做什么）

| 文件 | 重要性 | 用途 |
|------|--------|------|
| `CLAUDE.md` | ⭐⭐⭐⭐⭐ 必读 | 项目完整规格：技术栈、架构、工具规格、编码规范 |
| `PROGRESS.md` | ⭐⭐⭐⭐⭐ 必读 | 每次迭代的进度记录，下次会话从这里了解上次做到哪 |
| `TESTING.md` | ⭐⭐⭐⭐ 测试时读 | 测试策略、覆盖矩阵、迭代测试流程 |
| `docs/dev-environment.md` | ⭐⭐⭐⭐ 必读 | Linux/macOS/Windows 环境策略，UI 窗口形态说明 |
| `docs/architecture.md` | ⭐⭐⭐ 理解设计时读 | 架构决策说明（含 Blueprint/Planner/Skill Builder） |
| `docs/dev-quickstart.md` | ⭐⭐⭐ 开发时读 | 各 Phase 操作手册和验收标准 |
| `docs/skills-guide.md` | ⭐⭐⭐ 开发 Skills 时读 | Skills 编写规范 |
| `config.yaml` | ⭐⭐⭐ | 运行时配置（需填写 API Key） |

---

## 启动方式

```bash
# Linux / macOS 开发模式（自动走浏览器模式）
pip install -r requirements-dev.txt
python main.py
# 启动后自动打开系统浏览器访问 http://127.0.0.1:{随机端口}
# 注意：macOS/Linux 显示浏览器是正常行为，非 bug
#       PyWebView 原生窗口仅在 Windows + requirements-prod.txt 下可用

# 运行测试
cp config.example.yaml config.yaml  # 首次需要复制配置
pytest tests/ -v
```

---

## 下一步任务

当前待办：
- Phase 4：dept_weekly_report / monthly_bond_summary（进入条件：C-02/03/04 模板确认后）
- Phase 5：切换 Windows 环境，验收 PyWebView 窗口 + toast 通知 + PyInstaller 打包

每次会话开始，请先阅读 `CLAUDE.md` 和 `PROGRESS.md`。
