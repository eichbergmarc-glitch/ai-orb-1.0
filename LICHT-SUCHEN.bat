@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI-Orb - Bluetooth-Lampen suchen
echo ============================================================
echo   AI-Orb  -  Bluetooth-Suche fuer die Lichtsteuerung
echo ============================================================
echo.
echo WICHTIG: Schliesse zuerst am Handy die Hue-App (oder schalte
echo dort kurz Bluetooth aus), damit die Lampen frei sind.
echo.
pause
echo.
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
echo Installiere die Bluetooth-Bibliothek (einmalig, kurz)...
"%PY%" -m pip install --quiet --no-warn-script-location bleak
echo.
echo Suche laeuft (ca. 15 Sekunden) - bitte warten...
"%PY%" "scripts\licht_scan.py" "LICHT-SUCHE-ERGEBNIS.txt"
echo.
echo ============================================================
echo Fertig. Das Ergebnis steht auch in der Datei:
echo   LICHT-SUCHE-ERGEBNIS.txt
echo ============================================================
pause
