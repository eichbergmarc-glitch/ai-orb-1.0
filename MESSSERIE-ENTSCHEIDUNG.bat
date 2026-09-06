@echo off
chcp 65001 >nul
title AI-Orb - Entscheidungsserie L6 L7 L8 (starker Bewerter, Positionskontrolle)
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messserie-entscheidung"
if not exist "%L%" mkdir "%L%"
if exist "%L%\_fertig.txt" del "%L%\_fertig.txt"

echo Entscheidungsserie gestartet > "%L%\_start.txt"
echo %DATE% %TIME% >> "%L%\_start.txt"

echo [0] Umgebung und Offline-Abnahme
"%PY%" -m backend.lernen.messen --umgebung > "%L%\0-umgebung.json" 2> "%L%\0-umgebung-protokoll.txt"
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\0-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\0-offline-abnahme.txt"

echo [L6] Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L6 > "%L%\L6-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L6-1-claude-code.txt"
echo [L6] Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L6 > "%L%\L6-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L6-2-ollama.txt"
echo [L6] Blindvergleich mit Positionskontrolle (qwen2.5:14b-instruct)
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L6 --lehrer claude_code --schueler ollama --bewerter ollama_richter > "%L%\L6-3-blindvergleich.json" 2> "%L%\L6-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L6-3-blindvergleich.exit"
echo   L6 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [L7] Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L7 > "%L%\L7-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L7-1-claude-code.txt"
echo [L7] Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L7 > "%L%\L7-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L7-2-ollama.txt"
echo [L7] Blindvergleich mit Positionskontrolle (qwen2.5:14b-instruct)
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L7 --lehrer claude_code --schueler ollama --bewerter ollama_richter > "%L%\L7-3-blindvergleich.json" 2> "%L%\L7-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L7-3-blindvergleich.exit"
echo   L7 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [L8] Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L8 > "%L%\L8-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L8-1-claude-code.txt"
echo [L8] Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L8 > "%L%\L8-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L8-2-ollama.txt"
echo [L8] Blindvergleich mit Positionskontrolle (qwen2.5:14b-instruct)
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L8 --lehrer claude_code --schueler ollama --bewerter ollama_richter > "%L%\L8-3-blindvergleich.json" 2> "%L%\L8-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L8-3-blindvergleich.exit"
echo   L8 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [A] Abschliessende Offline-Abnahme
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\9-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\9-offline-abnahme.txt"

echo [B] Uebergabestand aus L6 L7 L8 aufbauen
"%PY%" -m backend.lernen.messen --stand-neu-aufbauen L6 L7 L8 --lehrer claude_code --schueler ollama > "%L%\9-uebergabe.json" 2> "%L%\9-uebergabe-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\9-uebergabe.exit"

echo [C] Pruefergebnis je Lauf (ohne Eintragen, nur Auskunft)
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L6 --lehrer claude_code --schueler ollama > "%L%\9-pruefergebnis-L6.json" 2> "%L%\9-pruefergebnis-L6-protokoll.txt"
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L7 --lehrer claude_code --schueler ollama > "%L%\9-pruefergebnis-L7.json" 2> "%L%\9-pruefergebnis-L7-protokoll.txt"
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L8 --lehrer claude_code --schueler ollama > "%L%\9-pruefergebnis-L8.json" 2> "%L%\9-pruefergebnis-L8-protokoll.txt"

echo [D] Gesamtbericht und Rohdaten
"%PY%" -m backend.lernen.messen --bericht > "%L%\9-bericht.json" 2> "%L%\9-bericht-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\9-bericht.exit"
copy /Y "data\lernen\messungen.jsonl" "%L%\9-messungen-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\blindurteile.jsonl" "%L%\9-blindurteile-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\uebergabe.json" "%L%\9-uebergabestand.json" >nul 2>&1

echo %DATE% %TIME% > "%L%\_fertig.txt"
echo Fertig. Alles liegt in %L%
