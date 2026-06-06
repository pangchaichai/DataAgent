# DataAgent 架构设计文档 v2.0

> 本文档记录关键架构决策及其背后的理由。
> v1.1 融入 GG 架构审查改进意见。
> v2.0 融入 Evolution I-1~I-10 架构演进。

---

## 一、核心设计决策

### 决策1：Skills 驱动的可扩展架构

**问题**：业务场景持续变化，每次新增场景都需要修改代码重新打包，独立开发维护成本极高。

**解决方案**：借鉴 Claude Code 的 Agent Skills 机制，将业务逻辑从代码中剥离，放入 `skills/` 文件夹的 Markdown 文件中。

**效果**：
- Python 核心代码（Agent Loop + 工具层）永远不需要修改
- 新增业务场景 = 新建一个 `skills/xxx/SKILL.md` 文件
- 技术能力边界（工具集）与业务知识边界（Skills）清晰分离

**渐进式披露原理**：
```
启动时：仅加载所有 Skill 的 name + description（约 200 Token）
运行时：LLM 判断任务相关性，按需加载完整 Skill 内容
优点：Skills 数量增加不影响基础 Token 消耗和启动速度
```

---

### 决策2：数据准确性优先于 LLM 灵活性

**问题**：金融数据错误会导致业务决策失误，后果严重。

**解决方案**：
- 数字计算由 DuckDB SQL 精确执行，LLM 只生成 SQL 代码
- LLM 不输出任何数值，只生成叙述性文字
- 关键计算结果必须展示给用户确认（Human-in-the-Loop）

**执行链路**：
```
LLM 职责：理解意图 → 生成 SQL → 生成文字叙述
DuckDB 职责：执行 SQL → 返回精确数值
人工确认：数值计算后、报告生成前，展示汇总表格供用户验证
```

---

### 决策3：Flask 随机端口（v1.1 GG审查改进）

**问题**：原设计固定 5000 端口，在金融机构办公机上极易与其他本地服务（本地代理、BI工具等）冲突，导致启动失败。

**解决方案**：`find_free_port()` 动态分配空闲端口。

**实现**：
```python
import socket
def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]
```

**权衡**：保留 Flask 而非改用 PyWebView js_api，原因：
- Flask + SSE 对独立开发者调试更友好
- Claude Code 对 Flask 的代码生成质量远高于 PyWebView js_api 模式
- 随机端口已解决端口冲突问题
- Flask 最小化配置下实际内存约 15MB（非 30-50MB），在约束范围内

---

### 决策4：DuckDB 内存硬性上限（v1.1 GG审查改进）

**问题**：多期文件叠加后复杂 JOIN 操作，DuckDB 默认动态抢占内存，可能冲破 200MB 约束甚至被系统强制终止。

**解决方案**：
```python
conn.execute("SET max_memory='80MB'")  # 内存天花板
conn.execute("SET threads=2")          # CPU线程限制
```

**为何选 80MB 而非 GG 建议的 60MB**：
- 持仓表 60列 × 283行，三表 JOIN 后中间结果集膨胀
- 60MB 在复杂聚合时可能触发 DuckDB 磁盘 Spill，性能下降明显
- 80MB 是平衡性能与内存约束的安全边界
- 即使 DuckDB 占 80MB，加上 Python/Flask/前端约 100MB，总计约 180MB < 200MB ✅

---

### 决策5：SQLGuard 动态元数据校验（v1.1 GG审查改进）

**问题**：原静态白名单（只允许 `holding`）在面对动态日期后缀表名（`holding_20260515`）时会误拒合规 SQL。

**解决方案**：每次执行前通过 `SHOW TABLES` 动态获取当前已加载的合法表名集合。

```python
valid_tables = set(conn.execute("SHOW TABLES").df()['name'].tolist())
# → {'holding_20260515', 'rating_entity_20260525', 'nav_20260514', ...}
# 动态感知，新加载的表自动加入白名单
```

---

### 决策6：ECharts 后置渲染（v1.1 GG审查改进）

