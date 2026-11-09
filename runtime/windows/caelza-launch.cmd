@echo off
rem Start menu "Caelza": starts the agent if it is not running, then opens the dashboard.
rem The first run is Cael's setup in the browser: until an agent exists the dashboard
rem lands on /setup (two doors, a provider wheel, a model wheel, one key box), and the
rem pairing screen before it shows its code already filled in, so pairing is one click.
rem No console wizard: the agent's own window stays minimised in the taskbar.
setlocal
set "HERE=%~dp0"
set "URL=http://127.0.0.1:42617"

curl.exe -s -f -o nul "%URL%/health" >nul 2>&1 && goto open

start "Caelza agent" /min "%HERE%caelza.exe" daemon
set /a tries=0
:wait
curl.exe -s -f -o nul "%URL%/health" >nul 2>&1 && goto open
set /a tries+=1
if %tries% geq 30 goto slow
timeout /t 1 /nobreak >nul
goto wait

:slow
echo Caelza is taking a while to start. The dashboard opens at %URL% as soon as it answers;
echo the agent's own window is minimised in the taskbar and says what it is doing.

:open
start "" "%URL%/"
endlocal
