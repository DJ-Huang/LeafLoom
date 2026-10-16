@echo off
setlocal
cd /d "%~dp0"
node scripts\dev-desktop.cjs
set "DEV_EXIT=%errorlevel%"
if not "%DEV_EXIT%"=="0" pause
exit /b %DEV_EXIT%
