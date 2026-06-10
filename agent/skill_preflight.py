"""
agent/skill_preflight.py — Skill 数据依赖预检

职责：
  1. 解析 Skill frontmatter 中的 required_files / optional_files / external_sources
  2. 校验已加载数据是否满足 Skill 的数据依赖
  3. 对匹配到的表检查 expected_fields 是否存在
  4. 生成用户提示（缺什么文件、缺什么字段）
  5. 生成数据映射（语义名 → 实际表名 + 字段映射）

设计原则：
  - 向后兼容：无新字段的 Skill 跳过预检，行为不变
  - 兼容旧字段：required_table_types 自动转换为 required_files 格式
  - 轻量：仅查询内存中的 _loaded_tables 和 information_schema
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

from agent.skill_loader import SkillInfo, _parse_frontmatter
from tools.data_loader import _loaded_tables, get_connection, get_loaded_tables


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
class PreflightResult:
    """预检总结果"""
    can_execute: bool = True
    file_matches: list[FileMatch] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    field_warnings: list[str] = field(default_factory=list)
    resolved_mapping: dict[str, str] = field(default_factory=dict)
    user_guidance: list[str] = field(default_factory=list)


def run_preflight(skill_content: str, skill_info: SkillInfo) -> PreflightResult:
    """
    对 Skill 执行数据依赖预检。

    1. 解析 frontmatter 中的 required_files / optional_files
    2. 若无新字段，回退到 required_table_types（兼容旧 Skill）
    3. 对每个文件依赖，在已加载表中匹配
    4. 对匹配到的表，检查 expected_fields
    5. 检查 external_sources
    6. 生成 user_guidance
    """
    metadata, _ = _parse_frontmatter(skill_content)
    result = PreflightResult()

    req_files = metadata.get("required_files", [])
    opt_files = metadata.get("optional_files", [])
    ext_sources = metadata.get("external_sources", [])

    has_new_fields = bool(req_files or opt_files or ext_sources)

    if not has_new_fields:
        req_files = _convert_legacy_table_types(skill_info)
        if not req_files:
            return result

    tables = get_loaded_tables()
    table_names = [t["name"] for t in tables]

    for file_dep in req_files:
        _check_file_dep(file_dep, required=True, table_names=table_names, result=result)

    for file_dep in opt_files:
        _check_file_dep(file_dep, required=False, table_names=table_names, result=result)

    for ext in ext_sources:
        _check_external_source(ext, result)

    if result.missing_required:
        result.can_execute = False

    return result


def _convert_legacy_table_types(skill_info: SkillInfo) -> list[dict]:
    """将旧版 required_table_types 转换为 required_files 格式"""
    files = []
    for tt in skill_info.required_table_types:
        files.append({
            "semantic": tt,
            "table_type": tt,
            "required": True,
            "expected_fields": [],
        })
    for tt in skill_info.optional_table_types:
        files.append({
            "semantic": tt,
            "table_type": tt,
            "required": False,
            "expected_fields": [],
        })
    return files


def _check_file_dep(
    file_dep: dict,
    required: bool,
    table_names: list[str],
    result: PreflightResult,
) -> None:
    """检查单个文件依赖是否满足"""
    semantic = file_dep.get("semantic", "未命名数据")
    file_pattern = file_dep.get("file_pattern", "")
    table_type = file_dep.get("table_type", "")
    expected_fields = file_dep.get("expected_fields", [])

    fm = FileMatch(semantic=semantic, required=required)
    matched = _find_matching_table(file_pattern, table_type, table_names)

    if matched:
        fm.matched_table = matched
        result.resolved_mapping[semantic] = matched
        if expected_fields:
            _check_fields(matched, expected_fields, fm, result)
    else:
        label = f"「{semantic}」"
        if file_pattern:
            label += f"（文件名匹配：{file_pattern}）"
        elif table_type:
            label += f"（表类型：{table_type}）"

        if required:
            result.missing_required.append(semantic)
            result.user_guidance.append(f"- 必需数据 {label} 尚未上传，请上传对应文件。")
        else:
            result.missing_optional.append(semantic)
            result.user_guidance.append(f"- 可选数据 {label} 未上传，相关步骤将跳过或输出"-"。")

    result.file_matches.append(fm)


def _find_matching_table(
    file_pattern: str,
    table_type: str,
    table_names: list[str],
) -> str | None:
    """在已加载表中查找匹配的表"""
    if file_pattern:
        for name in table_names:
            if fnmatch.fnmatch(name, file_pattern):
                return name
            clean_pattern = re.sub(r'[*?]', '', file_pattern)
            if clean_pattern and clean_pattern in name:
                return name

    if table_type:
        for name, loaded in _loaded_tables.items():
            if loaded.table_type == table_type:
                return name

    return None


def _check_fields(
    table_name: str,
    expected_fields: list[str],
    fm: FileMatch,
    result: PreflightResult,
) -> None:
    """检查表中是否存在期望的字段"""
    actual_cols = _get_table_columns(table_name)
    actual_set = set(actual_cols)

    loaded = _loaded_tables.get(table_name)
    field_map = loaded.field_map if loaded else {}
    reverse_map = {v: k for k, v in field_map.items()} if field_map else {}

    for expected in expected_fields:
        if expected in actual_set:
            fm.found_fields.append(expected)
        elif expected in field_map:
            fm.found_fields.append(expected)
            fm.fuzzy_matches[expected] = field_map[expected]
        else:
            best = _fuzzy_find(expected, actual_cols)
            if best:
                fm.fuzzy_matches[expected] = best
                fm.found_fields.append(expected)
            else:
                fm.missing_fields.append(expected)
                result.field_warnings.append(
                    f"表「{table_name}」中未找到字段「{expected}」"
                )


def _get_table_columns(table_name: str) -> list[str]:
    """从 DuckDB information_schema 获取表的实际列名"""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = '{table_name}' ORDER BY ordinal_position"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _fuzzy_find(target: str, candidates: list[str], threshold: float = 0.6) -> str | None:
    """简单的模糊匹配：基于子串包含和字符重叠"""
    target_lower = target.lower()
    best_score = 0.0
    best_match = None

    for c in candidates:
        c_lower = c.lower()
        if target_lower in c_lower or c_lower in target_lower:
            score = min(len(target_lower), len(c_lower)) / max(len(target_lower), len(c_lower))
            if score > best_score:
                best_score = score
                best_match = c

    if best_score >= threshold:
        return best_match

    for c in candidates:
        c_lower = c.lower()
        common = set(target_lower) & set(c_lower)
        union = set(target_lower) | set(c_lower)
        if union:
            score = len(common) / len(union)
            if score > best_score:
                best_score = score
                best_match = c

    return best_match if best_score >= threshold else None


def _check_external_source(ext: dict, result: PreflightResult) -> None:
    """检查外部数据源是否可用"""
    source_type = ext.get("type", "")
    purpose = ext.get("purpose", "")
    required = ext.get("required", False)

    if source_type == "groups_yaml":
        from pathlib import Path
        groups_path = Path("groups.yaml")
        if not groups_path.exists():
            msg = f"- 外部数据「{purpose or 'groups.yaml'}」不存在"
            if required:
                result.missing_required.append(f"external:{source_type}")
                result.user_guidance.append(msg + "，请配置集团关系树或使用网络搜索。")
            else:
                result.missing_optional.append(f"external:{source_type}")
                result.user_guidance.append(msg + "（可选，将尝试网络搜索替代）。")


def build_data_aware_skill_context(
    skill_content: str,
    preflight: PreflightResult,
) -> str:
    """
    将原始 Skill 内容转化为 LLM 可直接执行的数据感知上下文。

    注入：
    1. 数据映射表（语义名 → 实际表名）
    2. 字段映射注意事项
    3. 缺失数据警告
    4. 原始 Skill 内容
    5. 执行指令
    """
    lines = []

    if preflight.resolved_mapping:
        lines.append("## 数据映射（已验证）")
        for semantic, table_name in preflight.resolved_mapping.items():
            lines.append(f"- {semantic} → `{table_name}`")
        lines.append("")

    fuzzy_items = []
    for fm in preflight.file_matches:
        for expected, actual in fm.fuzzy_matches.items():
            fuzzy_items.append((expected, actual, fm.matched_table or ""))
    if fuzzy_items:
        lines.append("## 字段映射注意事项")
        for expected, actual, table in fuzzy_items:
            lines.append(f"- 需求字段「{expected}」→ 实际列名「{actual}」（表 `{table}`）")
        lines.append("")

    if preflight.missing_optional:
        lines.append("## 缺失的可选数据")
        for name in preflight.missing_optional:
            lines.append(f"- {name}：未加载，相关步骤请输出"-"或提示用户上传")
        lines.append("")

    if preflight.field_warnings:
        lines.append("## 字段缺失警告")
        for w in preflight.field_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append(skill_content)

    lines.append("")
    lines.append("## 执行要求")
    lines.append("- SQL 中的表名必须使用上面「数据映射」中的实际表名")
    lines.append("- 列名必须使用 Schema 上下文中列出的实际列名，不得编造")
    lines.append("- 如果某个数据需求对应的表未加载，使用 ask_user 提示用户上传")

    return "\n".join(lines)
