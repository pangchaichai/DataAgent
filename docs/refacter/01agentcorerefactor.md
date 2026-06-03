# Step R1：把 loop 重构为真正的 tool-calling Agent（核心）

> 这是整个方案的**根因修复**。完成后 Agent 才会"思考、追问、自我修正"。

---

## 前置阅读（动手前必须读，核对真实签名）

- `agent/loop.py`（现状：直线流水线，`run_agent_loop` 是 generator）
- `agent/llm_client.py`（`LLMClient._call(provider, prompt, system, timeout, max_tokens) -> LLMResponse`；目前**没有**原生 function-calling 方法）
- `agent/context.py`（`build_schema_context()`）
- `agent/skill_loader.py`（`SkillInfo.calc_type` / `.fixed_calculator` / `load_full()`）
- `tools/query_runner.py`（`execute_query(sql, conn) -> QueryResult{success,columns,rows,row_count,error,requires_confirmation}`）
- `tools/data_loader.py`（`get_connection()` / `get_loaded_tables()` / `_loaded_tables[name].field_map`）
- `tools/entity_manager.py`（`EntityManager.list_groups()/get_members()/get_group_mapping()`）
- `calculators/concentration.py`（`calc_entity_concentration(conn, holding_table, market_value_field, threshold_pct, use_group_merge, group_mapping, entity_alias, product_filter)`）及其余 calculators 的签名
- `main.py`（`/api/chat` 闭包内构造 `run_agent_loop(message, llm_client, skill_loader, turn_count)`；`_session` 仅存 `turn_count`；有 `/api/reset`）
- `tests/test_agent.py`

---

## 目标

把单次流水线替换为标准 Agent 循环：

```
组装 messages（系统提示+schema+skills+对话历史+用户）
for turn in range(MAX_TURNS):
    assistant = llm.chat(messages, tools=TOOL_DEFINITIONS)   # 模型自己决定调用哪个工具
    流式输出 assistant 文本
    若无 tool_calls → 结束（最终回答）
    for call in tool_calls:
        执行工具 → 把结果作为 tool message 追加回 messages
        遇到 ask_user / confirm → 暂停，等用户决定后再续跑
emit stream_end
```

---

## 1. 新增 `agent/tools_spec.py`（工具定义 + 分发）

定义 OpenAI 风格 function schema 与分发表。**工具是只读/受控的**，写操作一律禁止。

```python
# agent/tools_spec.py（骨架，按真实签名实现）
TOOL_DEFINITIONS = [
  {
    "type": "function",
    "function": {
      "name": "profile_table",
      "description": "剖析一张已加载的数据表：返回列名、推断类型、关键文本列的样本去重值、空值率。"
                     "当你不确定某列含义或口径时，先调用它，而不是猜或要求用户标注。",
      "parameters": {"type":"object","properties":{
        "table_name":{"type":"string"},
        "columns":{"type":"array","items":{"type":"string"},
                   "description":"可选，只剖析这些列"}},
        "required":["table_name"]}
    }
  },
  {
    "type":"function",
    "function":{
      "name":"run_sql",
      "description":"对已加载表执行只读 SELECT（探索式 A 类查询）。禁止用于合规/报告口径。",
      "parameters":{"type":"object","properties":{
        "sql":{"type":"string"},
        "purpose":{"type":"string","description":"一句话说明这条查询要回答什么"}},
        "required":["sql"]}
    }
  },
  {
    "type":"function",
    "function":{
      "name":"run_calculator",
      "description":"调用固化口径计算（合规/报告 B 类）。结果口径正确、可审计。"
                   "凡涉及集中度/净值指标/资产结构/评级分布等合规或报告数字，必须用本工具，禁止自己写 SQL。",
      "parameters":{"type":"object","properties":{
        "calculator":{"type":"string","enum":[
           "entity_concentration","nav_metrics","asset_structure","credit_distribution"]},
        "holding_table":{"type":"string"},
        "product_filter":{"type":"array","items":{"type":"string"}},
        "group_name":{"type":"string","description":"可选，按集团系过滤/合并"}},
        "required":["calculator"]}
    }
  },
  {
    "type":"function",
    "function":{
      "name":"ask_user",
      "description":"当存在影响结果正确性的歧义（如口径=穿透后/半穿透、是否集团合并、指哪个产品）时，"
                   "向用户提出【一个】关键选择题。不要用它问无关紧要的问题。",
      "parameters":{"type":"object","properties":{
        "question":{"type":"string"},
        "options":{"type":"array","items":{"type":"string"}}},
        "required":["question"]}
    }
  },
  {
    "type":"function",
    "function":{
      "name":"request_confirmation",
      "description":"在生成对外报告 / 落库合规结论前，把关键数值与口径交用户确认。",
      "parameters":{"type":"object","properties":{
        "title":{"type":"string"},
        "summary":{"type":"array","items":{"type":"object"}},
        "sql_or_formula":{"type":"string"}},
        "required":["title","summary"]}
    }
  }
]
```

