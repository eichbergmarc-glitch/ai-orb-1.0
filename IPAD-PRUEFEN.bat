@echo off
chcp 65001 >nul
title AI-Orb - Warum haengt das iPad?

REM ===========================================================================
REM  Ein haengender Browser sagt nichts. Diese Datei sagt etwas.
REM
REM  Sie fragt der Reihe nach ab, was zwischen dem iPad und dem Orb liegt:
REM  Laeuft der Orb? Ist Tailscale angemeldet? Darf das Netz Zertifikate
REM  ausstellen? Worauf zeigt die Weiterleitung? Jede Antwort landet in
REM  logs\ipad-einrichtung.txt und kann weitergegeben werden.
REM
REM  Sie aendert nichts.
REM ===========================================================================

setlocal EnableDelayedExpansion

set "ORB="
call :istProjekt "%~dp0."
if !errorlevel! equ 0 set "ORB=%~dp0."

if not defined ORB (
  call :istProjekt "%USERPROFILE%\AI-Orb"
  if !errorlevel! equ 0 set "ORB=%USERPROFILE%\AI-Orb"
)

if not defined ORB (
  echo.
  echo   Der AI-Orb-Ordner wurde nicht gefunden. Diese Datei gehoert dorthin,
  echo   wo auch ORB-STARTEN.bat und config.yaml liegen:
  echo       %USERPROFILE%\AI-Orb
  echo.
  pause
  exit /b 1
)

cd /d "!ORB!"

set "PY="
call :pruefePython "runtime\python\python.exe"
if !errorlevel! equ 0 set "PY=runtime\python\python.exe"

if not defined PY (
  call :pruefePython "py" "-3"
  if !errorlevel! equ 0 set "PY=py -3"
)

if not defined PY (
  call :pruefePython "python"
  if !errorlevel! equ 0 set "PY=python"
)

if not defined PY (
  echo.
  echo   Kein arbeitsfaehiges Python gefunden. Einmal ORB-STARTEN.bat
  echo   ausfuehren - der Orb bringt sein eigenes mit.
  echo.
  pause
  exit /b 1
)

!PY! scripts\fernzugang.py --pruefen
set "ERGEBNIS=!errorlevel!"

echo.
echo Alles davon steht auch in logs\ipad-einrichtung.txt
echo.
pause
exit /b !ERGEBNIS!


:istProjekt
if not exist "%~1\scripts\fernzugang.py" exit /b 1
if not exist "%~1\config.yaml" exit /b 1
exit /b 0

:pruefePython
"%~1" %~2 -c "pass" >nul 2>&1
exit /b !errorlevel!
