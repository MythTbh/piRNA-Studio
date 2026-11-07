@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\launch-windows.ps1"
if errorlevel 1 (
  echo.
  echo piRNA Studio could not start. Review the message above, then reopen this launcher to retry.
  pause
  exit /b 1
)
