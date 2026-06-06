"""
agent/skill_loader.py — Skill 加载器（渐进式披露）

职责：
  1. 扫描 skills/ 目录（支持多目录）
  2. load_registry()：只加载所有 SKILL.md 的 name + description（轻量）
  3. load_full(skill_name)：按需加载完整 SKILL.md 内容
  4. detect_relevant_skill()：基于关键词匹配（Phase 1 简单版，Phase 4 改 LLM 分类）
  5. 解析 YAML frontmatter（name, description, calc_type, fixed_calculator, ...）

设计原则：
  - 渐进式披露：Agent 上下文先只看到 Skill 名和描述，命中了才加载完整内容
  - 开闭原则：新增 Skill = 在 skills/ 创建目录 + SKILL.md，不修改本文件
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ═══════════════════════════════════════════════════════════════
#  Dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class SkillInfo:
    """Skill 注册表条目（轻量，只含名称和描述）"""
    name: str
    description: str
    calc_type: str = "exploratory"    # fixed | exploratory
    fixed_calculator: str = ""        # calc_type=fixed 时指定 calculators 函数路径
    required_table_types: list[str] = field(default_factory=list)
    optional_table_types: list[str] = field(default_factory=list)
    skill_dir: str = ""               # Skill 目录路径（用于按需加载完整内容）


# ═══════════════════════════════════════════════════════════════
#  YAML Frontmatter 解析
# ═══════════════════════════════════════════════════════════════

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    解析 SKILL.md 的 YAML frontmatter。
    返回 (metadata_dict, body_text)。
    """
    # 匹配 ---\n...\n--- 格式
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if not match:
        return {}, content
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        metadata = {}
    body = match.group(2).strip()
    return metadata, body


# ═══════════════════════════════════════════════════════════════
#  SkillLoader
# ═══════════════════════════════════════════════════════════════

