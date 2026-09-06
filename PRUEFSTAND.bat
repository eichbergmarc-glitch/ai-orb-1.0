@echo off
setlocal
chcp 65001 >nul
title AI-Orb - Pruefstand
cd /d "%~dp0"

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   AI-Orb - Pruefstand
echo   ===================
echo.
echo   Geht einmal durch alle Funktionen und sagt, was laeuft.
echo   Es wird nichts geaendert und nichts gestartet.
echo.
echo   Lass den Orb dabei ruhig laufen - dann werden auch seine
echo   Schnittstellen mitgeprueft.
echo.
"%PY%" "%~dp0werkzeug\pruefstand.py"
echo.
pause
endlocal
