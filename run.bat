@echo off
chcp 65001 >nul 2>&1
title DataAgent

:: 检查 .venv 是否存在
if not exist .venv (
    echo [错误] 未找到 .venv，请先运行 setup.bat 安装
    pause
    exit /b 1
)

:: 检查配置文件
if not exist config.yaml (
    echo [提示] 请先编辑 config.yaml 配置 LLM
    echo        可复制 config.example.yaml 为 config.yaml 后修改
    pause
    exit /b 1
)

:: 激活虚拟环境并启动
call .venv\Scripts\activate.bat
python main.py
pause
