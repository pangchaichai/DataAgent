# DataAgent 开发交接文档 v2.3

> 适用环境：Linux Claude Code，分支 `claude/gracious-dijkstra-3msWc`
> 上次修改时间：2026-06-04

---

## 一、本轮改动概述

本轮对 8 个文件进行了改动，主要目标：
1. 完善前端 UI，让所有后端配置项均可通过界面操作
2. 新增 10 个后端 API 路由
3. 修复代码审查发现的全部 P0/P1 级缺陷

**改动文件清单：**

| 文件 | 改动类型 | 关键内容 |
|------|---------|---------|
| `ui/index.html` | 重大增强 | 设置面板、集团 CRUD、表/会话删除按钮、Toast 通知 |
| `main.py` | 重大增强 | 10 条新 API 路由，配置读写锁，安全修复 |
| `tools/data_loader.py` | 小修 | 新增 `drop_table()` 函数；修复 `dict_data` 变量未初始化 |
| `agent/llm_client.py` | 中等修复 | 占位 Key 检测；`classify_intent` 大小写修复；流式 Result 修复 |
| `scheduler/task_manager.py` | 中等修复 | 自身任务表 population；补跑记录机制；配置路径绝对化 |
| `agent/loop.py` | 小修 | 会话暂停/恢复辅助 |
| `platform_adapter/ui_driver.py` | 小修 | `text_select=True` 支持文字选择 |
| `prompts/system_prompt.txt` | 小修 | 优化 Agent 指令 |

---

## 二、新增 API 路由（main.py）

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/config` | GET | 读取配置（API Key 只返回 `api_key_set: bool`） |
| `/api/config` | POST | 写入用户档案、阈值、Memory/Scheduler 开关、DeepSeek Key |
| `/api/groups` | POST | 创建集团系 |
| `/api/groups/<name>/members` | POST | 向集团系添加主体 |
| `/api/groups/<name>/members` | DELETE | 从集团系移除主体（entity 从请求体读取） |
| `/api/groups/<name>` | DELETE | 删除整个集团系 |
| `/api/sessions/<id>` | DELETE | 删除历史会话文件（有路径校验） |
| `/api/tables/<name>` | DELETE | 卸载 DuckDB 数据表 |
| `/api/tasks` | GET | 读取 task_config.yaml 中的任务列表 |
| `/api/memory/clear` | POST | 清空 AgentMemory（未启用时返回 400） |

---

## 三、已修复的缺陷清单

### 安全级（S）

| ID | 文件 | 缺陷描述 | 修复方式 |
|----|------|---------|---------|
| S-1 | main.py | `api_config_write` 无并发保护，竞争写坏 config.yaml | 新增 `_config_file_lock`，读-改-写全程加锁；原子写（写临时文件再 `replace`） |
| S-2 | data_loader.py | `dict_data` 在 `if table_type:` 块内赋值，但块外第 394 行引用，存在 `NameError` | 在块前加 `dict_data = None` |
| S-3 | llm_client.py | 配置占位符 `你的DeepSeek_API_Key` 被当作真实 Key 发送 | 新增 `_PLACEHOLDER_KEYS` 常量，`_call` / `_call_with_messages` / `_call_streaming` 三处均检测并清空 |
| S-4 | main.py + index.html | DELETE member 路由使用 `<path:entity_name>`，存在路径注入风险 | 改为从请求 JSON body 读取 `entity`；前端 `removeMember` 改用 body 传参 |

### 逻辑级（L）

| ID | 文件 | 缺陷描述 | 修复方式 |
|----|------|---------|---------|
| L-3 | llm_client.py | `classify_intent` 将 LLM 返回值转大写后与小写注册名对比，永远匹配失败 | 改为大小写不敏感匹配（`name.lower()` vs `s['name'].lower()`） |
| L-6 | main.py | 保存 DeepSeek API Key 时，同时写入 `report_text` 块，覆盖内网 LLM 配置 | 只写 `deepseek` 块，不动 `report_text` |
| S-6 | llm_client.py | `_call_streaming` 在 generator 消费前就创建 `LLMResponse(success=bool(full_text))`，此时 `full_text==""` → `success=False` | `stream_sql_gen` 消费完 generator 后重新构造含真实 `full_text` 的 `LLMResponse` |

### 中优先级（M）

| ID | 文件 | 缺陷描述 | 修复方式 |
|----|------|---------|---------|
| M-1 | index.html | `loadGroups` 用 `esc(name)`（HTML 编码）作 ID，`addMember` 直接拼 `'addm-'+groupName`（原始字符串），单引号/特殊字符时 ID 不匹配 | 引入 `grpSid(name)` 函数生成纯字母数字+CJK 的安全 ID；用 `_grpMap` 字典保存 sid→realName 映射；member 行用 `data-group`/`data-member` 属性传值 |
| M-2 | index.html | CJK Unicode 范围 `一-鿿`（U+4E00–U+9FFF）漏掉扩展区 | 改用 `㐀-鿿豈-﫿`（覆盖 U+3400–U+9FFF 及兼容汉字区） |
| M-3 | index.html | `clearMemory` 失败时只显示「清空失败」，不展示后端错误信息 | 改为 `toast('清空失败：'+(r.error\|\|''),'error')` |
| M-6 | task_manager.py | `_detect_missed_tasks` 在**检测阶段**就将所有任务标记为今日已执行，导致用户跳过后下次启动不再提示 | 删除检测阶段的预写逻辑；改在任务真正执行成功后（`_execute_task` 末尾）调用新增的 `_record_task_run()` 写日志 |
| M-7 | task_manager.py | `_validate_data_freshness` 用相对路径 `open('config.yaml')` 读配置，CWD 不一致时报错 | 改为基于 `self.config_path` 推导的绝对路径 |

---

## 四、UI v2.3 新增功能

### 设置面板（右侧划出）
- 点击 Header 右上角 ⚙ 打开，Esc 关闭
- **用户档案**：姓名、部门、角色、管理产品（标签输入）
- **LLM 配置**：DeepSeek API Key（写入/更新），显示是否已配置
- **计算口径**：主体集中度阈值、单券阈值
- **记忆功能**：开/关开关，查看记录数，清空按钮
- **定时任务**：开/关调度器，展示当前任务列表

### 集团系 CRUD（侧边栏）
- 新建、展开/折叠、删除集团系
- 添加/移除成员（回车或点击 +）
- 使用 `data-*` 属性传值，安全处理含特殊字符的名称

### 表/会话管理
- 持仓表列表右侧出现 × 删除按钮（Hover 显示），可卸载 DuckDB 表
- 历史会话列表同样支持删除

---

## 五、当前开发阶段状态

```
本次改动已经完成，本次改动注册为Phase R 重构进度（详见PROGRESSrefactor.md）的"Step R5-r - 测试优化 "任务
---

