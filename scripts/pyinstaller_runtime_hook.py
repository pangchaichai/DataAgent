"""PyInstaller runtime hook — 在应用启动前创建必要的运行时目录和配置文件.

用法：在 .spec 文件中添加:
    runtime_hooks=['scripts/pyinstaller_runtime_hook.py']
"""

import os
import shutil
import sys
from pathlib import Path


def _ensure_dirs():
    """确保运行时数据目录存在（PyInstaller bundle 中）"""
    # PyInstaller bundle 的基准目录
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent

    dirs = [
        'data/uploads',
        'data/outputs',
        'data/sessions',
        'data/compliance_audit',
        'data/logs',
        'data/skill_drafts',
    ]

    for d in dirs:
        p = base / d
        p.mkdir(parents=True, exist_ok=True)


def _ensure_config():
    """首次启动时自动从 config.example.yaml 创建 config.yaml"""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent

    cfg_path = base / 'config.yaml'
    example_path = base / 'config.example.yaml'

    if not cfg_path.exists() and example_path.exists():
        shutil.copy2(example_path, cfg_path)


_ensure_dirs()
_ensure_config()
