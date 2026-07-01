#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DataAgent Windows 内测包构建脚本 (在 Linux 上运行).

生成一个 zip 包，解压后运行 setup.bat 即可离线安装。

用法: python scripts/package_windows.py [--output ./dist]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _run(cmd: list, cwd=None) -> subprocess.CompletedProcess:
    """运行子进程，强制 UTF-8 编码避免乱码。"""
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=cwd)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 运行时依赖（排除 pyinstaller / pytest） ──────────────────────────
RUNTIME_DEPS = [
    "flask>=3.0.3",
    "flask-cors>=4.0.1",
    "duckdb>=1.0.0",
    "pandas>=2.2.0",
    "openpyxl>=3.1.0",
    "xlrd>=2.0.1",            # .xls格式读取
    "chardet>=5.0.0",
    "pyyaml>=6.0.1",
    "jinja2>=3.1.4",
    "python-docx>=1.1.0",
    "requests>=2.32.0",
    "sqlglot>=23.0.0",
    "schedule>=1.2.0",
    "pypdf>=3.0",
    "duckduckgo-search>=6.0",
    "psutil>=5.9.0",
    "rank_bm25>=0.2.2",
    "pywebview>=4.3.3",
    "winotify>=1.1.0",
    "pythonnet>=3.0.4",        # pywebview 在 Windows 上的硬依赖
    "python-dotenv>=1.0",
]

# ── 打包时复制的项目文件 ──────────────────────────────────────────────
INCLUDE_DIRS = [
    "agent",
    "calculators",
    "data_dictionary",
    "platform_adapter",
    "scheduler",
    "skills",
    "templates",
    "tools",
    "ui",
    "api",
    "prompts",
    "schemas",
]

INCLUDE_FILES = [
    "main.py",
    "session_store.py",
    "config.example.yaml",
    ".env.example",
    "groups.yaml",
]

# ── 打包时排除的文件/目录 ──────────────────────────────────────────────
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    ".git",
    ".gitignore",
    "data/",
    "testdata/",
    "tests/",
    "docs/",
    ".claude/",
    "CLAUDE.md",
    "PROGRESS.md",
    "HANDOFF.md",
    "TESTING.md",
    "requirements-dev.txt",
    "requirements-prod.txt",
    "requirements.txt",
    "pyproject.toml",
    ".ruff.toml",
]

# ── 内测包版本号 ──────────────────────────────────────────────────────
BUNDLE_VERSION = "v3.4"


# ═══════════════════════════════════════════════════════════════════════
# 步骤
# ═══════════════════════════════════════════════════════════════════════

