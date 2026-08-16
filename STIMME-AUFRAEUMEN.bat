@echo off
chcp 65001 >nul
title AI-Orb - Reste der Stimmserver-Versuche entfernen

echo ============================================================
echo   Reste der Stimmserver-Versuche entfernen
echo ============================================================
echo.
echo   Entfernt werden vier Dateien, die zu den Versuchen mit
echo   einem eigenen Stimmserver gehoerten. Der Orb benutzt sie
echo   nicht - sie liegen nur noch im Ordner herum:
echo.
echo     AI-Orb-Stimmserver.ipynb
echo     STIMME-AUFNEHMEN.bat
echo     STIMME-VERBINDEN.bat
echo     scripts\stimme_verbinden.py
echo.
echo   Am Orb selbst aendert sich dadurch nichts. Seine Stimme,
echo   die Animation und alle Korrekturen bleiben, wie sie sind.
echo.
echo   Deine eigenen Sprachaufnahmen unter data\stimmproben
echo   werden NICHT angeruehrt - die gehoeren zur Sprecher-
echo   erkennung und haben mit dem Stimmserver nichts zu tun.
echo.
pause

cd /d "%~dp0"

for %%D in (
  "AI-Orb-Stimmserver.ipynb"
  "STIMME-AUFNEHMEN.bat"
  "STIMME-VERBINDEN.bat"
  "scripts\stimme_verbinden.py"
) do (
  if exist "%%~D" (
    del /f /q "%%~D" 2>nul
    if exist "%%~D" (
      echo   [FEHLER]  %%~D liess sich nicht loeschen.
    ) else (
      echo   entfernt: %%~D
    )
  ) else (
    echo   war schon weg: %%~D
  )
)

echo.
echo ============================================================
echo   Fertig. Der Orb muss dafuer nicht neu gestartet werden.
echo ============================================================
echo.
pause

REM  Zum Schluss loescht sich diese Datei selbst - sie wird kein
REM  zweites Mal gebraucht.
(goto) 2>nul & del /f /q "%~f0"
