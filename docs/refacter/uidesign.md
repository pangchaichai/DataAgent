# DataAgent UI 设计规格（合并版 / 权威）

> 本文件 = CC4.6 `ui-design-v2.md` + Phase R 修订，**合并为单一权威**。
> Phase R 实现 `ui/index.html` 时**只看本文件**，不再参考 `ui-design-v2.md`（已被本文件取代）。
> 配套：`docs/refactor/ui-mockup.svg`（静态效果图）、`docs/refactor/index-preview.html`（可点击原型，浏览器直接打开）。

---

## 0. Phase R 关键修订（相对 CC4.6 v2 的差异，先读）

| 项 | CC4.6 v2 | 本文件（生效） |
|----|----------|----------------|
| 前端资源 | Tailwind Play CDN / marked.js CDN | **全本地资源，零 CDN**（内网离线底线，见 §7.1） |
| 侧边栏会话 | 无 | **新增「💬 最近会话」分区**，可调取历史会话（见 §4.2 / §4.6） |
| 记忆库 | 自动启用 | **用户开关，默认 OFF**，仅本机、不外发（见 §4.2） |
| 确认/澄清 | 仅"人工确认" | 增加 **`ask`（澄清选择题）卡片**；确认/澄清未决时**禁用输入框**（见 §4.3） |
| 工具卡片 | run_sql | 增 **`run_calculator`** 卡片，显式标注"固化口径/来源 config"（见 §4.3） |
| 思考过程 | — | 新增 `thinking` 折叠块（见 §4.3） |

---

## 1. 设计原则

1. **信息分层**：对话内容与确认节点最大；Agent 状态与数据列表在侧边栏；技术细节（SQL/公式）默认折叠。
2. **状态透明**：思考 / 调用工具 / 等待确认 都有明确视觉反馈，用户始终知道系统在做什么。
3. **零歧义操作**：需要用户决策的节点（人工确认、口径澄清、草稿确认）用醒目卡片**中断流程**，且未决时禁用输入框，不可被忽略。
4. **金融专业感**：色调中性偏冷，数字规范（千分位、tabular-nums、颜色编码），空间宽松。

---

## 2. 视觉系统

### 2.1 色彩（CSS 变量，亮/暗双主题）

```css
:root{
  --bg-base:#F8F9FA; --bg-sidebar:#FFFFFF; --bg-card:#FFFFFF; --bg-input:#FFFFFF;
  --bg-agent:#F0F4FF; --bg-code:#F1F5F9; --bg-hover:#F1F5F9;
  --border:#E2E8F0; --border-focus:#3B82F6;
  --text-primary:#0F172A; --text-secondary:#64748B; --text-muted:#94A3B8;
  --blue:#3B82F6; --blue-bg:#EFF6FF; --indigo:#6366F1;
  --success:#10B981; --success-bg:#ECFDF5; --warning:#F59E0B; --warning-bg:#FFFBEB;
  --error:#EF4444; --error-bg:#FEF2F2; --neutral:#6B7280;
  --sidebar-w:240px; --header-h:52px; --radius:8px; --radius-lg:12px;
}
[data-theme="dark"]{
  --bg-base:#0F172A; --bg-sidebar:#1E293B; --bg-card:#1E293B; --bg-input:#1E293B;
  --bg-agent:#1E2D4A; --bg-code:#0F172A; --bg-hover:#334155; --border:#334155;
  --text-primary:#F1F5F9; --text-secondary:#94A3B8; --text-muted:#64748B;
}
```

### 2.2 字体
```css
body{font-family:"Inter","PingFang SC","Microsoft YaHei",system-ui,sans-serif;font-size:14px;line-height:1.6;}
.numeric{font-variant-numeric:tabular-nums;}
code,pre{font-family:"JetBrains Mono","Cascadia Code",monospace;}
```
> 字体一律走系统字体栈，**不引入需联网下载的 web font**。

### 2.3 间距/圆角
基础单位 4px。卡片圆角 8px，大卡片/弹层 12px，按钮 6px。

---

## 3. 整体布局

```
┌──────────────────────────────────────────────────────────────┐
│ Header (52px)  [📊 DataAgent] [●Qwen3-32B 180ms][🧠记忆 关][8.2K/64K][92MB][🌙][⚙]│
├──────────┬───────────────────────────────────────────────────┤
│ Sidebar  │  会话标题 / 面包屑                        [＋新对话] │
│ (240px)  ├───────────────────────────────────────────────────┤
│ 💬最近会话│                                                    │
│ 📂已加载  │            消息列表（可滚动）                       │
│ 🔖Skills │                                                    │
│ 👥集团系  │  [人工确认卡片] ← sticky，未决时输入框禁用          │
│ 🧠记忆库  ├───────────────────────────────────────────────────┤
│          │  [快捷按钮]  [📎] [输入框...] [发送↵]               │
└──────────┴───────────────────────────────────────────────────┘
```
侧边栏可收起为 48px（图标态 + 数量徽标）。

