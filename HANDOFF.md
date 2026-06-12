# DataAgent — 会话交接文件（HANDOFF.md）

> **每次会话结束前，Claude Code 必须更新此文件。**
> 下次会话开始时，优先读取本文件（在 CLAUDE.md 之前）。
>
> 本文件回答三个问题：上次做了什么？现在的状态是什么？下次从哪里开始？

---

## 最后更新
- **日期**：2026-06-12
- **提交**：f4c2c2d feat(upload): local work directory + batch upload support
- **分支**：`claude/sleepy-cori-5b5xow`（主开发分支，`feature/skill-data-awareness` 已合并）

---

## 上次会话完成的工作（2026-06-10 ~ 2026-06-12）

### 分支整合
- `feature/skill-data-awareness` fast-forward 合并至 `claude/sleepy-cori-5b5xow`（f4c2c2d）
- 本地 `feature/skill-data-awareness` 分支已删除（远端因权限限制保留，作为历史归档）
- `dataagent2.0-win-betabug` 分支为旧 Windows beta 快照，保留为历史参考

### Skill v3 完整实现（共 5 个 commit 在主线）
**Phase A — 数据感知预检**（b3c878a 前）：
- `agent/skill_preflight.py` 新建（`prepare_skill_for_execution()` 单一入口）
- `agent/skill_loader.py` 加 `metadata: dict` 字段
- `agent/loop.py` Skill 注入替换为 preflight 调用

**Phase B — Skill Builder 数据感知**（a1597ab）：
- `tools/skill_builder.py` generate prompt 注入 `data_context`
- `SkillDraft` 新增 required_files/optional_files/external_sources
- `api/skill_api.py` generate 端点传 schema context

**Phase C — 需求文档直接导入**（9c874b9）：
- `tools/skill_builder.py`：`import_from_requirement_doc()` + `build_import_prompt()`
- `api/skill_api.py`：新增 `POST /api/skill-builder/import`
- `ui/js/skill_builder.js` + `ui/index.html`：Step 0 "从文档导入"入口

**两个验收用 Skill**（e390f5a）：
- `skills/weekly_report_generator/SKILL.md`（新建）— 理财周报多模板生成器，5 个输出 CSV
- `skills/meeting_report/SKILL.md`（替换）— 谈参要点 v3，含集团关系树 + 动态持仓表

**文件上传升级**（f4c2c2d）：
- `tools/workdir_loader.py`（新建）— 工作目录扫描
- `api/data.py` — 3 个新端点（workdir files/preview/load）
- `api/config_api.py` — `app.work_dir` 配置字段
- `agent/skill_preflight.py` — Phase 1.5 自动扫描工作目录，block_message 显示候选文件
- `ui/js/sidebar.js` — "工作目录"侧边栏区块
- `ui/js/settings.js` / `ui/js/upload.js` / `ui/index.html` — 配套 UI
- `tests/test_workdir_loader.py`（新建）— 9 个单测

### 测试结果
- **341/341 通过**，2 跳过，无回归（最后运行：2026-06-10）

---

## 当前项目状态

### 阶段
```
Skill v3 全部完成并已合并主线（claude/sleepy-cori-5b5xow @ f4c2c2d）
文件上传升级（批量 + 工作目录）已完成
Phase 4 待进入：需等 C-02/C-03/C-04 模板业务方确认
```

### 已知外部阻塞项
- Phase 4 进入条件：C-02（周报模板）、C-03（月报模板）、C-04（Word 格式）待业务方确认
- Phase 5 PyInstaller 打包：需 Windows 11 环境执行
- Windows 内测包重建：当前 `dist/DataAgent-v2.0-beta1.zip` 基于旧 betabug 分支，应从主线重建

---

## 立即可执行的下一步（按优先级排序）

1. **Windows 内测包重建**（高优先级）
   - 在 Windows 11 上从 `claude/sleepy-cori-5b5xow` 重新运行 `python scripts/package_windows.py`
   - 验证 Skill v3（weekly_report_generator / meeting_report v3）+ 工作目录功能

2. **Windows 内测继续**
   - 验证 `weekly_report_generator` Skill：上传周报数据源 CSV → 触发 → 验证 5 个输出 CSV
   - 验证 `meeting_report` v3：上传信用数据 CSV → 验证谈参要点生成
   - 验证工作目录：设置工作目录路径 → 确认侧边栏显示文件 → 按需加载

3. **Phase 4 进入条件**（外部依赖）
   - 等待 C-02/C-03/C-04 模板确认后开始 `dept_weekly_report` / `monthly_bond_summary` Skill

4. **旧分支清理**（低优先级，可选）
   - 在 GitHub 上手动删除 `feature/skill-data-awareness` 远端分支（CLI 因权限被 403 拒绝）
   - 为 `dataagent2.0-win-betabug` 打 tag `v2.0-beta1-win` 后可考虑删除

---

## 关键设计决策记录

| 决策 | 原因 | 影响 |
|------|------|------|
| OCP 分层：loop.py 稳态 / skill_preflight.py 敏态 | 新增 Skill 准备逻辑不改核心循环 | 所有 Skill 相关改进集中在 skill_preflight.py |
| 工作目录文件不复制到 uploads/ | 避免大文件重复占用磁盘 | load_file() 直接从 workdir 路径入库，路径安全校验放 api 层 |
| Phase C 用 LLM 解析需求文档 | 需求文档格式多样，正则无法可靠提取 | 依赖 LLM 可用性，parse 失败有清晰错误提示 |
| DataSource 抽象不引入（YAGNI） | 当前只有两种来源（uploads/workdir），抽象层为时过早 | 代码以兼容未来 RemoteDBDataSource 的方式编写，零成本迁移 |

---

## 本次会话修改的文件清单

```
HANDOFF.md                         # 分支合并后状态同步
PROGRESS.md                        # 两个验收 Skill 标记完成，工作目录功能标记完成
CLAUDE.md                          # 版本历史表新增 v2.2 两条记录
```

---

## 会话交接模板（下次会话结束时复制此模板填写）

```markdown
## 最后更新
- **日期**：<YYYY-MM-DD>
- **提交**：<git log -1 --format="%h %s">
- **分支**：`<git branch --show-current>`

## 上次会话完成的工作
1. <具体做了什么>

## 当前项目状态
### 阶段
<当前阶段描述>

### 测试
- **结果**：<X/Y 通过，Z 失败>
- **最后运行**：<date>

## 立即可执行的下一步
1. <具体可操作的步骤>

## 本次会话修改的文件清单
- <文件路径>  # <一句话说明变更>
```
