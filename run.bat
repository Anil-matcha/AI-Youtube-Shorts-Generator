@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo   YouTube Shorts Generator
echo ==============================================
echo.

set /p YTURL="Paste the YouTube link: "
set /p NUMCLIPS="How many clips do you want? (e.g. 3): "

if "%NUMCLIPS%"=="" set NUMCLIPS=3

echo.
echo Running... this can take a few minutes depending on video length.
echo.

venv\Scripts\python.exe main.py "%YTURL%" --mode local --num-clips %NUMCLIPS%
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 (
  echo ==============================================
  echo   FAILED with exit code %EXITCODE%.
  echo ==============================================
) else (
  echo ==============================================
  echo   Done. Check the "output" folder for your clips.
  echo ==============================================
)
pause
exit /b %EXITCODE%
