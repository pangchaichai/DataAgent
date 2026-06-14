# DataAgent CHANGELOG
> 此文件由 `scripts/sync_project_state.py` 在每次提交后自动维护。
> 人工编写内容请放入对应版本节标题下的「版本说明」子节。

## [Unreleased]

### 2026-06-14
**🔧 维护**
- `c42fd1a` auto-update management docs after 4b730a1
- `08f312e` auto-update management docs after 30bdac2
- `4b730a1` auto-update management docs after eab4c77
- `30bdac2` auto-update management docs after 9d66f9d
- `eab4c77` auto-update management docs after d967fba
- `9d66f9d` auto-update management docs after ace38a1
- `de22c41` 项目管理完整性审计与修复，新增业务用户使用说明
**✨ 新功能**
- `d967fba` 完整项目管理机制 — git hooks + CHANGELOG + 自动同步
- `f3468ff` 项目状态自动同步机制（sync_project_state.py + hooks）
- `14422cf` DA 小猫头鹰任务状态动画组件
**📖 文档更新**
- `d7f8466` v3.0 evolution final plan + project deliverable updates

### 2026-06-13
**📖 文档更新**
- `f36596e` add v3.0 architecture evolution plan

### 2026-06-12
**📖 文档更新**
- `9aef807` sync version records after feature/skill-data-awareness merge

### 2026-06-10
**✨ 新功能**
- `f4c2c2d` local work directory + batch upload support
- `e390f5a` add weekly_report_generator + replace meeting_report (v3)
- `9c874b9` Phase C — requirement document import
- `a1597ab` Phase B — data-aware Skill Builder
- `b3c878a` Phase A — data-aware skill preflight (OCP compliant)
**📖 文档更新**
- `71522b3` establish Skill v3 data-awareness design and project documentation
**🚧 进行中**
- `3e1ade2` draft skill preflight module (pending design approval)
**🐛 问题修复**
- `e68d46a` skill content injection, frontmatter fallback parsing, error translator improvement

### 2026-06-09
**🧪 测试**
- `3af4143` add meeting_report UAT simulation script + fix template available_str
**🔧 维护**
- `dd9061b` rebuild Windows package — fix stale system prompt after table upload
- `c2217e3` rebuild Windows package with web-search and document-context fixes
**🐛 问题修复**
- `d2c168d` system prompt not refreshed after table upload
- `8d98415` web search refusing + document context not retained in follow-up
- `60b61fd` read_csv fallback 使用无效的 errors 参数导致上传大型中文 CSV 崩溃
- `ffc65fa` .env 占位符覆盖 config.yaml 真实 API Key 导致 401 认证失败
- `43d508d` UAT全面修复 — 设置面板LLM切换+上传错误处理+启动崩溃+CSS变量
- `f34cada` health/status endpoints read model name and API key from wrong config section
- `cf7fe57` resolve Windows UAT issues — upload confirm button invisible + LLM error diagnostics
**🚀 版本发布**
- `ce64584` rebuild package with read_csv encoding fallback fix
- `06095c4` rebuild Windows package with .env API key override fix
- `45efa48` add Windows internal testing package v2.0-beta1 (45.6MB)
**✨ 新功能**
- `ef07641` Windows offline installer + fix 5 upload/auth/setup defects

### 2026-06-08
**✨ 新功能**
- `9f40776` add client_meeting_report skill via Skill Builder
**🐛 问题修复**
- `68fd9d8` resolve all three technical debts (I-9, I-7, I-10)

### 2026-06-07
**✨ 新功能**
- `9d11e23` establish project continuity system (PCS)
- `8abf329` comprehensive UX optimization — LLM settings, @mention autocomplete, data quality, profile modal
**📖 文档更新**
- `d5272b7` update CLAUDE.md and PROGRESS.md to reflect v2.0 Evolution architecture
**🐛 问题修复**
- `ac10756` align report_builder and file_reader APIs with test expectations
- `4e04c90` v1.6.1 — 5项Bug修复 + 文档支持 + 图表 + Word导出 + 设置迁移
- `79d8417` align UX features with refactored blueprint API structure
**📌 其他**
- `05ff293` Fix 7 UAT issues: macOS client, skill builder, document upload, LLM error, no-table block, UI clarity

### 2026-06-06
**📌 其他**
- `8f3ab3f` Fix UAT bugs and update docs for Evolution I-1~I-10
**📖 文档更新**
- `ca0d112` 更新项目文档至 v2.0，回灌 Evolution I-1~I-10 全部变更
