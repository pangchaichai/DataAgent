"""
tools/entity_normalizer.py

主体名称归一化工具

解决：不同系统导出的同一主体写法不一致，导致跨表 JOIN 静默错配。
例：「厦门象屿集团有限公司」「象屿集团有限公司」「象屿」→ 均归一为「象屿集团」

加载数据后，对「限额占用主体」等字段自动应用此归一，
JOIN 前使用归一后的标准名称，保证跨表关联准确。

数据来源：data_dictionary/entity_alias.yaml
"""


import yaml


class EntityNormalizer:
    def __init__(self, alias_file: str = "data_dictionary/entity_alias.yaml"):
        self.alias_to_canonical: dict[str, str] = {}
        self.canonical_to_group: dict[str, str] = {}
        self._load(alias_file)

    def _load(self, alias_file: str):
        with open(alias_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for entity in config.get("entities", []):
            canonical = entity["canonical"]
            group = entity.get("group", "")
            self.canonical_to_group[canonical] = group
            # 标准名本身也是别名之一
            self.alias_to_canonical[canonical] = canonical
            for alias in entity.get("aliases", []):
                self.alias_to_canonical[alias] = canonical

    def normalize(self, name: str) -> str:
        """将别名归一为标准名，未知名称原样返回"""
        return self.alias_to_canonical.get(name, name)

    def get_group(self, name: str) -> str:
        """获取主体所属集团系，未归属则返回空字符串"""
        canonical = self.normalize(name)
        return self.canonical_to_group.get(canonical, "")

    def validate_join_keys(
        self,
        left_values: list[str],
        right_values: list[str],
        join_semantic: str,
    ) -> tuple[bool, list[str]]:
        """
        JOIN 前校验：检查左表的关联键值是否都能在右表中找到（归一后）
        返回 (is_clean, unmatched_list)

        is_clean=False 时，在界面提示用户哪些主体无法对齐，
        而不是静默漏数据。
        """
        right_normalized = {self.normalize(v) for v in right_values}
        unmatched = []
        for v in left_values:
            if self.normalize(v) not in right_normalized:
                unmatched.append(v)
        return len(unmatched) == 0, unmatched
