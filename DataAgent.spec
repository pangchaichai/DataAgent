# -*- mode: python ; coding: utf-8 -*-
"""DataAgent PyInstaller spec -- Windows onedir packaging (beta v3.0-beta1)

On Windows run:
    pyinstaller DataAgent.spec

Output: dist/DataAgent/DataAgent.exe (PyWebView native window)
"""

import sys
from pathlib import Path

# -- Data files/directories to bundle ----------------------------------
_RAW_DATAS = [
    ('ui', 'ui'),
    ('templates', 'templates'),
    ('skills', 'skills'),
    ('data_dictionary', 'data_dictionary'),
    ('calculators', 'calculators'),
    ('prompts', 'prompts'),
    ('schemas', 'schemas'),
    ('groups.yaml', '.'),
    ('config.example.yaml', '.'),
    ('.env.example', '.'),
]

# Filter out missing files/dirs to avoid PyInstaller build failures
DATAS = []
for src, dst in _RAW_DATAS:
    if Path(src).exists():
        DATAS.append((src, dst))
    else:
        print(f"[WARN] Skipping missing data file: {src}")

# -- Hidden imports PyInstaller might miss -----------------------------
HIDDEN_IMPORTS = [
    'tools.data_loader',
    'sqlglot.dialects',
    'sqlglot.dialects.duckdb',
    'jinja2.ext',
    'pandas.io',
    'pandas.io.sql',
    'docx.opc',
    'docx.oxml',
    'duckduckgo_search',
    'schedule',
    'winotify',
    'pythonnet',
    'clr_loader',
    'psutil._pswindows',
    'chardet',
    'session_store',
    'agent.loop', 'agent.tools_spec', 'agent.llm_client', 'agent.context',
    'agent.planner', 'agent.executor', 'agent.self_check', 'agent.hooks',
    'agent.skill_loader', 'agent.memory', 'agent.tool_dispatch', 'agent.skill_preflight',
    'agent.execution_tracker', 'agent.fast_path', 'agent.tool_defs',
    'api.chat', 'api.data', 'api.config_api', 'api.skill_api', 'api.report_api', 'api.system_api',
    'platform_adapter.ui_driver', 'platform_adapter.notify_driver',
    'scheduler.task_manager',
    'tools.query_runner', 'tools.profiler', 'tools.quality',
    'tools.entity_manager', 'tools.entity_normalizer',
    'tools.report_builder', 'tools.chart_builder',
    'tools.file_reader', 'tools.web_search', 'tools.cost_tracker',
    'tools.notify', 'tools.error_translator', 'tools.compliance_audit',
    'tools.skill_builder', 'tools.runtime_logger',
]

# -- Modules to exclude (reduce bundle size) ---------------------------
EXCLUDES = [
    'pytest', 'unittest', 'test', 'tests',
    'pkg_resources', 'setuptools', 'jaraco', 'pip', 'wheel',
    'tkinter', 'PyQt5', 'PySide2', 'wx',
    'matplotlib', 'scipy', 'PIL', 'cv2',
    'numpy.tests', 'pandas.tests',
]

# ======================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DataAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DataAgent',
)
