"""
tools/notify.py — 业务通知层

职责：
  1. 封装平台通知驱动，添加业务语义
  2. 区分通知场景：合规告警 / 报告完成 / 一般提示 / 错误
  3. 格式化通知内容（投资经理、产品名、数值等）
  4. 同时推送到桌面弹窗 + 聊天界面消息
"""

from platform_adapter.notify_driver import get_notify_driver

# ═══════════════════════════════════════════════════════════════
#  单例
# ═══════════════════════════════════════════════════════════════

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        _driver = get_notify_driver()
    return _driver


# ═══════════════════════════════════════════════════════════════
#  通知类型
# ═══════════════════════════════════════════════════════════════

def notify_compliance_breach(
    product_name: str,
    manager_name: str,
    entity_name: str,
    concentration_pct: float,
    threshold_pct: float,
    data_date: str,
):
    """
    合规超标告警通知（场景 5.3.1 / 5.3.2）。

    格式如：
      ⚠️ 主体集中度超标提醒（2026-06-01 08:30）
      产品：XX稳健理财01号  负责经理：张三
      超标主体：象屿集团
      当前集中度：12.5%（监控阈值：10%）
      建议：请在 3 个交易日内核查并调整至合规范围
    """
    title = "⚠️ 集中度超标提醒"
    message = (
        f"产品：{product_name}  负责经理：{manager_name}\n"
        f"超标主体：{entity_name}\n"
        f"当前集中度：{concentration_pct}%（监控阈值：{threshold_pct}%）\n"
        f"数据日期：{data_date}\n"
        f"建议：请在 3 个交易日内核查并调整至合规范围"
    )
    _get_driver().push(message, title=title, level="warning")
    return {"title": title, "message": message}


def notify_data_expired(data_type: str, expected_date: str, actual_date: str):
    """数据过期提醒"""
    title = "⚠️ 数据过期"
    message = (
        f"{data_type} 数据不是最新。\n"
        f"要求日期：{expected_date}，实际日期：{actual_date}\n"
        f"合规计算已停止，请上传今日数据后重试。"
    )
    _get_driver().push(message, title=title, level="warning")
    return {"title": title, "message": message}


def notify_report_ready(report_type: str, output_path: str = ""):
    """报告生成完成通知"""
    title = "✅ 报告已生成"
    message = f"「{report_type}」已生成完成。"
    if output_path:
        message += f"\n输出路径：{output_path}"
    _get_driver().push(message, title=title, level="info")
    return {"title": title, "message": message}


def notify_task_failed(task_name: str, error: str):
    """定时任务执行失败通知"""
    title = "❌ 任务执行失败"
    message = f"定时任务「{task_name}」执行失败：{error}"
    _get_driver().push(message, title=title, level="error")
    return {"title": title, "message": message}


def notify_info(message: str):
    """一般信息通知"""
    _get_driver().push(message, title="DataAgent", level="info")


def notify_warning(message: str):
    """一般警告通知"""
    _get_driver().push(message, title="DataAgent", level="warning")
