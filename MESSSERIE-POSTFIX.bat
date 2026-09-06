@echo off
chcp 65001 >nul
title AI-Orb - Post-Fix-Messserie L3 L4 L5
cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\messserie-postfix"
if not exist "%L%" mkdir "%L%"
if exist "%L%\_fertig.txt" del "%L%\_fertig.txt"

echo Post-Fix-Messserie gestartet > "%L%\_start.txt"
echo %DATE% %TIME% >> "%L%\_start.txt"

echo [1/6] Offline-Abnahme nach den Reparaturen
(echo.&echo.) | call OFFLINE-ABNAHME.bat > "%L%\0-offline-abnahme.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\0-offline-abnahme.txt"

echo [2/6] Lauf L3: Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L3 > "%L%\L3-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L3-1-claude-code.txt"
echo [2/6] Lauf L3: Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L3 > "%L%\L3-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L3-2-ollama.txt"
echo [2/6] Lauf L3: Blindvergleich
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L3 --lehrer claude_code --schueler ollama --bewerter ollama_fast > "%L%\L3-3-blindvergleich.json" 2> "%L%\L3-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L3-3-blindvergleich.exit"
echo [2/6] Lauf L3: Pruefergebnis
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L3 --lehrer claude_code --schueler ollama --eintragen > "%L%\L3-4-pruefergebnis.json" 2> "%L%\L3-4-pruefergebnis-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L3-4-pruefergebnis.exit"
echo   Lauf L3 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [3/6] Lauf L4: Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L4 > "%L%\L4-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L4-1-claude-code.txt"
echo [3/6] Lauf L4: Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L4 > "%L%\L4-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L4-2-ollama.txt"
echo [3/6] Lauf L4: Blindvergleich
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L4 --lehrer claude_code --schueler ollama --bewerter ollama_fast > "%L%\L4-3-blindvergleich.json" 2> "%L%\L4-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L4-3-blindvergleich.exit"
echo [3/6] Lauf L4: Pruefergebnis
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L4 --lehrer claude_code --schueler ollama --eintragen > "%L%\L4-4-pruefergebnis.json" 2> "%L%\L4-4-pruefergebnis-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L4-4-pruefergebnis.exit"
echo   Lauf L4 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [4/6] Lauf L5: Claude Code
"%PY%" -m backend.lernen.messen --modell claude_code --lauf L5 > "%L%\L5-1-claude-code.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L5-1-claude-code.txt"
echo [4/6] Lauf L5: Ollama
"%PY%" -m backend.lernen.messen --modell ollama --lauf L5 > "%L%\L5-2-ollama.txt" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%L%\L5-2-ollama.txt"
echo [4/6] Lauf L5: Blindvergleich
"%PY%" -m backend.lernen.messen --blindvergleich --lauf L5 --lehrer claude_code --schueler ollama --bewerter ollama_fast > "%L%\L5-3-blindvergleich.json" 2> "%L%\L5-3-blindvergleich-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L5-3-blindvergleich.exit"
echo [4/6] Lauf L5: Pruefergebnis
"%PY%" -m backend.lernen.messen --pruefergebnis --lauf L5 --lehrer claude_code --schueler ollama --eintragen > "%L%\L5-4-pruefergebnis.json" 2> "%L%\L5-4-pruefergebnis-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\L5-4-pruefergebnis.exit"
echo   Lauf L5 fertig: %DATE% %TIME% >> "%L%\_start.txt"

echo [5/6] Gesamtbericht
"%PY%" -m backend.lernen.messen --bericht > "%L%\9-bericht.json" 2> "%L%\9-bericht-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\9-bericht.exit"

echo [6/6] Rohdaten sichern
copy /Y "data\lernen\messungen.jsonl" "%L%\9-messungen-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\blindurteile.jsonl" "%L%\9-blindurteile-roh.jsonl" >nul 2>&1
copy /Y "data\lernen\uebergabe.json" "%L%\9-uebergabestand.json" >nul 2>&1

echo %DATE% %TIME% > "%L%\_fertig.txt"
echo Fertig. Alles liegt in %L%
