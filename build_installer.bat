@echo off
setlocal
cd /d "%~dp0"
set "ISCC="
for %%P in (ISCC.exe) do set "ISCC=%%~$PATH:P"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo Inno Setup 6 was not found.
  echo Install it from https://jrsoftware.org/isinfo.php, then run this file again.
  pause
  exit /b 1
)
if not exist "dist\ShortsStudio\ShortsStudio.exe" (
  echo Build the portable app first so dist\ShortsStudio exists.
  pause
  exit /b 1
)
if not exist "release" mkdir release
for /f "delims=" %%V in ('venv\Scripts\python.exe -c "from shorts_generator import __version__; print(__version__)" 2^>nul') do set "SHORTS_STUDIO_VERSION=%%V"
if not defined SHORTS_STUDIO_VERSION set "SHORTS_STUDIO_VERSION=0.10.1"
"%ISCC%" /DMyAppVersion="%SHORTS_STUDIO_VERSION%" "installer\ShortsStudio.iss"
if errorlevel 1 goto :failed
echo.
echo Installer created in release\ShortsStudio-Setup-v%SHORTS_STUDIO_VERSION%.exe
pause
exit /b 0
:failed
echo Installer build failed.
pause
exit /b 1
