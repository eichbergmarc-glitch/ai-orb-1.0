@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title AI-Orb - Suche beschleunigen

echo.
echo ======================================================================
echo   DER HAENGER BEI DER SUCHE
echo ======================================================================
echo.
echo   Die Websuche hatte kein Gesamt-Zeitlimit. Die Zugaenge wurden
echo   nacheinander versucht, jeder mit eigener Frist, und die Fristen
echo   addierten sich. Eine Gegenstelle, die langsam tropft statt zu
echo   schweigen, konnte den Orb sogar unbegrenzt festhalten.
echo.
echo   Dieses Skript aendert genau zwei Funktionen in
echo   backend\tools\web_tools.py und legt vorher eine Sicherung an.
echo.

python --version >nul 2>nul
if errorlevel 1 (
  echo   Python ist nicht im Pfad.
  echo.
  pause
  exit /b 1
)

echo ----------------------------------------------------------------------
echo  Zuerst nur pruefen - es wird noch nichts geaendert.
echo ----------------------------------------------------------------------
echo.
python werkzeug\suche_beschleunigen.py --pruefen
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
set /p WEITER="  Aendern? [j/n] "
if /i not "%WEITER%"=="j" goto ende

echo.
python werkzeug\suche_beschleunigen.py
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

echo.
echo ----------------------------------------------------------------------
echo  Zum Nachmessen ^(der Orb muss dafuer nicht laufen^):
echo     python werkzeug\suche_zeitprobe.py
echo  Zum Zuruecknehmen:
echo     python werkzeug\suche_beschleunigen.py --rueckgaengig
echo ----------------------------------------------------------------------

:ende
echo.
pause
endlocal
