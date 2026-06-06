"""
main.py — DataAgent 入口

支持两种运行模式（通过环境变量 DATAAGENT_ENV 控制）：
  DATAAGENT_ENV=dev  → 浏览器模式（Linux/Mac 开发）
  DATAAGENT_ENV=prod → PyWebView 模式（Windows 生产）
  不设置             → 自动检测

Linux 开发启动：
  python main.py

Windows 生产启动：
  python main.py
"""

import os
import socket
from pathlib import Path

from flask import Flask
from flask_cors import CORS

BASE_DIR = Path(__file__).parent


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def load_config(path: str = None) -> dict:
    import yaml
    cfg_path = path or str(BASE_DIR / 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def create_flask_app() -> Flask:
    import tools.data_loader as _dl
    _dl._db_path = str(BASE_DIR / 'data' / 'dataagent.duckdb')
    _dl.init_duckdb_connection()

    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / 'ui'),
        static_url_path='/static',
        template_folder=str(BASE_DIR / 'ui'),
    )
    CORS(app)

    @app.route('/')
    def index():
        return app.send_static_file('index.html')

    from api import register_blueprints
    register_blueprints(app)

    return app


def main():
    os.chdir(BASE_DIR)

    config = load_config()
    port = find_free_port()

    from tools.runtime_logger import init_logger
    log_mode = config.get('logging', {}).get('mode', 'basic')
    log_max_days = config.get('logging', {}).get('max_days', 30)
    logger = init_logger(mode=log_mode, max_days=log_max_days)
    logger.cleanup_old_logs()

    from platform_adapter.notify_driver import get_notify_driver
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

    from platform_adapter.ui_driver import get_driver
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
