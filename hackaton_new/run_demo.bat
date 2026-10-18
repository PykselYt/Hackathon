@echo off
rem Full demo on config server.port: both SUMO simulations + dashboard (+ ESP32 when connected).
rem   run_demo.bat               real simulations, serial bridge on (the ESP32 COM port is found on its own)
rem   run_demo.bat --no-serial   without the board
rem   run_demo.bat --serial-port COM5
setlocal
cd /d "%~dp0"
call scripts\env.bat || goto :fail
where npm >nul 2>nul
if errorlevel 1 goto :no_npm
pushd web
call npm run build >nul || (popd & goto :fail)
popd
goto :web_ok
:no_npm
if not exist "web\dist\index.html" (
  echo EROARE: web\dist lipseste si npm nu e instalat. Instaleaza Node.js LTS: https://nodejs.org
  goto :fail
)
echo npm nu e instalat - folosesc web\dist existent.
:web_ok
for /f "usebackq delims=" %%P in (`python scripts\cfg_get.py server.port`) do set "PORT=%%P"
echo Dashboard: http://localhost:%PORT%    Ctrl+C pentru oprire
start "" /min powershell -NoProfile -Command "Start-Sleep 6; Start-Process 'http://localhost:%PORT%'"
python -m server.main %*
exit /b %errorlevel%
:fail
pause
exit /b 1
