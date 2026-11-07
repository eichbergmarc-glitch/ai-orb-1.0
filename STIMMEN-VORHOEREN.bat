@echo off
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
  echo Die Python-Runtime fehlt. Erst ORB-STARTEN.bat ausfuehren.
  pause
  exit /b 1
)
runtime\python\python.exe stimmen_vorhoeren.py
pause
