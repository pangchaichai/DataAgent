#!/usr/bin/env python3
"""DataAgent macOS 内测包构建脚本（在 Linux/macOS 上运行）.

生成一个 zip 包，解压后运行 setup.sh 即可安装。

用法: python scripts/package_mac.py [--output ./dist]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 运行时依赖（macOS，排除 winotify / PyInstaller） ─────────────────
RUNTIME_DEPS = [
    "flask>=3.0.3",
    "flask-cors>=4.0.1",
    "duckdb>=1.0.0",
    "pandas>=2.2.0",
    "openpyxl>=3.1.0",
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
    "pywebview>=4.3.3",        # macOS 原生窗口（可选，缺失时回退浏览器）
    "python-dotenv>=1.0",
]

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
    "scripts/",
]

BUNDLE_VERSION = "v3.0-beta1"

# ═══════════════════════════════════════════════════════════════════════

SETUP_SH = f"""\
#!/bin/bash
set -e
echo ""
echo "============================================================"
echo "    DataAgent {BUNDLE_VERSION} 内测版 - macOS 安装程序"
echo "============================================================"
echo ""

# 检查 Python 版本（支持 3.11 / 3.12 / 3.13）
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.11+"
    echo ""
    echo "推荐：brew install python@3.13"
    echo " 或 https://www.python.org/downloads/"
    exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{{print $2}}')
PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
PYMINOR=$(echo "$PYVER" | cut -d. -f2)
echo "[检测] Python 版本: $PYVER"

SUPPORTED=0
for v in 11 12 13; do
    if [ "$PYMAJOR" = "3" ] && [ "$PYMINOR" = "$v" ]; then
        SUPPORTED=1
        break
    fi
done

if [ "$SUPPORTED" = "0" ]; then
    echo ""
    echo "[错误] 此内测包支持 Python 3.11 / 3.12 / 3.13，当前版本: $PYVER"
    echo "       请使用受支持的 Python 版本后重试："
    echo ""
    echo "         brew install python@3.13"
    echo "         python3.13 -m venv .venv"
    echo "         source .venv/bin/activate"
    echo "         ./setup.sh"
    exit 1
fi
echo ""

# 创建虚拟环境
if [ -d ".venv" ]; then
    echo "[跳过] .venv 已存在"
else
    echo "[创建] 虚拟环境 ..."
    python3 -m venv .venv
fi

# 激活并安装
echo "[安装] 依赖包（离线模式）..."
source .venv/bin/activate
pip install --no-index --find-links=deps/ -r requirements-bundle.txt

# 配置文件
if [ ! -f "DataAgent/config.yaml" ]; then
    echo "[提示] 从 config.example.yaml 创建初始 config.yaml"
    cp DataAgent/config.example.yaml DataAgent/config.yaml
fi

# 运行时数据目录
mkdir -p DataAgent/data/{{uploads,outputs,sessions,compliance_audit,logs,skill_drafts}}

# 赋予运行脚本执行权限
chmod +x run.sh

echo ""
echo "============================================================"
echo "  安装完成！"
echo "  请先编辑 DataAgent/config.yaml 填写 LLM API Key"
echo "  然后运行:  ./run.sh"
echo "============================================================"
echo ""
"""

RUN_SH = """\
#!/bin/bash
set -e

if [ ! -d ".venv" ]; then
    echo "[错误] 未找到 .venv，请先运行 setup.sh"
    exit 1
fi

if [ ! -f "DataAgent/config.yaml" ]; then
    echo "[提示] 请先编辑 DataAgent/config.yaml 填写 LLM API Key"
    exit 1
fi

source .venv/bin/activate
cd DataAgent
python3 main.py
"""

README_TXT = f"""\
DataAgent {BUNDLE_VERSION} — macOS 内测版

══════════════════════════════════════════════════
  系统要求
══════════════════════════════════════════════════
  • macOS 12 Monterey 或更新版本
  • Python 3.11 / 3.12 / 3.13
  • 4 GB+ RAM

══════════════════════════════════════════════════
  安装步骤（首次）
