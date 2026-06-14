#!/usr/bin/env python3
"""
scripts/install_hooks.py — 安装 DataAgent git 钩子

将 scripts/hooks/ 中的钩子复制到 .git/hooks/ 并设置可执行权限。
新开发者克隆仓库后运行一次即可。

用法：python scripts/install_hooks.py
"""
import shutil
import stat
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "scripts" / "hooks"
DST = BASE / ".git" / "hooks"


def main():
    if not DST.exists():
        print("❌ 未找到 .git/hooks 目录，请在 git 仓库根目录执行")
        return 1

    installed = []
    for hook in sorted(SRC.iterdir()):
        if hook.name.startswith("."):
            continue
        dst = DST / hook.name
        shutil.copy2(hook, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(hook.name)
        print(f"  ✅ {hook.name} → .git/hooks/{hook.name}")

    print(f"\n已安装 {len(installed)} 个 git 钩子：{', '.join(installed)}")
    print("\n钩子作用：")
    print("  pre-commit  — ruff lint + pytest 测试（阻断低质量提交）")
    print("  post-commit — 自动更新 HANDOFF.md / START_HERE.md / CHANGELOG.md")
    print("\n如需跳过钩子：git commit --no-verify（需在 HANDOFF.md 记录原因）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