**问题**：LLM 流式输出时，ECharts 图表的 Canvas 容器可能尚未被 `marked.js` 渲染到 DOM 中，立即调用 `echarts.init()` 会报 `Canvas container not found`。

**解决方案**：双阶段渲染，`stream_end` 事件触发后统一初始化。

```
流式阶段：图表数据加入 pendingCharts[] 队列，DOM 中插入占位容器
stream_end：DOM 稳定，遍历 pendingCharts[]，统一 echarts.init()
```

---

### 决策7：Skills 共享目录（v1.1 GG审查改进）

**问题**：团队多人使用时，每台电脑各自维护 Skills 文件，无法共享专家经验。

**解决方案**：`config.yaml` 中配置 `skills.shared_dir`，指向内网共享盘路径。

```yaml
skills:
  local_dir: skills/
  shared_dir: "\\\\fileserver\\DataAgent\\skills"
```

一人写好 Skill → 放入共享目录 → 团队所有人下次启动自动加载。

---

## 二、数据流设计

```
用户上传 CSV/Excel
    ↓
data_loader.py（chardet编码检测 → pandas清洗 → DuckDB注册）
    ↓
用户自然语言输入
    ↓
agent/loop.py
  ↓ skill_loader 检测相关 Skill（渐进式，按需加载完整内容）
  ↓ context.build()（Schema路由注入，仅注入相关表核心字段）
    ↓
LLM（DeepSeek V3，只传Schema，无敏感数据）
  生成 SQL 代码
    ↓
query_runner.py
  ↓ SQLGuard（SHOW TABLES 动态校验 → 只允许SELECT → LIMIT检查）
  ↓ DuckDB 执行（max_memory=80MB）
  返回精确数值
    ↓
[人工确认节点] → 展示数值汇总 → 等待用户确认
    ↓
report_builder.py（如需报告）
  ↓ Jinja2 填充数值字段
  ↓ LLM（企业内网，传实际数值）生成文字段落
  输出 Markdown 报告文件
    ↓
SSE 推送前端 → stream_end → ECharts 图表渲染
```

---

## 三、ADP 设计模式应用

| ADP 章节 | 在 DataAgent 中的应用 |
|---------|---------------------|
| Ch.1 提示词链 | SQL生成→执行→报告生成多步链路 |
| Ch.2 路由 | skill_loader 识别意图，路由到对应 Skill |
| Ch.4 反思 | SQL失败 → 错误返回LLM → LLM修正 → 重试 |
| Ch.5 工具使用 | 6个工具的 Function Calling 设计 |
| Ch.8 记忆管理 | Schema路由注入 + Token压缩 + 历史截断 |
| Ch.12 异常处理 | 工具失败计数 + 最大重试上限 + 错误反馈LLM |
| Ch.13 人机协同 | 数值计算后、报告生成前的强制确认节点 |
| Ch.16 资源感知 | DuckDB内存上限 + Flask最小化配置 |
| Ch.18 Guardrails | SQLGuard（动态白名单+只读SELECT）+ 数据隔离 |

---

## 四、内存使用分析

| 组件 | 内存占用 | 说明 |
|------|---------|------|
| Python 进程基础 | ~30 MB | Flask + 基础库 |
| Flask + SSE | ~15 MB | 最小化配置 |
| DuckDB | ≤ 80 MB | 硬性上限，max_memory=80MB |
| PyWebView WebView | ~40 MB | Chromium 内核 |
| **合计预估** | **~165 MB** | **< 200MB 约束 ✅** |

---

---

### 决策8：Flask Blueprint 拆分（I-7）

**问题**：随着功能增加，`main.py` 承载了所有路由（数据上传、聊天、配置、报告、Skills、系统），单文件超过 500 行，维护困难且无法独立测试各模块。

**解决方案**：将路由拆分为 6 个 Blueprint 模块：

