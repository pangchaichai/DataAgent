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
    from platform_adapter.ui_driver import get_driver, BrowserDevDriver
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
