@echo off
setlocal
title NULLPROTOKOLL - Spracherkennung einrichten
set "NP_PROJECT=%~dp0"
set "NP_PROJECT=%NP_PROJECT:~0,-1%"
set "NP_LOG=%NP_PROJECT%\setup_sprache.log"

echo Richtet die lokale Spracherkennung ein (whisper.cpp).
echo Das Modell ist etwa 470 MB gross, der Download dauert entsprechend.
echo Die vollstaendige Ausgabe landet in:
echo   %NP_LOG%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%NP_PROJECT%\SETUP_SPRACHE.ps1" -SkipVoice %* > "%NP_LOG%" 2>&1
set "NP_CODE=%errorlevel%"

type "%NP_LOG%"
echo.
if not "%NP_CODE%"=="0" (
  echo Die Einrichtung endete mit Fehlercode %NP_CODE%.
  echo Schick mir setup_sprache.log, dann sehe ich die Ursache.
) else (
  echo Fertig. STARTEN.bat startet den Dienst ab jetzt automatisch mit.
)
echo.
pause
