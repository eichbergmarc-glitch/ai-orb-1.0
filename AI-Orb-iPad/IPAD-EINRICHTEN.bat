@echo off
chcp 65001 >nul
title AI-Orb - iPad einrichten

REM ===========================================================================
REM  Den Orb vom iPad aus bedienen - ein Doppelklick.
REM
REM  Drei Dinge passieren hier:
REM    1. Der Server hoert kuenftig auf das Heimnetz statt nur auf sich selbst.
REM    2. Die Windows-Firewall laesst Anfragen aus dem Heimnetz durch.
REM    3. Ein Losungswort wird angelegt und angezeigt.
REM
REM  Schritt 2 braucht Administratorrechte. Diese Datei holt sie sich selbst
REM  - Windows fragt einmal nach, und das ist die einzige Rueckfrage.
REM ===========================================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Windows fragt gleich nach Administratorrechten.
  echo Sie werden fuer die Firewall-Regel gebraucht - sonst verwirft
  echo Windows die Anfragen des iPad, ohne dass jemand etwas merkt.
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\fernzugang.py --wlan
set "ERGEBNIS=%errorlevel%"

echo.
echo Das alles steht auch in logs\ipad-einrichtung.txt
echo.
pause
exit /b %ERGEBNIS%
