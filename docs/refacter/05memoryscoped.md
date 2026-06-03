# Step R5：收窄版跨会话记忆（合规优先，最后做）

> CC4.6 原方案让记忆自动提炼 `sql_pattern` / `business_rule` 并**静默注入** system prompt。
> 对"数字正确性高于灵活性"的第一性约束，这有风险：一段在 A 场景成功的 SQL 被召回注入 B 场景，
> 会产出**精确的错误**；自动"业务规则"无签字、无版本、难审计，与 `compliance_audit` 冲突。
>
> 因此本 Step **收窄**：只记口径纠正、只做显式建议、绝不自动注入 SQL/合规口径。

依赖 R1。优先级最低，属增强项。

---

## 0. 两种"记忆"要分清（重要）

| 类型 | 来自哪个 Step | 能否关闭 | 说明 |
|------|---------------|----------|------|
| **会话内多轮记忆**（`_session["messages"]`） | R1 | **不提供关闭**（关了 Agent 就退回单次问答，等于没改） | 这是 Agent 能"连续追问、复用上下文"的基础，属内核能力，非"记忆库" |
| **跨会话持久记忆**（`memory.db`，本 Step） | R5 | **提供用户开关**（默认关闭） | 跨重启、跨会话的口径纠正记忆，对应你要的开关 |

> 你要的"记忆开关"指的是后者。前者是 Agent 正常工作的前提，不应也无法有意义地关闭。

## 0.1 用户开关设计（默认 OFF）

```yaml
# config.yaml 新增
memory:
  enabled: false          # 默认关闭；用户在 UI 设置里开启
  max_db_mb: 5            # 体积告警阈值
```

- `enabled=false` 时：`save_correction()` 与 `recall()` **直接 no-op 返回**，不建库、不读库、不在 UI 出现任何记忆建议。整条记忆链路对系统**零副作用**（满足"数字正确性高于灵活性"——默认不引入任何历史影响）。
- UI（Header/设置面板）提供「🧠 记忆」开关：
  - 开启：提示"将跨会话记住你的字段口径纠正，仅本机存储、不外发"。
  - 关闭：同时提供「清空记忆库」按钮（删除 `data/memory.db`）。
- `/api/memory/stats` 在关闭时返回 `{enabled:false}`，前端据此置灰。
- 开关状态持久化到 `config.yaml`（或 `data/` 下的用户偏好文件），重启保留。

---

## 范围裁剪（与 v1.4 的差异）

| v1.4 原方案 | 本方案 |
|-------------|--------|
| 记 schema_correction / sql_pattern / business_rule 三类 | **只记 `schema_correction`（字段口径纠正）** |
| BM25 召回后**自动注入** system prompt | **不自动注入**；召回结果作为 UI **显式建议**，用户点确认才采用 |
| 自动提炼业务规则 | 不做 |
| 记 SQL 模式 | **禁止**（避免跨场景误用） |

---

## 实现（`agent/memory.py`，BM25 + SQLite，纯 Python，PyInstaller 友好）

```python
class AgentMemory:
    DB_PATH = "data/memory.db"
    def initialize(self): ...          # 建表 + 载入 BM25
    def save_correction(self, key, content, source=""): ...   # 仅 schema_correction
    def recall(self, query, top_k=3) -> list[dict]: ...       # 空库返回 []
    def get_stats(self) -> dict: ...   # 供 /api/memory/stats
```

- 触发写入：**仅当**用户在确认/澄清节点**显式纠正了字段口径**（如"市值用穿透后"），由 loop 调 `save_correction`。不做"会话结束后 LLM 自动提炼"。
- 召回使用：新会话里 `recall()` 命中 → 前端显示一条**建议** chip："上次你把'市值'定为穿透后，这次也这样？[采用]"。用户点采用，才把该口径写进本轮上下文。
- 依赖：`rank_bm25`（加入 requirements）。中文按字符 `list(text)` 切分，无需 jieba。

---

## 合规护栏

- memory **不参与** B 类固化计算的口径选择；合规口径只能来自 `config.yaml` 的 `calculation_config` + 人工签字。
- memory 内容**不外发**（即使 external_allowed=true，也不把记忆塞进发往外网的 prompt）。
- `data/memory.db` 体积告警：> 5MB 时 `/api/health` 提示。

---

## 验收（`tests/test_intelligence.py`）

- `test_memory_save_and_recall()`
- `test_memory_recall_empty_db()`（空库不报错）
- `test_memory_no_sql_pattern()`（断言不存在 sql_pattern/business_rule 写入路径）
- `test_memory_not_auto_injected()`（断言召回不直接进 system prompt，仅作建议）
- 手动：会话中纠正口径 → 新会话出现"采用上次口径"建议；点采用后生效。

---

## 交付物

- [ ] `agent/memory.py`（仅 schema_correction）
- [ ] `config.yaml` 新增 `memory.enabled`（默认 false）+ no-op 短路逻辑
- [ ] UI 记忆开关 + 清空按钮（与 R3 协同）
- [ ] `main.py` `/api/memory/stats`（关闭时返回 enabled:false）
- [ ] loop：确认/澄清纠正时 `save_correction`；新会话 `recall` 作建议（不自动注入）
- [ ] `requirements-*.txt` 加 `rank_bm25`
- [ ] 单测 4 项；旧测试绿
- [ ] 更新 PROGRESS-refactor.md，并触发"收尾"
