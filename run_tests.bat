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
REM 使用本地 basetemp，避免系统临时目录权限不足导致用例全部 setup 失败
python -m pytest core/tests/ -v --tb=short --basetemp=".pytest_tmp"

echo.
echo ============================================
echo 测试完成！
echo ============================================
pause
