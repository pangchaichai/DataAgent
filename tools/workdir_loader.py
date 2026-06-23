"""
tools/workdir_loader.py — 本地工作目录管理

职责：
  1. 读取/写入 config.yaml 中的 app.work_dir 配置
  2. 列出工作目录下的数据文件（CSV/Excel）
  3. 按 file_pattern 匹配工作目录中的候选文件（供 skill_preflight 调用）
  4. 启动时自动加载工作目录中的数据文件（auto_load）
"""

from __future__ import annotations

import fnmatch
import os
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


def auto_load_workdir(config: dict) -> list[dict]:
    """
    启动时自动加载工作目录中的数据文件。

    流程：
      1. 读取 config.app.auto_load.file_rules
      2. 对每个规则匹配工作目录文件
      3. 增量检测：已加载且 mtime 未变 → 跳过
      4. 调用 load_file() 加载
      5. 按 max_versions 淘汰旧版本

    返回已加载的文件列表 [{"filename", "table_name", "table_type", "rows"}]
    """
    from tools.data_loader import (
        _loaded_tables,
        evict_old_versions,
        extract_date_from_filename,
        load_file,
    )

    auto_cfg = config.get('app', {}).get('auto_load', {})
    if not auto_cfg.get('enabled', False):
        return []

    work_dir = get_work_dir()
    if not work_dir:
        return []

    file_rules = auto_cfg.get('file_rules', [])
    max_versions = auto_cfg.get('max_versions', 3)
    all_files = list_workdir_files()
    loaded: list[dict] = []

    for rule in file_rules:
        pattern = rule.get('pattern', '')
        table_type = rule.get('table_type', 'unknown')
        sheet_select = rule.get('sheet_select')
        sheet_mode = rule.get('sheet_mode')

        if sheet_mode == 'merge_all':
            sheet_select = None
        elif sheet_select is None:
            pass

        matched = [f for f in all_files if fnmatch.fnmatch(f['filename'], pattern)]
        if not matched:
            clean = pattern.replace('*', '').replace('?', '').replace('[', '').replace(']', '')
            if clean:
                matched = [f for f in all_files if clean in f['filename']]

        for file_info in matched:
            file_path = file_info['path']
            filename = file_info['filename']

            date_tag = extract_date_from_filename(filename)
            stem = Path(filename).stem.replace('-', '_').replace('.', '_').replace(' ', '_')
            table_name = f"{table_type}_{date_tag}" if date_tag else f"{table_type}_{stem}"

            existing = _loaded_tables.get(table_name)
            if existing and existing.file_path == file_path:
                try:
                    current_mtime = os.path.getmtime(file_path)
                    cached_mtime = os.path.getmtime(existing.file_path)
                    if current_mtime <= cached_mtime:
                        continue
                except OSError:
                    continue

            try:
                result = load_file(
                    file_path, table_name,
                    date_tag=date_tag,
                    table_type=table_type,
                    sheet_select=sheet_select,
                )
                loaded.append({
                    "filename": filename,
                    "table_name": result.table_name,
                    "table_type": table_type,
                    "rows": result.row_count,
                })
            except Exception as e:
                print(f"[auto_load] ⚠️ 加载失败 {filename}: {e}")

        if max_versions > 0:
            evict_old_versions(table_type, max_versions)

    return loaded
