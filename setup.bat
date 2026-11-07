@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
        if errorlevel 1 goto :failed
        .venv\Scripts\python.exe -m pip install -r requirements.txt
        if errorlevel 1 goto :failed
        echo Setup complete.
        pause
        exit /b 0
    )
)

where python >nul 2>nul
if errorlevel 1 goto :missing_python
python --version >nul 2>nul
if errorlevel 1 goto :missing_python
python -m venv .venv
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo Setup complete.
pause
exit /b 0

:missing_python
echo Python 3 was not found. Opening the Python download page.
start "" "https://www.python.org/downloads/"
echo Install Python 3, making sure to enable "Add Python to PATH", then run setup.bat again.
pause
exit /b 1

:failed
echo Setup failed. Check the error above and try again.
pause
exit /b 1
