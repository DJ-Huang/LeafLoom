@echo off
setlocal
wscript.exe "%~dp0scripts\windows\launch.vbs" open
exit /b %errorlevel%
