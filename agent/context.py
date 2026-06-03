"""
agent/context.py — Agent 上下文构建

职责：
  1. 从已加载的数据表中提取 Schema 信息，构建 LLM system prompt
  2. 注入字段映射信息（语义名 → 实际列名）
  3. 注入 JOIN 键提示
  4. 注入已注册 Skill 列表

所有信息来源于 data_loader 的已加载表注册表，不重复读取文件。
"""

from tools.data_loader import get_loaded_tables, _loaded_tables


def build_schema_context() -> str:
    """
    构建供 LLM SQL 生成使用的 Schema 上下文。

    从已加载的数据表中提取：
      - 表名、行数
      - 列名列表（去引号显示）
      - 字段映射（语义名 -> 实际列名）
      - JOIN 键信息

    返回一段 Markdown 文本，注入到 SQL 生成的 system/user prompt 中。
    """
    tables = get_loaded_tables()
    if not tables:
        return "（当前没有加载任何数据表。请先上传 CSV/Excel 文件。）"

    lines = ["## 已加载数据表\n"]
    for t in tables:
        name = t['name']
        loaded = _loaded_tables.get(name)
        lines.append(f"### {name}（{t['rows']}行 × {t['cols']}列，类型：{t['type']}）")

        if loaded:
            field_map = loaded.field_map
            if field_map:
                lines.append("")
                lines.append("**可用列名（SQL 只能用下面列出的列名，禁止编造或简化）：**")
                # 只列出实际列名，不展示语义名（防止 LLM 误用）
                physical_names = sorted(set(field_map.values()))
                lines.append("  " + ", ".join(f'"{n}"' for n in physical_names[:20]))
                if len(physical_names) > 20:
                    lines.append(f"  ... 共 {len(physical_names)} 个可用列")

                # 关键映射：明确列出语义名禁止使用
                critical_mappings = []
                for semantic, physical in field_map.items():
                    if semantic != physical:  # 只列出不同的
                        critical_mappings.append(f'禁止 "{semantic}"，必须用 "{physical}"')
                if critical_mappings:
                    lines.append("")
                    lines.append("**⚠️ 禁止规则（常见错误）：**")
                    for m in critical_mappings[:5]:
                        lines.append(f"  - {m}")

            # 列出所有实际列名（帮助 LLM 了解完整表结构）
            conn = __import__('tools.data_loader', fromlist=['get_connection']).get_connection()
            try:
                real_cols = conn.execute(f'SELECT column_name FROM information_schema.columns WHERE table_name = \'{name}\' ORDER BY ordinal_position').fetchall()
                col_names = [c[0] for c in real_cols]
                # 只展示最有用的列（前 30 个）
                display_cols = col_names[:30]
                if len(col_names) > 30:
                    display_cols.append(f'... 共 {len(col_names)} 列')
                lines.append(f"**完整列名列表：** {', '.join(display_cols)}")
            except Exception:
                pass

        # ★R2：质量诊断摘要
        if loaded and loaded.quality_report:
            qr = loaded.quality_report
            critical = getattr(qr, 'critical_issues', []) or []
            warnings = getattr(qr, 'warnings', []) or []
            if critical:
                lines.append("")
                lines.append("**⚠️ 数据质量问题（可能影响计算正确性）：**")
                for issue in critical:
                    lines.append(f"  - 🔴 {issue}")
            if warnings:
                for w in warnings[:5]:
                    lines.append(f"  - ⚠️ {w}")

        lines.append("")

    # JOIN 键提示
    lines.append("## JOIN 键提示")
    lines.append("- 关联主体评级表：使用「限额占用主体_标准」（已归一化）↔ 主体评级表的「主体名称」")
    lines.append("- 关联产品净值表：使用「产品名称」字段")
    lines.append("- 关联债券评级表：使用「资产代码」字段")
    lines.append("")

    return "\n".join(lines)


def build_skill_context(skills_summary: list[str]) -> str:
    """
    构建 Skill 列表上下文（供意图识别和 SQL 生成时参考）。

    skills_summary: Skill 的简短描述列表，如 ["持仓查询", "灵活统计", ...]
    """
    if not skills_summary:
        return ""
    return "## 可用技能\n" + "\n".join(f"- {s}" for s in skills_summary)


def count_tables() -> int:
    """已加载数据表的数量"""
    return len(get_loaded_tables())
