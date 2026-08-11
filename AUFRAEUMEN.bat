@echo off
REM ===========================================================================
REM  AI-Orb - Alte Installation aufraeumen
REM ===========================================================================
REM  Diese Datei entfernt alles, was von der bisherigen Arbeitsweise mit
REM  Skripten und Patches uebrig ist, damit eine saubere Neuinstallation
REM  ueber AI-Orb-Setup.exe moeglich ist.
REM
REM  Entfernt werden:
REM    - .venv              die alte Python-Umgebung
REM    - node_modules       die Node-Pakete
REM    - desktop\...\dist   der alte Build
REM    - logs               alte Protokolle
REM    - upgrades           Patch-Pakete
REM    - alte Start- und Reparaturskripte
REM    - __pycache__        Zwischenstaende von Python
REM
REM  NICHT entfernt wird ohne ausdrueckliche Zustimmung:
REM    - data\              Erinnerungen, Wissensbasis, Karteikarten
REM    - .env               deine Zugangsdaten
REM    - config.yaml        deine Einstellungen
REM
REM  Danach ist alles bereit fuer: BUILD-INSTALLER.bat
REM
REM  Zusaetzliche Schalter:
REM    /auch-daten   Auch Erinnerungen, Wissensbasis und Einstellungen
REM                  loeschen. Wird zweimal bestaetigt.
REM    /probelauf    Nur zeigen, was geschehen wuerde
REM ===========================================================================

setlocal
cd /d "%~dp0"
title AI-Orb aufraeumen

set PS_ARGS=

:parse
if "%~1"=="" goto run
if /i "%~1"=="/auch-daten" set PS_ARGS=%PS_ARGS% -IncludeData
if /i "%~1"=="/probelauf"  set PS_ARGS=%PS_ARGS% -DryRun
shift
goto parse

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cleanup.ps1" %PS_ARGS%
set CLEAN_RESULT=%errorlevel%

echo.
pause
endlocal
exit /b %CLEAN_RESULT%
