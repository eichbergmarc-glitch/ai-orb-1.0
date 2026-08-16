@echo off
chcp 65001 >nul
title AI-Orb - Bilder und Kalender pruefen

echo ============================================================
echo   Pruefen, was neu dazugekommen ist
echo ============================================================
echo.
echo   Drei Dinge werden geprueft:
echo     1. Ein Diagramm zeichnen  (muss immer gehen, ohne Netz)
echo     2. Die Bilddienste im Netz (koennen ausfallen)
echo     3. Alle Tests
echo.
pause

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo ------------------------------------------------------------
echo   [1/3] Ein Diagramm zeichnen
echo ------------------------------------------------------------
"%PY%" -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from backend.grafik.diagramm import diagramm_zeichnen, Reihe; p=diagramm_zeichnen(art='balken', titel='Probe', kategorien=['Mo','Di','Mi','Do','Fr'], reihen=[Reihe('Stunden',[3,5,2,6,4])], einheit='h', quelle='Probelauf', ziel=Path('data/grafiken/probe.png')); print('        OK:', p)"
if errorlevel 1 (
  echo   [FEHLER] Das Zeichnen ging nicht. Fehlt Pillow?
  echo            "%PY%" -m pip install -r requirements-vision.txt
) else (
  echo.
  echo   Das Bild oeffnet sich jetzt zur Ansicht.
  start "" "data\grafiken\probe.png"
)

echo.
echo ------------------------------------------------------------
echo   [2/3] Die Bilddienste im Netz
echo ------------------------------------------------------------
echo   Diese drei konnte ich beim Bauen nicht selbst erreichen -
echo   deshalb wird hier auf DEINEM Rechner nachgesehen.
echo.
"%PY%" -c "import sys; sys.path.insert(0,'.'); from backend.grafik import bildquellen as b; t=b.bilder_suchen('Brandenburger Tor', anzahl=1); print('        Fotosuche:', (t[0].nachweis() if t else 'KEIN TREFFER - siehe Protokoll'))"
"%PY%" -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from backend.grafik import bildquellen as b; p=b.bild_erzeugen('a friendly robot reading a book, watercolor', Path('data/grafiken/probe-ki.jpg')); print('        Bilderzeugung:', p or 'DIENST ANTWORTET NICHT - der Orb macht dann ohne Bild weiter')"

echo.
echo ------------------------------------------------------------
echo   [3/3] Alle Tests
echo ------------------------------------------------------------
"%PY%" -m pytest tests\backend\test_grafik_und_bilder.py tests\backend\test_kalender.py -q
if errorlevel 1 (
  echo.
  echo   [FEHLER] Es sind Tests fehlgeschlagen. Bitte die Ausgabe
  echo            oben weitergeben.
) else (
  echo.
  echo   Alle Tests bestanden.
)

echo.
echo ============================================================
echo   Fertig.
echo.
echo   Fuer den Kalender fehlt noch EIN Schritt: Starte den Orb
echo   neu und sage einmal "Melde mich bei Gmail an". Auf der
echo   Google-Seite steht jetzt auch der Kalender.
echo ============================================================
echo.
pause
