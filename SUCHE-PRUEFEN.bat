@echo off
chcp 65001 >nul
title AI-Orb - Suche pruefen

echo ============================================================
echo   Die neue Suche pruefen
echo ============================================================
echo.
echo   Bisher hat der Orb fuenf Suchmaschinen im Browsergewand
echo   abgefragt. Alle fuenf haben ihn abgewiesen - sie halten
echo   ihn fuer einen Automaten, und sie haben damit recht.
echo.
echo   Jetzt fragt er zuerst Dienste, die von Programmen
echo   abgefragt werden WOLLEN: GDELT fuer Nachrichten aus aller
echo   Welt, Wikipedia fuer Sachfragen, OpenAlex und Crossref
echo   fuer Forschungsliteratur. Kein Konto, kein Schluessel.
echo.
echo   Dieser Test sieht nach, ob sie von deinem Rechner aus
echo   antworten. Das konnte ich beim Bauen nicht pruefen -
echo   meine Umgebung kommt nicht ins offene Netz.
echo.
pause

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\suche_pruefen.py
set ERGEBNIS=%errorlevel%

echo.
echo ------------------------------------------------------------
echo   Die Tests dazu
echo ------------------------------------------------------------
"%PY%" -m pytest tests\backend\test_offene_suche.py -q

echo.
echo ============================================================
if "%ERGEBNIS%"=="0" (
  echo   Die Suche ist wieder da - ohne Konto, ohne Schluessel.
) else (
  echo   Es kam nichts zurueck. Bitte die Ausgabe oben weitergeben.
)
echo.
echo   Wer zusaetzlich die echte Google-Suche will: In der .env
echo   GOOGLE_CSE_KEY und GOOGLE_CSE_ID eintragen. Hundert
echo   Anfragen am Tag sind kostenfrei, und der Orb nimmt sie
echo   dann von selbst zuerst. Noetig ist es nicht.
echo ============================================================
echo.
pause
