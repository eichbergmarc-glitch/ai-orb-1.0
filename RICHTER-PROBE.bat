@echo off
chcp 65001 >nul
title AI-Orb - Probe des Blindbewerters
cd /d "%~dp0"
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
set "L=logs\richterprobe"
if not exist "%L%" mkdir "%L%"

echo Probe: antwortet qwen2.5:14b-instruct, und wie schnell?
"%PY%" -m scripts.richter_probe > "%L%\probe.json" 2> "%L%\probe-protokoll.txt"
echo EXITCODE=%ERRORLEVEL% > "%L%\probe.exit"
echo %DATE% %TIME% > "%L%\_fertig.txt"
echo Fertig.
