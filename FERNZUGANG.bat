@echo off
chcp 65001 >nul
title AI-Orb - Zugang von unterwegs (Tailscale)

REM ===========================================================================
REM  Der Orb von unterwegs, ueber Tailscale.
REM
REM  Dieser Weg gibt eine verschluesselte Adresse (HTTPS). Erst damit
REM  erlaubt Apple auf dem iPad das Mikrofon und ein Symbol auf dem
REM  Startbildschirm. Voraussetzung: Tailscale ist auf diesem Rechner
REM  installiert und angemeldet, und auf dem iPad ebenso.
REM
REM  Fuer das eigene WLAN genuegt IPAD-EINRICHTEN.bat - ohne Zusatzsoftware.
REM ===========================================================================

setlocal EnableDelayedExpansion

REM  Tailscale richtet unter Windows einen Dienst ein; das Einrichten der
REM  Weiterleitung verlangt deshalb Administratorrechte.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Windows fragt gleich nach Administratorrechten.
  echo Tailscale braucht sie, um die verschluesselte Weiterleitung
  echo einzurichten.
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

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

!PY! scripts\fernzugang.py %*
set "ERGEBNIS=!errorlevel!"

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
