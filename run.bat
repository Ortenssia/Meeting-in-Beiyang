@echo off
chcp 65001 >nul
echo ============================================
echo   相识北洋 - 校园社交应用 (挑战3)
echo ============================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [1/2] 检查并安装依赖...
pip install -r requirements.txt -q

echo.
echo [2/2] 启动应用...
echo.
echo 提示：按 Ctrl+C 可退出应用
echo ============================================
python main.py

pause
