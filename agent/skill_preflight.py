"""
agent/skill_preflight.py — Skill 数据依赖预检与执行准备

职责（全部集中于此，loop.py 只调用 prepare_skill_for_execution）：
  1. 解析 SKILL.md frontmatter 中的 required_files / optional_files / external_sources
  2. 校验已加载数据是否满足 Skill 的数据依赖
  3. 对匹配到的表校验 expected_fields 是否存在
  4. 生成用户提示（缺什么文件、缺什么字段）
  5. 生成数据感知的注入内容（真实表名/列名映射）

架构原则（OCP）：
  - loop.py 调用 prepare_skill_for_execution()，此后不再为 Skill 功能改 loop.py
  - 新增 Skill 准备逻辑（权限校验、成本预估等）只在此文件扩展
  - 向后兼容：无 required_files 的旧 Skill 走 required_table_types 兼容路径
  - 无论哪种路径，只有明确缺少必需数据时才阻断；否则正常执行并注入上下文
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from agent.skill_loader import SkillInfo, _parse_frontmatter
from tools.data_loader import _loaded_tables, get_connection, get_loaded_tables

# ═══════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class FileMatch:
    """单个文件依赖的匹配结果"""
    semantic: str
    required: bool
    matched_table: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    found_fields: list[str] = field(default_factory=list)
    fuzzy_matches: dict[str, str] = field(default_factory=dict)


@dataclass
class SkillPrepareResult:
    """prepare_skill_for_execution() 的返回值，供 loop.py 使用"""
    blocked: bool = False           # True 时 loop.py 应终止并展示 block_message
    block_message: str = ""         # 缺必需数据时的用户提示
    skill_note: str = ""            # 注入到用户消息末尾的内容


# ═══════════════════════════════════════════════════════════════
#  对外唯一入口（loop.py 调用此函数）
# ═══════════════════════════════════════════════════════════════

def prepare_skill_for_execution(
    skill_content: str,
    skill_info: SkillInfo,
    schema_ctx: str = "",
) -> SkillPrepareResult:
    """
    Skill 执行前的准备流程（单一入口）：

    阶段1：预检数据依赖
    阶段2：构建数据感知上下文
    阶段3（未来）：权限校验 / 成本预估 等可在此追加

    返回 SkillPrepareResult：
      - blocked=True → loop.py 终止执行并展示 block_message
      - blocked=False → loop.py 将 skill_note 追加到用户消息
    """
    # ── 阶段1：预检 ─────────────────────────────────────────
    metadata = skill_info.metadata or _parse_frontmatter(skill_content)[0]
    req_files = metadata.get("required_files", [])
    opt_files = metadata.get("optional_files", [])
    ext_sources = metadata.get("external_sources", [])

    has_new_fields = bool(req_files or opt_files or ext_sources)
    if not has_new_fields:
        req_files, opt_files = _legacy_table_types_to_files(skill_info)

    tables = get_loaded_tables()
    table_names = [t["name"] for t in tables]

    file_matches: list[FileMatch] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []
    resolved_mapping: dict[str, str] = {}

    for dep in req_files:
        fm = _match_file_dep(dep, required=True, table_names=table_names)
        file_matches.append(fm)
        if fm.matched_table:
            resolved_mapping[fm.semantic] = fm.matched_table
        else:
            missing_required.append(fm.semantic)

    for dep in opt_files:
        fm = _match_file_dep(dep, required=False, table_names=table_names)
        file_matches.append(fm)
        if fm.matched_table:
            resolved_mapping[fm.semantic] = fm.matched_table
        else:
            missing_optional.append(fm.semantic)

    ext_warnings = _check_external_sources(ext_sources)

    # ── 阶段1.5：缺必需数据时扫描工作目录 ────────────────
    workdir_hints: dict[str, list[dict]] = {}
    if missing_required:
        try:
            from tools.workdir_loader import scan_for_pattern
            for dep in req_files:
                sem = dep.get("semantic", "")
                if sem in missing_required:
                    candidates = scan_for_pattern(dep.get("file_pattern", ""))
                    if candidates:
                        workdir_hints[sem] = candidates
        except Exception:
            pass

    # ── 阶段2：构建结果 ────────────────────────────────────
    if missing_required:
        msg = _format_block_message(
            skill_info.name, missing_required, req_files, workdir_hints
        )
        return SkillPrepareResult(blocked=True, block_message=msg)

    enriched = _build_skill_note(
        skill_content, resolved_mapping, file_matches,
        missing_optional, ext_warnings,
        skill_name=skill_info.name,
    )
    return SkillPrepareResult(blocked=False, skill_note=enriched)


# ═══════════════════════════════════════════════════════════════
#  内部实现
# ═══════════════════════════════════════════════════════════════

def _legacy_table_types_to_files(
    skill_info: SkillInfo,
) -> tuple[list[dict], list[dict]]:
    """将旧版 required_table_types / optional_table_types 转为 required_files 格式。"""
    req = [{"semantic": tt, "table_type": tt, "expected_fields": []}
           for tt in skill_info.required_table_types]
    opt = [{"semantic": tt, "table_type": tt, "expected_fields": []}
           for tt in skill_info.optional_table_types]
    return req, opt


def _match_file_dep(
    dep: dict,
    required: bool,
    table_names: list[str],
) -> FileMatch:
    """尝试在已加载表中匹配一个文件依赖。"""
    semantic = dep.get("semantic", "未命名数据")
    file_pattern = dep.get("file_pattern", "")
    table_type = dep.get("table_type", "")
    expected_fields = dep.get("expected_fields", [])

    fm = FileMatch(semantic=semantic, required=required)
    matched = _find_table(file_pattern, table_type, table_names)

    if matched:
        fm.matched_table = matched
        if expected_fields:
            _check_fields(matched, expected_fields, fm)

    return fm


def _find_table(
    file_pattern: str,
    table_type: str,
    table_names: list[str],
) -> str | None:
    """按 file_pattern（优先）或 table_type 在已加载表中查找匹配项。"""
    if file_pattern:
        # 精确 fnmatch
        for name in table_names:
            if fnmatch.fnmatch(name, file_pattern):
                return name
        # 去掉通配符后做子串匹配（宽松回退）
        clean = file_pattern.replace("*", "").replace("?", "")
        if clean:
            for name in table_names:
                if clean in name:
                    return name

    if table_type:
        for name, loaded in _loaded_tables.items():
            if loaded.table_type == table_type:
                return name

    return None


def _check_fields(table_name: str, expected_fields: list[str], fm: FileMatch) -> None:
    """校验表中是否存在期望字段，结果写入 FileMatch。"""
    actual_cols = _get_columns(table_name)
    actual_set = set(actual_cols)

    loaded = _loaded_tables.get(table_name)
    field_map = loaded.field_map if loaded else {}

    for expected in expected_fields:
        if expected in actual_set or expected in field_map:
            fm.found_fields.append(expected)
        else:
            best = _fuzzy_find(expected, actual_cols)
            if best:
                fm.fuzzy_matches[expected] = best
                fm.found_fields.append(expected)
            else:
                fm.missing_fields.append(expected)


def _get_columns(table_name: str) -> list[str]:
    """从 DuckDB information_schema 获取表的列名列表。"""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _fuzzy_find(target: str, candidates: list[str], threshold: float = 0.5) -> str | None:
    """子串包含优先的简单模糊匹配。threshold 默认 0.5（包含即认为相关）。"""
    t = target.lower()
    best_score, best = 0.0, None
    for c in candidates:
        cl = c.lower()
        if t in cl or cl in t:
            score = min(len(t), len(cl)) / max(len(t), len(cl), 1)
            if score > best_score:
                best_score, best = score, c
    if best_score >= threshold:
        return best
    for c in candidates:
        cl = c.lower()
        common = len(set(t) & set(cl))
        union = len(set(t) | set(cl))
        score = common / union if union else 0
        if score > best_score:
            best_score, best = score, c
    return best if best_score >= threshold else None


def _check_external_sources(ext_sources: list[dict]) -> list[str]:
    """检查外部依赖（groups.yaml 等），返回警告信息列表。"""
    warnings: list[str] = []
    for ext in ext_sources:
        if ext.get("type") == "groups_yaml":
            from pathlib import Path
            if not Path("groups.yaml").exists():
                purpose = ext.get("purpose", "集团关系树")
                if ext.get("required", False):
                    warnings.append(f"⚠ {purpose}（groups.yaml）不存在，相关步骤将失败")
                else:
                    warnings.append(f"ℹ {purpose}（groups.yaml）未配置，将尝试网络搜索替代")
    return warnings


def _format_block_message(
    skill_name: str,
    missing_required: list[str],
    req_files: list[dict],
    workdir_hints: dict[str, list[dict]] | None = None,
) -> str:
    """生成缺数据时的用户提示文本，若工作目录有候选文件则附加提示。"""
    lines = [f"技能「{skill_name}」需要以下数据才能执行：\n"]
    for sem in missing_required:
        dep = next((d for d in req_files if d.get("semantic") == sem), {})
        fields = dep.get("expected_fields", [])
        hint = f"- 必需数据「{sem}」尚未加载"
        if dep.get("file_pattern"):
            kw = dep['file_pattern'].replace('*', '').replace('?', '')
            hint += f"（文件名包含「{kw}」）"
        if fields:
            hint += f"\n  需包含字段：{', '.join(fields[:6])}"
            if len(fields) > 6:
                hint += f" 等 {len(fields)} 个字段"
        lines.append(hint)

        candidates = (workdir_hints or {}).get(sem, [])
        if candidates:
            lines.append("\n  💡 工作目录中发现候选文件：")
            for c in candidates[:3]:
                lines.append(f"     • {c['filename']}（{c['size_kb']} KB，{c['mtime']}）")
            lines.append("     → 请在左侧边栏「工作目录」中点击「加载」，再重新发送指令")

    if not any((workdir_hints or {}).get(sem) for sem in missing_required):
        lines.append("\n请上传对应数据文件后，重新发送指令即可。")
    return "\n".join(lines)


def _build_skill_note(
    skill_content: str,
    resolved_mapping: dict[str, str],
    file_matches: list[FileMatch],
    missing_optional: list[str],
    ext_warnings: list[str],
    skill_name: str,
) -> str:
    """构建注入到用户消息的数据感知 Skill 上下文。"""
    lines = [f"[系统提示：检测到与技能「{skill_name}」匹配，请严格按以下步骤执行]\n"]

    if resolved_mapping:
        lines.append("## 数据映射（已验证）")
        for sem, tbl in resolved_mapping.items():
            lines.append(f"- {sem} → 表 `{tbl}`")
        lines.append("")

    fuzzy_items = [
        (exp, act, fm.matched_table or "")
        for fm in file_matches
        for exp, act in fm.fuzzy_matches.items()
    ]
    if fuzzy_items:
        lines.append("## 字段映射（近似匹配，请使用实际列名）")
        for exp, act, tbl in fuzzy_items:
            lines.append(f"- 需求字段「{exp}」→ 实际列「{act}」（表 `{tbl}`）")
        lines.append("")

    field_warns = [
        f"- 表「{fm.matched_table}」中未找到字段「{f}」，请用 profile_table 确认"
        for fm in file_matches if fm.matched_table
        for f in fm.missing_fields
    ]
    if field_warns:
        lines.append("## 字段缺失警告")
        lines.extend(field_warns)
        lines.append("")

    if missing_optional:
        lines.append("## 可选数据未加载")
        for sem in missing_optional:
            lines.append(f"- 「{sem}」未上传，相关步骤输出\"-\"或跳过")
        lines.append("")

    if ext_warnings:
        lines.append("## 外部依赖提示")
        lines.extend(ext_warnings)
        lines.append("")

    lines.append(skill_content)

    lines.append("\n## 执行要求")
    lines.append("- 表名必须使用上面「数据映射」中列出的实际表名，不得编造")
    lines.append("- 列名必须使用 Schema 上下文或 profile_table 返回的实际列名")
    lines.append("- 如遇数据缺失，使用 ask_user 提示用户上传")

    return "\n".join(lines)
