@echo off
cd /d "%~dp0"
set PY=
if exist "%LOCALAPPDATA%\Python\bin\python.exe" set PY="%LOCALAPPDATA%\Python\bin\python.exe"
if not defined PY ( py --version >nul 2>&1 && set PY=py )
if not defined PY ( python --version >nul 2>&1 && set PY=python )
if not defined PY (
  echo Nu gasesc Python. Instaleaza-l de pe python.org si bifeaza "Add python.exe to PATH".
  pause
  exit /b 1
)
echo Folosesc: %PY%
%PY% --version
echo Creez mediul Python si instalez pachetele (cateva minute)...
%PY% -m venv .venv
if not exist .venv\Scripts\activate.bat (
  echo Nu am putut crea mediul .venv. Trimite un screenshot cu fereastra asta.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo A aparut o eroare la instalare. Trimite un screenshot cu fereastra asta.
  pause
  exit /b 1
)
echo.
echo Gata! Porneste cu porneste.bat
pause
