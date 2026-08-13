@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title AI-Orb sicher auf GitHub schieben

REM Startet immer im Ordner dieser Datei, nicht in einem fest verdrahteten
REM Benutzerverzeichnis. Dadurch funktioniert auch eine verschobene Kopie.
set "PROJEKT=%~dp0"
set "PROJEKT=%PROJEKT:~0,-1%"
set "REMOTE=https://github.com/eichbergmarc-glitch/ai-orb-1.0.git"
if /I "%~1"=="--check" set "NUR_PRUEFEN=1"

cd /d "%PROJEKT%" 2>nul || (echo Projektordner nicht erreichbar. & pause & exit /b 1)

where git >nul 2>&1 || (
  echo Git ist nicht installiert: https://git-scm.com/download/win
  pause
  exit /b 1
)

if not exist "package.json" (
  echo package.json fehlt. Das ist nicht der AI-Orb-Projektordner.
  pause
  exit /b 1
)

REM Die Versionsnummer kommt aus derselben Datei wie Build und Installer.
set "VERSION="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "(Get-Content -Raw -LiteralPath 'package.json' | ConvertFrom-Json).version"`) do set "VERSION=%%V"
if not defined VERSION (
  echo Die Version konnte nicht aus package.json gelesen werden.
  pause
  exit /b 1
)

echo.
echo   AI-Orb %VERSION%
echo   Projekt: %PROJEKT%
echo   Ziel:    %REMOTE%
echo.

REM Schutzregeln vervollständigen. Die öffentliche Vorlage bleibt erlaubt.
if not defined NUR_PRUEFEN (
  call :ignorieren ".env"
  call :ignorieren ".env.*"
  call :ignorieren "!.env.example"
  call :ignorieren "runtime/"
  call :ignorieren "node_modules/"
  call :ignorieren "models/"
  call :ignorieren "data/"
  call :ignorieren "logs/"
  call :ignorieren "audio/"
  call :ignorieren "build/"
  call :ignorieren "dist/"
  call :ignorieren "__pycache__/"
  call :ignorieren "*.pyc"
)

if not exist ".git" (
  if defined NUR_PRUEFEN (
    echo Abbruch: Dieser Ordner ist noch kein Git-Repository.
    exit /b 1
  )
  git init || goto :gitfehler
  git branch -M main || goto :gitfehler
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /I not "!BRANCH!"=="main" (
  echo Abbruch: Aktiver Branch ist "!BRANCH!", erwartet wird "main".
  echo Wechsle bewusst auf main und starte das Skript danach erneut.
  pause
  exit /b 1
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  if defined NUR_PRUEFEN (
    echo Abbruch: Das Git-Remote origin fehlt.
    exit /b 1
  )
  git remote add origin "%REMOTE%" || goto :gitfehler
) else (
  for /f "delims=" %%R in ('git remote get-url origin') do set "AKTUELLER_REMOTE=%%R"
  if /I not "!AKTUELLER_REMOTE!"=="%REMOTE%" (
    echo Abbruch: origin zeigt auf ein anderes Repository:
    echo   !AKTUELLER_REMOTE!
    echo Erwartet:
    echo   %REMOTE%
    echo Das Skript ändert ein bestehendes Ziel niemals stillschweigend.
    pause
    exit /b 1
  )
)

REM Keine fest eingebauten persönlichen Git-Daten mehr. Fehlen sie, wird
REM verständlich erklärt, was einmalig einzutragen ist.
git config user.name >nul 2>&1 || (
  echo Git-Benutzername fehlt. Einmalig ausführen:
  echo   git config --global user.name "Dein Name"
  pause
  exit /b 1
)
git config user.email >nul 2>&1 || (
  echo Git-E-Mail fehlt. Einmalig ausführen:
  echo   git config --global user.email "deine-adresse@example.com"
  pause
  exit /b 1
)

if defined NUR_PRUEFEN goto :pruefung

REM Falls eine echte .env früher versehentlich versioniert wurde, wird nur
REM ihre Git-Verfolgung entfernt; die lokale Datei bleibt erhalten.
git rm --cached --ignore-unmatch .env >nul 2>&1

echo Aktuellen Projektstand aufnehmen ...
git add -A || goto :gitfehler

REM Nach dem Staging nochmals kontrollieren. Dieser Test betrachtet exakt
REM das, was in den nächsten Commit käme.
powershell -NoProfile -Command "$bad = @(git diff --cached --name-only | Where-Object { $_ -eq '.env' -or $_ -match '^(runtime|node_modules|models|data|logs|audio)/' }); if ($bad.Count -gt 0) { Write-Host ('Nicht erlaubte Dateien im Commit: ' + ($bad -join ', ')); exit 1 }" || goto :geheimnis

powershell -NoProfile -Command "$bad = git diff --cached --name-only | ForEach-Object { if (Test-Path -LiteralPath $_) { $f=Get-Item -LiteralPath $_; if (-not $f.PSIsContainer -and $f.Length -gt 50MB) { $_ } } }; if ($bad) { $bad | ForEach-Object { Write-Host ('Zu gross: ' + $_) }; exit 1 }" || (
  echo Abbruch: Mindestens eine neue Datei ist größer als 50 MB.
  pause
  exit /b 1
)

git diff --cached --quiet
if errorlevel 1 (
  echo Commit für AI-Orb %VERSION% erstellen ...
  git commit -m "AI-Orb %VERSION% - aktueller Projektstand" || goto :gitfehler
) else (
  echo Keine neuen lokalen Änderungen; vorhandener Commit wird geprüft.
)

for /f "delims=" %%H in ('git rev-parse HEAD') do set "LOKALER_COMMIT=%%H"
if not defined LOKALER_COMMIT goto :gitfehler

echo Ohne Force-Push nach origin/main hochladen ...
git push -u origin main
if errorlevel 1 (
  echo.
  echo Push fehlgeschlagen. Es wurde KEIN Force-Push versucht.
  echo Häufige Ursachen: GitHub-Anmeldung fehlt oder origin/main enthält
  echo fremde neue Commits. Führe GITHUB-DIAGNOSE.bat aus.
  pause
  exit /b 1
)

REM Erfolg nicht nur aus dem Exitcode ableiten: GitHub wird direkt gefragt,
REM welcher Commit nun wirklich auf main liegt.
set "REMOTE_COMMIT="
for /f "tokens=1" %%H in ('git ls-remote origin refs/heads/main') do set "REMOTE_COMMIT=%%H"
if not defined REMOTE_COMMIT (
  echo Push lief durch, aber der GitHub-Stand konnte nicht verifiziert werden.
  pause
  exit /b 1
)
if /I not "!REMOTE_COMMIT!"=="!LOKALER_COMMIT!" (
  echo Verifikation fehlgeschlagen:
  echo   lokal:  !LOKALER_COMMIT!
  echo   GitHub: !REMOTE_COMMIT!
  pause
  exit /b 1
)

echo.
echo ==============================================================
echo Erfolgreich verifiziert: GitHub main entspricht exakt dem
echo lokalen Commit !LOKALER_COMMIT!  ^(AI-Orb %VERSION%^).
echo https://github.com/eichbergmarc-glitch/ai-orb-1.0
echo ==============================================================
echo.
pause
exit /b 0

:geheimnis
echo Abbruch: Eine sensible oder lokale Laufzeitdatei wäre im Commit.
pause
exit /b 1

:gitfehler
echo.
echo Git-Vorgang fehlgeschlagen. Es wurde kein Erfolg behauptet.
echo Führe GITHUB-DIAGNOSE.bat für die genaue Ursache aus.
pause
exit /b 1

:pruefung
echo Skriptprüfung ohne Commit und ohne Push ...
git status -sb || goto :gitfehler
set "AENDERUNGEN="
set "LOCAL_SHA="
set "REMOTE_SHA="
for /f "delims=" %%S in ('git status --porcelain') do set "AENDERUNGEN=1"
for /f "delims=" %%S in ('git rev-parse HEAD 2^>nul') do set "LOCAL_SHA=%%S"
for /f "tokens=1" %%S in ('git ls-remote origin refs/heads/main 2^>nul') do set "REMOTE_SHA=%%S"
if not defined REMOTE_SHA (
  echo GitHub-Ziel oder Anmeldung ist nicht erreichbar.
  exit /b 1
)
if defined AENDERUNGEN (
  echo ERGEBNIS: Lokale Aenderungen sind noch nicht auf GitHub.
) else if /I "!LOCAL_SHA!"=="!REMOTE_SHA!" (
  echo ERGEBNIS: Lokaler Stand und GitHub sind identisch.
) else (
  echo ERGEBNIS: Der lokale Commit ist noch nicht auf GitHub.
)
echo Der echte Push wurde nicht ausgefuehrt.
exit /b 0

:ignorieren
findstr /x /l /c:"%~1" .gitignore >nul 2>&1
if errorlevel 1 echo %~1>>.gitignore
exit /b 0
