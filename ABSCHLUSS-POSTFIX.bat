@echo off
chcp 65001 >nul
title AI-Orb - Uebergabestand neu aufbauen und Gesamtbericht
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messserie-postfix"
if not exist "%L%" mkdir "%L%"

echo [1/4] Offline-Abnahme nach den letzten Korrekturen
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\A-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\A-offline-abnahme.txt"

echo [2/4] Uebergabestand aus L3 L4 L5 neu aufbauen
"%PY%" -m backend.lernen.messen --stand-neu-aufbauen L3 L4 L5 --lehrer claude_code --schueler ollama > "%L%\B-uebergabe-neuaufbau.json" 2> "%L%\B-uebergabe-neuaufbau-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\B-uebergabe-neuaufbau.exit"

echo [3/4] Gesamtbericht
"%PY%" -m backend.lernen.messen --bericht > "%L%\C-bericht.json" 2> "%L%\C-bericht-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\C-bericht.exit"

echo [4/4] Rohdaten sichern
copy /Y "data\lernen\messungen.jsonl" "%L%\C-messungen-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\blindurteile.jsonl" "%L%\C-blindurteile-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\uebergabe.json" "%L%\C-uebergabestand.json" >nul 2>&1

echo %DATE% %TIME% > "%L%\_abschluss.txt"
echo Fertig.
