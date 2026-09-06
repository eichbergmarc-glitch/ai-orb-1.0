@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AI-Orb - iPad dauerhaft

echo.
echo ======================================================================
echo   IPAD-ZUGANG DAUERHAFT
echo ======================================================================
echo.
echo   Danach ist das iPad erreichbar, sobald der Orb laeuft - ohne dass
echo   du hier noch etwas startest.
echo.
echo   Die Bruecke laeuft dafuer still im Hintergrund mit und wartet auf
echo   den Orb. Sie greift NICHT in den Start des Orb ein: Geht mit ihr
echo   etwas schief, merkt der Orb davon nichts.
echo.

python --version >nul 2>nul
if errorlevel 1 (
  echo   Python ist nicht im Pfad.
  echo.
  pause
  exit /b 1
)

echo ----------------------------------------------------------------------
python ipad\orb_ipad_dienst.py --zustand
echo ----------------------------------------------------------------------
echo.
echo   [1] Einrichten   - beim Anmelden mitstarten und jetzt gleich starten
echo   [2] Entfernen    - den Mitstart wieder zuruecknehmen
echo   [3] Nichts tun
echo.
set /p WAHL="  Deine Wahl [1/2/3] "

if "%WAHL%"=="1" goto einrichten
if "%WAHL%"=="2" goto entfernen
goto ende

:einrichten
echo.
python ipad\orb_ipad_dienst.py --einrichten
if errorlevel 1 goto fehler

echo.
echo   Und jetzt gleich starten ...
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AI-Orb-iPad.vbs"
if exist "%VBS%" (
  wscript "%VBS%"
  timeout /t 3 >nul
)

echo.
echo ----------------------------------------------------------------------
python ipad\orb_ipad_dienst.py --zustand
echo ----------------------------------------------------------------------
echo.
echo   Ab jetzt gilt: Orb starten, aufs iPad tippen, fertig.
echo.
echo   Nachsehen, wie es steht : python ipad\orb_ipad_dienst.py --zustand
echo   Mitgeschrieben wird nach: logs\ipad-bruecke.log
goto ende

:entfernen
echo.
python ipad\orb_ipad_dienst.py --entfernen
echo.
echo   Der Mitstart ist weg. Eine bereits laufende Bruecke bleibt bis zum
echo   naechsten Neustart des Rechners bestehen.
goto ende

:fehler
echo.
echo   Das hat nicht geklappt. Naeheres steht in logs\ipad-bruecke.log
echo.

:ende
echo.
pause
endlocal
