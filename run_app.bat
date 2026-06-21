@echo off
setlocal
cd /d "%~dp0"

set CODEX_PY=C:\Users\jessi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if exist "%CODEX_PY%" (
  start "" "http://127.0.0.1:8060"
  "%CODEX_PY%" app.py
  pause
  exit /b
)

where py >nul 2>nul
if %errorlevel%==0 (
  start "" "http://127.0.0.1:8060"
  py app.py
  pause
  exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "" "http://127.0.0.1:8060"
  python app.py
  pause
  exit /b
)

echo Python nao foi encontrado.
pause
