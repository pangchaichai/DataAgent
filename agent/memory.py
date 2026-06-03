"""
agent/memory.py — 收窄版跨会话记忆（R5）

只能记「字段口径纠正」，只做「显式建议」，绝不自动注入 SQL/合规口径。
用户开关控制（默认关闭），关闭时整条链路零副作用。

存储：SQLite + BM25 全文检索，纯 Python，PyInstaller 友好。
"""

import json
import os
import sqlite3
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

DB_PATH = "data/memory.db"
MAX_DB_MB_DEFAULT = 5


# ═══════════════════════════════════════════════════════════════
#  AgentMemory
# ═══════════════════════════════════════════════════════════════

class AgentMemory:
    """跨会话记忆（仅 schema_correction）"""

    def __init__(self, db_path: str = None, enabled: bool = False):
        self.db_path = db_path or DB_PATH
        self.enabled = enabled
        self._conn: Optional[sqlite3.Connection] = None

    # ── 公开接口 ──────────────────────────────────────────────

    def initialize(self):
        """建表 + 载入（仅在 enabled=True 时调用）"""
        if not self.enabled:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def save_correction(self, key: str, content: str, source: str = ""):
        """
        保存一条口径纠正。
        仅当 enabled=True 时生效；否则 no-op。
        key: 如 "市值字段-holding"
        content: 如 "使用穿透后市值"
        source: 如 "用户确认"
        """
        if not self.enabled or not self._conn:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory (key, content, source) VALUES (?, ?, ?)",
                (key, content, source),
            )
            self._conn.commit()
            # 体积告警
            size_mb = os.path.getsize(self.db_path) / 1024 / 1024
            if size_mb > MAX_DB_MB_DEFAULT:
                print(f"[memory] ⚠️ 记忆库体积 {size_mb:.1f}MB，超过 {MAX_DB_MB_DEFAULT}MB 阈值")
        except Exception as e:
            print(f"[memory] 写入失败：{e}")

    def recall(self, query: str, top_k: int = 3) -> list[dict]:
        """
        BM25 召回相关记忆。
        enabled=False 时返回空列表。
        返回: [{key, content, source, score}, ...]
        """
        if not self.enabled or not self._conn:
            return []
        try:
            rows = self._conn.execute(
                "SELECT key, content, source FROM memory"
            ).fetchall()
            if not rows:
                return []

            # 简单 BM25：中文按字符切分
            from rank_bm25 import BM25Okapi
            corpus = [_tokenize(r[1]) for r in rows]
            bm25 = BM25Okapi(corpus)
            tokenized_query = _tokenize(query)
            scores = bm25.get_scores(tokenized_query)

            # 取 top_k（含分数为0但含查询词的文档，BM25全命中时IDF可能为0）
            indexed = [(scores[i], rows[i]) for i in range(len(rows))]
            indexed.sort(key=lambda x: x[0], reverse=True)

            results = []
            for score, row in indexed[:top_k]:
                # 接受分数>=0的结果（0分文档可能包含查询词但IDF为0）
                has_hit = score > 0 or any(
                    t in _tokenize(row[1]) for t in tokenized_query
                )
                if has_hit:
                    results.append({
                        "key": row[0],
                        "content": row[1],
                        "source": row[2],
                        "score": round(float(score), 4),
                    })
            return results
        except Exception as e:
            print(f"[memory] 召回失败：{e}")
            return []

    def get_stats(self) -> dict:
        """获取记忆库统计"""
        if not self.enabled:
            return {"enabled": False}
        try:
            count = 0
            size_mb = 0
            if self._conn:
                count = self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
            if os.path.exists(self.db_path):
                size_mb = round(os.path.getsize(self.db_path) / 1024 / 1024, 2)
            return {
                "enabled": True,
                "count": count,
                "size_mb": size_mb,
                "max_mb": MAX_DB_MB_DEFAULT,
                "warning": size_mb > MAX_DB_MB_DEFAULT,
            }
        except Exception as e:
            return {"enabled": True, "count": 0, "size_mb": 0, "error": str(e)}

    def clear(self):
        """清空记忆库"""
        if self._conn:
            self._conn.execute("DELETE FROM memory")
            self._conn.commit()


# ═══════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════

def _tokenize(text: str) -> list[str]:
    """中文按字符切分，英文按空格"""
    tokens = []
    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            tokens.append(ch)
        elif ch.isalnum():
            tokens.append(ch.lower())
    # 也处理英文单词
    import re
    words = re.findall(r'[a-zA-Z]+', text)
    tokens.extend(w.lower() for w in words)
    return tokens if tokens else [text]


def load_memory_from_config(config_path: str = "config.yaml") -> AgentMemory:
    """从 config.yaml 读取 memory.enabled 并初始化"""
    enabled = False
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        enabled = cfg.get("memory", {}).get("enabled", False)
    except Exception:
        pass
    mem = AgentMemory(enabled=enabled)
    mem.initialize()
    return mem
