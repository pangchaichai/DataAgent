#!/usr/bin/env python3
"""DataAgent Windows 内测包构建脚本 (在 Linux 上运行).

生成一个 zip 包，解压后运行 setup.bat 即可离线安装。

用法: python scripts/package_windows.py [--output ./dist]
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 运行时依赖（排除 pyinstaller / pytest） ──────────────────────────
RUNTIME_DEPS = [
    "flask==3.0.3",
    "flask-cors==4.0.1",
    "duckdb==0.10.3",
    "pandas==2.2.2",
    "openpyxl==3.1.2",
    "chardet==5.2.0",
    "pyyaml==6.0.1",
    "jinja2==3.1.4",
    "python-docx==1.1.2",
    "requests==2.32.3",
    "sqlglot==23.12.2",
    "schedule==1.2.1",
    "pypdf>=3.0",
    "duckduckgo-search>=6.0",
    "psutil>=5.9.0",
    "rank_bm25>=0.2.2",
    "pywebview==4.3.3",
    "winotify==1.1.0",
    "pythonnet==3.0.4",        # pywebview 在 Windows 上的硬依赖
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
BUNDLE_VERSION = "v2.0-beta1"


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
    result1 = subprocess.run(cmd1, capture_output=True, text=True, cwd=PROJECT_ROOT)
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
        result2 = subprocess.run(cmd2, capture_output=True, text=True, cwd=PROJECT_ROOT)
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
            result2b = subprocess.run(cmd2b, capture_output=True, text=True, cwd=PROJECT_ROOT)
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

    import email.parser
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
        result3 = subprocess.run(cmd3, capture_output=True, text=True, cwd=PROJECT_ROOT)
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
            result3b = subprocess.run(cmd3b, capture_output=True, text=True, cwd=PROJECT_ROOT)
            if result3b.returncode != 0:
                # 通用下载尝试
                cmd3c = [
                    sys.executable, "-m", "pip", "download",
                    "--no-deps",
                    "--dest", str(deps_dir),
                    dep_spec,
                ]
                result3c = subprocess.run(cmd3c, capture_output=True, text=True, cwd=PROJECT_ROOT)
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
            result3d = subprocess.run(cmd3d, capture_output=True, text=True, cwd=PROJECT_ROOT)
            if result3d.returncode != 0:
                cmd3e = [
                    sys.executable, "-m", "pip", "download",
                    "--no-deps",
                    "--dest", str(deps_dir),
                    dep_spec,
                ]
                result3e = subprocess.run(cmd3e, capture_output=True, text=True, cwd=PROJECT_ROOT)
                if result3e.returncode != 0:
                    print(f"   ⚠️  {dep_spec}: 下载失败")
                else:
                    print(f"   ✅  {dep_spec} (通用版本)")
            else:
                print(f"   ✅  {dep_spec}")

    tmp_req.unlink(missing_ok=True)

    whl_count = len(list(deps_dir.glob("*.whl"))) + len(list(deps_dir.glob("*.tar.gz")))
    print(f"   ✅ 下载完成 ({whl_count} 个文件)")


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

:: 检查 .env
if not exist DataAgent\.env (
    if exist DataAgent\.env.example (
        copy DataAgent\.env.example DataAgent\.env >nul 2>nul
    )
)

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
  安装步骤（首次）
══════════════════════════════════════════════════
  1. 安装 Python 3.11（https://www.python.org/downloads/）
     勾选 "Add Python to PATH"
  2. 双击 setup.bat 等待安装完成
  3. 编辑 config.yaml，填写 LLM API Key 等信息
  4. 双击 run.bat 启动

══════════════════════════════════════════════════
  启动
══════════════════════════════════════════════════
  双击 run.bat

══════════════════════════════════════════════════
  内测说明
══════════════════════════════════════════════════
  本版本为 DataAgent v2.0 Evolution 内测版。
  包含功能：
  • 数据上传（CSV，支持 GB18030/UTF-8 编码）
  • 自然语言查询（探索式分析）
  • 固化计算器（集中度/净值/收益率/杠杆率/流动性等）
  • 图表生成（柱状图/饼图/折线图/散点图）
  • 报告生成（Markdown + Word 导出）
  • 文档解析（Word/PDF/TXT 上传）
  • 联网搜索（可选）
  • 合规监控 + 参谈要点

  反馈请联系：<内部沟通渠道>
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
    print(f"  ✅ 内测包构建完成")
    print(f"  📁 {zip_path}")
    print(f"  📏 大小: {zip_size_mb:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
