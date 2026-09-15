@echo off
setlocal
cd /d "%~dp0"
echo Shorts Studio Windows installer
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo Python 3.10 or newer is required. Found an older Python on PATH.
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 goto :failed
)

echo Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements-local.txt
if errorlevel 1 goto :failed

if not exist ".env" copy /y ".env.example" ".env" >nul
echo.
echo Installation complete. Edit .env with your LLM key, then run start_studio.bat.
pause
exit /b 0

:failed
echo.
echo Installation failed. Scroll up for the error details.
pause
exit /b 1