## 六、已知遗留问题（不影响当前功能）

| 问题 | 说明 | 建议处理时机 |
|------|------|------------|
| YAML 注释丢失 | `yaml.dump` 会清除 config.yaml 中的注释 | Phase 5 换用 `ruamel.yaml` 保留注释 |
| M-4 `window.confirm` | WebView2 默认可能屏蔽 `confirm()` 弹窗 | Phase 5 Windows 测试时替换为自定义 Modal |
| M-5 `_execute_with_retry` 命名 | loop.py 中该函数实际不重试，名称误导 | 低优先级重命名 |
| M-8 暂停恢复消息完整性 | 会话暂停时 messages 末尾可能缺少 tool_result，恢复时 API 报错 | Phase 3 加强暂停点逻辑 |

---

## 七、测试策略建议

### 单元测试（现有）
```bash
pytest tests/test_tools.py         # data_loader, query_runner
pytest tests/test_calculators.py   # calculators/ 固化计算（Phase 2 后填充）
pytest tests/test_platform.py      # 平台适配层
```

### 集成测试路径（手动）
1. 上传持仓 CSV → 侧边栏出现表名 → 自然语言查询 → 表格展示
2. 打开设置面板 → 修改阈值 → 保存 → 重新读取配置验证
3. 创建集团系 → 添加成员 → 删除成员 → 删除集团系

### LLM 相关测试注意
- `classify_intent` 修复后，`concentration_monitor` / `dept_weekly_report` 等关键词重叠场景需人工验证路由是否正确
- `stream_sql_gen` 流式 `LLMResponse.success` 现在真实反映流式返回结果，相关后续逻辑需重测

---

## 八、快速启动

```bash
cd /home/user/DataAgent
pip install -r requirements-dev.txt
python main.py
# 浏览器自动打开 http://127.0.0.1:<随机端口>
```

如遇 `config.yaml` 不存在，系统自动回退到 `config.example.yaml`（LLM 连接会失败，但其他功能正常）。
