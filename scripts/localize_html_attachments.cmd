@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONUTF8=1
set "PY="
if exist ".cache\desktop-dev\.venv\Scripts\python.exe" set "PY=.cache\desktop-dev\.venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY set "PY=python"
"%PY%" "scripts\localize_html_attachments.py" %*
exit /b %ERRORLEVEL%
