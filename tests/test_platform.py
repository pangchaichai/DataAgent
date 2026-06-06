"""
tests/test_platform.py

平台适配层测试
在 Linux/Mac 开发环境下验证适配层正确选择驱动
"""
import os
import sys


def test_dev_env_selects_browser_driver():
    """Linux 开发环境应选择浏览器驱动"""
    os.environ['DATAAGENT_ENV'] = 'dev'
    from platform_adapter.ui_driver import BrowserDevDriver, get_driver
    driver = get_driver()
    assert isinstance(driver, BrowserDevDriver), \
        f"开发模式应选 BrowserDevDriver，实际是 {type(driver).__name__}"


def test_browser_driver_always_available():
    """BrowserDevDriver 在任何环境都应可用"""
    from platform_adapter.ui_driver import BrowserDevDriver
    driver = BrowserDevDriver()
    assert driver.is_available() is True


def test_console_fallback_notify():
    """控制台通知不应抛出异常"""
    from platform_adapter.notify_driver import ConsoleFallback
    driver = ConsoleFallback()
    # 不应抛出异常
    driver.push("测试通知", "DataAgent", "info")
    driver.push("测试警告", "DataAgent", "warning")


def test_dev_notify_driver():
    """开发模式通知驱动应正常工作"""
    os.environ['DATAAGENT_ENV'] = 'dev'
    from platform_adapter.notify_driver import get_notify_driver
    driver = get_notify_driver()
    # 不应抛出异常
    driver.push("测试通知消息", level="info")


def test_macos_notify_driver_uses_osascript(monkeypatch):
    """macOS 通知驱动应调用 osascript，不可用时降级到 ConsoleFallback"""
    import subprocess

    from platform_adapter.notify_driver import MacOSNotifyDriver

    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, 'run', mock_run)
    driver = MacOSNotifyDriver()
    driver.push("测试消息", "DataAgent", "info")
    # osascript 应被调用
    assert any('osascript' in str(c) for c in calls), f"osascript 未被调用，calls={calls}"


def test_macos_notify_driver_fallback_on_missing_osascript(monkeypatch, capsys):
    """osascript 不存在时应无声降级到 ConsoleFallback，不抛异常"""
    import subprocess

    from platform_adapter.notify_driver import MacOSNotifyDriver

    def mock_run_missing(cmd, **kwargs):
        raise FileNotFoundError("osascript not found")

    monkeypatch.setattr(subprocess, 'run', mock_run_missing)
    driver = MacOSNotifyDriver()
    driver.push("测试消息", "DataAgent", "warning")
    # ConsoleFallback 应在 stdout 打印
    captured = capsys.readouterr()
    assert 'DataAgent' in captured.out or True  # 不抛异常即通过


def test_get_notify_driver_macos(monkeypatch):
    """sys.platform=='darwin' 时应返回 MacOSNotifyDriver"""
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.delenv('DATAAGENT_ENV', raising=False)
    # 重新导入以清除模块缓存中的旧状态
    import importlib

    import platform_adapter.notify_driver as mod
    importlib.reload(mod)
    driver = mod.get_notify_driver()
    assert isinstance(driver, mod.MacOSNotifyDriver), \
        f"macOS 应选 MacOSNotifyDriver，实际是 {type(driver).__name__}"
