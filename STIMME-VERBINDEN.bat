@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb - Stimmserver verbinden

echo ============================================================
echo   Den Stimmserver mit dem Orb verbinden
echo ============================================================
echo.
echo   Colab hat dir am Ende eine Adresse gezeigt, etwa:
echo       https://vier-woerter-zufall.trycloudflare.com
echo.
echo   Diese Adresse traegst du hier ein. Sie aendert sich bei
echo   jedem Neustart der Colab-Sitzung - dann einfach noch
echo   einmal ausfuehren.
echo.

cd /d "%~dp0"

set "ADRESSE="
set /p ADRESSE="   Adresse einfuegen (leer = Fernstimme abschalten): "

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

if "%ADRESSE%"=="" (
  echo.
  echo   Die Fernstimme wird abgeschaltet. Der Orb spricht wieder
  echo   mit seiner eingebauten Stimme.
) else (
  echo.
  echo   [1/2] Server pruefen ...
  "%PY%" -c "import urllib.request,json,sys; a='%ADRESSE%'.strip().rstrip('/'); r=json.loads(urllib.request.urlopen(a+'/health',timeout=20).read()); print('        Antwort:', r); sys.exit(0 if r.get('status')=='ok' else 1)"
  if errorlevel 1 (
    echo.
    echo   [FEHLER] Der Server antwortet nicht.
    echo            - Laeuft die Colab-Zelle 5 noch?
    echo            - Ist die Adresse vollstaendig kopiert ^(mit https://^)?
    echo.
    pause
    exit /b 1
  )
)

echo.
echo   [2/2] In die Konfiguration eintragen ...

REM  Beides in einem Schritt: die Adresse eintragen UND 'remote' in der
REM  Stimmenliste nach vorn stellen. Der zweite Teil ist der wichtigere -
REM  ohne ihn laeuft der Server, die Adresse steht drin, und es spricht
REM  trotzdem die alte Stimme.
"%PY%" scripts\stimme_verbinden.py "%ADRESSE%" config.yaml

if errorlevel 4 (
  echo.
  echo   Die Adresse ist eingetragen, die Stimmenliste aber nicht.
  echo   Siehe Hinweis oben.
  echo.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo   [FEHLER] Die Konfiguration liess sich nicht aendern.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
if "%ADRESSE%"=="" (
  echo   Fernstimme abgeschaltet.
) else (
  echo   Verbunden. Starte den Orb neu, dann spricht er
  echo   ueber den Server.
  echo.
  echo   Wenn Colab spaeter einschlaeft, faellt der Orb von
  echo   selbst auf seine eingebaute Stimme zurueck - er
  echo   verstummt nicht.
)
echo ============================================================
echo.
pause