**分发表** `dispatch_tool(name, args, ctx) -> ToolResult`：
- `profile_table` → 新增 `tools/profiler.py`（见 §3）。
- `run_sql` → `query_runner.execute_query`（SQLGuard 已保证只读+LIMIT）。把结果整成 `{columns, rows(截断 200 行), row_count, sql}`。
- `run_calculator` → 见 §4，**从 config 读口径**，调用 `calculators/`。
- `ask_user` / `request_confirmation` → 不"执行"，而是**产出暂停信号**（见 §5）。

> 护栏：分发层对 `run_calculator` 传入的任何 SQL 字段一律忽略；口径字段（如 `market_value_field`）只能来自 `config.yaml` 的 `calculation_config`，**不接受 LLM 传值**。

---

## 2. `llm_client` 新增 `chat()`（带工具）

**模型能力已核实**：开发用 DeepSeek（`deepseek-chat`，V3.2 系）与生产用 Qwen3-32B **均原生支持** OpenAI 风格 function-calling。
→ **默认 `tool_mode = native`，直接做这一种即可。**

```yaml
# config.yaml 新增
llm:
  sql_gen:
    tool_mode: native   # native = OpenAI function-calling（默认，dev/prod 都用这个）
                        # react  = 文本 JSON 协议（仅作兜底，见下方"何时才做"）
```

**部署注意**：Qwen3-32B 经 vLLM/SGLang 暴露 OpenAI 端点时，需开启工具解析，例如
vLLM：`--enable-auto-tool-choice --tool-call-parser hermes`（按实际 vLLM 版本/模板调整）。
若该解析器在你的部署里不稳定（tool_calls 偶发解析失败），**再**实现 `react` 兜底；
否则**本期可不写 react**，节省一半适配代码。`chat()` 内部把两种模式归一成同一 `tool_calls` 结构，
loop 不感知差异，后补 react 不影响 loop。

新增方法（在 `LLMClient` 内，复用现有 `_call` 的 HTTP 逻辑）：

```python
def chat(self, messages: list[dict], tools: list[dict] | None = None
         ) -> ChatResult:
    """
    返回 ChatResult(text, tool_calls, raw, success, error, elapsed_ms)。
    - tool_mode=native：payload 带 "tools"/"tool_choice":"auto"，解析 choices[0].message.tool_calls
    - tool_mode=react：把工具说明拼进 system，要求模型输出
        最终回答 或 一个 JSON：{"action":"run_sql","args":{...}}
        由 _parse_react_action() 解析为 tool_calls
    """
```

- 复用既有 provider 选择（primary=内网优先，external_allowed 控制外发）。
- `ChatResult.tool_calls = [{id, name, arguments(dict)}]`，两种模式归一成同一结构，**loop 不感知模式差异**。
- 记录 `_last_latency_ms` / `_cached_status`（顺便满足后续 `/api/health`）。

---

## 3. 新增 `tools/profiler.py` —— 让 Agent 自己读懂数据

```python
def profile_table(conn, table_name: str, columns: list[str] | None = None) -> dict:
    """
    只读剖析。返回：
      {
        "table": name, "row_count": int,
        "columns": [
           {"name","dtype","null_rate",
            "samples": [去重样本最多5个],   # 文本列才给
            "min","max"}                    # 数值/日期列才给
        ],
        "field_map": {语义名: 实际列名}      # 来自 _loaded_tables[name].field_map（若有字典）
      }
    """
```

- 全部用 `SELECT ... LIMIT` + `information_schema`，不读原始文件。
- 文本列样本要**脱敏到量级/占位**？——不需要，profiler 结果只回流给**本地 loop 的下一轮 LLM**；若 primary 是外网且 external_allowed=true，则 §6 的安全说明生效。
- 配套单测 `tests/test_profiler.py`：未知表、空值率、样本去重。

---

## 4. `run_calculator` 接入（让 B 类价值真正跑起来）

当前 loop 对固化类直接拒绝，必须改为真正调用。映射示例（**以真实签名为准**）：

```python
def _run_calculator(args, ctx) -> ToolResult:
    cfg = ctx.calculation_config            # config.yaml -> calculation_config
    conn = get_connection()
    if args["calculator"] == "entity_concentration":
        c = cfg["concentration"]
        em = EntityManager()
        results = calc_entity_concentration(
            conn,
            holding_table = args["holding_table"],
            market_value_field = c["market_value_field"],   # ★口径来自config，非LLM
            threshold_pct = c["threshold_entity"],
            use_group_merge = c["use_group_merge"],
            group_mapping = em.get_group_mapping(),
            entity_alias = load_entity_alias(),              # data_dictionary/entity_alias.yaml
            product_filter = args.get("product_filter"),
        )
        # 命中超标 → 强制 request_confirmation 路径 + compliance_audit
        ...
```

- 计算完成后，**B 类必须**：①走 `request_confirmation` 让用户确认口径；②确认后调用 `compliance_audit.log_compliance_event(...)`（数据指纹/公式/阈值/确认人）。
- `holding_table` 未给时，从 `get_loaded_tables()` 里挑 `type==holding` 的最新一张，并在文本里说明用了哪张。

---

## 5. 暂停/续跑：`ask_user` 与 `request_confirmation`

