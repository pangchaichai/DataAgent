"""
agent/executor.py — Plan-Execute 执行层（I-8）

职责：
  1. 接收 Plan 对象，向前端 SSE 推送 plan 事件（进度展示）
  2. 将计划步骤提示注入用户消息，增强 run_agent_loop 的执行效果
  3. 监听 tool_start/tool_end 事件，匹配计划步骤，推送 plan_step 进度事件

设计：
  - executor 不替换 loop，而是包装 loop：计划是"给 Agent 的路线图"，
    Agent 仍然自主决定每步用什么工具、SQL 怎么写
  - plan_step 匹配是尽力而为（heuristic），不严格绑定
  - 规划失败（build_plan 返回 None）时调用方直接走 run_agent_loop 即可
"""

from collections.abc import Generator
from typing import Optional

from agent.loop import run_agent_loop
from agent.planner import Plan


# ═══════════════════════════════════════════════════════════════
#  主入口：带计划的执行
# ═══════════════════════════════════════════════════════════════

def run_with_plan(
    plan: Plan,
    user_message: str,
    llm_client,
    skill_loader,
    turn_count: int = 0,
    session_messages: Optional[list] = None,
    pending: Optional[dict] = None,
    document_context: Optional[dict] = None,
) -> Generator[dict, None, None]:
    """
    将 Plan 包装执行：
      1. 推送 plan 事件（前端显示规划步骤）
      2. 将计划提示拼接到用户消息
      3. 调用 run_agent_loop，透传所有 SSE 事件
      4. 追踪 tool_start 事件，推送 plan_step 进度

    Yields SSE 事件字典。
    """
    # 1. 推送计划概览
    yield {"type": "plan", "data": plan.to_sse_data()}

    # 2. 拼接计划提示到用户消息
    plan_hint = plan.to_prompt_hint()
    augmented_message = (
        f"{user_message}\n\n{plan_hint}"
        if plan_hint else user_message
    )

    # 3. 执行 loop，监听进度
    tracker = _StepTracker(plan.steps)

    for event in run_agent_loop(
        augmented_message,
        llm_client,
        skill_loader,
        turn_count=turn_count,
        session_messages=session_messages,
        pending=pending,
        document_context=document_context,
    ):
        # 在 tool_start 事件时推送 plan_step 进度
        if event.get("type") == "tool_start":
            tool_name = event.get("data", {}).get("tool", "")
            step = tracker.match_next(tool_name)
            if step:
                yield {
                    "type": "plan_step",
                    "data": {
                        "step_id": step.step_id,
                        "name": step.name,
                        "status": "running",
                    },
                }

        elif event.get("type") == "tool_end":
            ok = event.get("data", {}).get("success", False)
            current = tracker.current_step()
            if current:
                yield {
                    "type": "plan_step",
                    "data": {
                        "step_id": current.step_id,
                        "name": current.name,
                        "status": "done" if ok else "failed",
                    },
                }
                tracker.advance()

        yield event

    # 4. 全部步骤完成
    yield {"type": "plan_done", "data": {"total_steps": len(plan.steps)}}


# ═══════════════════════════════════════════════════════════════
#  步骤追踪器（尽力匹配）
# ═══════════════════════════════════════════════════════════════

# 工具名→计划工具类别的粗粒度映射
_TOOL_CATEGORY = {
    "profile_table": "profile_table",
    "run_sql": "run_sql",
    "run_calculator": "run_calculator",
    "ask_user": "ask_user",
    "request_confirmation": "request_confirmation",
    "read_document": "run_sql",   # 文档读取归类为探索式
    "web_search": "run_sql",      # 联网搜索归类为探索式
}


class _StepTracker:
    """
    顺序追踪计划步骤，尝试将 tool_start 事件匹配到计划步骤。
    匹配是尽力而为：tool 类别相同或当前步骤建议 run_sql 且实际也是 run_sql 即匹配。
    """

    def __init__(self, steps: list):
        self._steps = steps
        self._idx = 0
        self._in_step = False

    def match_next(self, tool_name: str):
        """
        尝试将 tool_name 匹配到下一个待执行步骤。
        若当前正在执行步骤则不推进。
        返回匹配的 PlanStep 或 None。
        """
        if self._in_step or self._idx >= len(self._steps):
            return None

        step = self._steps[self._idx]
        category = _TOOL_CATEGORY.get(tool_name, tool_name)
        step_tool = _TOOL_CATEGORY.get(step.tool, step.tool)

        # 宽松匹配：工具类别相同，或步骤建议 run_sql（探索式）且实际工具也是探索类
        if category == step_tool or (
            step_tool in ("run_sql", "run_calculator") and category in ("run_sql", "run_calculator")
        ):
            self._in_step = True
            return step

        # 即使不匹配，也推进到下一步（避免卡住）
        self._in_step = True
        return step

    def current_step(self):
        if self._in_step and self._idx < len(self._steps):
            return self._steps[self._idx]
        return None

    def advance(self):
        self._in_step = False
        self._idx += 1
