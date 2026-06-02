# DataAgent 开发快速启动指南 v1.1

> 给 Claude Code 的操作手册：从零到 Phase 1 验收。
> 本文档已融入 GG 架构审查改进意见（随机端口、DuckDB内存限制、动态SQLGuard、ECharts钩子）。

---

## 环境准备（Day 1，执行一次）

```bash
# 1. 创建项目目录
mkdir DataAgent && cd DataAgent

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate        # Windows

# 3. 安装依赖
pip install pywebview flask flask-cors duckdb pandas chardet \
            pyyaml jinja2 python-docx requests pyinstaller

# 4. 验证关键依赖
python -c "
import webview; print('pywebview OK')
import duckdb; print('duckdb OK')
import pandas; print('pandas OK')
import chardet; print('chardet OK')
import flask; print('flask OK')
import socket
with socket.socket() as s:
    s.bind(('',0)); print(f'random port test OK: {s.getsockname()[1]}')
"

# 5. 生成 requirements.txt
pip freeze > requirements.txt
```

---

## Phase 1 开发顺序（Day 2-5）

### Step 1：main.py（随机端口启动验证）

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第十章的规格，创建 main.py。

要求：
1. 用 find_free_port() 获取随机空闲端口（不得硬编码5000）
2. 在后台线程启动 Flask 服务
3. 等待 0.5 秒确保 Flask 就绪
4. 创建 PyWebView 窗口加载 http://127.0.0.1:{port}
5. 窗口标题 'DataAgent'，大小 1280×800
6. Flask 只注册一个测试路由 GET / 返回 "DataAgent Running"
```

**验证**：运行 `python main.py`，弹出窗口显示"DataAgent Running"，
控制台输出类似 `Flask running on port 54321`（每次不同）。

---

### Step 2：ui/index.html（基础聊天界面）

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第九章 UI 规格，创建 ui/index.html。

布局要求：
- 左侧边栏 190px（已加载数据区、集团系区、Skills区，各带图标）
- 右侧主聊天区（消息列表 + 工具执行卡片区 + 快捷按钮行 + 输入框）
- 底部状态栏（LLM状态 + 上下文使用率 + 内存 + 对话轮数）
- Tailwind CSS CDN 引入（不使用构建工具）
- Enter 发送，Shift+Enter 换行
- 支持文件拖拽到聊天区（触发上传，暂不实现后端，只显示文件名）

★ 必须实现 ECharts 后置渲染机制（CLAUDE.md 第九章 9.2节）：
- 定义全局 pendingCharts 数组
- renderStreamChunk(chunk) 函数：text直接显示，chart加入队列
- stream_end 事件触发时统一 echarts.init() 所有待渲染图表

暂时不连接后端，所有操作打 console.log 即可。
```

---

### Step 3：tools/data_loader.py

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第七章 7.1节 和 docs/data-schemas.md，
创建 tools/data_loader.py。

★ 必须包含以下关键实现：

1. init_duckdb_connection() 函数：
   conn = duckdb.connect(':memory:')
   conn.execute("SET max_memory='80MB'")   # 必须，GG审查要求
   conn.execute("SET threads=2")            # 必须，GG审查要求
   return conn
   （全局调用一次，后续所有工具复用此连接）

2. load_file(file_path, table_name, date_tag=None) 函数：
   - chardet 自动检测编码（禁止硬编码 utf-8 或 gbk）
   - 处理千分位逗号数值字段
   - 清洗列名（去首尾空格）
   - 注册到 DuckDB 内存表
   - 返回 LoadResult dataclass

3. get_loaded_tables() 函数：
   返回已加载的所有表名、行数、列数列表
   （用于侧边栏展示和 SQLGuard 动态校验）

同时在 tests/test_tools.py 创建测试：
- test_init_duckdb_memory_limit()：验证内存限制生效
- test_load_csv_auto_encoding()：测试 GB18030 文件加载
- test_load_csv_with_thousands()：测试千分位数值处理
```

**验证**：
```python
from tools.data_loader import init_duckdb_connection, load_file
conn = init_duckdb_connection()
# 验证内存设置
result = conn.execute("SELECT current_setting('max_memory')").fetchone()
print(result)  # 应显示 80MB 相关内容
```

---

### Step 4：tools/query_runner.py（动态SQLGuard）

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第七章 7.2节，创建 tools/query_runner.py。

★ SQLGuard 必须使用动态元数据白名单（GG审查改进）：

class SQLGuard:
    def validate(self, sql: str, conn) -> tuple[bool, str]:
        # 规则1：只允许 SELECT
        # 规则2：必须含 LIMIT，且 <= 10000
        # 规则3：★动态表名校验（核心改进）
        #   valid_tables = conn.execute("SHOW TABLES").df()['name'].tolist()
        #   用正则提取 SQL 中 FROM/JOIN 后的表名
        #   检查是否都在 valid_tables 中
        #   （支持 holding_20260515 等带日期后缀的动态表名）
        # 规则4：禁止 information_schema 等系统表
        # 规则5：执行超时 30 秒

返回 QueryResult：
  success, data, columns, row_count, sql, requires_confirmation=True

在 tests/test_tools.py 增加测试：
- test_guard_blocks_delete()
- test_guard_requires_limit()  
- test_guard_dynamic_table_unknown()：访问未加载的表应被拒绝
- test_guard_dynamic_table_with_date_suffix()：holding_20260515 应通过
```

---

### Step 5：agent/llm_client.py

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第八章，创建 agent/llm_client.py。

要求：
1. 读取 config.yaml 中的 llm 配置
2. stream() 方法：调用 LLM 返回流式 SSE 响应
3. 支持 code_gen / report_text / fallback 三个端点
4. Fallback 逻辑：code_gen 超时或 5xx 错误时，自动切换到 fallback
5. 超时：code_gen 30秒，report_text 60秒
6. 所有异常有明确错误信息（禁止空 except）

