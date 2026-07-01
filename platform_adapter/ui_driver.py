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
import threading
import time
import webbrowser
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
        platform_name = "macOS" if sys.platform == 'darwin' else "Linux"
        stop_key = "Cmd+C" if sys.platform == 'darwin' else "Ctrl+C"
        print(f"\n{'='*50}")
        print(f"  DataAgent 开发模式（{platform_name}/Browser）")
        print(f"  访问地址：{url}")
        print(f"  关闭方式：{stop_key}")
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
    原生窗口驱动（Windows / macOS / Linux 均可用）
    Windows 使用 WebView2（Edge Chromium 内核），macOS 使用 WebKit。

    Windows 注意：需安装 WebView2 Runtime（大多数 Win10/11 已预装）。
    macOS 注意：需安装 pywebview（pip install pywebview）。
    """

    def is_available(self) -> bool:
        try:
            import webview  # noqa
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_webview2_runtime() -> bool:
        """检测 WebView2 Runtime 是否已安装（Windows Only）。

        检查两个来源：
        1. 注册表 Evergreen Runtime 键
        2. 文件系统中的 DLL（更可靠）
        """
        # 方法1：检查注册表
        try:
            import winreg
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
        except Exception:
            pass

        # 方法2：检查 DLL 文件是否存在
        import os as _os
        program_files = _os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        webview_dir = _os.path.join(program_files, 'Microsoft', 'EdgeWebView', 'Application')
        if _os.path.isdir(webview_dir):
            for ver in _os.listdir(webview_dir):
                dll_path = _os.path.join(webview_dir, ver, 'EBWebView', 'x64', 'EmbeddedBrowserWebView.dll')
                if _os.path.isfile(dll_path):
                    return True

        return False

    def start(self, flask_app, port: int, title: str, width: int, height: int):
        import sys as _sys
        import webbrowser as _wb

        if not title:
            title = 'DataAgent'

        # Windows: 检测 WebView2，缺失则自动降级浏览器模式
        use_native = False
        if _sys.platform == 'win32':
            if self._check_webview2_runtime():
                use_native = True
            else:
                print("[DataAgent] WebView2 Runtime 未安装，自动切换浏览器模式")
                print("[DataAgent] 安装 Microsoft Edge 后可获得原生窗口体验")

        if use_native:
            # ── 原生窗口模式 ──────────────────────────────
            import webview

            flask_thread = threading.Thread(
                target=lambda: flask_app.run(
                    host='127.0.0.1', port=port,
                    threaded=True, use_reloader=False, debug=False
                ),
                daemon=True
            )
            flask_thread.start()

            if not _wait_for_flask(port, timeout=15.0):
                print(f"[DataAgent] WARNING: Flask not ready within 15s (port {port})")

            webview.create_window(
                title=title,
                url=f'http://127.0.0.1:{port}',
                width=width,
                height=height,
                resizable=True,
                min_size=(800, 600),
                text_select=True,
            )
            webview.start(gui='edgechromium')
        else:
            # ── 浏览器模式 ────────────────────────────────
            print(f"[DataAgent] 浏览器模式 — http://127.0.0.1:{port}")
            print("[DataAgent] 按 Ctrl+C 退出")
            _wb.open(f'http://127.0.0.1:{port}')
            flask_app.run(
                host='127.0.0.1', port=port,
                threaded=True, use_reloader=False, debug=False
            )


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
