"""
tools/skill_builder.py — Skill 自助创建与发布

职责：
  1. 引导非技术用户通过对话/模板创建自定义 Skill
  2. 校验 SKILL.md 的格式、安全性、命名冲突
  3. 预览和测试 Skill
  4. 发布到 skills/ 目录
"""

import os
import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from agent.skill_loader import SkillLoader, _parse_frontmatter


# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

SKILLS_DIR = Path(__file__).resolve().parent.parent / 'skills'
DRAFTS_DIR = Path(__file__).resolve().parent.parent / 'data' / 'skill_drafts'

REQUIRED_FRONTMATTER = ['name', 'description']
VALID_CALC_TYPES = ['exploratory', 'fixed']
VALID_TABLE_TYPES = ['holding', 'nav', 'rating_entity', 'rating_bond',
                     'monitoring', 'weekly_report', 'user_product_mapping']

NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{2,39}$')

SQL_DANGEROUS_PATTERNS = [
    r'\bDROP\b', r'\bDELETE\b', r'\bINSERT\b', r'\bUPDATE\b',
    r'\bCREATE\b', r'\bALTER\b', r'\bTRUNCATE\b',
    r'\bread_csv_auto\b', r'\bread_parquet\b', r'\bread_json\b',
    r'\bcopy\b', r'\battach\b', r'\binstall\b', r'\bload\b',
    r'\bpragma\b', r'\bexport_database\b',
    r'\binformation_schema\b', r'\bpg_catalog\b',
]

MAX_SKILL_SIZE = 10000  # SKILL.md 最大字符数


# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    level: str          # 'error' | 'warning'
    field: str
    message: str


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, field_name: str, msg: str):
        self.issues.append(ValidationIssue('error', field_name, msg))
        self.ok = False

    def add_warning(self, field_name: str, msg: str):
        self.issues.append(ValidationIssue('warning', field_name, msg))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [asdict(i) for i in self.issues],
            "error_count": sum(1 for i in self.issues if i.level == 'error'),
            "warning_count": sum(1 for i in self.issues if i.level == 'warning'),
        }


@dataclass
class SkillDraft:
    """用户创建中的 Skill 草稿"""
    name: str
    description: str
    calc_type: str = "exploratory"
    required_table_types: list[str] = field(default_factory=list)
    optional_table_types: list[str] = field(default_factory=list)
    trigger_words: str = ""
    scenarios: str = ""
    prerequisites: str = ""
    steps: str = ""
    sql_examples: str = ""
    output_format: str = ""
    notes: str = ""


# ═══════════════════════════════════════════════════════════════
#  模板生成
# ═══════════════════════════════════════════════════════════════

def generate_skill_md(draft: SkillDraft) -> str:
    """将 SkillDraft 渲染为 SKILL.md 文本"""
    lines = ['---']
    lines.append(f'name: {draft.name}')

    desc_body = draft.description.strip()
    if draft.trigger_words:
        desc_body += f'\n  触发词：{draft.trigger_words}'
    lines.append(f'description: |')
    for dl in desc_body.split('\n'):
        lines.append(f'  {dl.strip()}')

    if draft.calc_type != 'exploratory':
        lines.append(f'calc_type: {draft.calc_type}')

    if draft.required_table_types:
        lines.append('required_table_types:')
        for t in draft.required_table_types:
            lines.append(f'  - {t}')

    if draft.optional_table_types:
        lines.append('optional_table_types:')
        for t in draft.optional_table_types:
            lines.append(f'  - {t}')

    lines.append('---')
    lines.append('')

    if draft.scenarios:
        lines.append('## 适用场景')
        lines.append(draft.scenarios.strip())
        lines.append('')

    if draft.prerequisites:
        lines.append('## 前提条件')
        lines.append(draft.prerequisites.strip())
        lines.append('')

    if draft.steps:
        lines.append('## 执行步骤')
        lines.append(draft.steps.strip())
        lines.append('')

    if draft.sql_examples:
        lines.append('## 数据计算规则')
        lines.append(draft.sql_examples.strip())
        lines.append('')

    if draft.output_format:
        lines.append('## 输出格式')
        lines.append(draft.output_format.strip())
        lines.append('')

    if draft.notes:
        lines.append('## 注意事项')
        lines.append(draft.notes.strip())
        lines.append('')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════
#  从对话描述生成草稿（供 LLM 调用）
# ═══════════════════════════════════════════════════════════════

