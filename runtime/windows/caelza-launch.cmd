@echo off
rem Start menu "Caelza": first run walks through setup, then starts the agent and opens the dashboard.
setlocal
set "HERE=%~dp0"
if not exist "%USERPROFILE%\.caelza\config.toml" (
  echo Welcome to Caelza. Answer the questions below to finish setup.
  echo.
  "%HERE%caelza.exe" quickstart
  if errorlevel 1 (
    echo.
    echo Setup did not finish. Close this window and open Caelza again to retry.
    pause
    exit /b 1
  )
)
start "Caelza agent" /min "%HERE%caelza.exe" daemon
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:42617"
