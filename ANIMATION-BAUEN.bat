@echo off
chcp 65001 >nul
title AI-Orb - Neue Energy-Orb-Animation bauen
echo ============================================================
echo   AI-Orb 0.26.15 - Energy-Orb-Animation bauen
echo ============================================================
echo.
echo Dieser Schritt uebersetzt die neue Orb-Animation (Renderer).
echo Er dauert nur wenige Sekunden.
echo.

cd /d "%~dp0"

where npm >nul 2>nul
if errorlevel 1 (
  echo [FEHLER] npm wurde nicht gefunden. Bitte Node.js installieren
  echo          oder AI-Orb neu installieren.
  pause
  exit /b 1
)

echo [1/2] Renderer bauen ...
call npm run build:renderer
if errorlevel 1 (
  echo.
  echo [FEHLER] Der Bau ist fehlgeschlagen. Die bisherige Animation
  echo          bleibt unveraendert in Betrieb. Bitte die Meldung oben
  echo          an den Assistenten weitergeben.
  pause
  exit /b 1
)

echo.
echo [2/2] Fertig. Starte AI-Orb neu, um die neue Animation zu sehen.
echo.
echo Test der Zustaende von Hand: Strg+Alt+1 bis Strg+Alt+9 schaltet
echo   idle, listening, thinking, executing, waiting, success, warning,
echo   error, offline durch.
echo Zurueck zur alten Anzeige: in config.yaml  orb.energie: false
echo.
pause
