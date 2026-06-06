"""
agent/context.py — Agent 上下文构建（I-3b 三级压缩）

职责：
  1. 从已加载的数据表中提取 Schema 信息，构建 LLM system prompt
  2. 三级 Schema 压缩：相关表全量→非相关表摘要→历史消息压缩
  3. compress_messages：保留最近 N 轮完整消息，早期消息压缩为摘要
  4. 注入字段映射 / JOIN 键 / 质量报告

所有信息来源于 data_loader 的已加载表注册表，不重复读取文件。
"""

import json

from tools.data_loader import _loaded_tables, get_loaded_tables


def build_schema_context(relevant_tables: list[str] | None = None) -> str:
    """
    构建供 LLM SQL 生成使用的 Schema 上下文（三级压缩，I-3b）。

    relevant_tables: @mention 提到或当前对话相关的表名列表。
      - 相关表 → 完整 schema（列名、映射、质量报告）
      - 其他表 → 仅一行摘要（名称/类型/行数），引导使用 profile_table

    返回一段 Markdown 文本，注入到 SQL 生成的 system/user prompt 中。
    """
    tables = get_loaded_tables()
    if not tables:
        return "（当前没有加载任何数据表。请先上传 CSV/Excel 文件。）"

    lines = ["## 已加载数据表\n"]
    for t in tables:
        name = t['name']
        loaded = _loaded_tables.get(name)
        is_relevant = not relevant_tables or name in relevant_tables

        if is_relevant:
            # Level 1: 完整 schema
            lines.append(f"### ■ {name}（{t['rows']}行 × {t['cols']}列，类型：{t['type']}）")

            if loaded:
                field_map = loaded.field_map
                if field_map:
                    lines.append("")
                    lines.append("**可用列名（SQL 只能用下面列出的列名，禁止编造或简化）：**")
                    physical_names = sorted(set(field_map.values()))
                    lines.append("  " + ", ".join(f'"{n}"' for n in physical_names[:20]))
                    if len(physical_names) > 20:
                        lines.append(f"  ... 共 {len(physical_names)} 个可用列")

                    critical_mappings = []
                    for semantic, physical in field_map.items():
                        if semantic != physical:
                            critical_mappings.append(f'禁止 "{semantic}"，必须用 "{physical}"')
                    if critical_mappings:
                        lines.append("")
                        lines.append("**⚠️ 禁止规则（常见错误）：**")
                        for m in critical_mappings[:5]:
                            lines.append(f"  - {m}")

                # 完整列名
                conn = __import__('tools.data_loader', fromlist=['get_connection']).get_connection()
                try:
                    real_cols = conn.execute(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = '{name}' ORDER BY ordinal_position"
                    ).fetchall()
                    col_names = [c[0] for c in real_cols]
                    display_cols = col_names[:30]
                    if len(col_names) > 30:
                        display_cols.append(f'... 共 {len(col_names)} 列')
                    lines.append(f"**完整列名列表：** {', '.join(display_cols)}")
                except Exception:
                    pass

            # 质量诊断
            if loaded and loaded.quality_report:
                qr = loaded.quality_report
                critical = getattr(qr, 'critical_issues', []) or []
                warnings_list = getattr(qr, 'warnings', []) or []
                if critical:
                    lines.append("")
                    lines.append("**⚠️ 数据质量问题（可能影响计算正确性）：**")
                    for issue in critical:
                        lines.append(f"  - 🔴 {issue}")
                if warnings_list:
                    for w in warnings_list[:3]:
                        lines.append(f"  - ⚠️ {w}")
        else:
            # Level 2: 仅摘要（一行）
            lines.append(
                f"### □ {name}（{t['type']}，{t['rows']}行）"
                f" — 如需详情请用 profile_table"
            )

        lines.append("")

    # JOIN 键提示
    lines.append("## JOIN 键提示")
    lines.append("- 关联主体评级表：使用「限额占用主体_标准」（已归一化）↔ 主体评级表的「主体名称」")
    lines.append("- 关联产品净值表：使用「产品名称」字段")
    lines.append("- 关联债券评级表：使用「资产代码」字段")
    lines.append("")

    return "\n".join(lines)


def compress_messages(messages: list[dict], max_keep_full: int = 6) -> list[dict]:
    """
    压缩会话历史（ETCLOVG C 层）。

    策略：
      - 保留 system 消息（始终完整）
      - 保留最近 max_keep_full 条非 system 消息完整
      - 更早的消息：assistant text 截断为前 200 字符，
        tool result 超 500 字符压缩为「[结果已压缩：N字符]」

    参数:
        messages:       当前会话消息列表（原地不修改）
        max_keep_full:  保留完整的最近消息条数（含 tool 消息）

    返回: 新的压缩后消息列表
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    if len(non_system) <= max_keep_full:
        return list(messages)

    keep_full = non_system[-max_keep_full:]
    compress_range = non_system[:-max_keep_full]

    compressed = []
    for m in compress_range:
        role = m.get("role", "")
        if role == "tool":
            content = m.get("content", "")
            if len(content) > 500:
                compressed.append({
                    **m,
                    "content": f"[工具结果已压缩：原 {len(content)} 字符]",
                })
            else:
                compressed.append(m)
        elif role == "assistant":
            text = m.get("content") or ""
            if len(text) > 200:
                truncated = text[:200] + "...[已截断]"
                compressed.append({**m, "content": truncated})
            else:
                compressed.append(m)
        else:
            compressed.append(m)

    return system_msgs + compressed + keep_full


def extract_mention_tables(user_message: str) -> list[str]:
    """
    从用户消息中提取 @mention 的表名列表。

    规则（CLAUDE.md §6.4）：
      - 匹配 @mention（非空白字符，到下一个空白/标点结束）
      - 只返回实际已加载的表名（过滤不存在的）
    """
    import re
    pattern = re.compile(r'@([\w一-鿿\-_]+)')
    mentions = pattern.findall(user_message)
    loaded = {t['name'] for t in get_loaded_tables()}
    return [m for m in mentions if m in loaded]


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