def download_deps(deps_dir: Path) -> None:
    """下载所有依赖 — 两阶段：先解析完整依赖树，再替换 C 扩展包为 Windows 版."""
    print("📦 下载依赖包 ...")
    deps_dir.mkdir(parents=True, exist_ok=True)

    tmp_req = deps_dir.parent / "_tmp_bundle_reqs.txt"
    tmp_req.write_text("\n".join(RUNTIME_DEPS))

    # ── 阶段 1：无平台限制下载，解析完整依赖树 ──────────────────────────
    # 这会下载当前平台（Linux）的 wheel/sdist。
    # 纯 Python 包（py3-none-any / sdist）跨平台通用，直接可用。
    # C 扩展包（duckdb, pandas, psutil）下载的是 Linux 版，阶段 2 替换。
    print("   阶段 1/2: 解析依赖树（当前平台）...")
    cmd1 = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(deps_dir),
        "-r", str(tmp_req),
    ]
    result1 = _run(cmd1, cwd=PROJECT_ROOT)
    if result1.returncode != 0:
        print("❌ 阶段 1 失败：")
        print(result1.stderr)
        tmp_req.unlink(missing_ok=True)
        sys.exit(1)

    # ── 阶段 2：下载 C 扩展包的 Windows 版本（覆盖 Linux 版） ────────────
    # 扫描阶段 1 下载的所有 Linux 专用 wheel，提取「包名==版本」，
    # 然后精确下载对应 Windows 版本。
    print("   阶段 2/2: 替换为 Windows 原生包 ...")

    def parse_wheel_pkg(filename: str) -> tuple[str, str] | None:
        """从 wheel 文件名提取 (包名, 版本). 例: numpy-2.4.6-cp311-... → ('numpy', '2.4.6')"""
        stem = filename.replace(".whl", "")
        parts = stem.split("-")
        # 找到版本号开始位置（第一个以数字开头的 part）
        pkg_parts = []
        version_idx = None
        for i, p in enumerate(parts):
            if p and p[0].isdigit():
                version_idx = i
                break
            pkg_parts.append(p)
        if version_idx is None:
            return None
        pkg_name = "-".join(pkg_parts)
        version = parts[version_idx]
        return pkg_name, version

    # 扫描 Linux wheel，收集需要替换的「包名==版本」
    to_replace: dict[str, str] = {}  # pkg_name → version
    for w in deps_dir.glob("*.whl"):
        name = w.name
        # 跳过已是 Windows wheel 的
        if "win_amd64" in name or "win32" in name:
            continue
        # 跳过纯 Python wheel（py3-none-any 或 py2.py3-none-any）
        if "none-any" in name:
            continue
        # 剩余的是平台特定 wheel → 需要 Windows 版本
        parsed = parse_wheel_pkg(name)
        if parsed:
            pkg_name, version = parsed
            if pkg_name not in to_replace:
                to_replace[pkg_name] = version

    for pkg_name, version in sorted(to_replace.items()):
        pkg_spec = f"{pkg_name}=={version}"
        cmd2 = [
            sys.executable, "-m", "pip", "download",
            "--platform", "win_amd64",
            "--python-version", "3.11",
            "--implementation", "cp",
            "--only-binary=:all:",
            "--no-deps",
            "--dest", str(deps_dir),
            pkg_spec,
        ]
        result2 = _run(cmd2, cwd=PROJECT_ROOT)
        if result2.returncode != 0:
            # 尝试无 --only-binary
            cmd2b = [
                sys.executable, "-m", "pip", "download",
                "--platform", "win_amd64",
                "--python-version", "3.11",
                "--implementation", "cp",
                "--no-deps",
                "--dest", str(deps_dir),
                pkg_spec,
            ]
            result2b = _run(cmd2b, cwd=PROJECT_ROOT)
            if result2b.returncode != 0:
                print(f"   ⚠️  {pkg_spec}: Windows wheel 不可用，保留通用版本")

    # 清理被替换的 Linux wheel（避免 pip 在 Windows 上回溯评估不兼容版本）
    for w in deps_dir.glob("*.whl"):
        name = w.name
        if "manylinux" in name or "linux" in name:
            # 检查是否有对应的 Windows wheel 或 none-any wheel
            parsed = parse_wheel_pkg(name)
            if parsed:
                pkg_name, version = parsed
                # 搜索同名同版本的 Windows 替代品
                win_pattern = f"{pkg_name}-{version}-"
                has_win = any(
                    (win_pattern in whl.name and ("win" in whl.name.lower() or "none-any" in whl.name))
                    for whl in deps_dir.glob("*.whl")
                    if whl != w
                )
                if has_win:
                    w.unlink()

    # ── 阶段 3：扫描所有依赖的 Windows-only 条件依赖 ────────────────
    # 阶段 1 在 Linux 上解析依赖树时跳过了 sys_platform=="win32" 等条件依赖。
    # 这里扫描 deps/ 中每个包的 METADATA，提取 Windows 专属传递依赖并下载。
    print("   阶段 3/3: 补充 Windows 专属传递依赖 ...")

    import zipfile as zf_mod

    windows_only_deps: dict[str, str] = {}  # pkg_name → requirement spec

    for whl in list(deps_dir.glob("*.whl")):
        try:
            with zf_mod.ZipFile(str(whl), "r") as z:
                # 查找 METADATA 文件
                meta_names = [n for n in z.namelist() if n.endswith("/METADATA") or n.endswith(".dist-info/METADATA")]
                if not meta_names:
                    continue
                meta_bytes = z.read(meta_names[0])
                meta_text = meta_bytes.decode("utf-8", errors="replace")
                # 解析 requires-dist 条目
                for line in meta_text.split("\n"):
                    line = line.strip()
                    if not line.lower().startswith("requires-dist:"):
                        continue
                    # 提取依赖和条件
                    req_str = line.split(":", 1)[1].strip()
                    # 检查是否是 Windows 专属依赖
                    if "sys_platform == \"win32\"" in req_str or \
                       "platform_system == \"Windows\"" in req_str:
                        parts = req_str.split(";")[0].strip()
                        dep_name = parts.split(">=")[0].split("==")[0].split("<=")[0].split("~=")[0].split("!=")[0].split("<")[0].split(">")[0].strip()
                        if dep_name not in windows_only_deps:
                            windows_only_deps[dep_name] = parts
        except Exception:
            continue

    # 也检查 tar.gz 源码包
    for sdist in deps_dir.glob("*.tar.gz"):
        try:
            import tarfile
            with tarfile.open(str(sdist), "r:gz") as tf:
                for member in tf.getmembers():
                    if member.name.endswith("PKG-INFO") or member.name.endswith("METADATA"):
                        f = tf.extractfile(member)
                        if f:
                            meta_text = f.read().decode("utf-8", errors="replace")
                            for line in meta_text.split("\n"):
                                line = line.strip()
                                if not line.lower().startswith("requires-dist:"):
                                    continue
                                req_str = line.split(":", 1)[1].strip()
                                if "sys_platform == \"win32\"" in req_str or \
                                   "platform_system == \"Windows\"" in req_str:
                                    parts = req_str.split(";")[0].strip()
                                    dep_name = parts.split(">=")[0].split("==")[0].split("<=")[0].split("~=")[0].split("!=")[0].split("<")[0].split(">")[0].strip()
                                    if dep_name not in windows_only_deps:
                                        windows_only_deps[dep_name] = parts
        except Exception:
            continue

    # 已存在于 deps/ 中的包名
    existing_pkgs = set()
    for w in deps_dir.glob("*.whl"):
        parsed = parse_wheel_pkg(w.name)
        if parsed:
            existing_pkgs.add(parsed[0])
    for tar in deps_dir.glob("*.tar.gz"):
        existing_pkgs.add(tar.name.split("-")[0])

    # 已知需要但可能不在 METADATA 中的 Windows 专属包（兜底）
    if "colorama" not in existing_pkgs:
        windows_only_deps["colorama"] = "colorama"

    for dep_name, dep_spec in sorted(windows_only_deps.items()):
        if dep_name in existing_pkgs:
            continue
        # 尝试下载 Windows 版本
        cmd3 = [
            sys.executable, "-m", "pip", "download",
            "--platform", "win_amd64",
            "--python-version", "3.11",
            "--implementation", "cp",
            "--only-binary=:all:",
            "--no-deps",
            "--dest", str(deps_dir),
            dep_spec,
        ]
        result3 = _run(cmd3, cwd=PROJECT_ROOT)
        if result3.returncode != 0:
            # 回退：不强制 binary
            cmd3b = [
                sys.executable, "-m", "pip", "download",
                "--platform", "win_amd64",
                "--python-version", "3.11",
                "--implementation", "cp",
                "--no-deps",
                "--dest", str(deps_dir),
                dep_spec,
            ]
            result3b = _run(cmd3b, cwd=PROJECT_ROOT)
            if result3b.returncode != 0:
                # 通用下载尝试
                cmd3c = [
                    sys.executable, "-m", "pip", "download",
                    "--no-deps",
                    "--dest", str(deps_dir),
                    dep_spec,
                ]
                result3c = _run(cmd3c, cwd=PROJECT_ROOT)
                if result3c.returncode != 0:
                    print(f"   ⚠️  {dep_name}: Windows 专属依赖下载失败")
                else:
                    print(f"   ✅  {dep_name} (通用版本)")
            else:
                print(f"   ✅  {dep_name}")
        else:
            print(f"   ✅  {dep_name}")

    # 也检查 RUNTIME_DEPS 中顶层缺失的包（兜底）
    for dep in RUNTIME_DEPS:
        pkg = dep.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip()
        if pkg not in existing_pkgs and pkg not in windows_only_deps:
            dep_spec = dep
            cmd3d = [
                sys.executable, "-m", "pip", "download",
                "--platform", "win_amd64",
                "--python-version", "3.11",
                "--implementation", "cp",
                "--only-binary=:all:",
                "--no-deps",
                "--dest", str(deps_dir),
                dep_spec,
            ]
            result3d = _run(cmd3d, cwd=PROJECT_ROOT)
            if result3d.returncode != 0:
                cmd3e = [
                    sys.executable, "-m", "pip", "download",
                    "--no-deps",
                    "--dest", str(deps_dir),
                    dep_spec,
                ]
                result3e = _run(cmd3e, cwd=PROJECT_ROOT)
                if result3e.returncode != 0:
                    print(f"   ⚠️  {dep_spec}: 下载失败")
                else:
                    print(f"   ✅  {dep_spec} (通用版本)")
            else:
                print(f"   ✅  {dep_spec}")

    # ── 下载 WebView2 Runtime（离线安装包） ────────────────────
    _download_webview2_runtime(deps_dir)

    tmp_req.unlink(missing_ok=True)

    whl_count = len(list(deps_dir.glob("*.whl"))) + len(list(deps_dir.glob("*.tar.gz")))
    whl_count += 1 if any(deps_dir.glob("MicrosoftEdgeWebView2RuntimeInstallerX64.exe")) else 0
    print(f"   ✅ 下载完成 ({whl_count} 个文件)")