class SkillLoader:
    """
    Skill 加载器。

    用法:
      loader = SkillLoader(local_dir='skills/', shared_dir='')
      registry = loader.load_registry()          # 轻量，只含名称+描述
      full_md = loader.load_full('position_query')  # 按需加载完整内容
      name = loader.detect_relevant_skill('查询持仓', registry)  # 关键词匹配
    """

    def __init__(self, local_dir: str = 'skills/', shared_dir: str = ''):
        self.local_dir = local_dir
        self.shared_dir = shared_dir
        self._full_cache: dict[str, str] = {}  # {skill_name: full_markdown_content}

    # ── 公开接口 ──────────────────────────────────────────────

    def load_registry(self) -> list[SkillInfo]:
        """
        渐进式加载：扫描所有 Skill 目录，只解析 YAML frontmatter 的
        name + description + calc_type 等关键字段。

        返回 SkillInfo 列表，不加载完整 Markdown 正文。
        """
        registry: list[SkillInfo] = []
        skill_dirs = self._collect_skill_dirs()

        for skill_dir in skill_dirs:
            md_path = os.path.join(skill_dir, 'SKILL.md')
            if not os.path.isfile(md_path):
                continue

            with open(md_path, encoding='utf-8') as f:
                content = f.read()

            metadata, _ = _parse_frontmatter(content)
            name = metadata.get('name', os.path.basename(skill_dir))
            if not name:
                continue

            registry.append(SkillInfo(
                name=name,
                description=metadata.get('description', name),
                calc_type=metadata.get('calc_type', 'exploratory'),
                fixed_calculator=metadata.get('fixed_calculator', ''),
                required_table_types=metadata.get('required_table_types', []),
                optional_table_types=metadata.get('optional_table_types', []),
                skill_dir=skill_dir,
            ))

        return registry

    def load_full(self, skill_name: str) -> str | None:
        """
        按需加载：返回指定 Skill 的完整 SKILL.md 内容。

        包含 YAML frontmatter + 正文。
        结果会被缓存，多次调用同一 Skill 只读一次文件。
        """
        if skill_name in self._full_cache:
            return self._full_cache[skill_name]

        skill_dirs = self._collect_skill_dirs()
        for skill_dir in skill_dirs:
            md_path = os.path.join(skill_dir, 'SKILL.md')
            if not os.path.isfile(md_path):
                continue
            with open(md_path, encoding='utf-8') as f:
                content = f.read()
            metadata, _ = _parse_frontmatter(content)
            if metadata.get('name') == skill_name:
                self._full_cache[skill_name] = content
                return content

        return None

    def detect_relevant_skill(
        self, user_message: str, registry: list[SkillInfo]
    ) -> str | None:
        """
        基于关键词匹配判断用户意图匹配的 Skill（Phase 1 简单实现）。

        Phase 4 将改为 LLM 分类（见 CLAUDE.md 第七章 P2-2）。

        匹配策略：
          1. 从 description 中提取触发词（用逗号/顿号/冒号分割）
          2. 用户消息与每个 Skill 的触发词集合计算匹配度
          3. 返回最高匹配 Skill 的 name，无匹配返回 None
          4. 多 Skill 评分接近时暂无歧义处理（Phase 4 加）

        返回: Skill name 或 None（表示探索式查询）
        """
        best_skill = None
        best_score = 0

        for skill in registry:
            score = self._score_skill(user_message, skill)
            if score > best_score:
                best_score = score
                best_skill = skill.name

        # 阈值：至少需要有一些匹配
        if best_score >= 1:
            return best_skill
        return None

    # ── 内部方法 ──────────────────────────────────────────────

    def _collect_skill_dirs(self) -> list[str]:
        """收集所有 Skill 目录路径"""
        dirs = []
        for base in [self.local_dir, self.shared_dir]:
            if not base:
                continue
            path = Path(base)
            if not path.exists():
                continue
            for entry in path.iterdir():
                if entry.is_dir() and (entry / 'SKILL.md').exists():
                    dirs.append(str(entry))
        return dirs

    def _score_skill(self, user_message: str, skill: SkillInfo) -> int:
        """
        计算用户消息与 Skill 的匹配度。

        从 description 中提取触发词，逐个在用户消息中匹配。
        得分 = 匹配触发词数量 + 匹配触发词的总长度（更具体的关键词权重更高）
        """
        triggers = self._extract_triggers(skill.description)
        if not triggers:
            triggers = [skill.name]

        score = 0
        msg_lower = user_message.lower()
        for trigger in triggers:
            if trigger.lower() in msg_lower:
                # 基础分 1 + 长度加权（长触发词更具体）
                score += 1 + len(trigger)
        return score

    def _extract_triggers(self, description: str) -> list[str]:
        """从 description 中提取触发词列表"""
        # 查找「触发词：...」「关键词：...」等
        for prefix in ['触发词：', '触发词:', '关键词：', '关键词:']:
            if prefix in description:
                # 提取该行
                lines = description.split('\n')
                for line in lines:
                    if prefix in line:
                        triggers_part = line.split(prefix, 1)[-1].strip()
                        # 按中文逗号、顿号、英文逗号分割
                        triggers = re.split(r'[，,、]', triggers_part)
                        return [t.strip() for t in triggers if t.strip()]
                break

        # 无显式触发词，尝试用 description 第一句话作为关键词
        first_line = description.split('\n')[0].strip()
        # 提取引号内的关键词
        quoted = re.findall(r'[「『](.+?)[」』]', first_line)
        if quoted:
            return quoted
        return []


# ═══════════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════════

def load_registry(local_dir: str = 'skills/', shared_dir: str = '') -> list[SkillInfo]:
    """便捷函数：加载 Skill 注册表"""
    loader = SkillLoader(local_dir, shared_dir)
    return loader.load_registry()


def load_full(skill_name: str, local_dir: str = 'skills/', shared_dir: str = '') -> str | None:
    """便捷函数：加载完整 SKILL.md"""
    loader = SkillLoader(local_dir, shared_dir)
    return loader.load_full(skill_name)
