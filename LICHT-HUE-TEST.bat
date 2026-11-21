@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI-Orb - Hue-Lampe testen
echo ============================================================
echo   AI-Orb  -  Steuertest fuer die Philips Hue
echo ============================================================
echo.
echo WICHTIG: Schliesse am Handy die Hue-App (oder Bluetooth aus),
echo sonst ist die Lampe blockiert. Die Hue muss eingeschaltet sein.
echo.
pause
echo.
set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install --quiet --no-warn-script-location bleak
echo Verbinde und teste - schau auf die Lampe...
"%PY%" "scripts\licht_hue_test.py" "E1:55:AF:52:A9:D1" "LICHT-HUE-ERGEBNIS.txt"
echo.
echo Fertig. Ergebnis auch in LICHT-HUE-ERGEBNIS.txt
pause
