# DataAgent — 会话交接文件（HANDOFF.md）

> **每次会话结束前，Claude Code 必须更新此文件。**
> 下次会话开始时，优先读取本文件（在 CLAUDE.md 之前）。
>
> 本文件回答三个问题：上次做了什么？现在的状态是什么？下次从哪里开始？

---

## 最后更新
- **日期**：2026-06-10
- **提交**：（本次提交后更新）
- **分支**：`feature/skill-data-awareness`（从 `claude/sleepy-cori-5b5xow` 分出）

---

## 上次会话完成的工作

### Skill v3 Phase A — 数据感知预检（2026-06-10，branch: feature/skill-data-awareness）

**架构决策（OCP）**：
- 稳态/敏态边界明确：loop.py / skill_loader.py 是稳态核心，skill_preflight.py 是敏态扩展点
- 不引入 Pipeline 框架（YAGNI），`prepare_skill_for_execution()` 内部线性分阶段，将来可零成本升级
- 与 Hook 事件总线讨论后确认：Hook 适合旁路观测（审计/成本），不适合需要阻断执行流的预检场景

**实施内容**：
1. 新建 `agent/skill_preflight.py`（单一入口 `prepare_skill_for_execution()`）
   - 预检数据依赖（required_files / optional_files / external_sources）
   - file_pattern 模糊匹配 + expected_fields 列校验 + 旧版 table_type 兼容
   - 缺必需数据时阻断并告知用户；数据就绪时注入真实表名/列名映射
2. `agent/skill_loader.py`：SkillInfo 加 `metadata: dict` 字段（一行）
3. `agent/loop.py`：Skill 注入替换为 `prepare_skill_for_execution()` 调用（最后一次为 Skill 改 loop.py）
4. 新建 `tests/test_skill_preflight.py`（16 个测试用例，全部通过）

**测试结果**：325/325 通过，2 跳过（含所有原有测试，无回归）

---

### Windows 内测 UAT 修复 — 2 个新缺陷

**1. 修复联网搜索被拒绝（prompts/system_prompt.txt）**
- 原问题：系统提示词第一行"运行在企业内网环境中"导致 LLM 拒绝调用 web_search 工具
- 修复：改为"部署在用户的本地设备上"；在核心能力列表中明确列出 web_search 工具；新增第 6 条准则，明确要求遇到公开信息查询时主动调用工具

**2. 修复上传文档后追问无上下文（多文件 + agent/loop.py）**
- 原问题：`sendMessage()` 只发送 `{message}` 不含文档信息；agent 不知道文档内容
- 修复路径：
  - `ui/js/chat.js`：发送消息时读取 `_documentContext` 全局变量并附加到 POST body
  - `api/chat.py`：从请求中提取 `document_context`，加入 `loop_kwargs`
  - `agent/loop.py`：`run_agent_loop()` 新增 `document_context` 参数，构造用户消息时将文档文件名、页数、字数、内容摘要附加到消息末尾
  - `agent/executor.py`：`run_with_plan()` 同步透传 `document_context`

### 前序会话（同日）完成的工作

#### Windows 内测包构建 + 5 个缺陷修复

**1. 创建 Windows 离线安装包（scripts/package_windows.py）**
- 三阶段依赖解析：当前平台全量下载 → C 扩展替换为 Windows 版 → 扫描 METADATA 补充 Win-only 传递依赖
- 自动清理 Linux wheel 避免 pip 回溯，包体从 102.5 MB 压缩到 45.6 MB
- 生成 `dist/DataAgent-v2.0-beta1.zip`，含 44 个 deps、setup.bat、run.bat

**2. 修复 setup.bat / run.bat 4 个问题**
- LF → CRLF 换行符（CMD 要求）
- 去掉 chcp 65001（GBK 编码文件中途切 UTF-8 乱码）
- 补充 pythonnet/clr_loader/cffi/colorama 4 个 Windows-only 传递依赖
- 路径修正：cd DataAgent 后运行 python main.py；config 写到 DataAgent/ 子目录