```
api/
├── chat.py      → /api/chat, /api/stream, /api/sessions, /api/confirm, /api/reset
├── data.py      → /api/upload, /api/upload/confirm, /api/tables
├── config_api.py → /api/config, /api/status, /api/suggestions, /api/llm/*
├── skill_api.py → /api/skills, /api/skill-builder/*
├── report_api.py → /api/report/*
└── system.py    → /api/health, /api/groups, /api/tasks, /api/memory/stats, /api/logs/*
```

**共享状态**：`session_store.py` 集中管理 `_session`、`_stream_queues`、`BASE_DIR`，所有 Blueprint 从这里导入。

**权衡**：DuckDB 持久化文件锁——当应用运行中时，诊断脚本不能重复调用 `create_flask_app()`。这是已知限制，不影响用户功能。

---

### 决策9：Plan-Execute 两阶段 Agent（I-8）

**问题**：单步 Agent Loop 对「多步骤分析任务」效果差——用户问「帮我分析持仓集中度并生成报告」时，Agent 一次只考虑一个工具调用，缺乏全局规划。

**解决方案**：在 Agent Loop 之上增加可选的 Plan-Execute 层：

```
用户消息
  ↓ should_plan() 判断（含多步骤、数据分析、报告等关键词）
  ↓ build_plan() → LLM 生成 Plan（步骤列表）
  ↓ run_with_plan() → 按步骤顺序调用 run_agent_loop()
  ↓ SSE 事件：plan / plan_step / plan_done（前端显示进度）
```

**降级策略**：`should_plan()` 返回 False 或 `build_plan()` 失败时，直接走单步 Agent Loop，不影响基本功能。

---

### 决策10：Skill Builder 自助发布（v1.6）

**问题**：非技术用户无法自己创建 Skills，每次新业务场景都需要开发人员介入修改文件。

**解决方案**：`tools/skill_builder.py` + API + 前端向导，让用户通过对话描述创建 Skill：

```
用户描述场景 → LLM 生成 SkillDraft → generate_skill_md() 渲染
  → save_draft() 草稿暂存 → validate_skill_md() 多维校验
  → publish_skill() 写入 skills/{name}/SKILL.md
```

**安全约束**：用户只能创建 `calc_type: exploratory` 类型（禁止创建固化计算 Skill）；SQL 示例经安全正则过滤；草稿未发布前对 Agent 不可见。

---

### 决策11：前端 JS 模块化（I-10）

**问题**：`ui/index.html` 内联 JavaScript 从 0 增长到 1280 行，单文件难以维护、无法复用，代码审查困难。

**解决方案**：将内联脚本拆分为 9 个独立文件，通过 Flask 的 `/static/` 路由提供：

```
ui/js/
├── state.js        → 全局状态（_upl, mentions 等）
├── dom.js          → DOM 工具（$, esc, toast）
├── render.js       → 消息渲染（Markdown, ECharts, 确认卡片）
├── chat.js         → 发送消息, SSE 流式接收
├── upload.js       → 两阶段上传（预览→确认）
├── sidebar.js      → 侧边栏（会话列表, 表列表, @mention）
├── settings.js     → 设置面板（配置, 集团管理, 任务, 记忆）
├── skill_builder.js → Skill 创建向导
└── main.js         → 入口（键盘事件, 初始化, 轮询健康检查）
```

**权衡**：纯浏览器原生 ES module（无 bundler），加载顺序由 `<script>` 标签顺序保证，全局函数挂在 `window` 上供 HTML `onclick` 调用。这保持了零构建工具的简洁性。

---

## 五、未来扩展路径

| 扩展方向 | 实现方式 | 是否需要改核心代码 |
|---------|---------|-----------------|
| 新增业务报告类型 | 新建 skills/xxx/SKILL.md | ❌ 不需要 |
| 新增数据源类型 | 扩展 data_loader.py | ✅ 需要（单文件改动） |
| 切换 LLM 模型 | 修改 config.yaml | ❌ 不需要 |
| 新增图表类型 | 扩展 chart_builder.py | ✅ 需要（单文件改动） |
| 团队共享 Skills | 配置 skills.shared_dir | ❌ 不需要 |
| 未来迁移到内网 Web | Flask 后端不变，去掉 PyWebView | 最小改动 |