LLM 调用遵守数据隔离规则（CLAUDE.md 8.2节）：
- code_gen 端点：只允许传 Schema + 用户问题，不传数据行
- report_text 端点：可传精确数值，不传完整明细
```

---

### Step 6：agent/skill_loader.py

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第五章，创建 agent/skill_loader.py。

要求：
1. 支持多 Skills 目录（来自 config.yaml 的 local_dir + shared_dir）
2. load_registry()：仅加载所有 SKILL.md 的 name + description（渐进式披露）
3. load_full(skill_name)：按需加载完整 SKILL.md 内容
4. detect_relevant_skill(user_message, registry)：
   基于关键词匹配判断当前任务相关的 Skill
   （简单实现：检查用户消息中是否含 Skill description 的触发词）
5. 解析 SKILL.md 的 YAML frontmatter（name, description字段）
```

---

### Step 7：agent/loop.py（最简版）

**给 Claude Code 的指令**：
```
根据 CLAUDE.md 第六章，创建 agent/loop.py 的 Phase 1 最简版。

本阶段实现：
1. 主循环：最多 15 轮
2. 工具分发：仅支持 run_sql 工具
3. Reflection：工具失败时将错误信息返回 LLM，触发自愈重试
4. 通过 Flask SSE 推送 LLM 流式文字和工具结果到前端
5. stream_end 事件：通知前端所有内容已推送完毕（触发ECharts渲染）

暂不实现：Skill加载、Token压缩、人工确认节点（Phase 2 加）

SSE 消息格式：
  {"type": "text", "data": "..."}          # 流式文字
  {"type": "table", "data": {...}}         # 表格数据
  {"type": "tool_start", "data": "..."}   # 工具开始
  {"type": "tool_end", "data": {...}}      # 工具结束
  {"type": "stream_end"}                   # 全部结束（触发ECharts）
  {"type": "error", "data": "..."}        # 错误信息
```

---

### Step 8：连通前后端，Phase 1 验收

**给 Claude Code 的指令**：
```
修改 ui/index.html 和 Flask 路由，完成前后端联通：

后端新增：
1. POST /api/chat：接收用户消息，启动 agent_loop，返回 SSE 流
2. POST /api/upload：接收文件上传，调用 data_loader.load_file()
3. GET /api/tables：返回已加载的表列表（供侧边栏展示）

前端修改：
1. 发送按钮：调用 /api/chat，消费 SSE 流，调用 renderStreamChunk()
2. 文件拖拽：调用 /api/upload，成功后刷新侧边栏数据列表
3. 侧边栏：启动时调用 /api/tables 渲染已加载数据列表
```

**Phase 1 验收步骤**：
```
1. python main.py → 窗口弹出，状态栏显示 DeepSeek 状态
2. 拖拽 "持仓产品管理-2026-05-15.csv" 到聊天区
   → 侧边栏出现 "持仓_20260515 · 283行"
3. 输入 "查询XX产品持有哪些债券，按市值排序"
   → Agent 生成 SQL（可在工具卡片展开查看）
   → 动态SQLGuard 校验通过（表名存在于已加载表中）
   → DuckDB 执行，返回表格结果
   → 用户看到数据表格
4. 检查内存：状态栏显示 < 150MB
```

---

## config.yaml 初始模板

将此内容保存为项目根目录的 `config.yaml`：

```yaml
llm:
  code_gen:
    provider: deepseek
    url: https://api.deepseek.com/v1
    model: deepseek-chat
    api_key: ""          # 填入 DeepSeek API Key
    timeout: 30
    max_tokens: 2000

  report_text:
    provider: enterprise
    url: http://localhost:8080/v1    # 填入企业内网 LLM 地址
    model: ""
    api_key: ""
    timeout: 60
    max_tokens: 3000

  fallback:
    provider: qwen
    url: https://dashscope.aliyuncs.com/compatible-mode/v1
    model: qwen3-32b
    api_key: ""          # 填入阿里云 DashScope API Key
    timeout: 30

app:
  window_title: DataAgent
  window_width: 1280
  window_height: 800
  debug: false
  max_agent_turns: 15
  max_tool_retry: 3
  context_budget_ratio: 0.75

skills:
  local_dir: skills/
  shared_dir: ""         # 可填内网共享目录，如 \\fileserver\DataAgent\skills
```

---

## 常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| PyWebView 显示空白 | Flask 未就绪 | 增加 time.sleep(1) 延迟 |
| CSV 加载中文乱码 | chardet 检测不准 | `print(chardet.detect(open(f,'rb').read()))` 查看 |
| DuckDB SQL 报"列不存在" | 列名含特殊字符 | 用双引号包裹列名 |
| SQLGuard 拒绝合法表名 | 表未加载 | 先调用 load_file 再查询 |
| ECharts 不显示 | DOM 未就绪 | 检查 stream_end 事件是否触发 |
| LLM 连接超时 | API Key 未配置 | 检查 config.yaml |
| 内存超过 200MB | DuckDB 未限制 | 确认 init_duckdb_connection() 含内存设置 |

---

## 未来路线图（当前阶段不实现）

以下是 GG 建议中认可但暂缓实现的功能，记录在此供后续参考：

- **Meta-Agent Skill生成器**：对话式引导业务人员生成 SKILL.md，无需手写SQL
- **Session-to-Skill宏录制**：将成功对话一键固化为新技能
- **低代码Skill脚手架表单**：可视化填空表单生成 Skill 配置
- **YAML公式契约**：在 Skill frontmatter 中定义强绑定计算公式

待用户规模扩大（>20个Skill，>10个非技术用户创建Skill）后启动。
