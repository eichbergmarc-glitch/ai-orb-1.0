@echo off
chcp 65001 >nul
title AI-Orb - Lokaler Modelltest

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo AI-Orb prueft das lokale Modell, die Antwortzeit und die Werkzeugschleife.
echo Der Bericht wird unter logs\local_model_benchmark.json gespeichert.
echo.

"%PY%" scripts\benchmark_local_orb.py
set "ERGEBNIS=%errorlevel%"

echo.
if "%ERGEBNIS%"=="0" (
  echo Lokaler Modelltest bestanden.
) else (
  echo Lokaler Modelltest mit Auffaelligkeiten beendet.
)
pause
exit /b %ERGEBNIS%
