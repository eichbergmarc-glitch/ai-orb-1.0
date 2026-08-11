@echo off
REM ===========================================================================
REM  AI-Orb - Diagnose
REM ===========================================================================
REM  Diese Datei aendert nichts. Sie sieht nach und schreibt einen Bericht
REM  auf den Desktop: AI-Orb-Diagnose.txt
REM
REM  Sie beantwortet die Fragen, die man dem laufenden Programm nicht ansieht:
REM
REM    - Wo ist AI-Orb installiert, und ist dort alles, was hingehoert?
REM    - Welche config.yaml ist wirklich wirksam?
REM    - Findet der Python-Kern sein eigenes Paket?
REM    - Welche Sprachpakete fehlen?
REM    - Ist ein Antwortgeber erreichbar (Claude Code oder Ollama)?
REM    - Darf AI-Orb auf das Mikrofon?
REM    - Was steht in den letzten Protokollzeilen?
REM
REM  Einfach doppelklicken. Der Bericht darf mir geschickt werden.
REM ===========================================================================

setlocal
cd /d "%~dp0"
title AI-Orb Diagnose

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\diagnose.ps1"

endlocal
exit /b 0
