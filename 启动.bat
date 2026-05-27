@echo off
chcp 65001 >nul
title 文旅集团数据查询系统

cd /d "%~dp0"

echo ========================================
echo   文旅集团 - 数据查询汇总系统
echo ========================================
echo.
echo 正在检查环境...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到Python，请先安装Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

pip show streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装依赖...
    pip install streamlit pandas openpyxl -q
)

echo.
echo 正在启动...
echo 浏览器将自动打开 http://localhost:8501
echo 手机端可访问 http://你的电脑IP:8501
echo 按 Ctrl+C 可停止服务
echo ========================================
echo.

streamlit run app.py --server.port 8501

pause
