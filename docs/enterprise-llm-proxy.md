# DataAgent v3.4 内网 LLM Proxy 链路说明

> 版本：v3.4 ｜ 适用配置：`config.yaml` 中 `enterprise_internal.gateway.enabled: true`

---

## 一、架构总览

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  浏览器   │────▶│  DataAgent   │────▶│  gateway     │────▶│  企业网关     │
│  (前端)   │◀────│  main.py     │◀────│  _proxy.py   │◀────│  11.146...   │
└──────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                       │                127.0.0.1:8081      企业内网:8080
                       │
                  llm_client.py
                  认为在访问标准
                  OpenAI API
```

**核心设计**：`gateway_proxy.py` 是本地的透明代理，DataAgent 始终以为自己在和 `127.0.0.1:8081/v1` 上的标准 OpenAI API 对话，完全不感知企业网关的 `txHeader/txBody` 包装格式。

---

## 二、配置示例

```yaml
# config.yaml
llm:
  sql_gen:
    primary: enterprise_internal
    tool_mode: native                 # native=OpenAI function-calling; react=纯文本兜底
    external_allowed: false

  enterprise_internal:
    url: http://127.0.0.1:8081/v1     # 指向本地代理，勿改
    model: qwen332b
    api_key: "123"                     # 代理统一鉴权，任意非空值即可
    auth_type: none                    # 不发 Authorization 头，代理配置了 APP_CODE

    gateway:
      enabled: true                    # 启动时自动拉起代理
      proxy_port: 8081                 # 代理监听端口，与上面 url 端口一致
      gateway_url: http://11.146.96.49:8080  # 企业内网网关实际地址
```

### 配置项说明

| 配置 | 说明 |
|------|------|
| `url` | 必须指向 `127.0.0.1:{proxy_port}/v1`，DataAgent 发送请求到本地代理 |
| `auth_type: none` | 代理已通过 APP_CODE 统一鉴权，DataAgent 不传 Authorization |
| `gateway.enabled` | `true` 时 `main.py` 启动后自动拉起代理后台线程 |
| `gateway.gateway_url` | 企业内网网关真实地址，代理会将请求转发到此 |
| `gateway.proxy_port` | 代理本地监听端口，需与 `url` 中端口一致 |

---

## 三、启动流程

```
双击 run.bat 或 DataAgent.exe
  │
  ├─ 1. 读取 config.yaml
  ├─ 2. 检测 gateway.enabled = true
  ├─ 3. from gateway_proxy import start_proxy_background
  ├─ 4. start_proxy_background(gateway_cfg, runtime_logger=logger)
  │      │
  │      ├─ 检查 127.0.0.1:8081 是否被占用 → 占用则复用
  │      ├─ 创建 Flask 应用（create_proxy_app）
  │      ├─ 启动 daemon 线程监听 127.0.0.1:8081
  │      └─ 写入运行时日志：网关代理启动 {port, gateway_url}
  │
  ├─ 5. Flask 主应用启动
  └─ 6. PyWebView 窗口打开（或浏览器模式）
```

### `gateway_proxy.py` 提供的端点

| 路由 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查，返回 `{"status":"ok","gateway":"..."}` |
| `/v1/models` | GET | 直接返回空列表（不转发），满足测试连通性 |
| `/v1/chat/completions` | POST | 核心端点：转发到企业网关，支持流式/非流式 |
| `/v1/completions` | POST | 文本补全（转发） |
| `/v1/embeddings` | POST | 向量嵌入（转发） |
| `/v1/rerank` | POST | 重排序（转发） |

---

## 四、场景一：测试连接

### 触发方式

设置页面 → 点击 LLM 配置旁的「测试连接」按钮

### 调用链路

```
前端 POST /api/llm/test
  │
  ▼
