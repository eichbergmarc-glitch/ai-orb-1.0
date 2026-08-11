@echo off
REM ===========================================================================
REM  AI-Orb starten
REM ===========================================================================
REM  Eine Datei, ein Klick:
REM
REM    1. Projektordner suchen  (auch auf einem Desktop, der in OneDrive liegt)
REM    2. Quellen uebernehmen   (aus dem entpackten Archiv, falls vorhanden)
REM    3. Python-Runtime        (wird geholt, wenn sie fehlt)
REM    4. Node-Pakete           (werden installiert, wenn sie fehlen)
REM    5. Oberflaeche bauen     (alter Stand wird vorher entfernt)
REM    6. Orb starten
REM
REM  Zwei Dinge sind gegenueber der ersten Fassung anders, und beide aus
REM  Schaden klug geworden:
REM
REM  Der alte Build wird vor dem Bauen geloescht. Vorher wurde nur geprueft,
REM  ob main.js existiert - eine Datei aus einem frueheren, geglueckten Bau
REM  erfuellt diese Bedingung aber auch dann noch, wenn der aktuelle Bau
REM  gescheitert ist. Der Orb startete daraufhin mit altem Code, und der
REM  Uebersetzungsfehler blieb unbemerkt.
REM
REM  Und der Rueckgabewert von npm wird ausgewertet, nicht nur das Ergebnis
REM  auf der Platte. Ein Programm, das sagt "das ging schief", sollte man
REM  nicht uebergehen und stattdessen selbst nachsehen.
REM ===========================================================================

setlocal EnableDelayedExpansion
title AI-Orb starten

echo.
echo   ==========================================================
echo     AI-Orb wird gestartet
echo   ==========================================================
echo.

REM ---------------------------------------------------------------------------
REM  1. Projektordner
REM ---------------------------------------------------------------------------

set "DST="

if exist "%~dp0backend\main.py" if exist "%~dp0package.json" set "DST=%~dp0."

for %%D in (
  "%OneDrive%\Desktop\AI-Orb\AI-Orb"
  "%USERPROFILE%\OneDrive\Desktop\AI-Orb\AI-Orb"
  "%USERPROFILE%\Desktop\AI-Orb\AI-Orb"
  "%OneDrive%\Desktop\AI-Orb"
  "%USERPROFILE%\OneDrive\Desktop\AI-Orb"
  "%USERPROFILE%\Desktop\AI-Orb"
  "%USERPROFILE%\Documents\AI-Orb\AI-Orb"
  "%USERPROFILE%\Documents\AI-Orb"
) do (
  if not defined DST if exist "%%~D\backend\main.py" if exist "%%~D\package.json" set "DST=%%~D"
)

if not defined DST (
  echo   Der Projektordner wurde nicht gefunden.
  echo.
  echo   Gesucht wurde nach einem Ordner mit  backend\main.py  und
  echo   package.json - auf dem Desktop, in OneDrive und in Dokumente.
  echo.
  pause
  exit /b 1
)

for %%P in ("%DST%") do set "DST=%%~fP"
echo   Projekt:  %DST%

REM Ab hier wird mitgeschrieben. Ein Fehler, der nur im Fenster steht,
REM ist beim naechsten Scrollen weg - und dann raet wieder jemand.
set "LOG=%DST%\AI-Orb-Start-Log.txt"
echo AI-Orb Start-Protokoll > "%LOG%"
echo Projekt: %DST% >> "%LOG%"
echo. >> "%LOG%"

REM ---------------------------------------------------------------------------
REM  2. Quellen uebernehmen
REM ---------------------------------------------------------------------------
REM  Erkennungsmerkmal ist splash.ts. Genau diese Datei fehlte zuletzt, und
REM  ein Archiv, das sie enthaelt, ist das vollstaendige.

REM  Das Uebernehmen aus einem Quellen-Ordner ist ABGESCHALTET.
REM
REM  Warum: Dieser Schritt kopierte bei JEDEM Start einen Ordner
REM  "AI-Orb-Quellen" ueber den Projektordner - mit xcopy, das die alten
REM  Zeitstempel mitnimmt. Jede Verbesserung wurde damit beim naechsten
REM  Start stillschweigend durch eine aeltere Fassung ersetzt. Der Orb
REM  startete danach mit altem Code, ohne dass irgendwo ein Fehler stand -
REM  man sah nur, dass Aenderungen "nicht ankamen".
REM
REM  Gepflegt wird jetzt genau ein Ordner: dieser hier. Wer Dateien
REM  einspielen will, legt sie direkt hierhin.

