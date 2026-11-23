@echo off
REM ===========================================================================
REM  Synapse-Modell einrichten (21.11.2026)
REM ===========================================================================
REM  Richtet dein eigenes, auf Colab trainiertes Synapse-Modell in Ollama ein.
REM  Vorher: synapse-Q4_K_M.gguf aus Google Drive (Ordner Synapse-Modell) in
REM  deinen Downloads-Ordner laden. Dann diese Datei doppelklicken.
REM ===========================================================================
setlocal EnableDelayedExpansion
title Synapse-Modell einrichten
echo.
echo   ==========================================================
echo     Synapse-Modell in Ollama einrichten
echo   ==========================================================
echo.

REM Zuerst Version 2 suchen (v3 vom 22.11. schnitt im Test schlechter ab), sonst die erste.
set "ORT="
set "DATEI="
set "BAUPLAN="
for %%V in ("synapse-v2-Q4_K_M.gguf|Modelfile-v2" "synapse-Q4_K_M.gguf|Modelfile") do (
  for /f "tokens=1,2 delims=|" %%A in (%%V) do (
    for %%D in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Downloads\Synapse-Modell" "G:\Meine Ablage\Synapse-Modell" "G:\My Drive\Synapse-Modell" "%~dp0training\modell") do (
      if not defined ORT if exist "%%~D\%%A" (
        set "ORT=%%~D"
        set "DATEI=%%A"
        set "BAUPLAN=%%B"
      )
    )
  )
)
if not defined ORT (
  echo   Weder synapse-v3-Q4_K_M.gguf, synapse-v2-Q4_K_M.gguf noch synapse-Q4_K_M.gguf wurde gefunden.
  echo   Lade sie aus Google Drive, Ordner "Synapse-Modell", in deinen
  echo   Downloads-Ordner und starte diese Datei noch einmal.
  echo.
  pause
  exit /b 1
)
echo   [1/3] Modell gefunden: %ORT%\%DATEI%

set "OLLAMA=ollama"
where ollama >nul 2>nul
if errorlevel 1 set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not "%OLLAMA%"=="ollama" if not exist "%OLLAMA%" (
  echo   Ollama wurde nicht gefunden. Ist Ollama installiert und gestartet?
  pause
  exit /b 1
)

copy /y "%~dp0training\%BAUPLAN%" "%ORT%\Modelfile-synapse" >nul
echo   [2/3] Lege das Modell "synapse" in Ollama an (dauert 1-2 Minuten) ...
pushd "%ORT%"
"%OLLAMA%" create synapse -f Modelfile-synapse
if errorlevel 1 (
  popd
  echo.
  echo   FEHLER: Ollama konnte das Modell nicht anlegen. Die Meldung steht oben.
  pause
  exit /b 1
)
popd

echo.
echo   [3/3] Testfrage an dein Synapse-Modell (mit Tempo-Messung):
echo   ----------------------------------------------------------
"%OLLAMA%" run --verbose synapse "Wer bist du? Antworte in zwei Saetzen."
echo   ----------------------------------------------------------
echo.
echo   Fertig. Die Zeilen "prompt eval rate" und "eval rate" oben zeigen,
echo   wie schnell das Modell auf deinem Rechner laeuft.
echo   Die Datei %DATEI% in Downloads darfst du jetzt loeschen -
echo   Ollama hat eine eigene Kopie.
echo   Sag Claude Bescheid, dann wird es als Synapses Offline-Gehirn eingebaut.
echo.
pause
