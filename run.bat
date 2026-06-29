@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

echo ============================================
echo   Meeting in Beiyang 1.8.95
echo ============================================
echo.

if exist "%VENV_PYTHON%" goto :venv_ready

set "BOOTSTRAP_PYTHON="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3"

if not defined BOOTSTRAP_PYTHON (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
)

if not defined BOOTSTRAP_PYTHON (
    echo [ERROR] Python was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo During installation, enable "Add Python to PATH".
    goto :failed
)

echo [1/3] Creating local Python environment...
%BOOTSTRAP_PYTHON% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not create .venv.
    echo Repair Python and make sure the venv module is installed.
    goto :failed
)

:venv_ready
"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The existing .venv uses an unsupported Python version.
    echo Delete the .venv folder and run this file again with Python 3.10+ installed.
    goto :failed
)

echo [2/3] Checking dependencies...
"%VENV_PYTHON%" -c "import importlib.metadata as m; import PIL, plyer; raise SystemExit(0 if m.version('flet') == '0.85.3' else 1)" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages into .venv...
    "%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        echo Check the internet connection, proxy, and firewall, then run again.
        goto :failed
    )
) else (
    echo Dependencies are ready.
)

echo.
echo [3/3] Starting app...
echo.
"%VENV_PYTHON%" "%~dp0core\main.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo App exited with code %EXIT_CODE%.
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%

:failed
echo.
pause
exit /b 1
