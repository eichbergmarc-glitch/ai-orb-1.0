@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb Browsersteuerung einrichten

REM ===========================================================================
REM  AI-Orb: die Browsersteuerung einrichten
REM ===========================================================================
REM  Fuehre das EINMAL aus, WAEHREND DU INTERNET HAST. Danach kann der Orb
REM  ein echtes Browserfenster bedienen: oeffnen, scrollen, klicken, tippen.
REM
REM  Es installiert zwei Dinge in die Python-Umgebung des Orb:
REM    1. Playwright   - die Steuerung selbst.
REM    2. Chromium     - einen Browser, den Playwright fernsteuern kann
REM                      (als Rueckfall, falls Google Chrome fehlt).
REM ===========================================================================

set "PROJEKT=%USERPROFILE%\AI-Orb"
set "PY=%PROJEKT%\runtime\python\python.exe"

echo.
echo   ==========================================================
echo     AI-Orb Browsersteuerung einrichten
echo   ==========================================================
echo.

if not exist "%PY%" (
  echo   Die Python-Umgebung des Orb fehlt noch.
  echo   Starte bitte zuerst einmal den Orb ueber "ORB-STARTEN.bat"
  echo   (oder die Verknuepfung "AI-Orb (lokal)"), dann diese Datei erneut.
  echo.
  pause
  exit /b 1
)

echo   Das laedt ein paar hundert MB (Browser). Einmalig, mit Internet.
echo.
pause

REM ---------------------------------------------------------------------------
REM  1. Playwright installieren
REM ---------------------------------------------------------------------------
echo.
echo   [1/2] Playwright installieren ...
"%PY%" -m pip install --upgrade playwright
if errorlevel 1 (
  echo.
  echo   Playwright liess sich nicht installieren. Ist Internet da?
  echo.
  pause
  exit /b 1
)

REM ---------------------------------------------------------------------------
REM  2. Den Browser (Chromium) holen
REM ---------------------------------------------------------------------------
echo.
echo   [2/2] Browser holen (Chromium) ...
"%PY%" -m playwright install chromium
if errorlevel 1 (
  echo.
  echo   Der Browser liess sich nicht holen. Ist Internet da?
  echo.
  pause
  exit /b 1
)

echo.
echo   ==========================================================
echo     Fertig. Die Browsersteuerung ist eingerichtet.
echo   ==========================================================
echo.
echo   Starte den Orb neu ueber "AI-Orb (lokal)". Dann kannst du sagen:
echo     "Oeffne im Browser example.com"  oder
echo     "Geh auf Wikipedia und such nach ..."
echo.
echo   Der Orb oeffnet ein eigenes Browserfenster. Melde dich darin einmal
echo   bei den Seiten an, die du brauchst - diese Anmeldungen bleiben dann
echo   erhalten. Standardmaessig nutzt der Orb dein Google Chrome; ist keines
echo   installiert, trage in der config.yaml unter "browser:" kanal: "" ein,
echo   dann nimmt er den soeben geholten Chromium.
echo.
pause
endlocal
