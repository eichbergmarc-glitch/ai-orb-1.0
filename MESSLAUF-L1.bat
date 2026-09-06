@echo off
chcp 65001 >nul
title AI-Orb - Messlauf L1 (Abnahme + Claude + Ollama + Bericht)
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messlauf-L1"
if not exist "%L%" mkdir "%L%"

echo Messlauf L1 gestartet > "%L%\_start.txt"
echo %DATE% %TIME% >> "%L%\_start.txt"
echo Python: %PY% >> "%L%\_start.txt"
if exist "%L%\_fertig.txt" del "%L%\_fertig.txt"

echo [0/6] Umgebung
"%PY%" -V > "%L%\0-umgebung.txt" 2>&1
where ollama >> "%L%\0-umgebung.txt" 2>&1
ollama --version >> "%L%\0-umgebung.txt" 2>&1
ollama list >> "%L%\0-umgebung.txt" 2>&1
where claude >> "%L%\0-umgebung.txt" 2>&1
claude --version >> "%L%\0-umgebung.txt" 2>&1
"%PY%" -m backend.lernen.messen --umgebung >> "%L%\0-umgebung.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\0-umgebung.txt"

echo [1/6] Offline-Abnahme (OFFLINE-ABNAHME.bat)
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\1-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\1-offline-abnahme.txt"

echo [2/6] Messlauf Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L1 > "%L%\2-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\2-claude-code.txt"

echo [3/6] Messlauf Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L1 > "%L%\3-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\3-ollama.txt"

echo [4/6] Bericht
"%PY%" -m backend.lernen.messen --bericht > "%L%\4-bericht.json" 2>&1
echo EXITCODE=%ERRORLEVEL% > "%L%\4-bericht.exit"

echo [5/6] Rohdaten sichern
copy /Y "data\lernen\messungen.jsonl" "%L%\5-messungen-roh.jsonl" >nul 2>&1

echo %DATE% %TIME% > "%L%\_fertig.txt"
echo [6/6] Fertig. Alles liegt in %L%
