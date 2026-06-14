"""
main.py — DataAgent 入口

支持两种运行模式（通过环境变量 DATAAGENT_ENV 控制）：
  DATAAGENT_ENV=dev  → 浏览器模式（Linux/Mac 开发）
  DATAAGENT_ENV=prod → PyWebView 模式（Windows 生产）
  不设置             → 自动检测

Linux 开发启动：
  python main.py
  # 或显式指定
  DATAAGENT_ENV=dev python main.py

Windows 生产启动：
  python main.py
  # 或双击打包后的 DataAgent.exe
"""

import os
import socket
import time
from pathlib import Path

from flask import Flask
from flask_cors import CORS

from platform_adapter.notify_driver import get_notify_driver
from platform_adapter.ui_driver import get_driver

# ═══════════════════════════════════════════════════════════════
#  基础路径（绝对路径，兼容 PyInstaller 打包 + 任意 CWD）
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def find_free_port() -> int:
    """随机分配空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def load_config(path: str = None) -> dict:
    from pathlib import Path

    import yaml
    cfg_path = Path(path) if path else BASE_DIR / 'config.yaml'
    if not cfg_path.exists():
        cfg_path = BASE_DIR / 'config.example.yaml'
    try:
        with open(cfg_path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def wait_for_flask(port: int, timeout: float = 10.0):
    """健康检查：等待 Flask 就绪再打开窗口，最多等 timeout 秒"""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


# ═══════════════════════════════════════════════════════════════
#  Flask 应用 + API 路由
# ═══════════════════════════════════════════════════════════════

def create_flask_app() -> Flask:
    """创建 Flask 应用，注册所有 API 路由"""
    # 使用绝对路径，兼容任意 CWD 和 PyInstaller
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / 'ui'),
        static_url_path='/static',
        template_folder=str(BASE_DIR / 'ui'),
    )
    CORS(app)

    # ── 注册 Blueprint 模块 ────────────────────────────────
    from api.chat import chat_bp
    from api.config_api import config_bp
    from api.data import data_bp
    from api.report_api import report_bp
    from api.skill_api import skill_bp
    from api.system_api import system_bp

    app.register_blueprint(chat_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(skill_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(system_bp)

    # ── 前端页面 ────────────────────────────────────────────
    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    return app


# ═══════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════

def main():
    # 将工作目录切换到项目根目录，确保各模块的相对路径兼容
    os.chdir(BASE_DIR)

    config = load_config()
    port = find_free_port()

    # 初始化运行时日志
    from tools.runtime_logger import init_logger
    log_mode = config.get('logging', {}).get('mode', 'basic')
    log_max_days = config.get('logging', {}).get('max_days', 30)
    logger = init_logger(mode=log_mode, max_days=log_max_days)
    logger.cleanup_old_logs()

    notify = get_notify_driver()
    notify.push(f"DataAgent 启动中... 端口：{port}", level="info")

    if config.get('scheduler', {}).get('enabled', False):
        from scheduler.task_manager import TaskManager
        task_mgr = TaskManager(
            task_config_path=config['scheduler']['task_config'],
            agent_loop_fn=None,
            notify_fn=notify.push,
        )
        task_mgr.load_and_register()
        task_mgr.on_startup()
        task_mgr.start_background()

    app = create_flask_app()

    driver = get_driver()
    run_mode = type(driver).__name__
    print(f"运行模式：{run_mode}")
    logger.log_app_start(port=port, mode=run_mode, log_mode=log_mode)

    driver.start(
        flask_app=app,
        port=port,
        title=config.get('app', {}).get('window_title', 'DataAgent'),
        width=config.get('app', {}).get('window_width', 1280),
        height=config.get('app', {}).get('window_height', 800),
    )


if __name__ == '__main__':
    main()
