# Step R3：UI 重建（全本地资源 · 状态透明 · 不可忽略的确认）

> 采纳 CC4.6 `ui-design-v2.md` 的信息架构，但**守住离线底线**，并对接 R1/R2 的新 chunk。
>
> **权威设计文件 = `docs/refactor/ui-design.md`（合并版，已取代 ui-design-v2.md）。**
> 配套：`ui-mockup.svg`（静态效果图）、`index-preview.html`（可点击原型，浏览器直接打开，DEMO 模式）。
> 实现 `ui/index.html` 时**只看 ui-design.md**；index-preview.html 是交互参照，可直接抽取其 CSS/结构后接后端。

---

## 前置阅读

- `docs/refactor/ui-design.md`（合并版权威规格）
- `docs/refactor/index-preview.html`（可运行的交互参照）
- `ui/index.html`（现状：本地 `/static/tailwind-local.css` + 本地 `echarts.min.js`，深色原型）
- R1 §7 的 SSE chunk 清单、R2 的 QualityReport 结构
- `main.py` 的 `/api/tables` `/api/reset` 与静态资源服务方式

---

## 红线（必须遵守）

1. **禁止任何 CDN**。`ui-design-v2.md §7.1` 写的 "Tailwind Play CDN / marked.js CDN" **不采纳**。所有 CSS/JS/字体**本地化**放 `ui/static/` 或 `/static/`，离线可运行。现状已是本地资源，**不要倒退**。
2. 单 HTML 文件 + 本地静态资源，**不引入 Node 构建链**（CLAUDE.md 技术栈已锁定）。
3. Markdown 渲染如需 marked.js，**下载到本地** `static/marked.min.js`。

---

## 必做组件（P0）

| 组件 | 对接 chunk / 接口 | 说明 |
|------|-------------------|------|
| Header 状态栏 | `GET /api/health`（R 阶段新增）+ `stats` chunk | LLM 状态/延迟、内存、Token、轮数 |
| **侧边栏「最近会话」（新增）** | `GET /api/sessions` / `GET /api/sessions/<id>` | 列最近会话、点击回放载入；`＋新对话`=`/api/reset` |
| 侧边栏数据表（带质量圆点） | `/api/tables` + 质量 | 🟢正常/🟡警告/🔵待确认 |
| 侧边栏 Skills（固化/探索标签） | `GET /api/skills`（新增） | 复用 `skill_loader.load_registry()` |
| 流式文字 + 思考折叠 | `text` / `thinking` | thinking 默认折叠 |
| 工具卡片三态 | `tool_start`/`tool_end`/`tool_error` | 进行中/成功/失败 |
| 数据表格（排序+导出CSV） | `table` | 数字右对齐、千分位 |
| **人工确认卡片（不可忽略）** | `confirm` + `POST /api/confirm` | 蓝色左边框、sticky、等待时禁用输入框 |
| **澄清卡片** | `ask` | 一个问题 + 选项按钮，点选即作为下一条消息发回 |
| 数据质量卡片 | `/api/upload` 的 `quality_report` | critical 红、warning 黄，可折叠 |
| 文件拖拽上传 | `/api/upload` | 蓝色虚线高亮 |
| 斜杠命令 / @mention 面板 | 本地 | 已有 @mention，补 `/` 命令 |

P1（可后置）：ECharts 后置渲染（保留现有 `pendingCharts` + `stream_end` 机制）、亮/暗主题、Token/内存超阈值变色、侧边栏折叠。

---

## 新增后端路由（配合 UI）

```
GET  /api/health        → {llm_status, llm_name, llm_latency, ram_mb, token_used, token_limit}
                          ram_mb 用 psutil；llm_status/latency 用 R1 的 client 缓存
GET  /api/skills        → {skills:[{name, description, calc_type}]}
POST /api/confirm       → {session_id, confirmed} 写回 _session["pending"]，续跑（见 R1 §5）
GET  /api/sessions      → {sessions:[{id, title, updated_at, tables}]}   # 读 data/sessions/ JSONL
GET  /api/sessions/<id> → {messages:[...]}   # 回放载入；标题取首条用户消息前若干字
```

> 会话持久化：R1 的 `_session` 需带 `session_id` 并把每轮消息落到 `data/sessions/{id}.jsonl`
> （沿用既有会话日志目录）。`/api/sessions` 扫描该目录生成列表。回放为只读，
> 点击"在此会话继续"后把该会话 messages 设为当前上下文继续对话。

依赖：`psutil` 加入 `requirements-dev.txt` / `requirements-prod.txt`。

---

## 关键交互规则

- **确认/澄清未完成时，输入框与发送按钮禁用**，强制用户先决策（零歧义原则）。
- 确认卡片必须展示：标题、关键指标表（计算值/阈值/状态）、口径说明、可展开的 SQL/公式、确认/取消按钮。
- ECharts **必须** stream_end 后统一 `init`（沿用现有机制，避免容器未就绪）。

---

## 验收（手动 P0 清单）

- [ ] 页面加载 Header 有 LLM/内存数据；侧边栏有表+Skills（含标签）
- [ ] 发消息流式文字正常；工具卡片三态正常
- [ ] 表格可排序、可导出 CSV
- [ ] 触发一次集中度 → **确认卡片出现且输入框禁用** → 确认后继续
- [ ] 触发一次澄清（含糊问题）→ 选项卡片 → 点选续跑
- [ ] 上传 CSV → 质量卡片，critical 红色
- [ ] 拖拽上传高亮；`/` 与 `@` 面板可用
- [ ] **断网（无外网）仍能打开页面并渲染**（验证零 CDN）

---

## 交付物

- [ ] `ui/index.html` 重建（参照 `ui-design.md` + 抽取 `index-preview.html`）+ `ui/static/` 本地资源（零 CDN）
- [ ] 侧边栏「最近会话」分区 + 回放
- [ ] `main.py` 新增 `/api/health` `/api/skills` `/api/confirm` `/api/sessions` `/api/sessions/<id>`
- [ ] 会话落盘 `data/sessions/{id}.jsonl` + `_session` 带 session_id
- [ ] `requirements-*.txt` 加 `psutil`
- [ ] 手动 P0 清单全过（含断网可打开 + 会话回放）
- [ ] 更新 PROGRESS-refactor.md
