@echo off
chcp 65001 >nul
setlocal
title AI-Orb - Einstellungen fuer die installierte Fassung uebernehmen
cd /d "%~dp0"

REM  Die installierte Fassung (AI-Orb.exe) liest ihre Einstellungen NICHT
REM  aus diesem Ordner, sondern aus %APPDATA%\AI-Orb. Dort lag noch die
REM  alte Einstellung: Claude Code als Hauptmodell, ElevenLabs-Stimme.
REM  Diese Datei kopiert die aktuelle config.yaml dorthin - die alte wird
REM  vorher gesichert. Die .env mit den Schluesseln kopierst du selbst.

set "ZIEL=%APPDATA%\AI-Orb"
if not exist "%ZIEL%" mkdir "%ZIEL%"

echo.
echo   ==========================================================
echo     Einstellungen fuer die installierte Fassung uebernehmen
echo   ==========================================================
echo.
echo   Von:  %~dp0config.yaml
echo   Nach: %ZIEL%\config.yaml
echo.

if exist "%ZIEL%\config.yaml" (
  copy /y "%ZIEL%\config.yaml" "%ZIEL%\config.yaml.vor-uebernahme" >nul
  echo   Alte Einstellung gesichert als config.yaml.vor-uebernahme
)
copy /y "config.yaml" "%ZIEL%\config.yaml" >nul
if errorlevel 1 (
  echo   [FEHLER] Kopieren fehlgeschlagen. Laeuft der Orb noch? Bitte beenden.
  pause
  exit /b 1
)
echo   config.yaml uebernommen.
echo.

REM  Die Stimmen-Modelle (Supertonic, Frauenstimme F1). Ohne sie faellt die
REM  installierte Fassung auf die Windows-Stimme zurueck - eine Maennerstimme.
REM  Die installierte Fassung sucht sie in %LOCALAPPDATA%\AI-Orb\cache\models.
set "MODELLE=%LOCALAPPDATA%\AI-Orb\cache\models"
if exist "data\cache\models" (
  echo   Kopiere die Stimmen-Modelle ^(etwa 500 MB, einmalig^) ...
  robocopy "data\cache\models" "%MODELLE%" /E /XO /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (
    echo   [FEHLER] Die Stimmen-Modelle liessen sich nicht kopieren.
  ) else (
    echo   Stimmen-Modelle uebernommen.
  )
  echo.
)
echo   JETZT NOCH DIE SCHLUESSEL:
echo   Es oeffnen sich gleich zwei Ordner. Kopiere die Datei .env aus
echo   dem Orb-Ordner in den Ordner AI-Orb (vorhandene ersetzen).
echo   Ohne sie kennt die installierte Fassung keine API-Schluessel.
echo.
explorer "%~dp0"
explorer "%ZIEL%"
echo   Danach AI-Orb neu starten.
echo.
pause
