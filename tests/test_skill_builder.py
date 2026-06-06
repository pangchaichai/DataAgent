"""
tests/test_skill_builder.py — Skill Builder 单元测试
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.skill_builder import (
    DRAFTS_DIR,
    SkillDraft,
    delete_draft,
    generate_skill_md,
    list_drafts,
    load_draft,
    parse_llm_skill_response,
    publish_skill,
    save_draft,
    validate_skill_md,
)

# ═══════════════════════════════════════════════════════════════
#  测试用的 SKILL.md 内容
# ═══════════════════════════════════════════════════════════════

VALID_SKILL = """---
name: test_bond_query
description: |
  查询债券到期日和剩余期限信息。
  触发词：到期、到期日、剩余期限、临近到期
required_table_types:
  - holding
---

## 适用场景
用户需要查看债券到期信息。

## 执行步骤
1. 查询持仓表中的到期日字段
2. 计算剩余天数

## 数据计算规则

```sql
SELECT 资产名称, 到期日, 剩余期限
FROM {target_table}
WHERE 到期日 IS NOT NULL
ORDER BY 到期日
LIMIT 100
```

## 输出格式
以表格形式展示。
"""

MISSING_NAME = """---
description: |
  一个测试用的 Skill。
---

## 内容
测试
"""

DANGEROUS_SQL = """---
name: dangerous_skill
description: |
  一个包含危险 SQL 的 Skill。
  触发词：测试
---

## 数据计算规则

```sql
DROP TABLE holding;
```
"""

BAD_NAME = """---
name: 123_invalid
description: |
  名称不合法的 Skill。
---
"""

EMPTY_CONTENT = ""

TOO_LARGE = """---
name: big_skill
description: |
  超大内容。
---
""" + "x" * 11000


# ═══════════════════════════════════════════════════════════════
#  校验测试
# ═══════════════════════════════════════════════════════════════

def test_validate_valid_skill():
    """合法的 Skill 应通过校验"""
    # 使用临时目录避免与已有 skills 冲突
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(VALID_SKILL, skills_dir=tmpdir)
        assert result.ok, f"Expected ok=True, got issues: {[i.message for i in result.issues]}"


def test_validate_missing_name():
    """缺少 name 字段应报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(MISSING_NAME, skills_dir=tmpdir)
        assert not result.ok
        error_fields = [i.field for i in result.issues if i.level == 'error']
        assert 'name' in error_fields


def test_validate_dangerous_sql():
    """包含 DROP 的 SQL 应被拦截"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(DANGEROUS_SQL, skills_dir=tmpdir)
        assert not result.ok
        sql_errors = [i for i in result.issues
                      if i.field == 'sql_safety' and i.level == 'error']
        assert len(sql_errors) > 0


def test_validate_bad_name():
    """不合法的名称应报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(BAD_NAME, skills_dir=tmpdir)
        assert not result.ok
        error_fields = [i.field for i in result.issues if i.level == 'error']
        assert 'name' in error_fields


def test_validate_empty_content():
    """空内容应报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(EMPTY_CONTENT, skills_dir=tmpdir)
        assert not result.ok


def test_validate_too_large():
    """超大内容应报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(TOO_LARGE, skills_dir=tmpdir)
        assert not result.ok


def test_validate_name_conflict():
    """与已有 Skill 同名应报错"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建一个已有的 skill
        skill_dir = Path(tmpdir) / 'test_bond_query'
        skill_dir.mkdir()
        (skill_dir / 'SKILL.md').write_text(VALID_SKILL, encoding='utf-8')

        result = validate_skill_md(VALID_SKILL, skills_dir=tmpdir)
        assert not result.ok
        error_msgs = [i.message for i in result.issues if i.level == 'error']
        assert any('冲突' in m for m in error_msgs)


def test_validate_missing_limit_warning():
    """SQL 缺少 LIMIT 应产生警告"""
    no_limit = """---
