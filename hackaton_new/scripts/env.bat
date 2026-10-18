@echo off
rem Called by the other .bat files: activates .venv, sets SUMO_HOME and PYTHONPATH (Windows twin of scripts/env.sh).
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo .venv pentru Windows lipseste. Ruleaza intai setup_windows.bat
  exit /b 1
)
call "%ROOT%\.venv\Scripts\activate.bat"
rem config.yaml and the logs contain Romanian diacritics: force UTF-8 instead of the cp1252 console default
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
if not defined SUMO_HOME for /f "usebackq delims=" %%S in (`python -c "import sumo; print(sumo.SUMO_HOME)"`) do set "SUMO_HOME=%%S"
if defined PYTHONPATH (set "PYTHONPATH=%ROOT%;%PYTHONPATH%") else (set "PYTHONPATH=%ROOT%")
exit /b 0
