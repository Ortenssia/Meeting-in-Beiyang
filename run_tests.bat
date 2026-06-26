@echo off
chcp 65001 >nul
echo ============================================
echo   相识北洋 - 运行单元测试
echo ============================================
echo.

REM 检查 pytest 是否安装
python -m pytest --version >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 pytest...
    pip install pytest -q
)

echo [1/1] 运行所有测试...
python -m pytest tests/ -v --tb=short

echo.
echo ============================================
echo 测试完成！
echo ============================================
pause
