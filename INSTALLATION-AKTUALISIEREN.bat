@echo off
chcp 65001 >nul
setlocal
title AI-Orb - installierte Fassung aktualisieren
cd /d "%~dp0"

REM  Die installierte Fassung (AI-Orb.exe) hat ihre EIGENE Kopie des
REM  Python-Kerns. Aenderungen in diesem Ordner kommen dort erst an, wenn
REM  sie hinueberkopiert werden. Genau das macht diese Datei:
REM    - backend\            -> installierte Fassung(en)
REM    - Oberflaeche         -> installierte Fassung(en)
REM    - config.yaml         -> %APPDATA%\AI-Orb (alte wird gesichert)
REM  Danach einfach nach jeder Aenderung wieder ausfuehren.

echo.
echo   ==========================================================
echo     Installierte Fassung von AI-Orb aktualisieren
echo   ==========================================================
echo.

tasklist /fi "imagename eq AI-Orb.exe" 2>nul | find /i "AI-Orb.exe" >nul
if not errorlevel 1 (
  echo   AI-Orb laeuft noch. Er wird jetzt beendet ...
  taskkill /im "AI-Orb.exe" /t /f >nul 2>&1
  timeout /t 3 /nobreak >nul
)

set "GEFUNDEN=0"
call :aktualisieren "%LOCALAPPDATA%\Programs\AI-Orb\resources\app"
call :aktualisieren "%~dp0dist-installer\win-unpacked\resources\app"
if "%GEFUNDEN%"=="0" (
  echo   [HINWEIS] Keine installierte Fassung gefunden.
  echo            Erwartet unter %LOCALAPPDATA%\Programs\AI-Orb
)

set "ZIEL=%APPDATA%\AI-Orb"
if not exist "%ZIEL%" mkdir "%ZIEL%"
if exist "%ZIEL%\config.yaml" copy /y "%ZIEL%\config.yaml" "%ZIEL%\config.yaml.vor-aktualisierung" >nul
copy /y "config.yaml" "%ZIEL%\config.yaml" >nul
if errorlevel 1 (
  echo   [FEHLER] config.yaml liess sich nicht nach %ZIEL% kopieren.
) else (
  echo   Einstellungen uebernommen: %ZIEL%\config.yaml
)
if not exist "%ZIEL%\.env" (
  echo.
  echo   [HINWEIS] In %ZIEL% fehlt die Datei .env mit den Schluesseln.
  echo            Bitte die .env aus diesem Ordner dorthin kopieren.
)

echo.
echo   Fertig. AI-Orb jetzt wieder starten.
echo.
pause
exit /b 0

:aktualisieren
set "APP=%~1"
if not exist "%APP%\backend" goto :eof
set "GEFUNDEN=1"
echo   Aktualisiere: %APP%
robocopy "%~dp0backend" "%APP%\backend" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo     [FEHLER] Kern liess sich nicht kopieren - laeuft der Orb noch?
) else (
  echo     Kern aktualisiert.
)
if exist "%~dp0desktop\electron\dist\renderer" (
  robocopy "%~dp0desktop\electron\dist\renderer" "%APP%\desktop\electron\dist\renderer" /E /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (echo     [FEHLER] Oberflaeche liess sich nicht kopieren.) else (echo     Oberflaeche aktualisiert.)
)
copy /y "%~dp0config.yaml" "%APP%\config.yaml" >nul
echo.
goto :eof
