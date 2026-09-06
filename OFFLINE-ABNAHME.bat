@echo off
chcp 65001 >nul
title AI-Orb - Offline-Abnahme

echo ============================================================
echo   Offline-Abnahme: Testlauf mit technisch gesperrtem Netz
echo ============================================================
echo.
echo   Ablauf:
echo     1. Das Netz wird im Programm gesperrt
echo     2. Die Sperre wird BEWIESEN (ein echter Verbindungsversuch
echo        muss scheitern - ein gewoehnlicher Netzfehler zaehlt nicht)
echo     3. Die Tests laufen im selben Prozess
echo     4. Die Sperre wird nochmals bewiesen
echo     5. Bericht nach logs\offline-abnahme-<zeit>.json
echo.
echo   Die Rueckschleife (127.0.0.1) bleibt offen, damit Ollama
echo   weiterarbeiten kann.
echo.
pause

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
"%PY%" -m scripts.offline_abnahme
set ERG=%ERRORLEVEL%

echo.
if "%ERG%"=="0" (
  echo   ============================================================
  echo     BESTANDEN - Sperre nachgewiesen, alle Tests gruen.
  echo   ============================================================
) else (
  echo   ============================================================
  echo     NICHT BESTANDEN - siehe Grund oben und den Bericht.
  echo   ============================================================
)
echo.
pause