**3. 修复上传确认对话框缺失（ui/index.html + ui/js/upload.js）**
- I-10 模块化时遗漏的 8 个 DOM 元素（ucFilename/ucRows/ucCols/ucType/ucDate/ucTableName/ucPreview/uploadConfirmPanel）
- 添加完整 HTML 确认面板 + JS 联动显示/隐藏

**4. 修复 .claude/settings.json 两个 hook 错误**
- PreCommit 不是有效 hook 事件 → 移除
- Stop hook 值需为数组格式 → 包装为 [{...}]

**5. 更新 config.yaml 模型名为 deepseek-v4-flash**
- report_text 和 deepseek 两个 provider 配置处均改为 deepseek-v4-flash

---

## 当前项目状态

### 阶段
```
Skill v3 数据感知改造 — Phase A 进行中（branch: feature/skill-data-awareness）
v2.0 主线完成 + Windows 内测包就绪（branch: claude/sleepy-cori-5b5xow）
```

### 测试
- **结果**：309/309 通过，2 跳过
- **DeepSeek 集成测试**：test_report_text_with_deepseek、test_sql_gen_with_deepseek 通过
- **web_search 测试**：6/6 通过（duckduckgo-search 已可用）
- **核心模块**：calculators 88-100%、chart_builder 100%、report_builder 81%
- **最后运行**：2026-06-09

### 已知外部阻塞项
- Phase 4 进入条件：C-02/C-03/C-04 模板待业务方确认
- Phase 5 PyInstaller 打包：需 Windows 11 环境执行

---

## 立即可执行的下一步（按优先级排序）

### 优先级 1 — Skill v3 Phase C + 两个新 Skill（下一步）

**Phase C — 需求文档直接导入**（用户可上传 .md 需求文档转为 Skill 草稿）
- `tools/skill_builder.py` 新增 `import_from_requirement_doc(content, data_context)` 函数
- `api/skill_api.py` 新增导入端点 `POST /api/skill-builder/import`
- 前端 `skill_builder.js` 新增"从文档导入"入口

**两个新 Skill（Phase C 后创建，作为验收用例）**
- `skills/weekly_report_generator/` — 理财周报多模板生成器（用户需求文档已有）
- `skills/meeting_report/SKILL.md` 替换 — 谈参要点新版（替换现有，用户需求文档已有）

### 优先级 2 — Windows 内测验证（并行）
- 主线包 `dist/DataAgent-v2.0-beta1.zip` 继续验证（与 Skill v3 并行）

### 优先级 3 — Phase 4 进入条件（外部依赖）
- C-02/C-03/C-04 模板由业务方确认后开始

---

## 关键设计决策记录

| 决策 | 原因 | 影响 |
|------|------|------|
| 离线包采用 venv+whl 方案而非 PyInstaller | Linux 无法交叉编译 Windows exe | 内测用户需装 Python 3.11 |
| 三阶段依赖解析 | Linux 会跳过 sys_platform=="win32" 的条件依赖 | Phase 3 扫描 METADATA 自动发现 Win-only 传递依赖 |
| 清理 Linux wheel 仅保留 Windows/通用版 | 消除 pip 在 Windows 上的回溯 | 包体减半(102→46 MB) + 安装不再卡死 |

---

## 本次会话修改的文件清单

```
prompts/system_prompt.txt     # 修复"企业内网"误导 + 添加 web_search 使用准则
ui/js/chat.js                 # sendMessage() 附加 _documentContext 到 POST body
api/chat.py                   # 提取 document_context 并传入 loop_kwargs
agent/loop.py                 # run_agent_loop 新增 document_context 参数，注入消息
agent/executor.py             # run_with_plan 透传 document_context
HANDOFF.md                    # 会话交接更新
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
