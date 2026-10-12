@echo off
setlocal
wscript.exe "%~dp0scripts\windows\launch.vbs" stop
exit /b %errorlevel%