def _download_webview2_runtime(deps_dir: Path) -> None:
    """下载 WebView2 Runtime 离线安装包（约 130MB，内网无需联网）。

    优先尝试程序化下载；失败时打印清晰的手动下载指引。
    Microsoft 不提供永久固定 URL，以下为当前有效地址（需定期更新）。
    """
    import urllib.request
    installer = deps_dir / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
    if installer.exists():
        print(f"   ✅ WebView2 离线安装包已存在 ({installer.stat().st_size / 1024 / 1024:.0f} MB)")
        return

    # WebView2 Evergreen Standalone Installer (x64, 离线)
    # Microsoft 官方固定转发链接，永久有效
    urls = [
        "https://go.microsoft.com/fwlink/p/?LinkId=2124700",  # 官方文档: Evergreen Standalone Installer x64
    ]
    downloaded = False
    for url in urls:
        try:
            print(f"   ⬇ 下载 WebView2 Runtime 离线安装包（约 130MB，请等待）...")
            urllib.request.urlretrieve(url, str(installer))
            downloaded = True
            break
        except Exception:
            continue

    if not downloaded:
        print("")
        print("   ╔══════════════════════════════════════════════════════════╗")
        print("   ║  ⚠️  WebView2 Runtime 离线安装包下载失败                ║")
        print("   ║                                                          ║")
        print("   ║  请手动下载并放入 deps/ 目录后重新构建：                 ║")
        print("   ║                                                          ║")
        print("   ║  1. 打开 https://developer.microsoft.com/microsoft-edge/webview2/")
        print("   ║  2. 找到「Evergreen Standalone Installer」→ 下载 X64 版本")
        print("   ║  3. 重命名为 MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
        print("   ║  4. 放入当前 deps/ 目录                                   ║")
        print("   ║                                                          ║")
        print("   ║  包体积将从 50MB 增长至约 180MB（含离线 Runtime）         ║")
        print("   ╚══════════════════════════════════════════════════════════╝")
        print("")
        return

    size_mb = installer.stat().st_size / 1024 / 1024
    print(f"   ✅ WebView2 Runtime 离线安装包 ({size_mb:.0f} MB)")


def copy_project(bundle_src: Path) -> None:
    """复制项目源码到打包目录."""
    print("📁 复制项目文件 ...")

    for d in INCLUDE_DIRS:
        src = PROJECT_ROOT / d
        if not src.exists():
            continue
        dst = bundle_src / d
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns(*EXCLUDE_PATTERNS),
            dirs_exist_ok=True,
        )

    for f in INCLUDE_FILES:
        src = PROJECT_ROOT / f
        if src.exists():
            shutil.copy2(src, bundle_src / f)

    # 确保运行时数据目录在代码中有占位（Flask 需要 outputs/）
    for sub in ["data/uploads", "data/outputs", "data/sessions",
                "data/compliance_audit", "data/logs", "data/skill_drafts"]:
        (bundle_src / sub).mkdir(parents=True, exist_ok=True)
        (bundle_src / sub / ".gitkeep").write_text("")

    print("   ✅ 项目文件复制完成")


