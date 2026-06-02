# DataAgent 开发环境指南

---

## 两套环境，一套代码

```
Linux（Claude Code）                 Windows 11（生产目标）
─────────────────                    ─────────────────────
✅ 业务逻辑开发测试                   ✅ 最终运行环境
✅ Flask 后端                         ✅ Flask 后端（同代码）
✅ Agent Loop                        ✅ Agent Loop（同代码）
✅ DuckDB 数据引擎                   ✅ DuckDB 数据引擎（同代码）
✅ calculators/ 固化计算             ✅ calculators/（同代码）
✅ data_dictionary/ 字典映射          ✅ data_dictionary/（同代码）
✅ Skills 系统                       ✅ Skills 系统（同代码）
✅ LLM 调用（DeepSeek/内网）         ✅ LLM 调用（同代码）
✅ 浏览器访问 UI（Chrome/Firefox）    ✅ PyWebView 原生窗口
✅ 终端/notify-send 通知              ✅ Windows toast 通知
❌ PyWebView 窗口                    ✅ PyWebView 窗口
❌ winotify toast                    ✅ winotify toast
❌ PyInstaller .exe 打包             ✅ PyInstaller .exe 打包
❌ WebView2 内存测试                 ✅ WebView2 内存测试
```

**结论：除 UI 窗口形态不同，所有业务逻辑完全一致，Linux 开发 = Windows 运行。**

---

## Linux 环境安装

```bash
# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装开发依赖（不含 Windows 专属库）
pip install -r requirements-dev.txt

# 3. 验证
python -c "
import duckdb; print('✅ duckdb')
import pandas; print('✅ pandas')
import flask; print('✅ flask')
import chardet; print('✅ chardet')
import sqlglot; print('✅ sqlglot')
import schedule; print('✅ schedule')
"
```

## 启动（Linux 开发模式）

```bash
# 方式1：自动检测（Linux 上自动走浏览器模式）
python main.py

# 方式2：显式指定开发模式
DATAAGENT_ENV=dev python main.py

# 启动后：自动打开系统浏览器访问 http://127.0.0.1:{随机端口}
# 关闭：Ctrl+C
```

---

## 平台适配层说明

所有平台差异被封装在 `platform_adapter/` 目录中：

| 文件 | 作用 | Linux行为 | Windows行为 |
|------|------|----------|------------|
| `platform_adapter/ui_driver.py` | 窗口驱动 | 打开系统浏览器 | PyWebView 原生窗口 |
| `platform_adapter/notify_driver.py` | 通知推送 | 终端打印/notify-send | Windows toast 弹窗 |

**业务代码的使用方式（不感知平台）**：

```python
# tools/notify.py 中
from platform_adapter.notify_driver import get_notify_driver

notify = get_notify_driver()  # 自动选择合适的驱动
notify.push("⚠️ 集中度超标：XX产品", level="warning")
# Linux：终端打印醒目提示
# Windows：右下角 toast 弹窗
```

---

## Linux 环境无法测试的项目（必须等 Windows）

以下 3 项必须在 Windows 上验证，记录在 Phase 5：

| 项目 | 验证时机 | 验证内容 |
|------|---------|---------|
| WebView2 内存占用 | Phase 5 Day 22 | Python进程 + WebView2进程树，记录到 docs/memory_baseline.md |
| Windows toast 通知 | Phase 5 Day 22 | winotify 是否正常弹出，超标提醒格式是否正确 |
| PyInstaller 打包 | Phase 5 Day 23-24 | 单目录绿色版，检查 WebView2 Runtime 是否需要随包 |

---

## Phase 1-4 在 Linux 的完整测试策略

Linux 开发期间，所有测试通过以下方式覆盖：

**1. 业务逻辑：单元测试（pytest）**
```bash
# 运行所有测试
pytest tests/ -v

# 运行固化计算测试
pytest tests/test_calculators.py -v

# 运行工具层测试（含数据加载、SQLGuard等）
pytest tests/test_tools.py -v
```

**2. 交互流程：浏览器 + Flask**
```bash
python main.py
# 在浏览器中完整测试对话流程、数据上传、图表渲染等
# 体验与 Windows PyWebView 完全一致，仅窗口形态不同
```

**3. 定时任务：手动触发测试**
```bash
# 在浏览器界面使用 /run 命令手动触发定时任务
# 或在 Python 控制台直接调用
from scheduler.task_manager import TaskManager
# 手动触发 + 观察终端通知输出
```

**4. LLM 调用：真实 API 测试**
```bash
# 配置 config.yaml 中的 DeepSeek API Key
# 在浏览器中测试自然语言查询，验证 SQL 生成和执行
```

---

## 文件上传在浏览器模式的说明

浏览器安全限制不允许直接拖拽文件到页面（与 PyWebView 行为不同）。
开发期间的替代方式：

**方式1（推荐）**：使用文件选择按钮（已在 UI 中实现）

**方式2**：直接通过 API 上传
```bash
curl -X POST http://127.0.0.1:{port}/api/upload \
  -F "file=@持仓产品管理-2026-05-15.csv" \
  -F "table_type=holding"
```

**方式3**：在 config.yaml 中配置预加载文件（开发专用）
```yaml
# 仅开发模式生效，生产环境忽略
dev_preload:
  - path: "data/uploads/holding/持仓_20260515.csv"
    table_type: holding
    date_tag: "20260515"
```

---

## Windows 部署流程（Phase 5）

Phase 1-4 全部在 Linux 上开发测试完毕后，切换到 Windows 执行：

```powershell
# 1. 克隆/拷贝代码到 Windows
# 2. 安装生产依赖
pip install -r requirements-prod.txt

# 3. 验证 Windows 专属功能
python main.py
# 确认：PyWebView 原生窗口弹出，非浏览器
# 确认：toast 通知正常（运行 /health 命令触发测试通知）

# 4. 记录内存基线
# 打开任务管理器，记录 python.exe + WebView2 进程内存
# 写入 docs/memory_baseline.md

# 5. PyInstaller 打包
pyinstaller DataAgent.spec
# 测试打包后的 dist/DataAgent/ 目录
```
