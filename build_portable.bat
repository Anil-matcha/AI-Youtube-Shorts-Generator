@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo venv\Scripts\python.exe was not found. Run install_windows.bat first.
  exit /b 1
)
venv\Scripts\python.exe scripts\build.py portable
exit /b %errorlevel%
