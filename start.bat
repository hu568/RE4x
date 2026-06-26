@echo off
chcp 936 >nul
title SD Enhance - 图片放大工具

echo ========================================
echo   SD Enhance - 图片放大工具
echo   正在启动服务，请稍候...
echo ========================================

:: 检测生产模式（打包 exe）
if exist "script\sd-enhance-server\sd-enhance-server.exe" (
    set "SERVER_CMD=script\sd-enhance-server\sd-enhance-server.exe"
    goto :start_server
)

:: 检测开发模式（venv）
if exist "server\.venv\Scripts\python.exe" (
    set "SERVER_CMD=server\.venv\Scripts\python.exe server\main.py"
    goto :start_server
)

:: 检测系统 Python
where python >nul 2>&1
if not errorlevel 1 (
    set "SERVER_CMD=python server\main.py"
    goto :start_server
)

:: 找不到 Python
echo [错误] 找不到 Python，请先安装 Python 3.12+
pause
exit /b 1

:start_server
start "SD-Enhance-Server" %SERVER_CMD%

echo 正在等待服务就绪...
:wait
timeout /t 1 /nobreak >nul
curl -s http://localhost:5000/ >nul 2>&1
if errorlevel 1 goto wait

echo 服务已就绪！正在打开浏览器...
start http://localhost:5000/

echo ========================================
echo   服务地址: http://localhost:5000/
echo   关闭此窗口即可停止服务
echo ========================================
pause
