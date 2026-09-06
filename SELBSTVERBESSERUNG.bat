@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AI-Orb - Selbstverbesserung

echo.
echo ======================================================================
echo   SELBSTVERBESSERUNG
echo ======================================================================
echo.
echo   Der Orb sieht sich nachts selbst durch, baut Patches in einer
echo   Arbeitskopie, testet sie - und legt dir morgens vor, was bestanden
echo   hat. An den laufenden Dateien aendert er nichts. Uebernommen wird
echo   nur, was du auf dem iPad antippst.
echo.

call :PythonFinden
if not defined ORBPY (
  echo   Kein Python gefunden - weder in runtime\python noch im Pfad.
  echo   Starte einmal ORB-STARTEN.bat, es holt die Runtime selbst.
  echo.
  pause
  exit /b 1
)
echo   Python: %ORBPY%
echo.
echo   [1] Jetzt einmal durchsehen  ^(nur analysieren, aendert nichts^)
echo   [0] Zeigen, wo der Orb ansetzen kann  ^(zwei Sekunden, ohne Modell^)
echo   [2] Jetzt durchsehen und Patches bauen
echo   [3] Nachtlauf einrichten     ^(taeglich 03:00 Uhr^)
echo   [4] Nachtlauf entfernen
echo   [5] Letzten Bericht zeigen
echo   [6] Nichts tun
echo.
set /p WAHL="  Deine Wahl [0-6] "

if "%WAHL%"=="0" ( "%ORBPY%" werkzeug\selbstverbesserung.py --ziele & goto ende )
if "%WAHL%"=="1" ( "%ORBPY%" werkzeug\selbstverbesserung.py & goto ende )
if "%WAHL%"=="2" ( "%ORBPY%" werkzeug\selbstverbesserung.py --patches & goto ende )
if "%WAHL%"=="3" ( "%ORBPY%" werkzeug\selbstverbesserung.py --einrichten 03:00 & goto ende )
if "%WAHL%"=="4" ( "%ORBPY%" werkzeug\selbstverbesserung.py --entfernen & goto ende )
if "%WAHL%"=="5" ( "%ORBPY%" werkzeug\selbstverbesserung.py --bericht & goto ende )
goto ende

:ende
echo.
echo ----------------------------------------------------------------------
echo   Freigeben auf dem iPad: Einstellungen - Vorschlaege des Orb
echo   Mitgeschrieben wird nach  logs\selbstverbesserung.log
echo ----------------------------------------------------------------------
echo.
pause
endlocal
goto :eof

:PythonFinden
set "ORBPY="
if exist "%~dp0runtime\python\python.exe" set "ORBPY=%~dp0runtime\python\python.exe"
if not defined ORBPY (where py >nul 2>nul && set "ORBPY=py")
if not defined ORBPY (where python >nul 2>nul && set "ORBPY=python")
goto :eof
