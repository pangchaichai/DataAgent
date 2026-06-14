# DataAgent — Claude Code 项目启动指引

> 首次打开此项目的 Claude Code 必读。
> 本文件说明项目当前状态和重要入口文件。

---

## 项目当前状态

**阶段**：v2.0 全部完成 + Skill v3（数据感知）已合并 + v3.0 演进规划就绪
**分支**：`claude/clever-meitner-fqsa3v`
**测试**：✅ 341/343 通过，0 失败（2026-06-14）

### 已完成阶段

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 0 — 环境搭建 | ✅ 完成 | 虚拟环境 + 数据目录 + 冒烟测试通过 |
| Phase R — Agent 内核重构 | ✅ 完成 | Tool-calling Agent / 质量诊断 / UI重建 / 自适应编码 / 跨会话记忆 |
| Phase 1 — 核心数据链路 | ✅ 完成 | 上传→查询→表格展示，57/57 单测通过 |
| Phase 2 — 语义层+报告生成 | ✅ 完成 | 5个计算器 + 4张数据字典 + 合规审计日志 |
| Phase 3 — 合规监控+参谈要点 | ✅ 完成 | Windows 平台已验收 |
| Evolution I-1~I-10 | ✅ 完成（2026-06-06~08）| Blueprint / Plan-Execute / JS模块化等 |
| v2.0 UX 修复 | ✅ 完成 | SSE修复 / Skill Builder / 文档上传 / 图表 / Word导出 |
| Windows 内测包 | ✅ 完成（2026-06-09）| DataAgent-v2.0-beta1.zip 已构建 |
| Skill v3 — 数据感知 | ✅ 完成（2026-06-10）| 三类 Skill / required_files / 预检 / 需求文档导入 |
| 文件上传升级 | ✅ 完成（2026-06-10）| 批量上传 + 本地工作目录 |
| v3.0 演进规划 | ✅ 完成（2026-06-14）| 最终实施计划产出（docs/v3-evolution-final-plan.md）|
| DA 小猫头鹰任务状态动画 | ✅ 完成（2026-06-14）| ui/js/agent_status.js |

---

## 关键文档阅读顺序

| 文件 | 重要性 | 用途 |
|------|--------|------|
| `CLAUDE.md` | ⭐⭐⭐⭐⭐ 必读 | 项目完整规格：技术栈、架构、工具规格、编码规范、会话协议 |
| `HANDOFF.md` | ⭐⭐⭐⭐⭐ 必读 | 上次做了什么、下次从哪开始 |
| `PROGRESS.md` | ⭐⭐⭐⭐⭐ 必读 | 阶段进度记录 |
| `TESTING.md` | ⭐⭐⭐⭐ 测试时读 | 测试策略、覆盖矩阵、迭代测试流程 |
| `docs/v3-evolution-final-plan.md` | ⭐⭐⭐⭐ 下一步必读 | v3.0 最终实施计划（Week 1-4） |
| `docs/dev-environment.md` | ⭐⭐⭐⭐ 必读 | Linux/macOS/Windows 环境策略 |
| `docs/user-guide.md` | ⭐⭐⭐ 业务用户 | 面向投资业务人员的使用说明 |
| `docs/skills-guide.md` | ⭐⭐⭐ 开发 Skills 时读 | Skills 编写规范 |

---

## 启动方式

```bash
# Linux / macOS 开发模式（自动走浏览器模式）
pip install -r requirements-dev.txt
cp config.example.yaml config.yaml   # 首次需要复制配置
# 编辑 config.yaml，填写 LLM API Key
python main.py
# 启动后自动打开系统浏览器访问 http://127.0.0.1:{随机端口}
# 注意：macOS/Linux 显示浏览器是正常行为，非 bug
#       PyWebView 原生窗口仅在 Windows + requirements-prod.txt 下可用

# 运行测试（应全绿 341 通过）
python -m pytest tests/ -q
```

---

## 下一步任务（v3.0 演进）

**参照**：`docs/v3-evolution-final-plan.md` 第四章

| 优先级 | 任务 | 目标文件 |
|--------|------|---------|
| P0 — Week 1 | 快速路径（<1s 响应固化计算） | `agent/fast_path.py` 新建 |
| P0 — Week 1 | 执行追踪 JSONL 写入 | `agent/execution_tracker.py` 新建 |
| P0 — Week 2 | fund_nav_report 合规修复 | `skills/fund_nav_report/SKILL.md` calc_type→fixed |
| P0 — Week 2 | Skill 卡片 UI | `ui/js/sidebar.js` 侧边栏重构 |

**外部阻塞**（等待业务方确认，不影响上述 P0 任务）：
- C-02：周报模板（dept_weekly_report）
- C-03：月报模板（monthly_bond_summary）
- C-04：Word 导出格式

---

## 会话协议提醒

每次会话**必须**按 CLAUDE.md 第一章执行：
```
会话开始：python scripts/project_check.py → HANDOFF.md → PROGRESS.md → 状态摘要
会话结束：更新 HANDOFF.md → 更新 PROGRESS.md → pytest → git commit + push
```