def build_skill_generation_prompt(user_description: str) -> str:
    """
    构建 LLM prompt，引导 LLM 从用户自然语言描述生成结构化 SkillDraft。
    返回 prompt 文本，由 llm_client 调用。
    """
    return f"""你是 DataAgent 的 Skill 配置生成助手。用户用自然语言描述了一个新的数据分析场景，
请将其转化为结构化的 Skill 配置。

用户描述：
{user_description}

请严格按以下 JSON 格式输出，不要添加其他内容：
{{
  "name": "小写字母+下划线，3-40字符，如 bond_maturity_check",
  "description": "1-3句话描述功能和适用场景",
  "trigger_words": "触发词，逗号分隔，如：到期、到期日、临近到期",
  "calc_type": "exploratory 或 fixed（临时查询选 exploratory，合规/报告选 fixed）",
  "required_table_types": ["holding 或 nav 或 rating_entity 等"],
  "scenarios": "适用场景的详细描述",
  "prerequisites": "需要哪些数据表和字段",
  "steps": "执行步骤的 Markdown 描述",
  "sql_examples": "SQL 查询示例（用 {{target_table}} 作占位符）",
  "output_format": "输出格式说明",
  "notes": "注意事项"
}}"""


def parse_llm_skill_response(llm_output: str) -> Optional[SkillDraft]:
    """解析 LLM 返回的 JSON 为 SkillDraft"""
    import json
    text = llm_output.strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None

    return SkillDraft(
        name=data.get('name', ''),
        description=data.get('description', ''),
        calc_type=data.get('calc_type', 'exploratory'),
        required_table_types=data.get('required_table_types', []),
        optional_table_types=data.get('optional_table_types', []),
        trigger_words=data.get('trigger_words', ''),
        scenarios=data.get('scenarios', ''),
        prerequisites=data.get('prerequisites', ''),
        steps=data.get('steps', ''),
        sql_examples=data.get('sql_examples', ''),
        output_format=data.get('output_format', ''),
        notes=data.get('notes', ''),
    )


# ═══════════════════════════════════════════════════════════════
#  校验
# ═══════════════════════════════════════════════════════════════

def validate_skill_md(content: str, skills_dir: str = None) -> ValidationResult:
    """
    对 SKILL.md 内容做质量和安全校验。

    校验维度：
      1. 格式：YAML frontmatter 可解析、必填字段存在
      2. 命名：name 合法且不与已有 Skill 冲突
      3. 安全：SQL 示例中无危险操作
      4. 质量：description 含触发词、有执行步骤、有输出格式
      5. 大小：不超过 MAX_SKILL_SIZE
    """
    result = ValidationResult(ok=True)
    dir_path = skills_dir or str(SKILLS_DIR)

    if len(content) > MAX_SKILL_SIZE:
        result.add_error('content', f'Skill 内容超过 {MAX_SKILL_SIZE} 字符限制')
        return result

    if not content.strip():
        result.add_error('content', 'Skill 内容为空')
        return result

    # ── 1. Frontmatter 解析 ──
    metadata, body = _parse_frontmatter(content)
    if not metadata:
        result.add_error('frontmatter', '无法解析 YAML 头部（需要 --- 包裹的 YAML 块）')
        return result

    # ── 2. 必填字段 ──
    for f in REQUIRED_FRONTMATTER:
        if not metadata.get(f):
            result.add_error(f, f'缺少必填字段：{f}')

    name = metadata.get('name', '')

    # ── 3. 名称合法性 ──
    if name and not NAME_PATTERN.match(name):
        result.add_error('name',
                         '名称格式不合法（需 3-40 位小写字母/数字/下划线，字母开头）')

    # ── 4. 名称冲突 ──
    if name:
        loader = SkillLoader(local_dir=dir_path)
        existing = loader.load_registry()
        existing_names = {s.name for s in existing}
        if name in existing_names:
            result.add_error('name', f'名称 "{name}" 与已有 Skill 冲突')

    # ── 5. calc_type 合法性 ──
    calc_type = metadata.get('calc_type', 'exploratory')
    if calc_type not in VALID_CALC_TYPES:
        result.add_error('calc_type',
                         f'calc_type 必须为 {VALID_CALC_TYPES} 之一')

    if calc_type == 'fixed' and not metadata.get('fixed_calculator'):
        result.add_error('fixed_calculator',
                         'calc_type=fixed 时必须指定 fixed_calculator')

    # ── 6. 数据表类型 ──
    for t in metadata.get('required_table_types', []):
        if t not in VALID_TABLE_TYPES:
            result.add_warning('required_table_types',
                               f'未知的数据表类型：{t}（已知类型：{", ".join(VALID_TABLE_TYPES)}）')

    # ── 7. SQL 安全检查 ──
    _check_sql_safety(body, result)

    # ── 8. 质量检查 ──
    desc = metadata.get('description', '')
    if desc and '触发词' not in desc and '关键词' not in desc:
        result.add_warning('description',
                           '建议在 description 中加入「触发词：xxx」以提高匹配准确率')

    if '## 执行步骤' not in body and '## 数据计算规则' not in body:
        result.add_warning('body', '建议包含「执行步骤」或「数据计算规则」章节')

    if '## 输出格式' not in body:
        result.add_warning('body', '建议包含「输出格式」章节，明确展示方式')

    # ── 9. LIMIT 检查 ──
    sql_blocks = re.findall(r'```sql\s*(.*?)```', body, re.DOTALL | re.IGNORECASE)
    for sql in sql_blocks:
        if 'SELECT' in sql.upper() and 'LIMIT' not in sql.upper():
            result.add_warning('sql', 'SQL 示例中缺少 LIMIT 子句，建议添加')

    return result


