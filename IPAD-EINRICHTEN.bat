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
REM  Schritt 2 braucht Administratorrechte. Diese Datei holt sie sich selbst.
REM
REM  Zwei Dinge sind gegenueber der ersten Fassung anders, beide aus Schaden
REM  klug geworden:
REM
REM  Der Projektordner wird gesucht, nicht vermutet. Aus einem entpackten
REM  Archiv gestartet landete die Datei sonst in einem Ordner ohne die
REM  mitgelieferte Python-Umgebung - und Windows antwortete mit seinem
REM  Hinweis auf den Microsoft Store, der mit dem Problem nichts zu tun hat.
REM
REM  Und Python wird ausprobiert, nicht nur gefunden. Den Eintrag "python"
REM  gibt es unter Windows auch ohne Python: Er ist eine Weiche zum Store.
REM  Wer nur nachsieht, ob es ihn gibt, glaubt an einen Interpreter, der
REM  nie einen Befehl ausfuehren wird.
REM ===========================================================================

setlocal EnableDelayedExpansion

REM --- Administratorrechte besorgen ------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Windows fragt gleich nach Administratorrechten.
  echo Sie werden fuer die Firewall-Regel gebraucht - ohne sie verwirft
  echo Windows die Anfragen des iPad, ohne dass jemand etwas merkt.
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

REM --- Den Projektordner finden ----------------------------------------------
REM  "%~dp0." statt "%~dp0": Der abschliessende Rueckstrich in Anfuehrungs-
REM  zeichen ist unter Windows eine alte Stolperstelle. Der Punkt bedeutet
REM  denselben Ordner und macht die Anfuehrungszeichen eindeutig.
set "ORB="
call :istProjekt "%~dp0."
if !errorlevel! equ 0 set "ORB=%~dp0."

if not defined ORB (
  call :istProjekt "%USERPROFILE%\AI-Orb"
  if !errorlevel! equ 0 set "ORB=%USERPROFILE%\AI-Orb"
)

if not defined ORB (
  echo.
  echo   Der AI-Orb-Ordner wurde nicht gefunden.
  echo.
  echo   Diese Datei gehoert in den Ordner, in dem auch ORB-STARTEN.bat
  echo   und config.yaml liegen - ueblicherweise:
  echo.
  echo       %USERPROFILE%\AI-Orb
  echo.
  echo   Aus einem entpackten Archiv heraus kann sie nicht arbeiten.
  echo.
  pause
  exit /b 1
)

cd /d "!ORB!"
echo Projektordner: !CD!

REM --- Python suchen und ausprobieren ----------------------------------------
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
  echo   Kein arbeitsfaehiges Python gefunden.
  echo.
  echo   Der Orb bringt sein eigenes mit. Es entsteht beim ersten Start:
  echo   einmal ORB-STARTEN.bat ausfuehren, danach diese Datei erneut.
  echo.
  pause
  exit /b 1
)

echo Python: !PY!
echo.

!PY! scripts\fernzugang.py --wlan
set "ERGEBNIS=!errorlevel!"

echo.
echo Das alles steht auch in logs\ipad-einrichtung.txt
echo.
pause
exit /b !ERGEBNIS!


REM --- Hilfsroutinen ---------------------------------------------------------

REM Ist das ein AI-Orb-Projektordner? Zwei Dateien muessen es beweisen.
:istProjekt
if not exist "%~1\scripts\fernzugang.py" exit /b 1
if not exist "%~1\config.yaml" exit /b 1
exit /b 0

REM Laeuft dieses Python wirklich? Vorhandensein allein genuegt nicht.
:pruefePython
"%~1" %~2 -c "pass" >nul 2>&1
exit /b !errorlevel!
