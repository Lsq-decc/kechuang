@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1" -Action Doctor
echo.
pause
exit /b %ERRORLEVEL%
