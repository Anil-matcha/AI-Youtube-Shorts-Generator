@echo off
setlocal
cd /d "%~dp0"
python scripts\build.py installer
exit /b %errorlevel%