现状 `/api/chat` 每次请求**无状态重建**，`_session` 只存 `turn_count`。要支持多轮 + 暂停续跑，需要服务端会话消息存储。

**最小实现**：在 `_session` 中增加 `messages: list[dict]` 与 `pending: dict|None`。
- 普通对话：把本轮 user/assistant/tool 消息追加进 `_session["messages"]`，下次请求带上 → 实现真多轮记忆。
- `ask_user`：loop `yield` 一个 chunk `{"type":"ask","data":{question,options}}`，然后 `yield stream_end` 并把当前 `messages` 存入 `_session["pending"]`。前端把用户的选择作为新一条 `/api/chat` 消息发回；loop 检测到 `pending` 存在则把用户回答作为 tool/user 结果续跑。
- `request_confirmation`：`yield {"type":"confirm","data":{...}}` + `stream_end`，前端 `/api/confirm`（新增路由，POST {confirmed}）写回 `_session["pending"]`，续跑生成报告或取消。

> 若想降低改造面，过渡期可把 `ask_user` 退化为：在文本里抛出选择题 + `stream_end`，用户下一条消息即视为回答（loop 靠 `_session["messages"]` 自然衔接）。`request_confirmation` 同理先用文本+表格+"回复 确认/取消"。**但 `_session["messages"]` 多轮存储是硬要求，必须做。**

---

## 6. 系统提示词改写（`prompts/system_prompt.txt`）

新增行为准则（要点）：
1. 不确定字段/口径时，**先 `profile_table` 或 `ask_user`，禁止猜**。
2. **绝不编造数字**，所有数值来自工具结果。
3. 合规/报告（集中度、净值、资产结构、评级分布、运作报告、参谈要点）**必须 `run_calculator`**，**禁止 `run_sql`** 出合规数字。
4. 回答时**显式说明你的字段假设**（"我把'市值'理解为'资产市值_穿透后'，如不对请指正"）。
5. 一次只问一个最关键的澄清问题；能自己剖析的不要问用户。
6. 外发安全：若 `external_allowed=false`，不得调用外部端点（由 client 保证），提示词里也声明不得在 SQL/问题中拼接真实数值。

---

## 7. SSE chunk 兼容与新增

保留：`text` `tool_start` `tool_end` `table` `chart` `error` `stream_end`。
新增（R3 的 UI 会渲染；R1 阶段前端可暂时降级为文本）：
- `{"type":"thinking","data":"..."}`（模型思考/计划，折叠显示）
- `{"type":"ask","data":{"question","options"}}`
- `{"type":"confirm","data":{"title","summary","sql_or_formula"}}`

`tool_start/tool_end` 的 `data` 增加 `id`，便于前端配对（现有前端已用 `data.id`）。

---

## 8. 验收（写进 `tests/test_agent.py` + 手动演练）

**自动化（mock LLM 的 tool_calls 序列）**：
- `test_loop_multistep_runs_tools()`：mock 返回 profile_table→run_sql→最终回答，断言三段事件顺序正确。
- `test_loop_calculator_path()`：mock 返回 run_calculator(entity_concentration)，断言走了 calculators 且产生 confirm 事件、写了 compliance_audit（mock）。
- `test_loop_ask_user_pause_resume()`：mock 返回 ask_user → 断言产生 ask + stream_end 且 `_session["pending"]` 被设置；再发一条消息断言续跑。
- `test_no_llm_sql_for_compliance()`：断言 run_calculator 路径中没有任何 LLM 生成的 SQL 进入 query_runner。
- `test_multiturn_memory()`：两条连续消息，断言第二条 messages 带上了第一条上下文。

**手动端到端**（配 `config.yaml` 指向可用 LLM）：
1. 上传持仓 → 问"象屿系集中度有没有超标" → Agent 应：识别集团成员 → run_calculator → confirm 卡片 → 确认后给结论（全程无 LLM 生成合规 SQL）。
2. 上传一张**没有字典**的表 → 问一个含糊问题 → Agent 应先 `profile_table` 或 `ask_user`，而不是直接报错或瞎猜。
3. 连续追问"那再看 B 产品" → Agent 复用上下文，不要求重新说明。

**回归**：原有 57+72 单测全绿；内存仍 < 200MB。

---

## 9. 交付物清单

- [ ] `agent/tools_spec.py`（工具定义+分发）
- [ ] `agent/llm_client.py` 新增 `chat()` + `ChatResult`（native 模式；react 兜底**可后置**）
- [ ] `tools/profiler.py` + `tests/test_profiler.py`
- [ ] `agent/loop.py` 重写为 tool-calling 循环（保留旧函数名 `run_agent_loop` 签名兼容 `main.py`，内部改实现）
- [ ] `_session` 增加 `messages`/`pending`；`main.py` 增加 `/api/confirm` 路由
- [ ] `prompts/system_prompt.txt` 改写
- [ ] `config.yaml` / `config.example.yaml` 增加 `llm.sql_gen.tool_mode`
- [ ] `tests/test_agent.py` 新增 5 项；全测试绿
- [ ] 更新 `docs/refactor/PROGRESS-refactor.md`
