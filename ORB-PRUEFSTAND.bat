@echo off
chcp 65001 >nul
title AI-Orb - Pruefstand

echo ============================================================
echo   Der Pruefstand: Der Orb wird auf DIESEM Rechner geprueft
echo ============================================================
echo.
echo   Die Bauumgebung hat kein Mikrofon, keine Lautsprecher und
echo   keinen Weg ins offene Netz. Was dort gruen ist, beweist
echo   die Logik - aber nicht das Verhalten hier. Der Pruefstand
echo   holt das nach: Umgebung, Geraete, offene Quellen und die
echo   komplette Testsuite, mit dem Python des Orbs auf den
echo   Dateien, die wirklich installiert sind.
echo.
echo   Das dauert ein paar Minuten. Der Bericht landet in
echo   logs\pruefstand.txt und kann direkt weitergegeben werden.
echo.
pause

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\pruefstand.py
set ERGEBNIS=%errorlevel%

echo.
echo ============================================================
if "%ERGEBNIS%"=="0" (
  echo   Bestanden. Der Orb ist auf diesem Rechner geprueft.
) else (
  echo   Es gibt Auffaelligkeiten - bitte logs\pruefstand.txt
  echo   an Claude weitergeben oder einfach sagen: lies den
  echo   Pruefstandsbericht.
)
echo ============================================================
echo.
pause
