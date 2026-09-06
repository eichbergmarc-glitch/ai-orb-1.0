@echo off
setlocal
title NULLPROTOKOLL - XTTS pruefen
set "NP_PROJECT=%~dp0"
set "NP_PROJECT=%NP_PROJECT:~0,-1%"
set "NP_PY=%NP_PROJECT%\.tools\speech\xtts-venv\Scripts\python.exe"
set "NP_LOG=%NP_PROJECT%\stimmen_pruefen.log"

if not exist "%NP_PY%" (
  echo Die XTTS-Umgebung fehlt. Erst STIMMEN_EINRICHTEN.bat ausfuehren.
  pause
  exit /b 1
)

set COQUI_TOS_AGREED=1
"%NP_PY%" "%NP_PROJECT%\tools\xtts_check.py" > "%NP_LOG%" 2>&1
type "%NP_LOG%"
echo.
echo Das Protokoll steht in stimmen_pruefen.log
pause