══════════════════════════════════════════════════
  1. 打开终端，进入解压目录：
       cd DataAgent-{BUNDLE_VERSION}

  2. 运行安装脚本：
       ./setup.sh

  3. 编辑配置文件，填写 LLM API Key：
       open DataAgent/config.yaml
       （或用文本编辑器打开 DataAgent/config.yaml）

  4. 启动应用：
       ./run.sh

══════════════════════════════════════════════════
  首次运行说明
══════════════════════════════════════════════════
  • 应用启动后会自动在默认浏览器打开界面
  • 若安装了 pywebview，则以原生窗口显示
  • 关闭浏览器标签页不会停止应用（在终端 Ctrl+C 停止）

══════════════════════════════════════════════════
  包含功能（v3.0）
══════════════════════════════════════════════════
  • 数据上传（CSV/Excel/Word/PDF，GB18030/UTF-8 自动识别）
  • 自然语言查询（探索式分析）
  • 分析技能卡片（就绪状态 + 一键执行）
  • 固化计算快速路径（集中度 < 0.5s，合规审计日志）
  • 净值/收益率/资产结构/信用分布等固化指标
  • 图表生成（柱状图/饼图/折线图/散点图）
  • 报告生成（Markdown + Word 导出）
  • 置信度标签（✓ 已审计 / ~ 需核实 / ✧ AI生成）
  • 参谈要点 + 合规监控

  反馈请联系：<内部沟通渠道>
