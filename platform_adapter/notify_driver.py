"""
platform/notify_driver.py

通知驱动适配层 — 跨平台通知推送

┌── WindowsToastDriver  → Windows 生产（winotify toast 弹窗）
├── LinuxDesktopDriver  → Linux 桌面（notify-send，开发调试用）
└── ConsoleFallback     → 无桌面环境（Claude Code SSH等，打印到终端）
"""

import os
import subprocess
import sys
from abc import ABC, abstractmethod


class NotifyDriver(ABC):

    @abstractmethod
    def push(self, message: str, title: str = "DataAgent", level: str = "info"):
        """
        level: 'info' | 'warning' | 'error'
        """
        pass


class WindowsToastDriver(NotifyDriver):
    """Windows 原生 toast 通知（生产环境）"""

    def push(self, message: str, title: str = "DataAgent", level: str = "info"):
        try:
            from winotify import Notification, audio
            icon_map = {
                "info": "",
                "warning": "⚠️ ",
                "error": "❌ "
            }
            toast = Notification(
                app_id="DataAgent",
                title=f"{icon_map.get(level, '')}{title}",
                msg=message,
                duration="long"
            )
            if level == "warning":
                toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            # 降级到控制台
            ConsoleFallback().push(message, title, level)


class LinuxDesktopDriver(NotifyDriver):
    """Linux 桌面通知（开发调试用，需要 notify-send）"""

    def push(self, message: str, title: str = "DataAgent", level: str = "info"):
        urgency_map = {"info": "normal", "warning": "critical", "error": "critical"}
        try:
            subprocess.run([
                "notify-send",
                "-u", urgency_map.get(level, "normal"),
                title, message
            ], timeout=3, capture_output=True)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # notify-send 不可用，降级
            ConsoleFallback().push(message, title, level)


class MacOSNotifyDriver(NotifyDriver):
    """macOS 原生通知（Notification Center，使用内置 osascript，零额外依赖）"""

    def push(self, message: str, title: str = "DataAgent", level: str = "info"):
        try:
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(
                ["osascript", "-e", script],
                timeout=3, capture_output=True
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            ConsoleFallback().push(message, title, level)


class ConsoleFallback(NotifyDriver):
    """
    控制台输出 — Claude Code SSH 环境的通知方式
    在终端打印醒目的通知，开发时完全够用
    """

    LEVEL_SYMBOLS = {
        "info": "ℹ️ ",
        "warning": "⚠️ ",
        "error": "❌ "
    }

    def push(self, message: str, title: str = "DataAgent", level: str = "info"):
        symbol = self.LEVEL_SYMBOLS.get(level, "")
        border = "─" * 50
        print(f"\n{border}")
        print(f"  {symbol}[{title}]")
        print(f"  {message}")
        print(f"{border}\n")


def get_notify_driver() -> NotifyDriver:
    """自动选择通知驱动"""
    env = os.environ.get('DATAAGENT_ENV', 'auto').lower()

    if env == 'dev':
        if sys.platform == 'darwin':
            return MacOSNotifyDriver()
        if sys.platform.startswith('linux'):
            return LinuxDesktopDriver()
        return ConsoleFallback()

    if sys.platform == 'win32':
        try:
            import winotify  # noqa
            return WindowsToastDriver()
        except ImportError:
            return ConsoleFallback()

    if sys.platform == 'darwin':
        return MacOSNotifyDriver()

    if sys.platform.startswith('linux'):
        return LinuxDesktopDriver()

    return ConsoleFallback()