---

## 4. 组件规格

### 4.1 Header
- 左：Logo + "DataAgent"。
- 中/右：状态 chips（点击可展开详情）：
  - `● 模型名 延迟ms`：圆点 绿=在线/黄=慢/红=离线。
  - `🧠 记忆 关/开`：点击切换跨会话记忆开关（默认关）。
  - `Token 已用/上限`：接近上限变橙→红。
  - `内存 MB`：≥160 橙，≥185 红。
  - `🌙` 主题切换、`⚙` 设置。

### 4.2 侧边栏分区

**💬 最近会话（新增，置顶）**
```
💬 最近会话                         [＋新对话]
  ● 象屿系集中度核查        今天 14:33
  ○ 5月持仓结构分析         昨天
  ○ 海晟租赁敞口查询        05-28
  [查看全部会话…]
```
- 数据源：`data/sessions/` 的会话日志（JSONL）。点击某条 → 调 `GET /api/sessions/<id>` 载入该会话消息并渲染到聊天区（只读回放 + 可在其基础上继续）。
- 当前活跃会话高亮（实心圆点），其余空心。
- `＋新对话` = `POST /api/reset` 后清空聊天区。
- `查看全部会话` 打开会话列表弹层（标题/时间/涉及表/可删除）。

**📂 已加载数据**：每行带质量圆点 🟢正常/🟡警告/🔵字典待确认/⚪未知；悬停弹出列数/字典状态/质量摘要；`＋上传`。

**🔖 Skills**：每项带 `固化`/`探索` 标签；当前激活高亮。

**👥 集团系**：`象屿系(3主体)` 等；`管理` 入口。

**🧠 记忆库**：显示"已关闭（点击开启）"或"N条（口径纠正）"；带开关；开启态提供"清空"。默认关闭。

### 4.3 消息与卡片

- **用户消息**：右对齐灰色气泡 + 时间。
- **Agent 消息**：左对齐，🤖 头像，markdown 渲染（marked.js **本地**）。
- **thinking（思考过程，折叠）**：浅靛蓝块，折叠态只显示当前步骤摘要；`[展开]` 看全部步骤。
- **工具卡片（三态）**：
  - 进行中：边框蓝 + 进度条动画 + "执行中…"。
  - 成功：边框绿 + "N行·420ms ✅"，可展开看 SQL。
  - 失败：边框红 + "❌ 失败，自动重试(2)"。
  - **`run_calculator` 卡片**：必须显示"口径来源：config（穿透后市值·集团合并·阈值10%）·非LLM生成"，强调 B 类可审计。
- **数据表格**：列头可排序，数字右对齐 + 千分位，合计行加粗，`导出CSV`。
- **人工确认卡片（最高优先级，视觉中断）**：蓝色左边框 + 浅蓝底 + `position:sticky`；含 标题、指标表（计算值/阈值/状态）、口径说明、可展开公式/SQL、`✅确认` `❌取消`。**等待确认时输入框与发送按钮禁用。**
- **澄清卡片 `ask`（新增）**：当存在影响正确性的歧义（口径=穿透/半穿透、指哪个产品等）时出现；一个问题 + 选项按钮；点选项即作为下一条消息发回；**等待时输入框禁用**。
- **数据质量卡片**：上传后自动插入；分"⚠️需要注意（critical 红/warning 黄）"与"✅正常"；展示空值率、未识别主体、JOIN 兼容率；`补充别名`等行动入口；可折叠。
- **Schema 草稿确认卡片**：未知表内联推断后，若用户要求"保存为字典"才出现；列出 原始列名→推断含义（可编辑）；`全部确认保存`/`仅本次使用`。
- **ECharts 图表卡片**：标题 + 容器 + `下载图片`；**stream_end 后统一 init**。

### 4.4 输入区
- 快捷按钮行：`/report` `/tables` `/health` `/skills` `/clear` 等。
- 文件拖拽：拖入时蓝色虚线高亮 + "松开上传"。
- 输入框：多行；`Enter` 发送，`Shift+Enter` 换行；`/` 唤出命令面板，`@` 唤出数据表面板。
- **确认/澄清未决时整体禁用**（灰底 + 占位提示）。

---

## 5. Agent 状态机（视觉）

