@echo off
chcp 65001 >nul
title AI-Orb - Waechter erneuern
cd /d "%~dp0"

echo.
echo   ==========================================================
echo     AI-Orb - Den Neustart-Waechter erneuern
echo   ==========================================================
echo.
echo   Beendet den unsichtbar laufenden Waechter und startet
echo   genau einen neuen mit dem aktuellen Programm.
echo.
echo   Ab jetzt macht er das von selbst: Aendert sich sein
echo   Programm, uebergibt er an die neue Fassung. Diese Datei
echo   wird also nur dieses eine Mal gebraucht.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\waechter_erneuern.ps1"

echo.
pause
