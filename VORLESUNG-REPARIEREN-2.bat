@echo off
setlocal
chcp 65001 >nul
title AI-Orb - Vorlesungen instand setzen
cd /d "%~dp0"

set "PY=%~dp0runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo   AI-Orb - Vorlesungen instand setzen
echo   ===================================
echo.
echo   Das hier bringt zwei Dinge in Ordnung:
echo.
echo     1. Der Orb erkennt eine NEUE Vorlesung auch dann, wenn du sie
echo        frei formulierst. Bisher lief die Haelfte dieser Saetze als
echo        gewoehnliche Frage weiter - und der Orb knuepfte dort an,
echo        wo er war.
echo.
echo     2. Das Thema wird so genommen, wie du es gesagt hast - mit
echo        Umlauten, ohne das Verb der Bitte, und mit deiner Einengung
echo        ("und zwar ueber das Mittelalter").
echo.
echo   ------------------------------------------------------------
echo     [1]  Erst einmal nur ZEIGEN, was geaendert wuerde
echo     [2]  Einsetzen  (eine Sicherung wird vorher angelegt)
echo     [3]  Rueckgaengig machen
echo     [0]  Ende
echo   ------------------------------------------------------------
echo.
set "WAHL="
set /p "WAHL=Deine Wahl: "
echo.
if "%WAHL%"=="1" goto pruefen
if "%WAHL%"=="2" goto einsetzen
if "%WAHL%"=="3" goto zurueck
goto ende

:pruefen
"%PY%" "%~dp0werkzeug\vorlesung2_reparieren.py" --pruefen
goto fertig

:einsetzen
"%PY%" "%~dp0werkzeug\vorlesung2_reparieren.py"
goto fertig

:zurueck
"%PY%" "%~dp0werkzeug\vorlesung2_reparieren.py" --rueckgaengig
goto fertig

:fertig
echo.
pause
:ende
endlocal
