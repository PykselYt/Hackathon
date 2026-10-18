@echo off
rem One-time setup on Windows: Python venv + packages, web dashboard build (Windows twin of the macOS setup).
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo === Semafoare AI - instalare pe Windows ===
echo.

rem The .venv copied from macOS cannot run on Windows: keep it aside, do not delete it
if exist ".venv\bin" if not exist ".venv\Scripts\python.exe" (
  echo .venv vine de pe macOS - il redenumesc in .venv_macos
  move ".venv" ".venv_macos" >nul || goto :fail
)

if exist ".venv\Scripts\python.exe" goto :venv_ok
where uv >nul 2>nul
if not errorlevel 1 goto :venv_uv
where py >nul 2>nul
if not errorlevel 1 goto :venv_py
goto :no_python

:venv_uv
echo [1/4] Creez .venv cu uv, Python 3.11 ...
uv venv --python 3.11 .venv || goto :fail
goto :venv_ok

:venv_py
echo [1/4] Creez .venv cu Python 3.11 ...
py -3.11 -m venv .venv
if not errorlevel 1 goto :venv_ok
echo   Python 3.11 nu e instalat, incerc versiunea implicita din py ...
py -3 -m venv .venv || goto :no_python

:venv_ok
set "PY=%CD%\.venv\Scripts\python.exe"
echo [2/4] Instalez pachetele Python - dureaza cateva minute, torch e mare ...
where uv >nul 2>nul
if errorlevel 1 goto :pip_install
uv pip install --python "%PY%" -r requirements.txt || goto :fail
goto :py_done
:pip_install
"%PY%" -m ensurepip --upgrade >nul 2>nul
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt || goto :fail
:py_done

echo [3/4] Interfata web ...
where npm >nul 2>nul
if not errorlevel 1 goto :web_npm
echo   ATENTIE: Node.js / npm nu e instalat. Folosesc web\dist, deja construit.
echo   Pentru modificari in interfata instaleaza Node.js LTS: https://nodejs.org
goto :web_done
:web_npm
rem node_modules from macOS holds darwin binaries (esbuild, rollup, tailwind): reinstall for Windows
if exist "web\node_modules" if not exist "web\node_modules\@esbuild\win32-x64" (
  echo   Sterg web\node_modules copiat de pe macOS, il reinstalez pentru Windows ...
  rmdir /s /q "web\node_modules"
)
pushd web
call npm install || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd
:web_done

echo [4/4] Verificare ...
call scripts\env.bat || goto :fail
python -c "import traci, sumolib, sumo_rl, stable_baselines3, fastapi, uvicorn, serial, yaml; print('  pachete Python: OK')" || goto :fail
python -c "import os, pathlib; b = pathlib.Path(os.environ['SUMO_HOME'], 'bin'); print('  SUMO:', os.environ['SUMO_HOME']); print('  sumo-gui:', 'da' if (b / 'sumo-gui.exe').exists() else 'nu (simularea ruleaza fara fereastra)')"

echo.
echo Gata. Porneste cu:
echo   run_mock.bat              - dashboard pe date simulate, fara SUMO
echo   run_demo.bat              - demo complet: SUMO + dashboard + ESP32
echo   run_demo.bat --no-serial  - demo fara placa ESP32
echo.
pause
exit /b 0

:no_python
echo.
echo EROARE: nu gasesc Python. Instaleaza Python 3.11 de la https://www.python.org/downloads/windows/
echo bifeaza "Add python.exe to PATH" si "py launcher", apoi ruleaza din nou setup_windows.bat
pause
exit /b 1

:fail
echo.
echo EROARE la instalare - vezi mesajul de mai sus.
pause
exit /b 1
