@echo off
chcp 65001 >nul
title AI-Orb - Losungswort

REM ===========================================================================
REM  Zeigt das Losungswort fuer iPad und Handy.
REM
REM  Es steht bewusst NICHT in den Protokolldateien. Die gibt man weiter,
REM  wenn etwas klemmt - und ein Losungswort, das mit jeder Fehlersuche
REM  mitwandert, ist keines mehr. Es steht in der .env, und diese Datei
REM  holt es von dort auf den Bildschirm, ohne dass man die .env oeffnen
REM  und zwischen Schluesseln suchen muss.
REM ===========================================================================

setlocal EnableDelayedExpansion

set "ORB=%~dp0."
if not exist "!ORB!\.env" (
  if exist "%USERPROFILE%\AI-Orb\.env" set "ORB=%USERPROFILE%\AI-Orb"
)

if not exist "!ORB!\.env" (
  echo.
  echo   Die Datei .env wurde nicht gefunden.
  echo   Einmal FERNZUGANG.bat ausfuehren - es legt ein Losungswort an.
  echo.
  pause
  exit /b 1
)

set "WORT="
for /f "usebackq tokens=1,* delims==" %%a in ("!ORB!\.env") do (
  if /i "%%a"=="AI_ORB_WEB_TOKEN" set "WORT=%%b"
)

echo.
echo ============================================================
if defined WORT (
  echo   Losungswort fuer iPad und Handy:
  echo.
  echo        !WORT!
  echo.
  echo   Auf dem Geraet einmalig eintippen. Danach merkt der
  echo   Browser es sich - ein Jahr lang.
  echo.
  echo   Gross oder klein getippt ist egal.
) else (
  echo   In der .env steht noch kein Losungswort.
  echo   Einmal FERNZUGANG.bat ausfuehren - es legt eines an.
)
echo ============================================================
echo.
pause
