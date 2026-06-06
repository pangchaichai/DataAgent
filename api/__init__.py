"""
api/__init__.py — Blueprint 注册入口
"""
from flask import Flask


def register_blueprints(app: Flask) -> None:
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
