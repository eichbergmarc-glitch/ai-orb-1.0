@echo off
chcp 65001 >nul
title AI-Orb - Zeugnis
cd /d "%~dp0"
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" scripts\zeugnis.py
pause