| 状态 | 表现 |
|------|------|
| 空闲 | 输入框正常 placeholder |
| LLM 流式 | 光标闪烁，文字逐字 |
| 思考 | thinking 折叠块滚动当前步骤 |
| 工具调用中 | 工具卡片进度条 |
| 等待人工确认/澄清 | 卡片出现 + 输入框禁用 |
| Schema 推断中 | 侧边栏表名旁"推断中…" |
| 记忆建议 | （仅开启时）出现"采用上次口径？"chip |
| 完成 | 发送按钮恢复，焦点回输入框 |

---

## 6. 交互细节

### 6.1 快捷键
Enter 发送 / Shift+Enter 换行 / `/` 命令 / `@` 表 / Esc 关面板 / Ctrl+K 聚焦输入 / Ctrl+L 清空。

### 6.2 消息 hover 操作
Agent 消息右上角悬停出现 `复制 / 重新生成 / 👍 / 👎`。

### 6.3 会话回放
点击"最近会话"载入历史：消息只读渲染，底部出现"在此会话继续"按钮，点击后可追加新消息（沿用该会话上下文）。

---

## 7. 实现指南（给 Claude Code）

### 7.1 资源策略（红线）
- **单 HTML 文件 + 本地静态资源**，全部放 `ui/static/`：`tailwind-local.css`（或手写 CSS）、`echarts.min.js`、`marked.min.js`、（可选）`fira-code` 字体。**禁止任何 CDN / 外网请求**。
- 不引入 Node 构建链（技术栈已锁定）。
- 现仓库 `ui/index.html` 已用本地资源，**保持，不可倒退为 CDN**。

### 7.2 JS 分区（单文件内注释分区）
STATE / API&SSE / RENDER-MESSAGES / RENDER-SIDEBAR / RENDER-HEADER / SSE-CHUNK-HANDLER / INPUT / ECHARTS-POSTRENDER / THEME&SIDEBAR / SESSIONS / INIT。

### 7.3 SSE 消费
逐行 `data: ` 解析（见 `index-preview.html` 与现仓库 `ui/index.html` 已有实现）。

---

## 8. SSE 消息格式（后端 loop.py 必须遵守 · 合并版）

```python
{"type":"text","data":"..."}                         # 流式文字
{"type":"thinking","data":"识别集团成员…"}            # 思考步骤（折叠）
{"type":"tool_start","data":{"id","name","args"}}     # 工具开始
{"type":"tool_end","data":{"id","row_count","duration_ms","sql"}}  # 工具完成
{"type":"tool_error","data":{"id","error","retry"}}   # 工具失败
{"type":"table","data":{"columns","rows","total","sql"}}
{"type":"chart","data":{"id","title","option"}}       # 入 pendingCharts，stream_end 渲染
{"type":"confirm","data":{"session_id","title","summary":[{label,value,threshold,status}],"sql_or_formula"}}
{"type":"ask","data":{"session_id","question","options":[...]}}    # ★新增 澄清
{"type":"quality","data":QualityReport,"table_name":"..."}
{"type":"schema_draft","data":{"table_type","fields":[{physical_name,semantic_name}]}}
{"type":"stats","data":{"llm_status","llm_name","llm_latency","ram_mb","token_used","token_limit","memory_count"}}
{"type":"stream_end"}
{"type":"error","data":"未找到表「持仓_0515」，请先上传数据文件。"}
```

---

## 9. 后端路由（UI 依赖 · 含会话历史）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 用户消息 → SSE 流 |
| POST | `/api/upload` | 上传，返回含 `quality_report` |
| GET  | `/api/tables` | 已加载表（含质量圆点状态） |
| POST | `/api/confirm` | 人工确认（写回 `_session["pending"]` 续跑） |
| POST | `/api/reset` | 新对话 |
| GET  | `/api/health` | 状态栏（psutil 内存等） |
| GET  | `/api/skills` | Skills 列表（含 calc_type） |
| **GET** | **`/api/sessions`** | **最近会话列表 `[{id,title,updated_at,tables}]`（读 data/sessions/）** |
| **GET** | **`/api/sessions/<id>`** | **载入某会话消息用于回放** |
| GET  | `/api/memory/stats` | 记忆统计（关闭时 `{enabled:false}`） |
| POST | `/api/schema-draft/confirm` | 草稿入库（R4） |

---

## 10. MVP 范围

**P0（必做）**：布局/侧边栏（**含最近会话**）/消息渲染/工具卡片三态/数据表格/人工确认卡片（禁用输入）/澄清卡片/数据质量卡片/流式/拖拽上传/斜杠+@面板/全本地资源。
**P1**：Schema 草稿卡片/会话回放与"继续"/悬停 tooltip/主题切换/Token·内存警告/侧边栏折叠/ECharts 后置渲染。
**P2**：消息 hover 操作/完整键盘导航/会话搜索。
