@echo off
title DataAgent EXE Builder

:: Switch to project root (parent of scripts/ directory)
cd /d "%~dp0.."

echo.
echo ============================================================
echo      DataAgent v3.0-beta1 - PyInstaller EXE Build
echo ============================================================
echo.

:: Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python not found. Please install Python 3.11 first.
    echo          Download: https://www.python.org/downloads/
    echo          Check: Add Python to PATH during installation
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [CHECK] Python version: %PYVER%

:: Install PyInstaller
echo.
echo [INSTALL] PyInstaller ...
pip install pyinstaller>=6.20.0 --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller install failed
    pause
    exit /b 1
)

:: Install runtime dependencies
echo [INSTALL] Runtime dependencies ...
pip install -r requirements-prod.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [WARN] Some dependencies failed to install, continuing...
)

:: Clean old build
echo.
echo [CLEAN] Removing old build artifacts ...
if exist build rmdir /s /q build
if exist dist\DataAgent rmdir /s /q dist\DataAgent

:: Run PyInstaller
echo.
echo [BUILD] Running PyInstaller (onedir mode) ...
echo         This may take 2-5 minutes...
echo.
pyinstaller DataAgent.spec --noconfirm --clean
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller build failed
    echo         See build\warn-DataAgent.txt for details
    pause
    exit /b 1
)

:: Create runtime data directories
echo.
echo [CREATE] Runtime data directories ...
for %%d in (data\uploads data\outputs data\sessions data\compliance_audit data\logs data\skill_drafts) do (
    if not exist dist\DataAgent\%%d mkdir dist\DataAgent\%%d
)

:: Copy README if exists
if exist README_USER.txt copy README_USER.txt dist\DataAgent\README.txt >nul

:: Copy config.example.yaml to config.yaml for first-run convenience
:: (Note: pyinstaller_runtime_hook.py also auto-creates config.yaml on first launch
::  as a safety net, so the EXE is self-sufficient even if this step fails)
if exist dist\DataAgent\config.yaml (
    echo [CONFIG] config.yaml already exists — skipped
) else (
    if exist config.example.yaml (
        copy config.example.yaml dist\DataAgent\config.yaml
        if exist dist\DataAgent\config.yaml (
            echo [CONFIG] Created config.yaml from config.example.yaml
        ) else (
            echo [WARN] Failed to create config.yaml — will be auto-created on first launch
        )
    ) else (
        echo [WARN] config.example.yaml not found — config.yaml will be auto-created on first launch
    )
)

:: Done
echo.
echo ============================================================
echo    BUILD COMPLETE
echo ============================================================
echo.
echo    Output:  dist\DataAgent\
echo    Launch:  dist\DataAgent\DataAgent.exe
echo.
echo    IMPORTANT: Edit config.yaml before first run:
echo      dist\DataAgent\config.yaml  (LLM API Key, etc.)
echo.
echo    To distribute: right-click dist\DataAgent\ and
echo      Send to ^> Compressed (zipped) folder
echo.
pause
