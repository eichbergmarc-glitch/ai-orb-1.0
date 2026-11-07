@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" werkzeug\cloud_pruefen.py
echo.
pause
