#!/usr/bin/env python3
"""
scripts/sync_project_state.py — DataAgent 项目状态自动同步器

在每次会话结束（Stop hook）或 git commit 后自动执行，无需手动更新以下文件：
  - data/test_reports/latest_summary.json  （运行 pytest，写入最新结果）
  - START_HERE.md                          （更新分支/测试状态行）
  - HANDOFF.md                             （更新"最后更新"块）

不自动修改（需要 Claude 判断的叙述性内容）：
  - HANDOFF.md "上次会话完成的工作" 段落
  - PROGRESS.md 进度打勾（[ ] → [x]）
  - HANDOFF.md "立即可执行的下一步"

用法：
  python scripts/sync_project_state.py            # 运行测试 + 同步状态
  python scripts/sync_project_state.py --no-test  # 仅同步状态（跳过测试，速度快）
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Git 工具
# ─────────────────────────────────────────────────────────────────────────────

def git(cmd: list) -> str:
    try:
        return subprocess.check_output(
            ["git"] + cmd, cwd=BASE, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def get_git_state() -> dict:
    return {
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit_hash": git(["log", "-1", "--format=%h"]),
        "commit_subject": git(["log", "-1", "--format=%s"]),
        "commit_date": git(["log", "-1", "--format=%ad", "--date=short"]),
        "dirty": bool(git(["status", "--porcelain"])),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 测试运行器
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> dict:
    """运行 pytest，解析 junit.xml，返回摘要 dict。失败时返回上次结果。"""
    print("  ▶ 运行 pytest tests/ ...")
    junit_path = BASE / "data" / "test_reports" / "junit.xml"
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--no-header",
             f"--junitxml={junit_path}"],
            cwd=BASE, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print("  ⚠️  pytest 超时（120s），使用上次结果")
        return _load_last_summary()

    # 解析最后一行摘要（形如 "341 passed, 2 skipped in 5.57s"）
    lines = result.stdout.strip().splitlines()
    summary_line = next((l for l in reversed(lines) if "passed" in l or "failed" in l), "")
    passed = _parse_int(r"(\d+) passed", summary_line)
    failed = _parse_int(r"(\d+) failed", summary_line)
    skipped = _parse_int(r"(\d+) skipped", summary_line)
    errors = _parse_int(r"(\d+) error", summary_line)
    total = passed + failed + skipped + errors

    # 提取失败用例列表（最多 10 条）
    failed_tests = []
    for line in lines:
        if line.startswith("FAILED "):
            node = line.removeprefix("FAILED ").split(" - ")[0].strip()
            msg = " - ".join(line.split(" - ")[1:])[:80] if " - " in line else ""
            failed_tests.append({"nodeid": node, "message": msg})
        if len(failed_tests) >= 10:
            break

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "exit_status": result.returncode,
        "duration_seconds": round(_parse_float(r"in ([\d.]+)s", summary_line), 2),
        "failed_tests": failed_tests,
    }
    icon = "✅" if failed == 0 else ("⚠️" if failed <= 5 else "❌")
    print(f"  {icon} {passed}/{total} 通过，{failed} 失败，{skipped} 跳过")
    return summary


def _parse_int(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def _parse_float(pattern: str, text: str) -> float:
    m = re.search(pattern, text)
    return float(m.group(1)) if m else 0.0


def _load_last_summary() -> dict:
    path = BASE / "data" / "test_reports" / "latest_summary.json"
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return {"timestamp": datetime.now().isoformat(), "total": 0, "passed": 0,
            "failed": 0, "skipped": 0, "errors": 0, "exit_status": -1,
            "duration_seconds": 0, "failed_tests": []}


# ─────────────────────────────────────────────────────────────────────────────
# 更新 latest_summary.json
# ─────────────────────────────────────────────────────────────────────────────

def update_test_report(summary: dict):
    path = BASE / "data" / "test_reports" / "latest_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"  ✏️  {path.relative_to(BASE)} 已更新")


# ─────────────────────────────────────────────────────────────────────────────
# 更新 START_HERE.md — 仅替换"分支"行和"测试"行
# ─────────────────────────────────────────────────────────────────────────────

def update_start_here(gs: dict, summary: dict):
    path = BASE / "START_HERE.md"
    if not path.exists():
        print("  ⚠️  START_HERE.md 不存在，跳过")
        return

    content = path.read_text("utf-8")
    p, f, t = summary["passed"], summary["failed"], summary["total"]
    date = summary["timestamp"][:10]
    test_str = f"**测试**：{p}/{t} 通过，{f} 失败（{date}）"
    branch_str = f"**分支**：`{gs['branch']}`"

    # 替换"**测试**：..."行
    content = re.sub(r"\*\*测试\*\*：.*", test_str, content)
    # 替换"**分支**：`...`"行
    content = re.sub(r"\*\*分支\*\*：`[^`]*`", branch_str, content)

    path.write_text(content, "utf-8")
    print(f"  ✏️  START_HERE.md 已更新（分支={gs['branch']}，测试={p}/{t}）")


# ─────────────────────────────────────────────────────────────────────────────
# 更新 HANDOFF.md — 仅替换"## 最后更新"块的三个字段
# ─────────────────────────────────────────────────────────────────────────────

def update_handoff(gs: dict):
    path = BASE / "HANDOFF.md"
    if not path.exists():
        print("  ⚠️  HANDOFF.md 不存在，跳过")
        return

    content = path.read_text("utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    commit_line = f"{gs['commit_hash']} {gs['commit_subject']}"

    # 替换"## 最后更新"块内的三个字段
    content = re.sub(r"(- \*\*日期\*\*：)\S+", rf"\g<1>{today}", content)
    content = re.sub(r"(- \*\*提交\*\*：).+", rf"\g<1>{commit_line}", content)
    content = re.sub(r"(- \*\*分支\*\*：`)[^`]*(`)", rf"\g<1>{gs['branch']}\g<2>", content)

    path.write_text(content, "utf-8")
    print(f"  ✏️  HANDOFF.md 最后更新块 已同步（{today} / {gs['commit_hash']}）")


# ─────────────────────────────────────────────────────────────────────────────
# 提示仍需手动处理的事项（输出给 Claude/开发者）
# ─────────────────────────────────────────────────────────────────────────────

def print_manual_checklist(summary: dict, gs: dict):
    f = summary["failed"]
    print()
    print("─" * 55)
    print("  📋 仍需手动完成（Claude 负责）")
    print("─" * 55)
    print("  [ ] HANDOFF.md —「上次会话完成的工作」段落")
    print("  [ ] HANDOFF.md —「立即可执行的下一步」更新")
    print("  [ ] PROGRESS.md — 将完成项 [ ] 改为 [x]，新增遗留项")
    if f > 0:
        print(f"  ⚠️  {f} 个测试失败，提交前请先修复或记录原因")
    if gs["dirty"]:
        print("  ⚠️  工作区有未提交变更，别忘了 git add + commit + push")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    run_test = "--no-test" not in sys.argv

    print()
    print("=" * 55)
    print("  DataAgent 项目状态自动同步")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # 1. 测试
    if run_test:
        summary = run_tests()
    else:
        print("  ⏭  跳过测试（--no-test）")
        summary = _load_last_summary()

    # 2. 写入测试报告
    update_test_report(summary)

    # 3. Git 状态
    gs = get_git_state()
    print(f"  🔀 分支: {gs['branch']}  提交: {gs['commit_hash']} {gs['commit_subject']}")

    # 4. 更新管理文档（机械性部分）
    update_start_here(gs, summary)
    update_handoff(gs)

    # 5. 提示手动部分
    print_manual_checklist(summary, gs)

    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
