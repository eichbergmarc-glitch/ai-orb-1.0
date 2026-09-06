@echo off
setlocal
title NULLPROTOKOLL - Das Erwachen
set "NP_PROJECT=%~dp0"
set "NP_PROJECT=%NP_PROJECT:~0,-1%"
set "NP_BUNDLED=%NP_PROJECT%\.tools\godot\bin\Godot_v4.7.2-stable_win64.exe"
set "NP_SPEECH=%NP_PROJECT%\.tools\speech\START_SPRACHE.bat"

rem Spracherkennung starten, falls sie eingerichtet ist und noch nicht laeuft.
if exist "%NP_SPEECH%" (
  tasklist /fi "imagename eq whisper-server.exe" 2>nul | find /i "whisper-server.exe" >nul
  if errorlevel 1 (
    echo Starte lokale Spracherkennung ...
    start "NULLPROTOKOLL Spracherkennung" /min cmd /c "%NP_SPEECH%"
    rem Dem Dienst kurz Zeit geben, das Modell zu laden.
    timeout /t 4 /nobreak >nul
  )
) else (
  echo Hinweis: Sprachsteuerung ist nicht eingerichtet.
  echo Fuehre dafuer einmalig SETUP_SPRACHE.ps1 aus. Maus und Tastatur funktionieren wie bisher.
  echo.
)

if exist "%NP_BUNDLED%" (
  rem Kurzer Einlesevorgang, damit neu hinzugekommene Skripte registriert sind.
  "%NP_BUNDLED%" --headless --path "%NP_PROJECT%" --import >nul 2>nul
  start "" "%NP_BUNDLED%" --path "%NP_PROJECT%"
  exit /b 0
)

where godot.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" godot.exe --path "%NP_PROJECT%"
  exit /b 0
)

where godot4.exe >nul 2>nul
if %errorlevel% equ 0 (
  start "" godot4.exe --path "%NP_PROJECT%"
  exit /b 0
)

echo.
echo Godot 4 wurde nicht gefunden.
echo Lade die Standardversion fuer Windows von https://godotengine.org/download/windows/
echo und oeffne danach diese Datei erneut.
echo.
pause
exit /b 1
