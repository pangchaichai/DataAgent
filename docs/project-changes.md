# DataAgent 项目变更记录

> 记录项目过程中所有偏离预设设计的调整，以及调整的时间、原因和具体内容。
> 每次出现类似情况时在此文件中追加记录。

---

## #1：`platform/` 目录重命名为 `platform_adapter/`

| 项目 | 内容 |
|------|------|
| **时间** | 2026-06-01（Phase 0 环境搭建阶段） |
| **原因** | `platform/` 与 Python 标准库 `platform` 模块重名，导致 pandas 等第三方库中 `import platform` 错误加载项目的 `platform/__init__.py`，而非标准库模块。pandas 初始化时调用 `platform.python_implementation()` 失败，启动即报错。 |
| **影响等级** | 🔴 阻断性——pandas 完全无法导入，项目无法启动 |

### 变更内容

**目录重命名：**
- `platform/` → `platform_adapter/`

**代码文件修改（3个文件，6处 import）：**

| 文件 | 修改内容 |
|------|---------|
| `main.py` | `from platform.ui_driver import ...` → `from platform_adapter.ui_driver import ...`（2处） |
| `tests/test_platform.py` | 同模式修改（4处） |
| `platform_adapter/__init__.py` | docstring 中的路径示例更新 |

**文档文件修改（5个文件，10处引用）：**

| 文件 | 修改处数 |
|------|---------|
| `CLAUDE.md` | 2处（目录结构图 + 文字描述） |
| `START_HERE.md` | 1处 |
| `PROGRESS.md` | 1处 |
| `docs/dev-environment.md` | 4处（目录说明 + 表格 + 代码示例） |
| `docs/claude-code-workflow.md` | 2处 |

**注意：** `notify_driver.py` 和 `ui_driver.py` 中的 `sys.platform` 是标准库调用（`sys` 模块属性），与项目目录名无关，无需修改。
