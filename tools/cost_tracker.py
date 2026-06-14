"""
tools/cost_tracker.py — LLM 成本追踪（ETCLOVG O 层，I-3b）

按 DeepSeek V3 公开定价估算成本（仅供参考，不影响业务逻辑）。
CostTracker 是线程安全的会话级单例，通过 get_cost_tracker() 获取。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

# DeepSeek V3 定价（CNY/1M tokens，仅估算用）
_DEEPSEEK_INPUT_PRICE_PER_1M = 1.0    # ¥1.0/1M input tokens
_DEEPSEEK_OUTPUT_PRICE_PER_1M = 2.0   # ¥2.0/1M output tokens

# LM Studio 本地模型——无 API 费用
_LOCAL_PRICE_PER_1M = 0.0


@dataclass
class CallRecord:
    provider: str
    input_tokens: int
    output_tokens: int
    duration_ms: float
    cost_cny: float


@dataclass
class CostSummary:
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cny: float = 0.0
    total_duration_ms: float = 0.0
    by_provider: dict[str, dict] = field(default_factory=dict)


class CostTracker:
    """线程安全的 LLM 调用成本追踪器"""

    def __init__(self, budget_cny: float = 10.0):
        self._lock = threading.Lock()
        self._records: list[CallRecord] = []
        self._budget_cny = budget_cny

    def record(
        self,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float = 0.0,
    ) -> None:
        """记录一次 LLM 调用"""
        cost = _estimate_cost(provider, input_tokens, output_tokens)
        record = CallRecord(
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            cost_cny=cost,
        )
        with self._lock:
            self._records.append(record)

    def get_summary(self) -> CostSummary:
        """返回当前会话累计统计"""
        with self._lock:
            records = list(self._records)

        summary = CostSummary()
        summary.total_calls = len(records)
        for r in records:
            summary.total_input_tokens += r.input_tokens
            summary.total_output_tokens += r.output_tokens
            summary.total_cost_cny += r.cost_cny
            summary.total_duration_ms += r.duration_ms

            p = r.provider
            if p not in summary.by_provider:
                summary.by_provider[p] = {
                    "calls": 0, "input_tokens": 0,
                    "output_tokens": 0, "cost_cny": 0.0,
                }
            summary.by_provider[p]["calls"] += 1
            summary.by_provider[p]["input_tokens"] += r.input_tokens
            summary.by_provider[p]["output_tokens"] += r.output_tokens
            summary.by_provider[p]["cost_cny"] += r.cost_cny

        return summary

    def check_budget(self) -> tuple[bool, str]:
        """
        检查是否超出预算。

        返回: (within_budget, message)
        """
        summary = self.get_summary()
        if summary.total_cost_cny > self._budget_cny:
            return False, (
                f"⚠️ 当前会话已消耗 ¥{summary.total_cost_cny:.4f}，"
                f"超出预算 ¥{self._budget_cny:.2f}"
            )
        remaining = self._budget_cny - summary.total_cost_cny
        return True, f"预算剩余 ¥{remaining:.4f}"

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的 dict（用于 API 返回）"""
        s = self.get_summary()
        within, msg = self.check_budget()
        return {
            "total_calls": s.total_calls,
            "total_input_tokens": s.total_input_tokens,
            "total_output_tokens": s.total_output_tokens,
            "total_tokens": s.total_input_tokens + s.total_output_tokens,
            "total_cost_cny": round(s.total_cost_cny, 6),
            "total_duration_ms": round(s.total_duration_ms, 1),
            "budget_cny": self._budget_cny,
            "within_budget": within,
            "budget_message": msg,
            "by_provider": {
                p: {**v, "cost_cny": round(v["cost_cny"], 6)}
                for p, v in s.by_provider.items()
            },
        }


# ═══════════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════════

_tracker_lock = threading.Lock()
_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = CostTracker()
    return _tracker


def reset_cost_tracker() -> None:
    """重置（新会话开始时调用）"""
    global _tracker
    with _tracker_lock:
        _tracker = CostTracker()


# ═══════════════════════════════════════════════════════════════
#  成本估算
# ═══════════════════════════════════════════════════════════════

def _estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    """估算调用成本（CNY）"""
    if provider in ("lmstudio", "local"):
        return 0.0
    # DeepSeek / enterprise / 默认
    input_cost = (input_tokens / 1_000_000) * _DEEPSEEK_INPUT_PRICE_PER_1M
    output_cost = (output_tokens / 1_000_000) * _DEEPSEEK_OUTPUT_PRICE_PER_1M
    return input_cost + output_cost