cd /d "%DST%"
echo.

REM ---------------------------------------------------------------------------
REM  3. Python-Runtime
REM ---------------------------------------------------------------------------

echo   ----------------------------------------------------------
echo    [1/4] Python-Runtime
echo   ----------------------------------------------------------

if exist "%DST%\runtime\python\python.exe" (
  echo   Vorhanden.
) else (
  echo   Fehlt - wird geholt. Beim ersten Mal einige Minuten, etwa 300 MB.
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%DST%\scripts\prepare-runtime.ps1"
  if not exist "%DST%\runtime\python\python.exe" (
    echo.
    echo   Die Runtime liess sich nicht vorbereiten. Ursache steht oben.
    echo.
    pause
    exit /b 1
  )
)

REM ---------------------------------------------------------------------------
REM  4. Node-Pakete
REM ---------------------------------------------------------------------------

echo.
echo   ----------------------------------------------------------
echo    [2/4] Node-Pakete
echo   ----------------------------------------------------------

where node >nul 2>&1
if errorlevel 1 (
  echo   Node.js fehlt. Lade die LTS-Fassung: https://nodejs.org/
  echo   Danach dieses Fenster schliessen und erneut klicken.
  echo.
  pause
  exit /b 1
)

if exist "%DST%\node_modules\.bin\electron.cmd" (
  echo   Vorhanden.
) else (
  echo   Werden installiert...
  echo === npm install === >> "%LOG%"
  call npm install --no-audit --no-fund >> "%LOG%" 2>&1
  type "%LOG%"
  if not exist "%DST%\node_modules\.bin\electron.cmd" (
    echo.
    echo   npm install ist fehlgeschlagen. Meldung steht oben.
    echo.
    pause
    exit /b 1
  )
)

REM ---------------------------------------------------------------------------
REM  5. Oberflaeche bauen
REM ---------------------------------------------------------------------------

echo.
echo   ----------------------------------------------------------
echo    [3/4] Oberflaeche
echo   ----------------------------------------------------------

REM Alten Stand entfernen. Sonst kann ein geglueckter Bau von gestern
REM einen gescheiterten von heute verdecken.
if exist "%DST%\desktop\electron\dist" rd /s /q "%DST%\desktop\electron\dist"

echo === npm run build === >> "%LOG%"
call npm run build >> "%LOG%" 2>&1
set "BUILD_RESULT=%errorlevel%"
type "%LOG%"

if not "%BUILD_RESULT%"=="0" goto :BuildFehler
if not exist "%DST%\desktop\electron\dist\electron\main.js" goto :BuildFehler
if not exist "%DST%\desktop\electron\dist\renderer\renderer.js" goto :BuildFehler

echo.
echo   Gebaut.

REM ---------------------------------------------------------------------------
REM  6. Starten
REM ---------------------------------------------------------------------------

echo.
echo   ----------------------------------------------------------
echo    [4/4] Orb starten
echo   ----------------------------------------------------------
echo.
echo   Dieses Fenster bleibt offen und zeigt die Meldungen des Orb.
echo   Schliessen beendet ihn.
echo.

echo === electron === >> "%LOG%"
call "%DST%\node_modules\.bin\electron.cmd" . 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG%' -Append"

echo.
echo   Der Orb wurde beendet.
echo.
pause
endlocal
exit /b 0

:BuildFehler
echo.
echo   ==========================================================
echo    Der Bau ist fehlgeschlagen
echo   ==========================================================
echo.
echo   Die Fehlermeldung steht oben - meist eine Zeile mit "error TS".
echo.
echo   Sagt sie "Cannot find module", fehlt eine Quelldatei. Dann liegt
echo   das vollstaendige Archiv noch nicht entpackt bereit; entpacke es
echo   nach Downloads\AI-Orb-Quellen und klicke erneut.
echo.
echo   Der Orb wird nicht gestartet - er liefe sonst mit altem Code
echo   weiter, und der Fehler bliebe unsichtbar.
echo.
echo   Alles Mitgeschriebene steht in:
echo   %LOG%
echo.
pause
endlocal
exit /b 1
