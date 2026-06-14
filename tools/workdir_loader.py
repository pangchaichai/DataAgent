"""
tools/workdir_loader.py — 本地工作目录管理

职责：
  1. 读取/写入 config.yaml 中的 app.work_dir 配置
  2. 列出工作目录下的数据文件（CSV/Excel）
  3. 按 file_pattern 匹配工作目录中的候选文件（供 skill_preflight 调用）
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


def get_work_dir() -> Path | None:
    """从 config.yaml 读取工作目录路径，不存在或未配置则返回 None。"""
    try:
        import yaml

        from session_store import BASE_DIR
        cfg_path = BASE_DIR / 'config.yaml'
        src = cfg_path if cfg_path.exists() else BASE_DIR / 'config.example.yaml'
        with open(src, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get('app', {}).get('work_dir', '')
        if raw:
            p = Path(raw)
            if p.is_dir():
                return p
    except Exception:
        pass
    return None


_DATA_EXTENSIONS = {'.csv', '.xlsx', '.xls'}


def list_workdir_files() -> list[dict]:
    """
    列出工作目录下所有数据文件（CSV/Excel）。

    返回:
      [{"filename": "...", "size_kb": ..., "mtime": "YYYY-MM-DD HH:MM"}]
    """
    work_dir = get_work_dir()
    if not work_dir:
        return []

    files = []
    for p in sorted(work_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in _DATA_EXTENSIONS:
            stat = p.stat()
            from datetime import datetime
            files.append({
                "filename": p.name,
                "path": str(p),
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            })
    return files


def scan_for_pattern(file_pattern: str) -> list[dict]:
    """
    在工作目录中查找匹配 file_pattern（fnmatch 格式）的文件。

    与 skill_preflight._find_table 的逻辑对称：
      先精确 fnmatch → 再去通配符子串匹配。

    返回匹配的文件列表（来自 list_workdir_files()）。
    """
    if not file_pattern:
        return []

    all_files = list_workdir_files()
    if not all_files:
        return []

    # 精确 fnmatch
    matches = [f for f in all_files if fnmatch.fnmatch(f['filename'], file_pattern)]
    if matches:
        return matches

    # 去通配符子串匹配
    clean = file_pattern.replace('*', '').replace('?', '')
    if clean:
        matches = [f for f in all_files if clean in f['filename']]
    return matches
