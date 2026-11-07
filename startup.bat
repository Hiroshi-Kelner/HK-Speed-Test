@echo off
setlocal
set "RUN_SCRIPT=%~dp0run.bat"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $shortcut = $ws.CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\HK Speed Test.lnk')); $shortcut.TargetPath = '%RUN_SCRIPT%'; $shortcut.WorkingDirectory = '%~dp0'; $shortcut.Save()"
if errorlevel 1 (
    echo Could not add the app to Windows startup.
    pause
    exit /b 1
)
echo HK Speed Test will start when you sign in to Windows.
pause
