@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AI-Orb - Lokales Sprachmodell

echo.
echo ======================================================================
echo   LOKALES SPRACHMODELL
echo ======================================================================
echo.
echo   Geht die Kette durch - Konfiguration, Ollama, Dienst, Modell -
echo   und stellt dem Modell am Ende eine echte Frage. Was danach
echo   dasteht, gilt.
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
echo   [1] Pruefen und reparieren
echo   [2] Pruefen und das Modell herunterladen  ^(mehrere Gigabyte^)
echo   [3] Offline-Betrieb: lokales Modell nach vorn stellen
echo   [4] Zurueck: Netzanbieter wieder nach vorn
echo   [5] Nichts tun
echo.
set /p WAHL="  Deine Wahl [1-5] "

if "%WAHL%"=="1" ( "%ORBPY%" werkzeug\ollama_reparieren.py & goto ende )
if "%WAHL%"=="2" ( "%ORBPY%" werkzeug\ollama_reparieren.py --laden & goto ende )
if "%WAHL%"=="3" ( "%ORBPY%" werkzeug\ollama_reparieren.py --offline & goto ende )
if "%WAHL%"=="4" ( "%ORBPY%" werkzeug\ollama_reparieren.py --online & goto ende )
goto ende

:ende
echo.
echo ----------------------------------------------------------------------
echo   Mitgeschrieben wird nach  ollama-diagnose.txt  - schick mir die
echo   Datei, wenn es weiter haengt.
echo ----------------------------------------------------------------------
echo.
pause
endlocal
goto :eof

:PythonFinden
REM  Der Orb bringt sein eigenes Python in runtime\python mit. Sich auf
REM  den Pfad zu verlassen war schon einmal der Fehler.
set "ORBPY="
if exist "%~dp0runtime\python\python.exe" set "ORBPY=%~dp0runtime\python\python.exe"
if not defined ORBPY (where py >nul 2>nul && set "ORBPY=py")
if not defined ORBPY (where python >nul 2>nul && set "ORBPY=python")
goto :eof
