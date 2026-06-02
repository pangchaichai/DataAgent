# Claude Code 使用工作流指南

> 本文档说明如何在 Claude Code 中高效推进 DataAgent 开发。

---

## 一次性准备（第一次启动前）

### 1. 解压项目材料

```bash
# 将 dataagent-v5.zip 解压到工作目录
unzip dataagent-v5.zip -d ~/projects/
cd ~/projects/dataagent-v5
```

### 2. 填写 config.yaml

打开 `config.yaml`，填写以下必填项：
```yaml
llm:
  deepseek:
    api_key: "sk-xxxxxxxx"        # 填入你的 DeepSeek API Key

user_profile:
  name: "你的姓名"
  department: "你的部门"
  role: "投资经理"                  # 或 研究员/部门负责人/合规
  managed_products:
    - "产品名称1"                   # 填入你管理的产品名称
```

### 3. 启动 Claude Code

```bash
# 在项目根目录启动
cd ~/projects/dataagent-v5
claude
```

Claude Code 会**自动读取项目根目录的 CLAUDE.md**——这是它了解整个项目的主要途径，无需手动告诉它读哪个文件。

---

## 每次开发会话的标准流程

### 第一步：让 Claude Code 确认状态

每次新开会话，先发这条消息：

```
请读取 CLAUDE.md，然后告诉我：
1. 当前项目是什么，目标是什么
2. 开发环境是 Linux 还是 Windows，有何影响
3. 当前应该处于哪个 Phase

不要开始写代码，先确认理解。
```

**为什么要这样做**：Claude Code 每次会话是独立的，CLAUDE.md 虽然会自动加载，但让它复述一遍可以验证它确实理解了，避免后续跑偏。

### 第二步：制定本次会话计划

确认状态正确后：

```
请阅读 docs/dev-quickstart.md 中 Phase [N] 的 Step [M] 部分。
制定本次会话的执行计划：
- 要创建/修改哪些文件
- 每个文件的核心函数签名（不写实现，只列接口）
- 完成后如何验证

计划制定好后等待我确认，不要开始写代码。
```

### 第三步：逐步执行，每步验证

计划确认后：

```
计划确认，开始执行 Step [M]。
完成后停下来等我验证，不要自动继续下一步。
```

每个 Step 完成后，**你自己运行验证命令**，确认无误后再让它继续。

---

## 各 Phase 的启动指令（直接复制使用）

### Phase 0 启动

```
请读取 CLAUDE.md 和 docs/dev-environment.md。

然后执行 Phase 0 的环境搭建：
1. 创建虚拟环境并激活
2. 安装 requirements-dev.txt（注意：不是 requirements-prod.txt）
3. 验证所有依赖可正常导入
4. 创建 data/ 目录结构

每步执行前告诉我在做什么，执行后告诉我结果。
```

### Phase 1 启动（核心数据链路）

```
请读取 CLAUDE.md 和 docs/dev-quickstart.md。

当前要开始 Phase 1。请先制定计划：
列出 Step 1 到 Step 8 各需要创建的文件和核心函数签名。
特别注意：
- main.py 使用 platform_adapter/ui_driver.py，不直接调用 pywebview
- data_loader.py 必须调用 data_dictionary/ 的字段映射
- query_runner.py 必须使用 sqlglot（不用正则）提取表名
- 所有错误必须经过 error_translator.py 转成用户友好提示

制定完计划后等我确认。
```

### Phase 2 启动（语义层 + 报告）

```
Phase 1 已验收通过。现在开始 Phase 2。

请先读取：
- CLAUDE.md 第五章（语义层设计）
- data_dictionary/ 目录下的现有文件
- docs/data-schemas.md

然后制定 Phase 2 计划，重点是：
1. 补全 data_dictionary/ 的四个字典文件
2. calculators/ 模块（必须有单元测试覆盖）
3. fund_nav_report Skill 改为调用 calculators

注意：calculators/ 的计算函数不允许 LLM 生成 SQL，必须是固化的参数化查询。
```

### Phase 3 启动（合规监控）

```
Phase 2 已验收通过。现在开始 Phase 3。

请读取：
- CLAUDE.md 第七章（工具规格）
- skills/concentration_monitor/SKILL.md（注意其中的 calc_type: fixed 要求）
- scheduler/task_manager.py（现有框架）

制定 Phase 3 计划，重点是：
1. concentration_monitor 必须调用 calculators.concentration，禁止 LLM 生成集中度 SQL
2. task_manager.py 需要补充 on_startup() 补跑检测
3. compliance_audit.py 合规审计日志
4. 告警消息通过 platform_adapter/notify_driver.py 推送，不直接调用 winotify
```

---

## 常见问题处理

### Claude Code 跑偏了（生成了不符合规格的代码）

```
停一下。你生成的 [xxx] 不符合 CLAUDE.md 的要求：
[引用 CLAUDE.md 中的具体条款]
请重新生成，严格遵守规格。
```

### Claude Code 想一次写太多代码

```
先停下。请只实现 [具体函数名]，不要同时写其他部分。
写完后我来验证这一个函数，确认无误再继续。
```

### 遇到不确定的设计决策

```
这里有个设计问题：[描述问题]
请给出 2-3 个方案，说明各自的优缺点，我来决策。
不要自作主张选择。
```

### 测试失败，需要调试

```
运行 pytest tests/[具体文件] 时出现以下错误：
[粘贴错误信息]
请分析原因并修复，修复后重新运行测试确认。
```

---

## 会话节奏建议

| 会话长度 | 建议完成量 | 说明 |
|---------|----------|------|
| 短会话（1-2小时） | 1个 Step | 适合复杂模块，如 query_runner.py |
| 中会话（2-4小时） | 2-3个 Step | 适合相关模块组合 |
| 长会话（4小时+） | 整个 Phase | 仅适合 Phase 0 这类简单阶段 |

**原则**：宁可多几次短会话，每次都有明确验收，也不要一次写一大堆难以验证的代码。

---

## 记录开发进度

建议在项目根目录维护一个 `PROGRESS.md`，记录每个 Step 的完成状态：

```markdown
# 开发进度记录

## Phase 0 ✅
- [x] 虚拟环境创建
- [x] 依赖安装验证
- [x] data/ 目录结构

## Phase 1 进行中
- [x] Step 1: main.py
- [x] Step 2: ui/index.html 基础布局
- [ ] Step 3: tools/data_loader.py
- [ ] ...
```

这个文件在每次会话开始时可以让 Claude Code 快速了解当前进度：

```
请读取 PROGRESS.md 了解当前开发进度，
然后继续 Phase 1 的 Step 3。
```
