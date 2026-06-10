"""
tests/test_skill_preflight.py — Skill 预检模块单元测试
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.skill_loader import SkillInfo
from agent.skill_preflight import (
    SkillPrepareResult,
    _find_table,
    _fuzzy_find,
    _legacy_table_types_to_files,
    prepare_skill_for_execution,
)


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

def _make_skill_info(
    name: str = "test_skill",
    required_table_types: list[str] | None = None,
    optional_table_types: list[str] | None = None,
    metadata: dict | None = None,
) -> SkillInfo:
    return SkillInfo(
        name=name,
        description="测试技能",
        required_table_types=required_table_types or [],
        optional_table_types=optional_table_types or [],
        metadata=metadata or {},
    )


SIMPLE_SKILL_MD = """---
name: test_skill
description: 测试技能
calc_type: exploratory
---
## 步骤
1. 查询数据
"""

SKILL_WITH_REQ_FILES = """---
name: weekly_report
description: 周报生成
calc_type: exploratory
required_files:
  - semantic: "周报数据源"
    file_pattern: "周报*数据源*"
    expected_fields:
      - 统计日期
      - 组合代码
      - 产品标签
optional_files:
  - semantic: "模板文件"
    file_pattern: "周报*模板*"
---
## 步骤
"""

SKILL_WITH_EXT_SOURCE = """---
name: meeting_report
description: 谈参要点
calc_type: exploratory
required_files:
  - semantic: "信用数据"
    file_pattern: "信用*"
    expected_fields:
      - 客户名称
      - 年份
external_sources:
  - type: groups_yaml
    purpose: "集团关系树"
    required: false