SETUP_BAT = r"""@echo off
title DataAgent 安装

echo.
echo ============================================================
echo      DataAgent %VERSION% 内测版 - 安装程序
echo ============================================================
echo.

:: 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.11
    echo.
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [检测] Python 版本: %PYVER%
echo.

:: 安装 WebView2 Runtime — 先检测是否已装，避免重复安装
set NEED_WEBVIEW2=1
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1
if %ERRORLEVEL% EQU 0 set NEED_WEBVIEW2=0
reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1
if %ERRORLEVEL% EQU 0 set NEED_WEBVIEW2=0
:: 也可通过 Edge 浏览器间接检测
if exist "C:\Program Files (x86)\Microsoft\EdgeWebView\Application" set NEED_WEBVIEW2=0
if exist "C:\Program Files\Microsoft\EdgeWebView\Application" set NEED_WEBVIEW2=0

if %NEED_WEBVIEW2% EQU 1 (
    if exist deps\MicrosoftEdgeWebView2RuntimeInstallerX64.exe (
        echo [安装] Microsoft Edge WebView2 Runtime（离线包，约需 1 分钟）...
        deps\MicrosoftEdgeWebView2RuntimeInstallerX64.exe /silent /install
        if %ERRORLEVEL% EQU 0 (
            echo [完成] WebView2 Runtime 安装成功
        ) else (
            echo [提示] WebView2 Runtime 安装失败，将使用浏览器模式运行
        )
    ) else if exist deps\MicrosoftEdgeWebview2Setup.exe (
        echo [安装] Microsoft Edge WebView2 Runtime（在线包）...
        deps\MicrosoftEdgeWebview2Setup.exe /silent /install
        if %ERRORLEVEL% EQU 0 (
            echo [完成] WebView2 Runtime 安装成功
        ) else (
            echo [提示] WebView2 Runtime 安装失败，将使用浏览器模式运行
        )
    ) else (
        echo [提示] 未找到 WebView2 Runtime 安装包，将使用浏览器模式运行
    )
) else (
    echo [跳过] WebView2 Runtime 已安装
)
echo.

:: 创建虚拟环境
if exist .venv (
    echo [跳过] .venv 已存在
) else (
    echo [创建] 虚拟环境 ...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

:: 激活虚拟环境并安装依赖
echo [安装] 依赖包（离线模式）...
call .venv\Scripts\activate.bat
pip install --no-index --find-links=deps\ -r requirements-bundle.txt
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: 检查配置文件（main.py 从 DataAgent/ 目录读取 config.yaml）
if not exist DataAgent\config.yaml (
    echo [提示] 未找到 config.yaml，从 config.example.yaml 自动创建
    if exist DataAgent\config.example.yaml (
        copy DataAgent\config.example.yaml DataAgent\config.yaml >nul
    )
)

:: .env 仅在用户需要环境变量覆盖 config.yaml 时手动创建
:: 不再自动复制 .env.example，避免占位符覆盖 config.yaml 中的真实 API Key

:: 创建运行时需要的空目录
if not exist DataAgent\data mkdir DataAgent\data
if not exist DataAgent\data\uploads mkdir DataAgent\data\uploads
if not exist DataAgent\data\outputs mkdir DataAgent\data\outputs
if not exist DataAgent\data\sessions mkdir DataAgent\data\sessions
if not exist DataAgent\data\logs mkdir DataAgent\data\logs
if not exist DataAgent\data\compliance_audit mkdir DataAgent\data\compliance_audit
if not exist DataAgent\data\skill_drafts mkdir DataAgent\data\skill_drafts

echo.
echo ============================================================
echo   安装完成！
echo   请先编辑 DataAgent\config.yaml 填写 LLM API Key
echo   然后双击 run.bat 启动
echo ============================================================
echo.
pause
"""

