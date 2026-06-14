#!/usr/bin/env python3
"""
scripts/sync_project_state.py — DataAgent 项目状态自动同步器

由 git post-commit hook 自动调用，也可手动运行。

默认行为（每次 git commit 后）：
  1. 读取最新提交信息
  2. 更新 HANDOFF.md "最后更新"块（日期/提交/分支）
  3. 更新 START_HERE.md 分支/测试状态行
  4. 更新 data/test_reports/latest_summary.json 时间戳
  5. 追加 CHANGELOG.md（按 conventional commit 类型分类）

选项：
  --run-tests   运行 pytest（默认跳过，由 pre-commit hook 负责）
  --no-test     同上（向后兼容别名）
  --quiet       最小化输出（由 post-commit hook 使用）
  --changelog   仅重新生成完整 CHANGELOG（不做其他更新）
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
QUIET = "--quiet" in sys.argv
RUN_TESTS = "--run-tests" in sys.argv
ONLY_CHANGELOG = "--changelog" in sys.argv


def log(msg: str):
    if not QUIET:
        print(msg)


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


SYNC_COMMIT_PATTERN = r"^chore\(sync\):"


def get_git_state() -> dict:
    """返回最后一个有意义提交的 git 状态（跳过 sync 提交）。"""
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
    # 找最近的非 sync 提交
    meaningful = git([
        "log", "-1", "--format=%h|%s|%ad", "--date=short",
        "--invert-grep", f"--grep={SYNC_COMMIT_PATTERN[1:]}"  # 去掉 ^ 前缀
    ])
    if "|" in meaningful:
        parts = meaningful.split("|", 2)
        h, s, d = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    else:
        h = git(["log", "-1", "--format=%h"])
        s = git(["log", "-1", "--format=%s"])
        d = git(["log", "-1", "--format=%ad", "--date=short"])
    return {
        "branch":          branch,
        "commit_hash":     h,
        "commit_subject":  s,
        "commit_date":     d,
        "dirty":           bool(git(["status", "--porcelain"])),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 测试运行器（仅 --run-tests 时调用）
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> dict:
    log("  ▶ 运行 pytest tests/ ...")
    junit_path = BASE / "data" / "test_reports" / "junit.xml"
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--no-header",
             f"--junitxml={junit_path}"],
            cwd=BASE, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        log("  ⚠️  pytest 超时（120s），使用上次结果")
        return _load_last_summary()

    lines = result.stdout.strip().splitlines()
    summary_line = next(
        (l for l in reversed(lines) if "passed" in l or "failed" in l), ""
    )
    passed  = _parse_int(r"(\d+) passed", summary_line)
    failed  = _parse_int(r"(\d+) failed", summary_line)
    skipped = _parse_int(r"(\d+) skipped", summary_line)
    errors  = _parse_int(r"(\d+) error", summary_line)
    total   = passed + failed + skipped + errors

    failed_tests = []
    for line in lines:
        if line.startswith("FAILED "):
            node = line.removeprefix("FAILED ").split(" - ")[0].strip()
            msg  = " - ".join(line.split(" - ")[1:])[:80] if " - " in line else ""
            failed_tests.append({"nodeid": node, "message": msg})
        if len(failed_tests) >= 10:
            break

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": total, "passed": passed, "failed": failed,
        "skipped": skipped, "errors": errors,
        "exit_status": result.returncode,
        "duration_seconds": round(_parse_float(r"in ([\d.]+)s", summary_line), 2),
        "failed_tests": failed_tests,
    }
    icon = "✅" if failed == 0 else ("⚠️" if failed <= 5 else "❌")
    log(f"  {icon} {passed}/{total} 通过，{failed} 失败，{skipped} 跳过")
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
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            pass
    return {"timestamp": datetime.now().isoformat(), "total": 0, "passed": 0,
            "failed": 0, "skipped": 0, "errors": 0, "exit_status": -1,
            "duration_seconds": 0, "failed_tests": []}


# ─────────────────────────────────────────────────────────────────────────────
# 更新 latest_summary.json
# ─────────────────────────────────────────────────────────────────────────────

def update_test_report(summary: dict):
    path = BASE / "data" / "test_reports" / "latest_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 仅更新时间戳，保留测试数值（避免 --no-test 时覆盖为空）
    if not RUN_TESTS:
        existing = _load_last_summary()
        existing["timestamp"] = datetime.now().isoformat()
        summary = existing
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", "utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 更新 START_HERE.md — 替换分支行和测试状态行
# ─────────────────────────────────────────────────────────────────────────────

def update_start_here(gs: dict, summary: dict):
    path = BASE / "START_HERE.md"
    if not path.exists():
        return
    content = path.read_text("utf-8")
    p, f, t = summary["passed"], summary["failed"], summary["total"]
    date = summary["timestamp"][:10]
    icon = "✅" if f == 0 else "⚠️"
    content = re.sub(
        r"\*\*测试\*\*：.*",
        f"**测试**：{icon} {p}/{t} 通过，{f} 失败（{date}）",
        content
    )
    content = re.sub(
        r"\*\*分支\*\*：`[^`]*`",
        f"**分支**：`{gs['branch']}`",
        content
    )
    path.write_text(content, "utf-8")
    log(f"  ✏️  START_HERE.md 已更新（{gs['branch']} | {p}/{t} 通过）")


# ─────────────────────────────────────────────────────────────────────────────
# 更新 HANDOFF.md — 仅替换"## 最后更新"块三个字段
# ─────────────────────────────────────────────────────────────────────────────

def update_handoff(gs: dict):
    path = BASE / "HANDOFF.md"
    if not path.exists():
        return
    content = path.read_text("utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    commit_line = f"{gs['commit_hash']} {gs['commit_subject']}"
    content = re.sub(r"(- \*\*日期\*\*：)\S+",       rf"\g<1>{today}",       content)
    content = re.sub(r"(- \*\*提交\*\*：).+",         rf"\g<1>{commit_line}", content)
    content = re.sub(r"(- \*\*分支\*\*：`)[^`]*(`)",  rf"\g<1>{gs['branch']}\g<2>", content)
    path.write_text(content, "utf-8")
    log(f"  ✏️  HANDOFF.md 最后更新块已同步（{today} / {gs['commit_hash']}）")


# ─────────────────────────────────────────────────────────────────────────────
# CHANGELOG.md — 从 git log 生成，按版本 tag 和 conventional commit 类型分组
# ─────────────────────────────────────────────────────────────────────────────

# conventional commit 类型 → 展示标签
COMMIT_TYPES = {
    "feat":     ("✨", "新功能"),
    "fix":      ("🐛", "问题修复"),
    "perf":     ("⚡", "性能优化"),
    "refactor": ("♻️",  "代码重构"),
    "docs":     ("📖", "文档更新"),
    "test":     ("🧪", "测试"),
    "chore":    ("🔧", "维护"),
    "release":  ("🚀", "版本发布"),
    "wip":      ("🚧", "进行中"),
}


def _classify_commit(subject: str) -> tuple[str, str, str]:
    """返回 (emoji, type_label, clean_subject)"""
    m = re.match(r"^(\w+)(?:\([^)]+\))?:\s*(.+)$", subject)
    if m:
        typ = m.group(1).lower()
        emoji, label = COMMIT_TYPES.get(typ, ("📌", typ))
        return emoji, label, m.group(2).strip()
    return "📌", "其他", subject


def build_changelog() -> str:
    """从 git log 生成完整 CHANGELOG.md 内容"""
    # 获取所有 tag 和对应 commit hash
    tags_raw = git(["tag", "--sort=-version:refname"])
    tags = tags_raw.splitlines() if tags_raw else []

    # 获取全量 commit 列表
    log_raw = git(["log", "--format=%h|%ad|%s", "--date=short"])
    commits = [l.split("|", 2) for l in log_raw.splitlines() if "|" in l]

    if not commits:
        return "# DataAgent CHANGELOG\n\n暂无提交记录。\n"

    # 按 tag 切割 commit 区间
    # tag_commits = {tag: hash}
    tag_hashes = {}
    for tag in tags:
        h = git(["rev-list", "-1", tag])
        if h:
            tag_hashes[tag] = h[:7]

    # 找每个 commit 属于哪个 tag 区间
    def find_version(commit_hash: str) -> str:
        """返回该 commit 所属的版本区间标题"""
        # 检查 commit 是否早于某个 tag
        for tag in tags:
            result = git(["merge-base", "--is-ancestor", commit_hash, tag + "^{commit}"])
            if result == "":  # merge-base 成功 = 是祖先
                ancestor = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", commit_hash, tag],
                    cwd=BASE, capture_output=True
                ).returncode
                if ancestor == 0:
                    return tag
        return "Unreleased"

    # 简化处理：直接按 commit 时间分组，标注版本 tag
    # 先建立 hash → 版本映射（基于 tag 的祖先关系）
    version_map = {}  # commit_short_hash → version_label
    if tags:
        for tag in tags:
            tagged_commits = git(["log", tag, "--format=%h"]).splitlines()
            for h in tagged_commits:
                if h[:7] not in version_map:
                    version_map[h[:7]] = tag

    # 按日期分组 commit
    from collections import defaultdict, OrderedDict
    by_date: dict = defaultdict(list)
    for parts in commits:
        if len(parts) < 3:
            continue
        h, date, subject = parts[0], parts[1], parts[2]
        # 跳过管理性提交（sync 自动提交 + 纯日志提交）
        clean_subj = subject.lower()
        if re.match(r"chore\(sync\):", subject) or any(skip in clean_subj for skip in [
            "update test report", "update handoff", "同步状态",
            "chore: update test", "chore: 更新 handoff", "auto-update management"
        ]):
            continue
        emoji, label, clean = _classify_commit(subject)
        by_date[date].append((h, emoji, label, clean))

    # 建立版本 → 日期列表映射
    # 简单策略：最新 tag 之后的 commit 归入 Unreleased
    lines = []
    lines.append("# DataAgent CHANGELOG\n")
    lines.append("> 此文件由 `scripts/sync_project_state.py` 在每次提交后自动维护。\n")
    lines.append("> 人工编写内容请放入对应版本节标题下的「版本说明」子节。\n")

    # Unreleased 区间
    if tags:
        latest_tag = tags[0]
        tag_date = git(["log", "-1", "--format=%ad", "--date=short", latest_tag])
        unreleased_dates = [d for d in sorted(by_date.keys(), reverse=True)
                            if d > tag_date]
    else:
        unreleased_dates = sorted(by_date.keys(), reverse=True)

    if unreleased_dates:
        lines.append("\n## [Unreleased]\n")
        for date in unreleased_dates:
            entries = by_date[date]
            if not entries:
                continue
            lines.append(f"\n### {date}\n")
            # 按 label 分组
            by_label: dict = defaultdict(list)
            for h, emoji, label, clean in entries:
                by_label[f"{emoji} {label}"].append((h, clean))
            for lbl, items in by_label.items():
                lines.append(f"**{lbl}**\n")
                for h, clean in items:
                    lines.append(f"- `{h}` {clean}\n")

    # 已发布版本
    if tags:
        for i, tag in enumerate(tags):
            tag_date = git(["log", "-1", "--format=%ad", "--date=short", tag])
            prev_tag = tags[i + 1] if i + 1 < len(tags) else None

            if prev_tag:
                prev_date = git(["log", "-1", "--format=%ad", "--date=short", prev_tag])
                version_dates = [d for d in sorted(by_date.keys(), reverse=True)
                                 if prev_date < d <= tag_date]
            else:
                # 最早的 tag 之前的所有 commit
                version_dates = [d for d in sorted(by_date.keys(), reverse=True)
                                 if d <= tag_date]

            lines.append(f"\n## {tag} — {tag_date}\n")
            has_content = False
            for date in version_dates:
                entries = by_date[date]
                if not entries:
                    continue
                has_content = True
                lines.append(f"\n### {date}\n")
                by_label: dict = defaultdict(list)
                for h, emoji, label, clean in entries:
                    by_label[f"{emoji} {label}"].append((h, clean))
                for lbl, items in by_label.items():
                    lines.append(f"**{lbl}**\n")
                    for h, clean in items:
                        lines.append(f"- `{h}` {clean}\n")
            if not has_content:
                lines.append("_（无实质性变更提交）_\n")
    else:
        # 无 tag：全部按日期列出
        all_dates = sorted(by_date.keys(), reverse=True)
        if not unreleased_dates:
            lines.append("\n## 开发记录\n")
            for date in all_dates:
                entries = by_date[date]
                if not entries:
                    continue
                lines.append(f"\n### {date}\n")
                by_label: dict = defaultdict(list)
                for h, emoji, label, clean in entries:
                    by_label[f"{emoji} {label}"].append((h, clean))
                for lbl, items in by_label.items():
                    lines.append(f"**{lbl}**\n")
                    for h, clean in items:
                        lines.append(f"- `{h}` {clean}\n")

    return "".join(lines)


def update_changelog():
    path = BASE / "CHANGELOG.md"
    content = build_changelog()
    path.write_text(content, "utf-8")
    log(f"  ✏️  CHANGELOG.md 已重新生成")


# ─────────────────────────────────────────────────────────────────────────────
# 手动清单输出（非 quiet 模式）
# ─────────────────────────────────────────────────────────────────────────────

def print_manual_checklist(gs: dict):
    if QUIET:
        return
    print()
    print("─" * 55)
    print("  📋 仍需 Claude 手动维护（叙述性内容）")
    print("─" * 55)
    print("  [ ] HANDOFF.md —「上次会话完成的工作」段落")
    print("  [ ] HANDOFF.md —「立即可执行的下一步」")
    print("  [ ] PROGRESS.md — [ ] → [x]，新增遗留项")
    if gs["dirty"]:
        print("  ⚠️  工作区有未提交变更")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not QUIET:
        print()
        print("=" * 55)
        print("  DataAgent 项目状态同步")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 55)

    if ONLY_CHANGELOG:
        update_changelog()
        return 0

    # 1. 测试（可选）
    summary = run_tests() if RUN_TESTS else _load_last_summary()

    # 2. Git 状态
    gs = get_git_state()
    if not QUIET:
        log(f"  🔀 {gs['branch']} | {gs['commit_hash']} {gs['commit_subject']}")

    # 3. 更新管理文档
    update_test_report(summary)
    update_start_here(gs, summary)
    update_handoff(gs)
    update_changelog()

    # 4. 手动清单
    print_manual_checklist(gs)
    return 1 if (RUN_TESTS and summary["failed"] > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
