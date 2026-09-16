@echo off
setlocal
cd /d "%~dp0"

echo Removing Windows download blocking from the portable app files...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File | Unblock-File"
if errorlevel 1 (
  echo Could not remove the download block automatically.
  echo Open ShortsStudio.exe with More info ^> Run anyway once, then retry this file.
  pause
  exit /b 1
)

if not exist "%~dp0ShortsStudio.exe" (
  echo ShortsStudio.exe was not found. Keep this file beside the executable.
  pause
  exit /b 1
)

echo Files unblocked. Starting Shorts Studio...
start "Shorts Studio" "%~dp0ShortsStudio.exe"
exit /b 0
