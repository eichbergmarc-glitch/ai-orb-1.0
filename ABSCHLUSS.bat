@echo off
chcp 65001 >nul
title AI-Orb - Abschluss: Abnahme und sauberer Bericht
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messlauf-abschluss"
if not exist "%L%" mkdir "%L%"
if exist "%L%\_fertig.txt" del "%L%\_fertig.txt"

echo [1/3] Offline-Abnahme nach den Korrekturen
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\1-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\1-offline-abnahme.txt"

echo [2/3] Bericht (reines JSON auf stdout, Protokoll getrennt)
"%PY%" -m backend.lernen.messen --bericht > "%L%\2-bericht.json" 2> "%L%\2-bericht-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\2-bericht.exit"

echo [3/3] Rohdaten sichern
copy /Y "data\lernen\messungen.jsonl" "%L%\3-messungen-roh.jsonl" >nul 2>&1

echo %DATE% %TIME% > "%L%\_fertig.txt"
echo Fertig. Alles liegt in %L%
