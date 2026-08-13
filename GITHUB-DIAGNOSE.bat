@echo off
chcp 65001 >nul
setlocal EnableExtensions
title AI-Orb GitHub Diagnose

REM Reine Diagnose: kein git add, kein Commit, kein Push, keine Remote-Änderung.
set "PROJEKT=%~dp0"
set "PROJEKT=%PROJEKT:~0,-1%"
set "LOG=%PROJEKT%\logs\github-diagnose.txt"

cd /d "%PROJEKT%" 2>nul || (echo Ordner nicht gefunden & pause & exit /b 1)
if not exist "logs" mkdir "logs"

echo AI-Orb GitHub Diagnose>"%LOG%"
echo Zeit: %DATE% %TIME%>>"%LOG%"
echo Projekt: %PROJEKT%>>"%LOG%"
echo.>>"%LOG%"

where git >nul 2>&1 || (
  echo GIT IST NICHT INSTALLIERT. https://git-scm.com/download/win>>"%LOG%"
  notepad "%LOG%"
  exit /b 1
)

if not exist ".git" (
  echo KEIN GIT-REPOSITORY. GITHUB-PUSH.bat richtet es beim ersten Lauf ein.>>"%LOG%"
  notepad "%LOG%"
  exit /b 1
)

echo === Version ===>>"%LOG%"
powershell -NoProfile -Command "(Get-Content -Raw -LiteralPath 'package.json' | ConvertFrom-Json).version" >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Git und Branch ===>>"%LOG%"
git --version >>"%LOG%" 2>&1
git status -sb >>"%LOG%" 2>&1
git log -3 --oneline --decorate >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Remote ===>>"%LOG%"
git remote -v >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Git-Identität ===>>"%LOG%"
git config --get user.name >>"%LOG%" 2>&1
git config --get user.email >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Lokale Änderungen ===>>"%LOG%"
git status --short >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Versehentlich versionierte lokale Dateien ===>>"%LOG%"
git ls-files .env runtime models node_modules data logs audio >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === GitHub main ===>>"%LOG%"
git ls-remote origin refs/heads/main >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo === Push-Trockenlauf (ändert nichts) ===>>"%LOG%"
git push --dry-run origin main >>"%LOG%" 2>&1
echo.>>"%LOG%"

echo Diagnose abgeschlossen. Es wurde nichts verändert.>>"%LOG%"
echo Fertig. Log: %LOG%
notepad "%LOG%"
endlocal