llm_client.test_connection("enterprise_internal")
  │
  ├── ① GET http://127.0.0.1:8081/v1/models
  │      │
  │      ▼ gateway_proxy
  │        → 收到 GET /v1/models
  │        → 直接返回 {"data":[], "object":"list"}（代理伪造，不转发）
  │        ← 200 OK
  │
  ├── ② POST http://127.0.0.1:8081/v1/chat/completions
  │      │  Body: {"model":"qwen332b","messages":[{"role":"user","content":"test"}],
  │      │         "max_tokens":5, "stream":false}
  │      │
  │      ▼ gateway_proxy (127.0.0.1:8081)
  │        │
  │        │  ┌─────────────────────────────────────┐
  │        │  │ 包装为企业网关格式                    │
  │        │  │ {                                   │
  │        │  │   "txHeader": {                     │
  │        │  │     "servNo": "390201",             │
  │        │  │     "globalBusiTrackNo": "...",     │
  │        │  │     "txStartTime": "20260702...",   │
  │        │  │     ...                             │
  │        │  │   },                                │
  │        │  │   "txBody": {                       │
  │        │  │     "txComin": "",                  │
  │        │  │     "txEntity": {原始 OpenAI 请求}    │
  │        │  │   }                                 │
  │        │  │ }                                   │
  │        │  └─────────────────────────────────────┘
  │        │
  │        → POST http://11.146.96.49:8080/ai
  │        ← 企业网关返回:
  │          {
  │            "txHeader": {...},
  │            "txBody": {"txEntity": {"choices":[...], "usage":{...}}}
  │          }
  │        │
  │        │  ┌─────────────────────────────────────┐
  │        │  │ 剥离网关外层                          │
  │        │  │ _from_gateway_format() 取 txEntity   │
  │        │  └─────────────────────────────────────┘
  │        │
  │        ← 200 OK {"choices":[...], "usage":{...}}
  │
  ▼
前端：「连接成功」或「连接失败 + 错误信息」
```

### 链路要点

| 项目 | 值 |
|------|-----|
| 流式 | 否（stream=false） |
| 携带 tools | 否 |
| LLM 调用次数 | 1 次 |
| 代理格式转换 | 请求 1 次 + 响应 1 次 |

---

## 五、场景二：会话功能

### 触发方式

用户在对话框输入任意分析需求，如「检查集中度」「生成运作报告」

### 调用链路

```
前端 POST /api/chat  {message: "检查集中度"}
  │
  ▼
run_agent_loop(user_message, llm_client, skill_loader, ...)
  │
  │  ┌─────────────────────────────────────────────┐
  │  │         Tool-calling 循环（MAX_TURNS=25）     │
  │  │                                             │
  │  ├─ Turn 0: LLM 理解问题 + 决策                  │
  │  │   llm_client.chat(messages, tools=[7个工具])  │
  │  │     │                                       │
  │  │     ▼ POST http://127.0.0.1:8081/v1/chat/completions
  │  │       {                                     │
  │  │         "model": "qwen332b",                │
  │  │         "messages": [                       │
  │  │           {"role":"system","content":"你是.."},│
  │  │           {"role":"user","content":"检查.."}  │
  │  │         ],                                  │
  │  │         "tools": [                          │
  │  │           profile_table, run_sql,           │
  │  │           run_calculator, ask_user,         │
  │  │           request_confirmation,             │
  │  │           generate_chart, render_report     │
  │  │         ],                                  │
  │  │         "stream": true                      │
  │  │       }                                     │
  │  │       │                                     │
  │  │       ▼ gateway_proxy                       │
  │  │         → 包装 txHeader/txBody              │
  │  │         → POST http://11.146.96.49:8080/ai │
  │  │         ← SSE 流式返回                        │
  │  │         → _parse_stream_line() 逐行剥离包装    │
  │  │         ← SSE data: {"choices":[...]}       │
  │  │       │                                     │
  │  │       ▼ LLM 返回 tool_calls:                │
  │  │         [{name:"run_calculator", args:{...}}]│
  │  │                                             │
  │  ├─ Turn 1: 执行工具                             │
  │  │   dispatch_tool("run_calculator", args, ctx) │
  │  │   → 本地 DuckDB 计算集中度                     │
  │  │   → 结果写入 messages（不经过 LLM）            │
  │  │                                             │
  │  ├─ Turn 2: LLM 解读结果 + 回答                   │
  │  │   llm_client.chat(messages + tool_result, ...)│
  │  │     ▼ 同上链路：代理 → 企业网关 → Qwen        │
  │  │     ▼ LLM 流式输出最终回答                     │
  │  │                                             │
  │  └─ ... 最多 25 轮 ...                          │
  │                                                 │
  └─────────────────────────────────────────────────┘
  │
  ▼
