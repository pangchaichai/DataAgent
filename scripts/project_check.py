#!/usr/bin/env python3
"""
scripts/project_check.py — DataAgent 项目状态一致性检查器

每次会话开始时运行，在 30 秒内生成项目状态快照，让 Claude Code 快速定位当前状态。
用法：python scripts/project_check.py
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# ── 关键文件清单（与 CLAUDE.md 目录树保持同步）──────────────────────────────
CRITICAL_FILES = [
    # 项目核心
    ("CLAUDE.md",              "项目主引导"),
    ("PROGRESS.md",            "开发进度"),
    ("HANDOFF.md",             "会话交接"),
    ("TESTING.md",             "测试策略"),
    ("main.py",                "Flask 入口"),
    ("session_store.py",       "会话状态管理"),
    # Agent 层
    ("agent/loop.py",          "Agent 主循环"),
    ("agent/tools_spec.py",    "7 工具定义"),
    ("agent/llm_client.py",    "LLM 客户端"),
    ("agent/context.py",       "三级压缩"),
    ("agent/planner.py",       "Plan-Execute 规划"),
    ("agent/executor.py",      "Plan-Execute 执行"),
    ("agent/self_check.py",    "SelfChecker"),
    ("agent/hooks.py",         "Hook 系统"),
    # 固化计算
    ("calculators/concentration.py",     "集中度"),
    ("calculators/nav_metrics.py",       "净值指标"),
    ("calculators/asset_structure.py",   "资产结构"),
    ("calculators/credit_distribution.py","信用分布"),
    ("calculators/leverage.py",          "杠杆率 (I-9)"),
    ("calculators/liquidity.py",         "流动性 (I-9)"),
    ("calculators/position_diff.py",     "持仓变动 (I-9)"),
    # 工具层
    ("tools/data_loader.py",      "数据加载"),
    ("tools/query_runner.py",     "SQLGuard"),
    ("tools/report_builder.py",   "报告+Word导出"),
    ("tools/chart_builder.py",    "图表"),
    ("tools/file_reader.py",      "文档解析"),
    ("tools/web_search.py",       "联网搜索"),
    ("tools/cost_tracker.py",     "成本追踪"),
    ("tools/compliance_audit.py", "合规审计"),
    ("tools/skill_builder.py",    "Skill 创建"),
    ("tools/runtime_logger.py",   "运行日志"),
    ("tools/entity_manager.py",   "集团系管理"),
    ("tools/notify.py",           "通知推送"),
    # 模板
    ("templates/reports/base_report.md.j2",           "报告基础模板"),
    ("templates/reports/concentration_report.md.j2",  "集中度报告模板"),
    ("templates/reports/nav_report.md.j2",             "净值报告模板"),
    # 前端
    ("ui/index.html",       "主界面"),
    ("ui/echarts.min.js",   "ECharts 本地"),
    # 平台适配
    ("platform_adapter/ui_driver.py",     "窗口驱动"),
    ("platform_adapter/notify_driver.py", "通知驱动"),
]

# ── v3.0 演进任务（按优先级，参照 docs/v3-evolution-final-plan.md）────────────
V3_NEXT_STEPS = [
    ("P0-W1", "fast_path.py",          "确定性快速路径（concentration_monitor <1s 响应）"),
    ("P0-W1", "execution_tracker.py",  "执行追踪 JSONL 写入端"),
    ("P0-W2", "fund_nav_report 修复",  "合规修复：B类场景违规使用 LLM SQL → 改调 calculators"),
    ("P0-W2", "Skill 卡片 UI",         "侧边栏 Skill 条目改为卡片 + 一键执行按钮"),
]

# ── Phase 4 进入条件（外部阻塞项）─────────────────────────────────────────────
PHASE4_BLOCKERS = [
    "C-02：业务方确认周报模板（dept_weekly_report）",
    "C-03：业务方确认月报模板（monthly_bond_summary）",
    "C-04：业务方确认 Word 导出格式",
]


def _run(cmd: list, cwd=BASE) -> str:
    try:
        return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def check_git():
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    last_commit = _run(["git", "log", "-1", "--format=%h %s (%ar)"])
    status_raw = _run(["git", "status", "--porcelain"])
    uncommitted = [l for l in status_raw.splitlines() if l.strip()] if status_raw else []
    return branch, last_commit, uncommitted


def check_handoff():
    path = BASE / "HANDOFF.md"
    if not path.exists():
        return "missing", None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    age = datetime.now() - mtime
    return "stale" if age > timedelta(days=7) else "ok", mtime


def check_files():
    missing, present = [], []
    for rel, desc in CRITICAL_FILES:
        if (BASE / rel).exists():
            present.append((rel, desc))
        else:
            missing.append((rel, desc))
    return present, missing


def check_tests():
    report = BASE / "data" / "test_reports" / "latest_summary.json"
    if not report.exists():
        return None
    try:
        return json.loads(report.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_phase():
    """从 PROGRESS.md 提取当前阶段信息"""
    progress = BASE / "PROGRESS.md"
    if not progress.exists():
        return "无法读取 PROGRESS.md"
    lines = progress.read_text(encoding="utf-8").splitlines()
    for line in lines[:10]:
        if line.startswith("## 当前阶段"):
            return line.replace("## 当前阶段：", "").strip()
    return "未标注"


def print_section(title: str):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


def main():
    width = 57
    print("=" * width)
    print(" DataAgent 项目状态快照".center(width))
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M')}".center(width))
    print("=" * width)

    # ── Git 状态 ──────────────────────────────────────────────────────────────
    print_section("Git 状态")
    branch, last_commit, uncommitted = check_git()
    print(f"  分支      : {branch or '未知'}")
    print(f"  最后提交  : {last_commit or '无'}")
    if uncommitted:
        print(f"  未提交变更: {len(uncommitted)} 个文件 ⚠️")
        for line in uncommitted[:6]:
            print(f"    {line}")
        if len(uncommitted) > 6:
            print(f"    ... 还有 {len(uncommitted)-6} 个文件")
    else:
        print("  工作区    : 干净 ✅")

    # ── 会话交接状态 ──────────────────────────────────────────────────────────
    print_section("会话交接（HANDOFF.md）")
    status, mtime = check_handoff()
    if status == "missing":
        print("  ⛔ HANDOFF.md 不存在 — 请立即创建（本会话结束前必须填写）")
    elif status == "stale":
        days = (datetime.now() - mtime).days
        print(f"  ⚠️  HANDOFF.md 已 {days} 天未更新（{mtime.strftime('%Y-%m-%d')}）")
        print("     建议先读取并确认内容仍有效，再开始新工作")
    else:
        print(f"  ✅ 最后更新：{mtime.strftime('%Y-%m-%d %H:%M')}")

    # ── 关键文件 ──────────────────────────────────────────────────────────────
    print_section("关键文件检查")
    present, missing = check_files()
    print(f"  存在：{len(present)}/{len(CRITICAL_FILES)} 个关键文件")
    if missing:
        print(f"  缺失 {len(missing)} 个 ⚠️：")
        for rel, desc in missing:
            print(f"    - {rel}  （{desc}）")
    else:
        print("  ✅ 全部关键文件存在")

    # ── 测试状态 ──────────────────────────────────────────────────────────────
    print_section("测试状态")
    tr = check_tests()
    if tr:
        p, f, t = tr.get("passed", 0), tr.get("failed", 0), tr.get("total", 0)
        date = tr.get("timestamp", "?")[:10]
        icon = "✅" if f == 0 else ("⚠️" if f <= 5 else "❌")
        print(f"  {icon} {p}/{t} 通过，{f} 失败（{date}）")
        if tr.get("failed_tests"):
            for ft in tr["failed_tests"][:3]:
                msg = ft.get("message", "")[:60]
                print(f"    - {ft['nodeid'].split('::')[-1]}: {msg}")
    else:
        print("  ⚠️  无测试报告（运行 pytest tests/ 生成）")

    # ── 当前阶段 ──────────────────────────────────────────────────────────────
    print_section("当前阶段")
    print(f"  {check_phase()}")

    # ── v3.0 演进下一步 ──────────────────────────────────────────────────────
    print_section("v3.0 演进下一步（参照 docs/v3-evolution-final-plan.md）")
    for tag, task, desc in V3_NEXT_STEPS:
        print(f"  [{tag}] {task}")
        print(f"       → {desc}")

    # ── Phase 4 阻塞项 ────────────────────────────────────────────────────────
    print_section("Phase 4 进入条件（外部阻塞，等待业务方）")
    for blocker in PHASE4_BLOCKERS:
        print(f"  ⏳ {blocker}")

    # ── 结束提示 ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * width}")
    print("  📖 建议阅读顺序：HANDOFF.md → PROGRESS.md → CLAUDE.md")
    print(f"{'=' * width}\n")

    # 若有未提交变更，返回非零退出码提醒
    return 1 if uncommitted else 0


if __name__ == "__main__":
    sys.exit(main())
