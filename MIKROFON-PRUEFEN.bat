@echo off
chcp 65001 >nul
title AI-Orb - Mikrofon pruefen
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     Mikrofon pruefen
echo   ==========================================================
echo.

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\mikrofon_bericht.py

echo.
echo   Der Bericht steht in logs\mikrofon-bericht.txt
echo.
pause
