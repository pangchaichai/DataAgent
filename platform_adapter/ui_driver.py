"""
platform/ui_driver.py

UI 驱动适配层 — 平台差异在此隔离，业务代码感知不到平台

设计思路（适配器模式）：
  定义统一接口 UIDriver
  ├── BrowserDevDriver   → Linux/Mac 开发环境（Flask + 系统浏览器）
  └── PyWebViewDriver    → Windows 生产环境（PyWebView 原生窗口）

选择逻辑：
  DATAAGENT_ENV=dev  → BrowserDevDriver（默认，Linux开发时使用）
  DATAAGENT_ENV=prod → PyWebViewDriver（Windows 生产时使用）
  或自动检测平台：sys.platform == 'win32' 且 pywebview 可导入

业务代码只调用 UIDriver 接口，永远不直接调用 pywebview 或浏览器。
"""

import os
import sys
import webbrowser
import threading
import time
from abc import ABC, abstractmethod


class UIDriver(ABC):
    """统一 UI 驱动接口"""

    @abstractmethod
    def start(self, flask_app, port: int, title: str, width: int, height: int):
        """启动窗口/浏览器，阻塞直到用户关闭"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检测当前环境是否支持此驱动"""
        pass


def _wait_for_flask(port: int, timeout: float = 10.0) -> bool:
    """健康检查：轮询直到 Flask 响应，避免窗口早于服务就绪而载入"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


class BrowserDevDriver(UIDriver):
    """
    Linux/Mac 开发驱动
    Flask 服务 + 自动打开系统浏览器
    功能完整，仅窗口形态不同（浏览器Tab而非原生窗口）
    """

    def is_available(self) -> bool:
        return True  # 任何环境都可用

    def start(self, flask_app, port: int, title: str, width: int, height: int):
        flask_thread = threading.Thread(
            target=lambda: flask_app.run(
                host='127.0.0.1', port=port,
                threaded=True, use_reloader=False, debug=False
            ),
            daemon=True
        )
        flask_thread.start()

        url = f'http://127.0.0.1:{port}'
        print(f"\n{'='*50}")
        print(f"  DataAgent 开发模式（Linux/Browser）")
        print(f"  访问地址：{url}")
        print(f"  关闭方式：Ctrl+C")
        print(f"{'='*50}\n")

        if _wait_for_flask(port):
            webbrowser.open(url)
        else:
            print(f"⚠️  Flask 未能在 10s 内就绪，请手动访问 {url}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nDataAgent 已停止。")


class PyWebViewDriver(UIDriver):
    """
    Windows 生产驱动
    PyWebView 原生窗口，强制使用 WebView2（Edge Chromium 内核）

    ★ 必须安装 WebView2 Runtime，否则会给出安装引导。
      WebView2 Runtime 下载：https://developer.microsoft.com/microsoft-edge/webview2/
      大多数 Windows 10/11 已预装，如未预装请下载「常青独立安装程序」。
    """

    def is_available(self) -> bool:
        if sys.platform != 'win32':
            return False
        try:
            import webview  # noqa
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_webview2_runtime() -> bool:
        """检测 WebView2 Runtime 是否已安装（Windows Only）"""
        try:
            import winreg
            # WebView2 Runtime 注册表路径（64位和32位）
            paths = [
                r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
                r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
            ]
            for reg_path in paths:
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
                    winreg.CloseKey(key)
                    return True
                except OSError:
                    pass
            return False
        except Exception:
            return False

    def start(self, flask_app, port: int, title: str, width: int, height: int):
        import webview

        # WebView2 Runtime 检测
        if not self._check_webview2_runtime():
            print("\n" + "="*60)
            print("  ⚠️  未检测到 WebView2 Runtime")
            print("  DataAgent 需要 Microsoft WebView2 Runtime 才能运行。")
            print()
            print("  请按以下步骤安装：")
            print("  1. 访问 https://developer.microsoft.com/microsoft-edge/webview2/")
            print("  2. 下载「常青独立安装程序」（Evergreen Standalone Installer）")
            print("  3. 安装完成后重新启动 DataAgent")
            print()
            print("  注意：Windows 11 和大多数 Windows 10 已预装 WebView2，")
            print("  若您看到此提示，请确认系统更新已完成。")
            print("="*60 + "\n")
            # 仍然尝试启动，让 PyWebView 显示自己的错误信息（可能有内置引导）

        flask_thread = threading.Thread(
            target=lambda: flask_app.run(
                host='127.0.0.1', port=port,
                threaded=True, use_reloader=False, debug=False
            ),
            daemon=True
        )
        flask_thread.start()

        # 健康检查：等 Flask 就绪后再创建窗口
        if not _wait_for_flask(port, timeout=15.0):
            print(f"⚠️  Flask 服务未能在 15s 内就绪（端口 {port}），强制继续...")

        webview.create_window(
            title=title,
            url=f'http://127.0.0.1:{port}',
            width=width,
            height=height,
            resizable=True,
            min_size=(800, 600),
        )

        # 强制指定 edgechromium（WebView2）后端，避免回退到 mshtml（IE11）
        # mshtml 不支持 fetch API / EventSource / CSS 变量等现代特性
        try:
            webview.start(gui='edgechromium')
        except Exception as e:
            err = str(e).lower()
            if 'edgechromium' in err or 'webview2' in err or 'not found' in err:
                print("\n⚠️  WebView2 启动失败，尝试默认后端...")
                print("   请安装 WebView2 Runtime 以获得最佳体验")
                try:
                    webview.start()
                except Exception as e2:
                    print(f"❌  PyWebView 启动失败：{e2}")
                    print("   请检查 WebView2 Runtime 是否已安装。")
            else:
                raise


def get_driver() -> UIDriver:
    """
    自动选择合适的 UI 驱动。
    优先级：环境变量 > 平台自动检测
    """
    env = os.environ.get('DATAAGENT_ENV', 'auto').lower()

    if env == 'dev':
        return BrowserDevDriver()
    if env == 'prod':
        driver = PyWebViewDriver()
        if not driver.is_available():
            print("⚠️  DATAAGENT_ENV=prod 但 pywebview 不可用，回退到浏览器模式")
            return BrowserDevDriver()
        return driver

    # auto：平台自动检测
    pywebview_driver = PyWebViewDriver()
    if pywebview_driver.is_available():
        return pywebview_driver
    return BrowserDevDriver()
