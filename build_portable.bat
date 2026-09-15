@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
  echo venv\Scripts\python.exe was not found. Run install_windows.bat first.
  exit /b 1
)

echo Building Shorts Studio portable executable...
venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --name ShortsStudio --windowed --icon "assets\shorts_studio_icon.ico" --add-data "web;web" --add-data "shorts_generator;shorts_generator" --add-data "assets;assets" --hidden-import web.app --collect-submodules shorts_generator --collect-all webview --collect-all pystray --collect-all PIL launcher.py
if errorlevel 1 exit /b 1

if not exist "dist\ShortsStudio\ShortsStudio.exe" (
  echo PyInstaller did not create dist\ShortsStudio\ShortsStudio.exe.
  exit /b 1
)

copy /y "unblock_and_start.bat" "dist\ShortsStudio\unblock_and_start.bat" >nul
copy /y ".env.example" "dist\ShortsStudio\.env.example" >nul

rem Include FFmpeg when it is installed in PATH or the standard WinGet folder.
set "FFMPEG_EXE="
set "FFPROBE_EXE="
for /f "delims=" %%F in ('where ffmpeg.exe 2^>nul') do if not defined FFMPEG_EXE set "FFMPEG_EXE=%%F"
for /f "delims=" %%F in ('where ffprobe.exe 2^>nul') do if not defined FFPROBE_EXE set "FFPROBE_EXE=%%F"
if not defined FFMPEG_EXE for /r "%LOCALAPPDATA%\Microsoft\WinGet\Packages" %%F in (ffmpeg.exe) do if not defined FFMPEG_EXE set "FFMPEG_EXE=%%F"
if not defined FFPROBE_EXE for /r "%LOCALAPPDATA%\Microsoft\WinGet\Packages" %%F in (ffprobe.exe) do if not defined FFPROBE_EXE set "FFPROBE_EXE=%%F"
if not defined FFMPEG_EXE if exist "%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe" set "FFMPEG_EXE=%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe"
if not defined FFPROBE_EXE if exist "%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffprobe.exe" set "FFPROBE_EXE=%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffprobe.exe"
if not defined FFMPEG_EXE if exist "C:\ffmpeg\bin\ffmpeg.exe" set "FFMPEG_EXE=C:\ffmpeg\bin\ffmpeg.exe"
if not defined FFPROBE_EXE if exist "C:\ffmpeg\bin\ffprobe.exe" set "FFPROBE_EXE=C:\ffmpeg\bin\ffprobe.exe"
if not defined FFMPEG_EXE if exist "%ChocolateyToolsLocation%\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe" set "FFMPEG_EXE=%ChocolateyToolsLocation%\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe"
if not defined FFPROBE_EXE if exist "%ChocolateyToolsLocation%\ffmpeg\tools\ffmpeg\bin\ffprobe.exe" set "FFPROBE_EXE=%ChocolateyToolsLocation%\ffmpeg\tools\ffmpeg\bin\ffprobe.exe"
if defined FFMPEG_EXE copy /y "!FFMPEG_EXE!" "dist\ShortsStudio\ffmpeg.exe" >nul
if defined FFPROBE_EXE copy /y "!FFPROBE_EXE!" "dist\ShortsStudio\ffprobe.exe" >nul

rem CTranslate2's CUDA build needs these CUDA 12 runtime DLLs at launch.
set "CUDA_ROOT=%LOCALAPPDATA%\Programs\Ollama\lib\ollama\cuda_v12"
if not exist "!CUDA_ROOT!\cublas64_12.dll" for /d %%D in ("%ProgramFiles%\NVIDIA GPU Computing Toolkit\CUDA\v12*") do if exist "%%~D\bin\cublas64_12.dll" set "CUDA_ROOT=%%~D\bin"
if exist "!CUDA_ROOT!\cublas64_12.dll" (
  copy /y "!CUDA_ROOT!\cublas64_12.dll" "dist\ShortsStudio\cublas64_12.dll" >nul
  copy /y "!CUDA_ROOT!\cublasLt64_12.dll" "dist\ShortsStudio\cublasLt64_12.dll" >nul
  copy /y "!CUDA_ROOT!\cudart64_12.dll" "dist\ShortsStudio\cudart64_12.dll" >nul
) else (
  echo WARNING: CUDA runtime not found; CUDA mode will fall back to CPU.
)
if exist "venv\Lib\site-packages\ctranslate2\cudnn64_9.dll" copy /y "venv\Lib\site-packages\ctranslate2\cudnn64_9.dll" "dist\ShortsStudio\cudnn64_9.dll" >nul

echo Portable build ready in dist\ShortsStudio
exit /b 0
