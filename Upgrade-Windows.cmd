@echo off
setlocal
if "%~1"=="" (
  echo Usage: Upgrade-Windows.cmd "D:\path\to\aistudio-api" [port]
  exit /b 2
)
set "PROJECT=%~1"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8080"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Upgrade-Windows.ps1" -ProjectPath "%PROJECT%" -Port %PORT%
exit /b %ERRORLEVEL%