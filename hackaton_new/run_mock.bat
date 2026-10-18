@echo off
rem Dashboard on fake telemetry (no SUMO, fake ESP32), serves on config server.port (Windows twin of scripts/run_mock.sh).
setlocal
cd /d "%~dp0"
call scripts\env.bat || goto :fail
if exist "web\dist\index.html" goto :web_ok
pushd web
call npm run build || (popd & goto :fail)
popd
:web_ok
for /f "usebackq delims=" %%P in (`python scripts\cfg_get.py server.port`) do set "PORT=%%P"
echo Dashboard: http://localhost:%PORT%    Ctrl+C pentru oprire
start "" /min powershell -NoProfile -Command "Start-Sleep 4; Start-Process 'http://localhost:%PORT%'"
python -m server.main --mock %*
exit /b %errorlevel%
:fail
pause
exit /b 1