"""


def download_deps(deps_dir: Path) -> None:
    """下载 macOS 运行时依赖（优先 macOS arm64 + x86_64 wheel）."""
    print("📦 下载依赖包 ...")
    deps_dir.mkdir(parents=True, exist_ok=True)

    tmp_req = deps_dir.parent / "_tmp_mac_reqs.txt"
    tmp_req.write_text("\n".join(RUNTIME_DEPS))

    # 阶段 1：下载当前平台（Linux）解析出的完整依赖树
    print("   阶段 1/2: 解析依赖树（当前平台）...")
    cmd1 = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(deps_dir),
        "-r", str(tmp_req),
    ]
    r1 = subprocess.run(cmd1, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if r1.returncode != 0:
        print("❌ 阶段 1 失败：")
        print(r1.stderr)
        tmp_req.unlink(missing_ok=True)
        sys.exit(1)

    # 阶段 2：替换 C 扩展包为 macOS 版本（优先 arm64，兼容 x86_64）
    print("   阶段 2/2: 替换为 macOS 原生包（macosx_11_0_arm64 / x86_64）...")

    def parse_wheel_pkg(filename: str):
        stem = filename.replace(".whl", "")
        parts = stem.split("-")
        pkg_parts, version_idx = [], None
        for i, p in enumerate(parts):
            if p and p[0].isdigit():
                version_idx = i
                break
            pkg_parts.append(p)
        if version_idx is None:
            return None
        return "-".join(pkg_parts), parts[version_idx]

    to_replace: dict[str, str] = {}
    for w in deps_dir.glob("*.whl"):
        name = w.name
        if "macosx" in name or "none-any" in name:
            continue
        parsed = parse_wheel_pkg(name)
        if parsed:
            pkg_name, version = parsed
            if pkg_name not in to_replace:
                to_replace[pkg_name] = version

    # 支持的 Python 3.x 版本（cp311/cp312/cp313 ABI）
    PY_VERSIONS = ["3.11", "3.12", "3.13"]
    # 支持的 macOS 平台（优先 arm64 → universal2 → x86_64）
    MAC_PLATFORMS = ["macosx_11_0_arm64", "macosx_10_9_universal2", "macosx_10_15_x86_64"]

    for pkg_name, version in sorted(to_replace.items()):
        pkg_spec = f"{pkg_name}=={version}"
        # 为所有 Python 版本 × 所有 macOS 平台下载 wheel（不 break，全部保留）
        # pip install --no-index 会自动选择兼容的 wheel
        any_success = False
        for py_ver in PY_VERSIONS:
            for platform in MAC_PLATFORMS:
                cmd2 = [
                    sys.executable, "-m", "pip", "download",
                    "--platform", platform,
                    "--python-version", py_ver,
                    "--implementation", "cp",
                    "--only-binary=:all:",
                    "--no-deps",
                    "--dest", str(deps_dir),
                    pkg_spec,
                ]
                r2 = subprocess.run(cmd2, capture_output=True, text=True, cwd=PROJECT_ROOT)
                if r2.returncode == 0:
                    any_success = True
                    # 不 break — 继续下载其他平台和 Python 版本
        if not any_success:
            print(f"   ⚠️  {pkg_spec}: macOS wheel 不可用，保留通用版本")

    # 清理 Linux manylinux wheel（已有 macOS 或 none-any 替代品的）
    for w in deps_dir.glob("*.whl"):
        if "manylinux" in w.name or ("linux" in w.name and "macosx" not in w.name):
            parsed = parse_wheel_pkg(w.name)
            if parsed:
                pkg_name, version = parsed
                win_pattern = f"{pkg_name}-{version}-"
                has_mac = any(
                    (win_pattern in whl.name and ("macosx" in whl.name or "none-any" in whl.name))
                    for whl in deps_dir.glob("*.whl") if whl != w
                )
                if has_mac:
                    w.unlink()

    tmp_req.unlink(missing_ok=True)
    whl_count = len(list(deps_dir.glob("*.whl"))) + len(list(deps_dir.glob("*.tar.gz")))
    print(f"   ✅ 下载完成 ({whl_count} 个文件)")


def copy_project(bundle_src: Path) -> None:
    print("📁 复制项目文件 ...")
    for d in INCLUDE_DIRS:
        src = PROJECT_ROOT / d
        if not src.exists():
            continue
        dst = bundle_src / d
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns(*EXCLUDE_PATTERNS),
                        dirs_exist_ok=True)
    for f in INCLUDE_FILES:
        src = PROJECT_ROOT / f
        if src.exists():
            shutil.copy2(src, bundle_src / f)
    for sub in ["data/uploads", "data/outputs", "data/sessions",
                "data/compliance_audit", "data/logs", "data/skill_drafts"]:
        (bundle_src / sub).mkdir(parents=True, exist_ok=True)
        (bundle_src / sub / ".gitkeep").write_text("")
    print("   ✅ 项目文件复制完成")


def write_scripts(bundle_root: Path) -> None:
    print("📝 生成启动脚本 ...")
    setup = bundle_root / "setup.sh"
    setup.write_text(SETUP_SH, encoding="utf-8")
    setup.chmod(0o755)

    run = bundle_root / "run.sh"
    run.write_text(RUN_SH, encoding="utf-8")
    run.chmod(0o755)

    (bundle_root / "README.txt").write_text(README_TXT, encoding="utf-8")
    (bundle_root / "requirements-bundle.txt").write_text("\n".join(RUNTIME_DEPS))
    print("   ✅ 脚本生成完成")


def main():
    parser = argparse.ArgumentParser(description="构建 DataAgent macOS 内测包")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "dist"),
                        help="输出目录 (默认: ./dist)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle_name = f"DataAgent-{BUNDLE_VERSION}-mac"
    bundle_root = output_dir / bundle_name
    deps_dir = bundle_root / "deps"
    bundle_src = bundle_root / "DataAgent"
    zip_path = output_dir / f"{bundle_name}.zip"

    if bundle_root.exists():
        shutil.rmtree(bundle_root)
    if zip_path.exists():
        zip_path.unlink()

    print("=" * 60)
    print(f"  DataAgent macOS 内测包构建 - {BUNDLE_VERSION}")
    print("=" * 60)
    print()

    download_deps(deps_dir)
    copy_project(bundle_src)
    write_scripts(bundle_root)

    print("📦 打包 zip ...")
    shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=str(output_dir),
        base_dir=bundle_name,
    )
    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    shutil.rmtree(bundle_root)

    print()
    print("=" * 60)
    print("  ✅ 内测包构建完成")
    print(f"  📁 {zip_path}")
    print(f"  📏 大小: {zip_size_mb:.1f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