RUN_BAT = r"""@echo off
title DataAgent

:: 检查 .venv 是否存在
if not exist .venv (
    echo [错误] 未找到 .venv，请先运行 setup.bat 安装
    pause
    exit /b 1
)

:: 检查配置文件
if not exist DataAgent\config.yaml (
    echo [提示] 请先编辑 DataAgent\config.yaml 填写 LLM API Key
    pause
    exit /b 1
)

:: 激活虚拟环境并启动
call .venv\Scripts\activate.bat
cd DataAgent
python main.py
pause
"""

README_TXT = """DataAgent %VERSION% — Windows 内测版

══════════════════════════════════════════════════
  系统要求
══════════════════════════════════════════════════
  • Windows 10 / 11（64 位）
  • Python 3.11（必须）
  • 4 GB+ RAM
  • WebView2 Runtime（Windows 11 自带，Windows 10 可能需要安装）

══════════════════════════════════════════════════
  方式一：直接运行（推荐内测使用）
══════════════════════════════════════════════════
  1. 安装 Python 3.11（https://www.python.org/downloads/）
     勾选 "Add Python to PATH"
  2. 双击 setup.bat 等待安装完成
  3. 编辑 DataAgent\\config.yaml，填写 LLM 配置
  4. 双击 run.bat 启动

══════════════════════════════════════════════════
  方式二：打包为 EXE（分发部署使用）
══════════════════════════════════════════════════
  1. 先完成方式一的步骤 1-3（setup.bat 安装依赖）
  2. 双击 build_exe.bat 等待打包完成（约 3-5 分钟）
  3. 打包结果在 output\\DataAgent\\ 目录
  4. 将 output\\DataAgent\\ 整个目录复制到目标机器
  5. 目标机器上双击 DataAgent.exe 启动
  注意：
  • 打包产物约 200-300 MB（含 Python 运行时和所有依赖）
  • 首次启动会自动创建 data/ 目录
  • config.yaml 需放在 DataAgent.exe 同级目录下

══════════════════════════════════════════════════
  配置 LLM（必须）
══════════════════════════════════════════════════
  编辑 DataAgent\\config.yaml 的 llm 区块：

  企业内网 LLM：
    sql_gen.primary: enterprise_internal
    enterprise_internal.url: http://[网关代理地址]:8081/v1
    enterprise_internal.model: [企业模型名称]

  DeepSeek（外部）：
    sql_gen.primary: deepseek
    deepseek.api_key: 你的API Key

  本地 LM Studio：
    sql_gen.primary: lmstudio
    （先启动 LM Studio 的 Local Server）

══════════════════════════════════════════════════
  v3.0-beta3 变更日志
══════════════════════════════════════════════════
  • 修复企业内网 LLM 调用失败（网关响应格式适配）
  • 修复 Agent 编造产品名称（两层反幻觉压缩架构）
  • 增强运行日志（LLM 调用始终记录，含原始响应预览）
  • 新增 PyInstaller 打包支持（build_exe.bat）
  • 615 个自动化测试全部通过

  反馈请联系：<内部沟通渠道>
"""


