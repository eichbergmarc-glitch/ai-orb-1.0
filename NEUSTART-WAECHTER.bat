@echo off
chcp 65001 >nul
title AI-Orb - Neustart-Waechter
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     AI-Orb - Neustart-Waechter
echo   ==========================================================
echo.
echo   Dieses Fenster bleibt offen und wartet auf den Auftrag,
echo   den Orb neu zu starten.
echo.
echo   Ausgeloest wird ein Neustart dadurch, dass eine Datei
echo   namens NEUSTART-BITTE.txt in diesem Ordner auftaucht -
echo   das kann auch aus der Ferne geschehen.
echo.
echo   Schliessen dieses Fensters beendet den Waechter.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\neustart_waechter.ps1"

echo.
echo   Der Waechter wurde beendet.
echo.
pause