def _check_sql_safety(body: str, result: ValidationResult):
    """检查 Markdown 正文中的 SQL 示例是否含危险操作"""
    sql_blocks = re.findall(r'```sql\s*(.*?)```', body, re.DOTALL | re.IGNORECASE)
    all_sql = ' '.join(sql_blocks)

    for pattern in SQL_DANGEROUS_PATTERNS:
        if re.search(pattern, all_sql, re.IGNORECASE):
            keyword = re.search(pattern, all_sql, re.IGNORECASE).group()
            result.add_error('sql_safety',
                             f'SQL 中包含危险操作：{keyword}（仅允许 SELECT 查询）')


# ═══════════════════════════════════════════════════════════════
#  草稿持久化
# ═══════════════════════════════════════════════════════════════

def save_draft(name: str, content: str) -> dict:
    """保存 Skill 草稿到 data/skill_drafts/"""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = DRAFTS_DIR / f'{name}.md'
    draft_path.write_text(content, encoding='utf-8')
    return {"ok": True, "path": str(draft_path)}


def load_draft(name: str) -> Optional[str]:
    """加载 Skill 草稿"""
    draft_path = DRAFTS_DIR / f'{name}.md'
    if not draft_path.exists():
        return None
    return draft_path.read_text(encoding='utf-8')


def list_drafts() -> list[dict]:
    """列出所有草稿"""
    if not DRAFTS_DIR.exists():
        return []
    drafts = []
    for f in DRAFTS_DIR.glob('*.md'):
        content = f.read_text(encoding='utf-8')
        metadata, _ = _parse_frontmatter(content)
        drafts.append({
            "name": metadata.get('name', f.stem),
            "description": (metadata.get('description', '') or '').split('\n')[0][:80],
            "file": f.name,
        })
    return drafts


def delete_draft(name: str) -> bool:
    """删除草稿"""
    draft_path = DRAFTS_DIR / f'{name}.md'
    if draft_path.exists():
        draft_path.unlink()
        return True
    return False


# ═══════════════════════════════════════════════════════════════
#  发布
# ═══════════════════════════════════════════════════════════════

def publish_skill(content: str, skills_dir: str = None) -> dict:
    """
    发布 Skill：校验通过后写入 skills/{name}/SKILL.md。

    返回:
      {"ok": True, "name": ..., "path": ...}
      {"ok": False, "error": ..., "validation": ...}
    """
    dir_path = skills_dir or str(SKILLS_DIR)

    validation = validate_skill_md(content, dir_path)
    if not validation.ok:
        return {
            "ok": False,
            "error": "Skill 校验未通过，请修正后重试",
            "validation": validation.to_dict(),
        }

    metadata, _ = _parse_frontmatter(content)
    name = metadata['name']

    skill_dir = Path(dir_path) / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / 'SKILL.md'
    skill_path.write_text(content, encoding='utf-8')

    delete_draft(name)

    return {
        "ok": True,
        "name": name,
        "path": str(skill_path),
        "validation": validation.to_dict(),
    }
