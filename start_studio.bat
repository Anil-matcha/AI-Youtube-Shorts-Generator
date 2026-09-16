@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Please run install_windows.bat first.
  pause
  exit /b 1
)
start "Shorts Studio" /b venv\Scripts\python.exe launcher.py
echo Shorts Studio is starting in its desktop window.
echo If WebView2 is unavailable it will open the local UI in your browser.
echo Use the Quit button inside Shorts Studio to close it.
pause