# ── PyInstaller build 脚本 ──────────────────────────────────────────────

BUILD_EXE_BAT = r"""@echo off
title DataAgent - 打包 EXE
chcp 65001 >nul 2>&1

echo.
echo ============================================================
echo      DataAgent EXE 打包工具
echo ============================================================
echo.

:: 检查虚拟环境
if not exist .venv (
    echo [错误] 请先运行 setup.bat 安装依赖
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

:: 安装 PyInstaller（如果没有）
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [安装] PyInstaller ...
    pip install pyinstaller>=6.6.0
)

echo.
echo [打包] 正在构建 DataAgent.exe ...
echo        （这可能需要 3-5 分钟，请耐心等待）
echo.

:: 使用 spec 文件打包
pyinstaller DataAgent\dataagent.spec --noconfirm

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 打包失败，请查看上方错误信息
    pause
    exit /b 1
)

:: 复制配置文件到输出目录
if not exist output\DataAgent\config.yaml (
    if exist DataAgent\config.yaml (
        copy DataAgent\config.yaml output\DataAgent\config.yaml >nul
    ) else if exist DataAgent\config.example.yaml (
        copy DataAgent\config.example.yaml output\DataAgent\config.yaml >nul
    )
)

:: 复制 WebView2 Runtime 到输出目录（EXE 首次启动时自动安装）
if not exist output\DataAgent\deps mkdir output\DataAgent\deps
if exist deps\MicrosoftEdgeWebView2RuntimeInstallerX64.exe (
    copy deps\MicrosoftEdgeWebView2RuntimeInstallerX64.exe output\DataAgent\deps\ >nul
)
if exist deps\MicrosoftEdgeWebview2Setup.exe (
    copy deps\MicrosoftEdgeWebview2Setup.exe output\DataAgent\deps\ >nul
)

echo.
echo ============================================================
echo   打包完成！
echo   输出目录: output\DataAgent\
echo   启动文件: output\DataAgent\DataAgent.exe
echo.
echo   部署方式:
echo     将 output\DataAgent\ 整个文件夹复制到目标机器
echo     编辑 config.yaml 配置 LLM
echo     双击 DataAgent.exe 启动（首次启动会自动安装 WebView2）
echo.
echo   提示：目标机器如为 Windows 10，首次启动可能需要
echo         1-2 分钟安装 WebView2 Runtime，请耐心等待。
echo         如仍无法启动，系统将自动在浏览器中打开。
echo ============================================================
echo.
pause
"""

