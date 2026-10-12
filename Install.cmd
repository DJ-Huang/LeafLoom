@echo off
setlocal
wscript.exe "%~dp0scripts\windows\launch.vbs" install
exit /b %errorlevel%
