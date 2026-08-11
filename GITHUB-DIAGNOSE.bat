@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb GitHub Diagnose

REM ===========================================================================
REM  Findet heraus, warum der Push nicht durchgeht - und schreibt ALLES in
REM  eine Datei, die ich lesen kann. Es wird NICHTS ueberschrieben:
REM  der Push-Versuch hier ist der gewoehnliche (kein --force).
REM ===========================================================================

set "PROJEKT=%USERPROFILE%\AI-Orb"
set "REMOTE=https://github.com/eichbergmarc-glitch/ai-orb-1.0.git"
set "LOG=%PROJEKT%\logs\github-diagnose.txt"

cd /d "%PROJEKT%" 2>nul || (echo Ordner nicht gefunden & pause & exit /b 1)
if not exist "logs" mkdir "logs"

echo AI-Orb GitHub Diagnose> "%LOG%"
echo Zeit: %DATE% %TIME%>> "%LOG%"
echo.>> "%LOG%"

where git >nul 2>&1
if errorlevel 1 (
  echo GIT IST NICHT INSTALLIERT. Hole es von https://git-scm.com/download/win>> "%LOG%"
  echo Git ist nicht installiert - Details in der Datei.
  notepad "%LOG%"
  exit /b 1
)

echo === git --version ===>> "%LOG%"
git --version >> "%LOG%" 2>&1
echo.>> "%LOG%"

REM Repo/Remote sicherstellen (ohne etwas zu ueberschreiben).
if not exist ".git" ( git init >> "%LOG%" 2>&1 )
git branch -M main >> "%LOG%" 2>&1
git remote get-url origin >nul 2>&1
if errorlevel 1 ( git remote add origin "%REMOTE%" >> "%LOG%" 2>&1 ) else ( git remote set-url origin "%REMOTE%" >> "%LOG%" 2>&1 )

echo === git remote -v ===>> "%LOG%"
git remote -v >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === credential.helper ===>> "%LOG%"
git config --get credential.helper >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === git user ===>> "%LOG%"
git config --get user.name >> "%LOG%" 2>&1
git config --get user.email >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === Anzahl geaenderter/neuer Dateien ===>> "%LOG%"
git add -A >> "%LOG%" 2>&1
git status --short | find /c /v "" >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === grosse Dateien ueber 50 MB, die hochgeladen wuerden ===>> "%LOG%"
forfiles /P "%PROJEKT%" /S /M *.* /C "cmd /c if @fsize GEQ 52428800 echo @fsize  @path" >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === git ls-remote (testet Anmeldung UND Verbindung zum Repo) ===>> "%LOG%"
git ls-remote origin >> "%LOG%" 2>&1
echo (Kam hier eine Fehlermeldung, liegt es an der Anmeldung oder der Adresse.)>> "%LOG%"
echo.>> "%LOG%"

echo === einen Stand festhalten (falls noch keiner da ist) ===>> "%LOG%"
git commit -m "AI-Orb 0.26.4" >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === PUSH-VERSUCH (gewoehnlich, ueberschreibt nichts) ===>> "%LOG%"
git push -u origin main >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo === Was ein Ersetzen taete (Trockenlauf, aendert nichts) ===>> "%LOG%"
git push origin main --force --dry-run >> "%LOG%" 2>&1
echo.>> "%LOG%"

echo Fertig. Die Datei oeffnet sich jetzt.
echo Log liegt unter: %LOG%
notepad "%LOG%"
endlocal
