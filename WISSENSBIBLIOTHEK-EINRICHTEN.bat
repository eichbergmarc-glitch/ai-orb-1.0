@echo off
REM ===========================================================================
REM  Synapses Wissensbibliothek einrichten (22.11.2026)
REM ===========================================================================
REM  Entpackt synapse_wikipedia_de.zip (aus Google Drive, Ordner Synapse-Modell)
REM  nach %APPDATA%\AI-Orb\data\wissen - dort sucht Synapse nach.
REM ===========================================================================
setlocal EnableDelayedExpansion
title Wissensbibliothek einrichten
echo.
echo   ==========================================================
echo     Synapses Wissensbibliothek einrichten
echo   ==========================================================
echo.
set "ZIP="
for %%D in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Downloads\Synapse-Modell" "G:\Meine Ablage\Synapse-Modell" "G:\My Drive\Synapse-Modell") do (
  if not defined ZIP if exist "%%~D\synapse_wikipedia_de.zip" set "ZIP=%%~D\synapse_wikipedia_de.zip"
)
if not defined ZIP (
  echo   synapse_wikipedia_de.zip wurde nicht gefunden.
  echo   Lade sie aus Google Drive, Ordner "Synapse-Modell", in Downloads.
  pause
  exit /b 1
)
set "ZIEL=%APPDATA%\AI-Orb\data\wissen"
if not exist "%ZIEL%" mkdir "%ZIEL%"
echo   [1/2] Gefunden: %ZIP%
echo   [2/2] Entpacke nach %ZIEL% (einige Minuten, bitte warten) ...
tar -xf "%ZIP%" -C "%ZIEL%"
if errorlevel 1 (
  echo.
  echo   FEHLER beim Entpacken. Ist genug Platz frei ^(ca. 6 GB^)?
  pause
  exit /b 1
)
if not exist "%ZIEL%\synapse_wikipedia_de.db" (
  echo   FEHLER: Nach dem Entpacken fehlt synapse_wikipedia_de.db.
  pause
  exit /b 1
)
for %%F in ("%ZIEL%\synapse_wikipedia_de.db") do set "GROESSE=%%~zF"
echo.
echo   Fertig: %ZIEL%\synapse_wikipedia_de.db  (!GROESSE! Bytes)
echo   Die ZIP-Datei in Downloads darfst du jetzt loeschen.
echo   Starte jetzt den Orb neu und sag Claude Bescheid.
echo.
pause