---
"""


# ═══════════════════════════════════════════════════════════════
#  _legacy_table_types_to_files
# ═══════════════════════════════════════════════════════════════

def test_legacy_conversion_required():
    skill_info = _make_skill_info(required_table_types=["holding", "nav"])
    req, opt = _legacy_table_types_to_files(skill_info)
    assert len(req) == 2
    assert req[0]["semantic"] == "holding"
    assert req[0]["table_type"] == "holding"
    assert opt == []


def test_legacy_conversion_optional():
    skill_info = _make_skill_info(optional_table_types=["rating_entity"])
    req, opt = _legacy_table_types_to_files(skill_info)
    assert req == []
    assert len(opt) == 1
    assert opt[0]["table_type"] == "rating_entity"


# ═══════════════════════════════════════════════════════════════
#  _find_table
# ═══════════════════════════════════════════════════════════════

def test_find_table_by_pattern_exact():
    tables = ["holding_20260515", "nav_20260515", "周报_本周数据源"]
    result = _find_table("周报*数据源*", "", tables)
    assert result == "周报_本周数据源"


def test_find_table_by_pattern_fnmatch():
    tables = ["周报_20260610_数据源", "其他表"]
    result = _find_table("周报*数据源*", "", tables)
    assert result == "周报_20260610_数据源"


def test_find_table_by_substring_fallback():
    tables = ["周报数据源20260610"]
    result = _find_table("周报*数据源*", "", tables)
    assert result == "周报数据源20260610"


def test_find_table_by_type():
    mock_loaded = {"holding_20260515": MagicMock(table_type="holding")}
    with patch("agent.skill_preflight._loaded_tables", mock_loaded):
        result = _find_table("", "holding", ["holding_20260515"])
    assert result == "holding_20260515"


def test_find_table_not_found():
    result = _find_table("不存在*", "unknown_type", ["其他表"])
    assert result is None


# ═══════════════════════════════════════════════════════════════
#  _fuzzy_find
# ═══════════════════════════════════════════════════════════════

def test_fuzzy_find_substring():
    result = _fuzzy_find("产品标签", ["统计日期", "产品标签_分类", "规模"])
    assert result == "产品标签_分类"


def test_fuzzy_find_no_match():
    result = _fuzzy_find("完全不相关", ["abc", "def", "xyz"])
    assert result is None


def test_fuzzy_find_exact():
    result = _fuzzy_find("统计日期", ["统计日期", "规模"])
    assert result == "统计日期"


# ═══════════════════════════════════════════════════════════════
#  prepare_skill_for_execution — 无数据时阻断
# ═══════════════════════════════════════════════════════════════

@patch("agent.skill_preflight.get_loaded_tables", return_value=[])
@patch("agent.skill_preflight._loaded_tables", {})
def test_blocked_when_required_file_missing(mock_tables):
    skill_info = _make_skill_info(
        name="weekly_report",
        metadata={
            "name": "weekly_report",
            "required_files": [{"semantic": "周报数据源", "file_pattern": "周报*数据源*"}],
        },
    )
    result = prepare_skill_for_execution(SKILL_WITH_REQ_FILES, skill_info)
    assert result.blocked is True
    assert "周报数据源" in result.block_message
    assert "请上传" in result.block_message


@patch("agent.skill_preflight.get_loaded_tables", return_value=[])
@patch("agent.skill_preflight._loaded_tables", {})
def test_not_blocked_when_only_optional_missing(mock_tables):
    """仅可选数据缺失时不阻断，但注入警告。"""
    skill_info = _make_skill_info(
        name="test_skill",
        metadata={
            "name": "test_skill",
            "required_files": [],
            "optional_files": [{"semantic": "可选数据", "file_pattern": "可选*"}],
        },
    )
    result = prepare_skill_for_execution(SIMPLE_SKILL_MD, skill_info)
    assert result.blocked is False
    assert "可选数据" in result.skill_note


# ═══════════════════════════════════════════════════════════════
#  prepare_skill_for_execution — 数据就绪时正常执行
# ═══════════════════════════════════════════════════════════════

@patch("agent.skill_preflight.get_loaded_tables", return_value=[
    {"name": "周报_本周数据源", "type": "unknown"},
])
@patch("agent.skill_preflight._loaded_tables", {})
@patch("agent.skill_preflight._get_columns", return_value=["统计日期", "组合代码", "产品标签"])
def test_resolved_mapping_injected(mock_cols, mock_tables):
    skill_info = _make_skill_info(
        name="weekly_report",
        metadata={
            "name": "weekly_report",
            "required_files": [{
                "semantic": "周报数据源",
                "file_pattern": "周报*数据源*",
                "expected_fields": ["统计日期", "组合代码"],
            }],
        },
    )
    result = prepare_skill_for_execution(SKILL_WITH_REQ_FILES, skill_info)
    assert result.blocked is False
    assert "周报_本周数据源" in result.skill_note
    assert "数据映射" in result.skill_note


@patch("agent.skill_preflight.get_loaded_tables", return_value=[
    {"name": "holding_20260515", "type": "holding"},
])
@patch("agent.skill_preflight._loaded_tables", {
    "holding_20260515": MagicMock(table_type="holding", field_map={})
})
def test_legacy_table_type_resolved(mock_tables):
    """旧版 required_table_types 能正确解析（兼容路径）。"""
    skill_info = _make_skill_info(
        name="old_skill",
        required_table_types=["holding"],
        metadata={},  # 无新字段，走兼容路径
    )
    result = prepare_skill_for_execution(SIMPLE_SKILL_MD, skill_info)
    assert result.blocked is False
    assert "holding_20260515" in result.skill_note


# ═══════════════════════════════════════════════════════════════
#  prepare_skill_for_execution — 无数据依赖声明（零影响路径）
# ═══════════════════════════════════════════════════════════════

@patch("agent.skill_preflight.get_loaded_tables", return_value=[])
@patch("agent.skill_preflight._loaded_tables", {})
def test_no_data_requirements_not_blocked(mock_tables):
    """无 required_files 且无 required_table_types 的 Skill 不阻断。"""
    skill_info = _make_skill_info(name="simple_skill", metadata={})
    result = prepare_skill_for_execution(SIMPLE_SKILL_MD, skill_info)
    assert result.blocked is False
    # skill_note 仍包含原始 Skill 内容
    assert "步骤" in result.skill_note


# ═══════════════════════════════════════════════════════════════
#  external_sources
# ═══════════════════════════════════════════════════════════════

@patch("agent.skill_preflight.get_loaded_tables", return_value=[
    {"name": "信用数据20260101", "type": "unknown"},
])
@patch("agent.skill_preflight._loaded_tables", {})
@patch("agent.skill_preflight._get_columns", return_value=["客户名称", "年份"])
@patch("pathlib.Path.exists", return_value=False)
def test_missing_optional_groups_yaml_warning(mock_exists, mock_cols, mock_tables):
    skill_info = _make_skill_info(
        name="meeting_report",
        metadata={
            "name": "meeting_report",
            "required_files": [{"semantic": "信用数据", "file_pattern": "信用*"}],
            "external_sources": [{"type": "groups_yaml", "purpose": "集团关系树", "required": False}],
        },
    )
    result = prepare_skill_for_execution(SKILL_WITH_EXT_SOURCE, skill_info)
    assert result.blocked is False
    assert "groups.yaml" in result.skill_note or "集团关系树" in result.skill_note
