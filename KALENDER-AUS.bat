@echo off
chcp 65001 >nul
title AI-Orb - Kalender ab- oder anschalten

echo ============================================================
echo   Den Kalender-Teil ab- oder wieder anschalten
echo ============================================================
echo.
echo   Nur zum Eingrenzen gedacht: Schaltet die Kalender-
echo   Werkzeuge und die Terminerinnerung aus. Diagramme,
echo   Bilder und alles andere bleiben unveraendert.
echo.
echo   Laeuft der Orb danach wieder normal, liegt es am
echo   Kalender-Teil. Laeuft er weiter nicht, liegt es woanders -
echo   und das ist genauso wertvoll zu wissen.
echo.

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import re,io,sys; p='config.yaml'; f=io.open(p,'r',encoding='utf-8',newline=''); roh=f.read(); f.close(); crlf=roh.count('\r\n')>roh.count('\n')/2; t=roh.replace('\r\n','\n'); m=re.search(r'(^kalender:\s*\n\s+enabled:\s*)(true|false)', t, re.M);  sys.exit(9) if not m else None; neu='false' if m.group(2)=='true' else 'true'; t=t[:m.start(2)]+neu+t[m.end(2):]; t=t.replace('\n','\r\n') if crlf else t; f=io.open(p,'w',encoding='utf-8',newline=''); f.write(t); f.close(); print('        Kalender steht jetzt auf:', neu)"

if errorlevel 9 (
  echo.
  echo   [FEHLER] Der Abschnitt 'kalender: enabled:' war in der
  echo            config.yaml nicht zu finden.
  echo.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo   [FEHLER] Die Konfiguration liess sich nicht aendern.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Fertig. Starte den Orb neu, damit es wirkt.
echo.
echo   Noch einmal ausfuehren schaltet wieder zurueck.
echo ============================================================
echo.
pause