name: no_limit_skill
description: |
  缺少 LIMIT 的 Skill。
  触发词：测试
---

## 数据计算规则

```sql
SELECT * FROM {target_table}
```

## 执行步骤
查询。

## 输出格式
表格。
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(no_limit, skills_dir=tmpdir)
        warnings = [i for i in result.issues if i.level == 'warning']
        assert any('LIMIT' in w.message for w in warnings)


# ═══════════════════════════════════════════════════════════════
#  模板生成测试
# ═══════════════════════════════════════════════════════════════

def test_generate_skill_md():
    """SkillDraft 应生成合法的 SKILL.md"""
    draft = SkillDraft(
        name="maturity_check",
        description="查询债券到期信息",
        trigger_words="到期、到期日、剩余期限",
        required_table_types=["holding"],
        scenarios="用户查看债券到期情况",
        steps="1. 查询到期日\n2. 计算剩余天数",
        output_format="表格展示",
    )
    content = generate_skill_md(draft)
    assert 'name: maturity_check' in content
    assert '触发词：到期、到期日、剩余期限' in content
    assert '## 适用场景' in content

    # 生成的内容应能通过校验
    with tempfile.TemporaryDirectory() as tmpdir:
        result = validate_skill_md(content, skills_dir=tmpdir)
        assert result.ok, f"Generated content failed validation: {[i.message for i in result.issues]}"


# ═══════════════════════════════════════════════════════════════
#  LLM 响应解析测试
# ═══════════════════════════════════════════════════════════════

def test_parse_llm_response():
    """应能从 LLM JSON 响应中提取 SkillDraft"""
    llm_output = """
Here is the skill configuration:
```json
{
  "name": "bond_expiry_alert",
  "description": "监控即将到期的债券",
  "trigger_words": "到期、即将到期",
  "calc_type": "exploratory",
  "required_table_types": ["holding"],
  "scenarios": "定期检查",
  "prerequisites": "持仓表",
  "steps": "查询到期日在30天内的债券",
  "sql_examples": "SELECT * FROM holding WHERE 到期日 < date_add(now(), INTERVAL 30 DAY) LIMIT 100",
  "output_format": "表格",
  "notes": "注意节假日"
}
```
"""
    draft = parse_llm_skill_response(llm_output)
    assert draft is not None
    assert draft.name == "bond_expiry_alert"
    assert draft.calc_type == "exploratory"


def test_parse_llm_response_invalid():
    """无效 JSON 应返回 None"""
    assert parse_llm_skill_response("这不是 JSON") is None
    assert parse_llm_skill_response("") is None


# ═══════════════════════════════════════════════════════════════
#  草稿持久化测试
# ═══════════════════════════════════════════════════════════════

def test_draft_lifecycle():
    """草稿的保存、读取、列表、删除"""
    test_name = "_test_draft_lifecycle"
    try:
        save_draft(test_name, VALID_SKILL)
        assert load_draft(test_name) == VALID_SKILL

        drafts = list_drafts()
        names = [d['name'] for d in drafts]
        assert test_name in names or 'test_bond_query' in names

        assert delete_draft(test_name) is True
        assert load_draft(test_name) is None
    finally:
        delete_draft(test_name)


# ═══════════════════════════════════════════════════════════════
#  发布测试
# ═══════════════════════════════════════════════════════════════

def test_publish_valid_skill():
    """合法 Skill 应成功发布"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = publish_skill(VALID_SKILL, skills_dir=tmpdir)
        assert result['ok']
        assert result['name'] == 'test_bond_query'
        assert (Path(tmpdir) / 'test_bond_query' / 'SKILL.md').exists()


def test_publish_invalid_skill():
    """不合法 Skill 应发布失败"""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = publish_skill(DANGEROUS_SQL, skills_dir=tmpdir)
        assert not result['ok']
        assert 'validation' in result


# ═══════════════════════════════════════════════════════════════
#  运行
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
