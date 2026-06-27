@echo off
setlocal
cd /d "%~dp0"
set PIP_DISABLE_PIP_VERSION_CHECK=1

echo ============================================
echo   Meeting in Beiyang - Challenge 3
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found. Please install Python 3.8 or newer.
    pause
    exit /b 1
)

echo [1/2] Checking dependencies...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [2/2] Starting app...
echo.
python core\main.py %*

set EXIT_CODE=%ERRORLEVEL%
echo.
echo App exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
