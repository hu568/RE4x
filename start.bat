@echo off
chcp 65001 >nul
title SD Enhance - Image Upscaler

echo ========================================
echo   SD Enhance - Image Upscaler (Desktop)
echo ========================================

REM --- Production mode: packaged GUI exe ---
if exist "tools\sd-enhance-server\sd-enhance-server.exe" (
    start "" "tools\sd-enhance-server\sd-enhance-server.exe"
    exit /b 0
)

REM --- Dev mode: venv python ---
if exist "server\.venv\Scripts\python.exe" (
    start "" "server\.venv\Scripts\python.exe" server\app.py
    exit /b 0
)

REM --- System Python ---
where python >nul 2>&1
if not errorlevel 1 (
    python server\app.py
    exit /b 0
)

echo [ERROR] Python not found. Please install Python 3.12+.
pause
exit /b 1
