@echo off
chcp 65001 >nul
title AI-Orb - Messlauf L2 (nach dem Fix der Messumgebung)
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messlauf-L2"
if not exist "%L%" mkdir "%L%"
if exist "%L%\_fertig.txt" del "%L%\_fertig.txt"

echo Messlauf L2 gestartet > "%L%\_start.txt"
echo %DATE% %TIME% >> "%L%\_start.txt"

echo [1/5] Offline-Abnahme
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\1-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\1-offline-abnahme.txt"

echo [2/5] Messlauf Claude Code (L2)
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L2 > "%L%\2-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\2-claude-code.txt"

echo [3/5] Messlauf Ollama (L2)
"%PY%" -m backend.lernen.messen --modell ollama --lauf L2 > "%L%\3-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\3-ollama.txt"

echo [4/5] Bericht
"%PY%" -m backend.lernen.messen --bericht > "%L%\4-bericht.json" 2>&1
echo EXITCODE=%ERRORLEVEL% > "%L%\4-bericht.exit"

echo [5/5] Rohdaten sichern
copy /Y "data\lernen\messungen.jsonl" "%L%\5-messungen-roh.jsonl" >nul 2>&1

echo %DATE% %TIME% > "%L%\_fertig.txt"
echo Fertig. Alles liegt in %L%