前端 SSE 流式展示 Agent 回答 + 表格/图表
```

### 链路要点

| 项目 | 值 |
|------|-----|
| 流式 | 是（stream=true），逐字返回 |
| 携带 tools | 是，每次 LLM 调用携带 7 个工具定义 |
| LLM 调用次数 | 每轮 tool-calling 1 次，最多 25 轮 |
| 代理格式转换 | 每轮请求 1 次 + 响应流中每行 SSE 1 次 |
| 数据不出内网 | 工具执行（DuckDB SQL / calculators）完全本地，不经过 LLM |
| 合规场景 | `run_calculator` 直接调本地函数，零 LLM 参与 |

---

## 六、代理数据转换格式

### 请求包装（OpenAI → 企业网关）

```
OpenAI 请求                         企业网关请求
{                                   {
  "model": "qwen332b",       →        "txHeader": {
  "messages": [...],                   "servNo": "390201",
  "tools": [...],                      "globalBusiTrackNo": "...",
  "stream": true                       "txStartTime": "...",
}                                      ...
                                      },
                                      "txBody": {
                                        "txComin": "",
                                        "txEntity": {
                                          "model": "qwen332b",
                                          "messages": [...],
                                          "tools": [...],
                                          "stream": true
                                        }
                                      }
                                    }
```

### 响应解包（企业网关 → OpenAI）

```
企业网关 SSE 行                      代理输出 SSE 行
data: {                             data: {
  "txHeader": {                       "choices": [{
    "messageType": "data"               "delta": {
  },                                      "content": "好的"
  "txBody": {                           }
    "txEntity": {                    }]
      "choices": [{                 }
        "delta": {
          "content": "好的"
        }
      }]
    }
  }
}
```

### 心跳过滤

企业网关定期发心跳保活，代理自动过滤不传给客户端：

```
企业网关: data: {"txHeader":{"messageType":"heartbeat"},...}
代理:     (丢弃，不输出)
```

---

## 七、双模式支持

`tool_mode` 控制 LLM 调用方式：

| mode | 说明 | 适用场景 |
|------|------|---------|
| `native` | 标准 OpenAI function-calling（发送 tools 数组） | 企业 LLM 支持 tools API |
| `react` | 纯文本协议兜底（工具说明拼入 system prompt，LLM 返回 JSON） | 企业 LLM 不支持 function-calling |

当 `tool_mode: native` 但企业 LLM 返回 `tool_calls: null` 时，`llm_client.py` 会安全降级为空列表，不会崩溃。

---

## 八、代理日志

启用代理后，`data/logs/dataagent_YYYYMMDD.jsonl` 中会出现以下日志：

```json
{"level": "INFO", "category": "gateway_proxy", "event": "网关代理启动",
 "detail": {"port": 8081, "gateway_url": "http://11.146.96.49:8080"}}

{"level": "INFO", "category": "gateway_proxy", "event": "代理转发请求",
 "detail": {"endpoint": "chat", "model": "qwen332b", "stream": true, "message_count": 5}}

{"level": "DEBUG", "category": "gateway_proxy", "event": "网关返回成功",
 "detail": {"status_code": 200, "response_size": 4521}}

{"level": "ERROR", "category": "gateway_proxy", "event": "网关返回错误",
 "detail": {"status_code": 500, "response_preview": "Internal Server Error"}}

{"level": "WARNING", "category": "gateway_proxy", "event": "端口占用跳过启动",
 "detail": {"port": 8081, "reason": "port already in use"}}
```

---

## 九、排查指引

| 问题 | 检查方法 |
|------|---------|
| 代理启动失败 | 查看启动日志 `网关代理启动`；检查 8081 端口是否被占用 |
| 代理启动后 LLM 无响应 | 检查 `gateway_url` 是否可达：`telnet 11.146.96.49 8080` |
| Token 超限 | 企业 Qwen 上下文窗口 32K，单轮 tool-calling messages 可能超限，查看日志中 `message_count` |
| tools 返回 null 崩溃 | v3.4 已修复：`tool_calls is None → []` |
| 流式响应中断 | 查看 `网关返回错误` 日志；企业网关可能有超时限制 |
| 代理日志级别 | `basic` 模式仅记录 ERROR/WARNING；`detailed` 模式记录全部请求详情 |