PYINSTALLER_SPEC = r"""# -*- mode: python ; coding: utf-8 -*-
# DataAgent PyInstaller spec 文件
# 用法: pyinstaller dataagent.spec --noconfirm

import os
import sys

block_cipher = None

# 项目根目录 — 使用 SPECPATH（spec 文件所在目录，即 DataAgent/ 子目录）
PROJECT_ROOT = SPECPATH

a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        # UI 文件
        ('ui', 'ui'),
        # 数据字典
        ('data_dictionary', 'data_dictionary'),
        # 报告模板
        ('templates', 'templates'),
        # Skills 定义
        ('skills', 'skills'),
        # Prompt 模板
        ('prompts', 'prompts'),
        # 配置模板
        ('config.example.yaml', '.'),
        # groups.yaml
        ('groups.yaml', '.'),
        # WebView2 Runtime 离线安装包（内网免联网，约130MB）
        ('../deps/MicrosoftEdgeWebView2RuntimeInstallerX64.exe', 'deps'),
        # 兼容：如只有在线 bootstrapper 也包含
        ('../deps/MicrosoftEdgeWebview2Setup.exe', 'deps'),
    ],
    hiddenimports=[
        # Flask 相关
        'flask', 'flask_cors',
        # 数据引擎
        'duckdb', 'pandas', 'openpyxl',
        # 工具链
        'chardet', 'yaml', 'jinja2', 'docx', 'sqlglot',
        'requests', 'schedule', 'pypdf',
        # Windows 专属
        'webview', 'winotify',
        'clr_loader', 'pythonnet',
        # 系统
        'psutil', 'rank_bm25',
        # 项目模块（确保被收集）
        'agent', 'agent.loop', 'agent.llm_client', 'agent.context',
        'agent.planner', 'agent.executor', 'agent.self_check',
        'agent.hooks', 'agent.skill_loader', 'agent.skill_preflight',
        'agent.tool_defs', 'agent.tool_dispatch', 'agent.tools_spec',
        'agent.fast_path', 'agent.memory', 'agent.execution_tracker',
        'calculators', 'calculators.columns',
        'calculators.concentration', 'calculators.nav_metrics',
        'calculators.asset_structure', 'calculators.credit_distribution',
        'calculators.leverage', 'calculators.liquidity',
        'calculators.position_diff',
        'tools', 'tools.data_loader', 'tools.query_runner',
        'tools.profiler', 'tools.quality',
        'tools.report_builder', 'tools.chart_builder',
        'tools.file_reader', 'tools.web_search',
        'tools.cost_tracker', 'tools.runtime_logger',
        'tools.error_translator', 'tools.compliance_audit',
        'tools.entity_manager', 'tools.entity_normalizer',
        'tools.skill_builder', 'tools.notify',
        'tools.workdir_loader',
        'platform_adapter', 'platform_adapter.ui_driver',
        'platform_adapter.notify_driver',
        'session_store',
        'api', 'api.chat', 'api.data', 'api.config_api',
        'api.skill_api', 'api.report_api', 'api.system_api',
        'scheduler', 'scheduler.task_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'pytest_cov', 'coverage',
        'tkinter', 'matplotlib', 'scipy', 'numpy.testing',
        'IPython', 'notebook', 'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=False,           # 无控制台窗口（PyWebView 提供 UI）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_ROOT, 'ui', 'img', 'dataagent.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DataAgent',
)
"""


