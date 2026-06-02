# DataAgent — Claude Code 项目启动指引

> 首次打开此项目的 Claude Code 必读。
> 本文件说明如何启动项目、当前状态和第一步任务。

---

## 项目当前状态

**阶段**：准备开发，尚未写任何业务代码
**设计文档**：已完备（见下方文件清单）
**开发环境**：Linux（Claude Code），目标运行环境 Windows 11

---

## 文件清单（读哪些文件、用来做什么）

| 文件 | 重要性 | 用途 |
|------|--------|------|
| `CLAUDE.md` | ⭐⭐⭐⭐⭐ 必读 | 项目完整规格：技术栈、架构、工具规格、开发计划 |
| `docs/dev-environment.md` | ⭐⭐⭐⭐⭐ 必读 | Linux/Windows 双环境策略，启动方式 |
| `docs/dev-quickstart.md` | ⭐⭐⭐⭐ 开发时读 | 每个 Phase 的逐步操作手册和验收标准 |
| `docs/data-schemas.md` | ⭐⭐⭐⭐ 开发工具层时读 | 数据表字段定义和关联关系 |
| `docs/skills-guide.md` | ⭐⭐⭐ 开发 Skills 时读 | Skills 编写规范 |
| `docs/architecture.md` | ⭐⭐⭐ 理解设计时读 | 架构决策说明 |
| `config.yaml` | ⭐⭐⭐ | 运行时配置（需填写 API Key） |
| `data_dictionary/` | ⭐⭐⭐⭐ 开发语义层时读 | 字段映射、主体归一定义 |
| `skills/` | ⭐⭐⭐ | 现有业务技能定义（可直接使用） |

---

## 第一步：确认理解

请在开始写代码前，先回答以下问题（用于验证你已正确理解项目）：

1. 本项目的运行模式是什么？（Linux开发 vs Windows生产，如何切换）
2. 业务能力层分为哪两类？区别是什么？
3. `calculators/` 和 LLM 生成 SQL 各负责什么场景？
4. Phase 1 的验收标准是什么？

---

## 第一步任务（Phase 0）

确认理解后，执行以下操作：

```bash
# 1. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装开发依赖
pip install -r requirements-dev.txt

# 3. 验证依赖
python -c "import duckdb,pandas,flask,chardet,sqlglot,schedule; print('✅ 全部依赖就绪')"

# 4. 创建必要的运行时目录
mkdir -p data/uploads/holding data/uploads/rating_entity \
         data/uploads/rating_bond data/uploads/nav \
         data/outputs data/sessions data/compliance_audit
```

验证通过后，按 `docs/dev-quickstart.md` 的 Phase 1 Step 1 开始编码。

---

## 重要约束提醒

- **不写 Windows 专属代码**（pywebview/winotify）：这些在 Linux 无法运行，统一在 Phase 5 切到 Windows 时处理
- **平台差异已封装**：`platform_adapter/ui_driver.py` 和 `platform_adapter/notify_driver.py` 处理了所有差异，业务代码调用接口即可
- **每次会话开始**：先读 `CLAUDE.md`，再读本次任务相关的具体文档
