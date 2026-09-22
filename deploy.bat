@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\deploy.ps1" -Action Deploy
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" (
    echo Deployment failed. See .deploy\deploy.log for details.
) else (
    echo Deployment completed.
)
pause
exit /b %EXIT_CODE%