def write_scripts(bundle_root: Path) -> None:
    """写入启动脚本和说明文件."""
    print("📝 生成启动脚本 ...")

    version = BUNDLE_VERSION

    (bundle_root / "setup.bat").write_text(
        SETUP_BAT.replace("%VERSION%", version).replace("\n", "\r\n"), encoding="gbk"
    )
    (bundle_root / "run.bat").write_text(
        RUN_BAT.replace("\n", "\r\n"), encoding="gbk"
    )
    (bundle_root / "README.txt").write_text(
        README_TXT.replace("%VERSION%", version), encoding="utf-8"
    )

    # 写入 bundle 专用的 requirements 文件
    req_path = bundle_root / "requirements-bundle.txt"
    req_path.write_text("\n".join(RUNTIME_DEPS))

    # PyInstaller 打包脚本（使用 UTF-8 编码以匹配 chcp 65001）
    (bundle_root / "build_exe.bat").write_text(
        BUILD_EXE_BAT.replace("\n", "\r\n"), encoding="utf-8"
    )

    # PyInstaller spec 文件（放在 DataAgent/ 子目录中，与源码同级）
    proj_dir = bundle_root / "DataAgent"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "dataagent.spec").write_text(
        PYINSTALLER_SPEC, encoding="utf-8"
    )

    print("   ✅ 脚本生成完成")


def main():
    parser = argparse.ArgumentParser(description="构建 DataAgent Windows 内测包")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "dist"),
                        help="输出目录 (默认: ./dist)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle_name = f"DataAgent-{BUNDLE_VERSION}"
    bundle_root = output_dir / bundle_name
    deps_dir = bundle_root / "deps"
    bundle_src = bundle_root / "DataAgent"
    zip_path = output_dir / f"{bundle_name}.zip"

    # 清理旧文件
    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    if zip_path.exists():
        zip_path.unlink()

    print("=" * 60)
    print(f"  DataAgent Windows 内测包构建 - {BUNDLE_VERSION}")
    print("=" * 60)
    print()

    # Step 1: 下载依赖
    download_deps(deps_dir)

    # Step 2: 复制项目文件
    copy_project(bundle_src)

    # Step 3: 生成脚本
    write_scripts(bundle_root)

    # Step 4: 打包 zip
    print("📦 打包 zip ...")
    shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=str(output_dir),
        base_dir=bundle_name,
    )
    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)

    # 清理临时目录
    shutil.rmtree(bundle_root)

    print()
    print("=" * 60)
    print("  ✅ 内测包构建完成")
    print(f"  📁 {zip_path}")
    print(f"  📏 大小: {zip_size_mb:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
