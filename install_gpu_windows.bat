@echo off
setlocal
cd /d "%~dp0"
echo Shorts Studio GPU setup
echo.
if not exist "venv\Scripts\python.exe" (
  echo Run install_windows.bat first to create the virtual environment.
  pause
  exit /b 1
)
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo NVIDIA Driver not found. CUDA Whisper requires a compatible NVIDIA GPU and driver.
  pause
  exit /b 1
)
echo Installing local dependencies...
venv\Scripts\python.exe -m pip install -r requirements-local.txt
if errorlevel 1 goto :failed
echo Installing PyTorch (CUDA-enabled wheel)...
venv\Scripts\python.exe -m pip install -r requirements-gpu.txt --extra-index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 goto :failed
echo.
echo GPU setup complete. In Shorts Studio choose Whisper device = CUDA GPU.
pause
exit /b 0
:failed
echo.
echo GPU setup failed. Check the error above and your NVIDIA driver version.
pause
exit /b 1
