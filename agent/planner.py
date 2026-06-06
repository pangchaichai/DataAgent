"""
agent/planner.py — Agent 规划层（I-8）

职责：
  1. 检测复杂多步查询（should_plan 启发式判断）
  2. 调用 LLM 生成结构化执行计划（build_plan）
  3. 将计划格式化为 prompt 提示和 SSE 事件数据

设计原则：
  - 规划层是可选增强：simple 查询直接走 loop，complex 查询先规划再执行
  - 规划失败时静默降级（不中断请求），返回 None 让 caller 走直接循环
  - 单步计划（1 个工具调用）不触发规划，避免无谓开销
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlanStep:
    step_id: str           # "1", "2", "3"…
    name: str              # 用户可读名称，如"检查主体集中度"
    tool: str              # 建议工具（提示，非强制）: run_sql / run_calculator / profile_table
    objective: str         # 本步骤要完成什么
    depends_on: list[str] = field(default_factory=list)  # 依赖的 step_id 列表


@dataclass
class Plan:
    query: str
    steps: list[PlanStep]
    rationale: str = ""    # 为什么需要多步

    def to_prompt_hint(self) -> str:
        """格式化为注入 system/user prompt 的文本"""
        if not self.steps:
            return ""
        lines = [f"请按以下 {len(self.steps)} 步执行："]
        for s in self.steps:
            dep = f"（依赖步骤 {', '.join(s.depends_on)}）" if s.depends_on else ""
            lines.append(f"  步骤{s.step_id}：{s.name}{dep} — {s.objective}")
        return "\n".join(lines)

    def to_sse_data(self) -> dict:
        """格式化为 SSE plan 事件的 data 字段"""
        return {
            "rationale": self.rationale,
            "steps": [
                {
                    "id": s.step_id,
                    "name": s.name,
                    "tool": s.tool,
                    "objective": s.objective,
                    "depends_on": s.depends_on,
                }
                for s in self.steps
            ],
        }


# ═══════════════════════════════════════════════════════════════
#  启发式判断：是否需要规划
# ═══════════════════════════════════════════════════════════════

# 关键词：暗示多步/顺序操作
_PLAN_KEYWORDS = [
    "然后", "再", "接着", "最后", "同时", "并且", "步骤",
    "先.*再", "首先.*其次", "一方面.*另一方面",
    "检查.*生成", "分析.*报告", "计算.*汇总",
    "多个", "分别", "逐一",
]

# 操作词：同一条消息出现 3+ 个不同操作动词
_ACTION_VERBS = [
    "查询", "检查", "计算", "生成", "分析", "汇总", "统计",
    "对比", "比较", "下载", "导出", "上传", "报告",
]


def should_plan(query: str, min_steps: int = 2) -> bool:
    """
    启发式判断查询是否需要多步规划。

    触发条件（满足任一）：
      1. 查询中出现多步关键词（先…再，然后，最后等）
      2. 查询中出现 min_steps 个以上不同操作动词
    """
    if not query or len(query.strip()) < 10:
        return False

    # 条件 1：顺序关键词
    for kw in _PLAN_KEYWORDS:
        if re.search(kw, query):
            return True

    # 条件 2：多操作动词（≥2 个不同动词时触发规划）
    verb_hits = sum(1 for v in _ACTION_VERBS if v in query)
    if verb_hits >= min_steps:
        return True

    return False


# ═══════════════════════════════════════════════════════════════
#  LLM 规划（build_plan）
# ═══════════════════════════════════════════════════════════════

_PLANNING_SYSTEM = """\
你是 DataAgent 的规划引擎。用户提出了一个需要多步操作的请求。
请分析请求，将其拆解为 2-5 个有序步骤，输出 JSON 数组。

可用工具：
  profile_table   - 剖析表结构（了解列名、样本值）
  run_sql         - 执行探索式 SELECT 查询
  run_calculator  - 运行固化口径计算（集中度/净值/资产结构/评级分布）
  ask_user        - 向用户提问（存在歧义时）
  request_confirmation - 结论确认

输出格式（JSON 数组，不含注释）：
[
  {"step_id": "1", "name": "步骤名称", "tool": "工具名", "objective": "本步骤目标", "depends_on": []},
  {"step_id": "2", "name": "...", "tool": "...", "objective": "...", "depends_on": ["1"]}
]

只输出 JSON，不要加任何说明文字。步骤数量控制在 2-5 步。"""


def build_plan(
    query: str,
    llm_client,
    schema_ctx: str = "",
    skills_ctx: str = "",
) -> Optional[Plan]:
    """
    调用 LLM 生成执行计划。失败时返回 None（降级为直接循环）。

    Args:
        query: 用户原始查询
        llm_client: LLMClient 实例
        schema_ctx: 已加载表的 schema 摘要
        skills_ctx: 可用 Skills 描述
    """
    prompt = _build_planning_prompt(query, schema_ctx, skills_ctx)
    try:
        result = llm_client.chat(
            [
                {"role": "system", "content": _PLANNING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            tools=None,
        )
        if not result.success or not result.text:
            return None

        steps = _parse_plan_json(result.text)
        if not steps or len(steps) < 2:
            return None

        return Plan(
            query=query,
            steps=steps,
            rationale=f"检测到 {len(steps)} 步操作",
        )
    except Exception:
        return None


def _build_planning_prompt(query: str, schema_ctx: str, skills_ctx: str) -> str:
    parts = [f"用户请求：{query}"]
    if schema_ctx:
        parts.append(f"\n已加载数据：\n{schema_ctx}")
    if skills_ctx:
        parts.append(f"\n可用技能：\n{skills_ctx}")
    parts.append("\n请输出执行步骤（JSON 数组）：")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
#  JSON 解析
# ═══════════════════════════════════════════════════════════════

def _parse_plan_json(text: str) -> list[PlanStep]:
    """
    从 LLM 输出文本中提取 JSON 数组并解析为 PlanStep 列表。
    支持 JSON 嵌入在 markdown 代码块中。
    """
    # 尝试提取 ```json...``` 或 [...] 块
    text = text.strip()

    # 剥离 markdown 代码块
    md_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if md_match:
        text = md_match.group(1).strip()

    # 找到 JSON 数组
    arr_match = re.search(r'\[[\s\S]*\]', text)
    if not arr_match:
        return []

    try:
        data = json.loads(arr_match.group())
        if not isinstance(data, list):
            return []
    except (json.JSONDecodeError, ValueError):
        return []

    steps = []
    for item in data:
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("step_id", len(steps) + 1))
        name = str(item.get("name", f"步骤{step_id}"))
        tool = str(item.get("tool", "run_sql"))
        objective = str(item.get("objective", ""))
        depends_on = [str(d) for d in item.get("depends_on", [])]
        steps.append(PlanStep(
            step_id=step_id,
            name=name,
            tool=tool,
            objective=objective,
            depends_on=depends_on,
        ))
    return steps
