"""
tools/entity_manager.py — 集团系管理

职责：
  1. 读取 groups.yaml 的集团系定义
  2. 提供 主体→集团系 的归属查询（供集中度合并计算使用）
  3. 支持运行时增删集团系成员（通过对话指令或 API）
  4. 集团系变更持久化回 groups.yaml

与 entity_normalizer.py 的关系：
  entity_normalizer: 别名 → 标准名（如 象屿股份 → 象屿集团）
  entity_manager:     标准名 → 集团系（如 象屿集团 → 象屿系）
  两者组合：别名 → 标准名 → 集团系，完成从原始数据到集团合并的完整链路
"""

from pathlib import Path

import yaml

# ═══════════════════════════════════════════════════════════════
#  EntityManager
# ═══════════════════════════════════════════════════════════════

class EntityManager:
    """
    集团系管理器。

    用法:
      mgr = EntityManager('groups.yaml')
      group = mgr.get_group('象屿集团')        # → '象屿系'
      members = mgr.get_members('象屿系')      # → ['象屿集团', '象屿股份', ...]
      mapping = mgr.get_group_mapping()        # → {主体: 集团系}（供 calculators 使用）
    """

    def __init__(self, groups_file: str = 'groups.yaml'):
        self.groups_file = Path(groups_file)
        self.groups: dict[str, list[str]] = {}
        self._entity_to_group: dict[str, str] = {}
        self._load()

    def _load(self):
        """从 groups.yaml 加载集团系定义"""
        if not self.groups_file.exists():
            return
        with open(self.groups_file, encoding='utf-8') as f:
            self.groups = yaml.safe_load(f) or {}
        # 构建逆向索引：主体 → 集团系
        self._rebuild_index()

    def _rebuild_index(self):
        """重建 主体→集团 逆向索引"""
        self._entity_to_group.clear()
        for group_name, members in self.groups.items():
            for member in members:
                self._entity_to_group[member] = group_name

    def _save(self):
        """持久化到 groups.yaml"""
        with open(self.groups_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.groups, f, allow_unicode=True, default_flow_style=False)
        self._rebuild_index()

    # ── 查询接口 ──────────────────────────────────────────────

    def get_group(self, entity_name: str) -> str:
        """查询主体所属集团系，未归属则返回空字符串"""
        return self._entity_to_group.get(entity_name, '')

    def get_members(self, group_name: str) -> list[str]:
        """查询集团系的成员列表"""
        return self.groups.get(group_name, [])

    def get_group_mapping(self) -> dict[str, str]:
        """
        获取 主体→集团系 的完整映射。
        返回: {主体名: 集团系名, ...}
        供 calculators.concentration 使用（use_group_merge=True 时）
        """
        return dict(self._entity_to_group)

    def list_groups(self) -> dict[str, list[str]]:
        """列出所有集团系及其成员"""
        return dict(self.groups)

    # ── 修改接口（支持对话指令或 API 调用）──────────────────

    def add_member(self, group_name: str, entity_name: str) -> bool:
        """向集团系添加成员"""
        if group_name not in self.groups:
            self.groups[group_name] = []
        if entity_name in self.groups[group_name]:
            return False  # 已存在
        self.groups[group_name].append(entity_name)
        self._save()
        return True

    def remove_member(self, group_name: str, entity_name: str) -> bool:
        """从集团系移除成员"""
        if group_name not in self.groups:
            return False
        if entity_name not in self.groups[group_name]:
            return False
        self.groups[group_name].remove(entity_name)
        self._save()
        return True

    def create_group(self, group_name: str, members: list[str] = None) -> bool:
        """新建集团系"""
        if group_name in self.groups:
            return False
        self.groups[group_name] = members or []
        self._save()
        return True

    def delete_group(self, group_name: str) -> bool:
        """删除集团系"""
        if group_name not in self.groups:
            return False
        del self.groups[group_name]
        self._save()
        return True
