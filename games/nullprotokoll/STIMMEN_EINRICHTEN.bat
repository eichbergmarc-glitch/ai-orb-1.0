@echo off
setlocal
title NULLPROTOKOLL - Stimmen einrichten
set "NP_PROJECT=%~dp0"
set "NP_PROJECT=%NP_PROJECT:~0,-1%"
set "NP_LOG=%NP_PROJECT%\setup_stimmen.log"

echo Richtet die Sprachausgabe ein. Die vollstaendige Ausgabe landet in:
echo   %NP_LOG%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%NP_PROJECT%\SETUP_STIMMEN.ps1" %* > "%NP_LOG%" 2>&1
set "NP_CODE=%errorlevel%"

type "%NP_LOG%"
echo.
if not "%NP_CODE%"=="0" (
  echo Die Einrichtung endete mit Fehlercode %NP_CODE%.
  echo Schick mir die Datei setup_stimmen.log, dann sehe ich die Ursache.
) else (
  echo Fertig. Das Protokoll steht in setup_stimmen.log.
)
echo.
pause
