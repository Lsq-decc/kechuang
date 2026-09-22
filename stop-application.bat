@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1" -Action Stop
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Stop failed. See .deploy\deploy.log for details.
    pause
)
exit /b %EXIT_CODE%
