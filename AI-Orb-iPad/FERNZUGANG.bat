@echo off
chcp 65001 >nul
title AI-Orb - Zugang von iPad und Handy

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   Richtet den Zugang zum Orb von anderen Geraeten ein:
echo   Losungswort anlegen, Tailscale einrichten, Adresse nennen.
echo.

"%PY%" scripts\fernzugang.py %*
set "ERGEBNIS=%errorlevel%"

echo.
pause
exit /b %ERGEBNIS%
