@echo off
chcp 65001 >nul
title AI-Orb - Neustart-Waechter in den Autostart legen
cd /d "%~dp0"

REM Spur hinterlassen, damit von aussen erkennbar ist, ob diese Datei lief.
> "%~dp0logs\autostart-einrichtung.txt" echo Gestartet am %DATE% um %TIME%

echo.
echo   ==========================================================
echo     Neustart-Waechter in den Autostart legen
echo   ==========================================================
echo.
echo   Danach ist der Waechter nach jedem Hochfahren von selbst
echo   bereit - ohne Fenster, im Hintergrund.
echo.

set "ZIEL=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AI-Orb Neustart-Waechter.lnk"
set "QUELLE=%~dp0scripts\waechter-still.vbs"

if not exist "%QUELLE%" (
  echo   Die Datei scripts\waechter-still.vbs fehlt.
  echo   Diese Einrichtung gehoert in den AI-Orb-Ordner.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%ZIEL%');" ^
  "$s.TargetPath = 'wscript.exe';" ^
  "$s.Arguments = '\"%QUELLE%\"';" ^
  "$s.WorkingDirectory = '%~dp0';" ^
  "$s.Description = 'Startet den AI-Orb Neustart-Waechter im Hintergrund';" ^
  "$s.Save()"

if exist "%ZIEL%" (
  echo   Eingerichtet.
  echo.
  echo   Der Waechter startet ab dem naechsten Hochfahren von selbst.
  echo   Er wird jetzt auch gleich gestartet, damit nicht bis zum
  echo   naechsten Hochfahren gewartet werden muss.
  echo.
  start "" wscript.exe "%QUELLE%"
  echo   Gestartet. Er meldet sich binnen einer halben Minute
  echo   in der Datei WAECHTER-LAEUFT.txt
) else (
  echo   Die Verknuepfung liess sich nicht anlegen.
  echo   Ziel war: %ZIEL%
)

:fertig
echo.
pause
