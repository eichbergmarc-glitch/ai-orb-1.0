@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb - Stand auf GitHub sichern

REM  Der Ordner, in dem DIESE Datei liegt - nicht mehr fest
REM  %USERPROFILE%\AI-Orb. Der Orb liegt seit Oktober 2026 in
REM  OneDrive\Dokumente\ai-orb-1.0-main; der feste Pfad zeigte ins Leere.
set "PROJEKT=%~dp0"
set "PROJEKT=%PROJEKT:~0,-1%"
set "REMOTE=https://github.com/eichbergmarc-glitch/ai-orb-1.0.git"

echo ============================================================
echo   AI-Orb auf GitHub sichern
echo ============================================================
echo.

cd /d "%PROJEKT%" 2>nul || (echo   Ordner "%PROJEKT%" nicht gefunden. & pause & exit /b 1)

where git >nul 2>&1
if errorlevel 1 (
  echo   [FEHLER] Git ist nicht installiert oder nicht im PATH.
  echo            Hole es von https://git-scm.com/download/win
  pause
  exit /b 1
)

REM --------------------------------------------------------------------
REM  Die Version aus backend\__init__.py lesen - fuer die Commit-Meldung.
REM
REM  Vorher stand dort fest "AI-Orb 0.26.4". Jede Sicherung trug damit
REM  dieselbe, laengst falsche Nummer, und auf GitHub war nicht zu sehen,
REM  welcher Stand eigentlich draufliegt.
REM --------------------------------------------------------------------
set "VERSION=unbekannt"
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" backend\__init__.py 2^>nul') do (
  set "VERSION=%%~v"
)
set "VERSION=%VERSION: =%"
set "VERSION=%VERSION:"=%"
echo   Version in diesem Ordner: %VERSION%

REM --------------------------------------------------------------------
REM  Wo stehen wir? Das war die eigentliche Ursache.
REM
REM  Die Arbeit lag zuletzt auf einem Nebenzweig
REM  ("codex/orb-recovery-..."), waehrend GitHub weiter den alten Stand
REM  von "main" zeigte. Die alte Fassung rief hier "git branch -M main"
REM  auf - das BENENNT den Zweig um und ueberschreibt dabei das
REM  vorhandene main. Sie tat das still (>nul) und konnte im
REM  ungluecklichen Fall Arbeit unerreichbar machen.
REM
REM  Jetzt wird nichts umbenannt. Der aktuelle Stand wird gesichert und
REM  gezielt nach main geschoben - gleichgueltig, wie der Zweig heisst.
REM --------------------------------------------------------------------
REM --------------------------------------------------------------------
REM  Noch kein Git in diesem Ordner? Dann NICHT mit leerer Geschichte
REM  anfangen - das wuerde GitHub als fremden Stand ablehnen und nur mit
REM  Ueberschreiben gehen. Stattdessen die Geschichte von GitHub holen
REM  und diesen Ordner als naechsten Stand darauf setzen. Die Dateien
REM  hier bleiben dabei unberuehrt (reset --mixed aendert nur den Index).
REM --------------------------------------------------------------------
if not exist ".git" (
  echo   Dieser Ordner ist noch nicht mit GitHub verbunden - wird eingerichtet ...
  git init >nul
  git remote add origin "%REMOTE%"
  git fetch origin main
  if errorlevel 1 (
    echo   [HINWEIS] GitHub-Stand nicht abrufbar - es wird neu begonnen.
    git checkout -b main >nul 2>&1
  ) else (
    git checkout -b main >nul 2>&1
    git reset --mixed origin/main >nul
    git branch --set-upstream-to=origin/main main >nul 2>&1
    echo   Mit dem GitHub-Stand verbunden. Deine Dateien wurden nicht veraendert.
  )
  echo.
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "ZWEIG=%%b"
if "%ZWEIG%"=="" set "ZWEIG=main"
if "%ZWEIG%"=="HEAD" (
  echo   [HINWEIS] Der Ordner steht auf keinem Zweig. Es wird einer angelegt.
  git checkout -b main >nul 2>&1
  set "ZWEIG=main"
)
echo   Aktueller Zweig: %ZWEIG%
echo.

git remote get-url origin >nul 2>&1
if errorlevel 1 ( git remote add origin "%REMOTE%" ) else ( git remote set-url origin "%REMOTE%" )

git config user.name  >nul 2>&1 || git config user.name  "Marc Eichberg"
git config user.email >nul 2>&1 || git config user.email "eichbergmarc@gmail.com"

REM  Was nie nach GitHub gehoert - Schluessel, Laufzeitdaten, Modelle.
git rm --cached -r --ignore-unmatch .env "models" "runtime" "node_modules" "data" "logs" "audio" >nul 2>&1

echo   [1/3] Aenderungen sichern ...
git add -A

REM --------------------------------------------------------------------
REM  Die Wache: .env und Riesen-Dateien duerfen NIE hinaus.
REM
REM  'git rm --cached' weiter oben nimmt die .env zwar aus dem Index -
REM  aber das folgende 'git add -A' legte sie wieder hinein, sobald die
REM  .gitignore fehlt oder verrutscht ist. Deshalb wird hier, NACH dem
REM  add und VOR dem Senden, in den Karton geschaut statt auf die
REM  Packliste vertraut: Liegt die .env im Paket oder eine Datei ueber
REM  50MB (GitHub weist ab 100MB ohnehin ab), bricht alles ab.
REM --------------------------------------------------------------------
powershell -NoProfile -Command "$fehler=0; git diff --cached --name-only | ForEach-Object { if ($_ -eq '.env') { Write-Host '  [STOPP] Die .env liegt im Paket - sie enthaelt deine Schluessel.'; $fehler=1 }; if ((Test-Path -LiteralPath $_) -and ((Get-Item -LiteralPath $_).Length -gt 50MB)) { Write-Host ('  [STOPP] Zu gross fuer GitHub (ueber 50MB): ' + $_); $fehler=1 } }; exit $fehler"
if errorlevel 1 (
  echo.
  echo   Es wurde NICHTS gesendet. Bitte die genannten Dateien aus dem
  echo   Ordner nehmen oder in die .gitignore eintragen und neu starten.
  pause
  exit /b 1
)
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "AI-Orb %VERSION% - aktueller Projektstand" || goto :gitfehler
) else (
  echo         Es gab nichts Neues zu sichern.
)

git rev-parse HEAD >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [FEHLER] Es gibt noch keinen einzigen gesicherten Stand.
  pause
  exit /b 1
)

for /f "delims=" %%c in ('git log -1 --pretty^=format:"%%h %%s" 2^>nul') do set "LETZTER=%%c"
echo         Zu senden: !LETZTER!
echo.
REM  Probelauf: 'set NUR_PRUEFEN=1' vor dem Start, und es wird nur
REM  gezeigt, was gesendet WUERDE - gesendet wird nichts.
if defined NUR_PRUEFEN (
  echo   [PROBELAUF] Es wird nichts gesendet. Das wuerde hinausgehen:
  git push --dry-run origin HEAD:main
  pause
  exit /b 0
)


REM --------------------------------------------------------------------
REM  Senden - ausdruecklich der AKTUELLE Stand nach main.
REM
REM  "HEAD:main" heisst: nimm, worauf dieser Ordner gerade steht, und
REM  lege es auf GitHub als main ab. Damit ist es gleichgueltig, ob der
REM  Zweig main, codex/... oder sonstwie heisst - es geht immer der
REM  Stand hinaus, den du hier vor dir hast.
REM --------------------------------------------------------------------
echo   [2/3] Nach GitHub senden (%ZWEIG% -^> main) ...
git push origin HEAD:main
if not errorlevel 1 goto :fertig

echo.
echo   ------------------------------------------------------------
echo   GitHub hat abgelehnt.
echo.
echo   Das heisst fast immer: Auf GitHub steht etwas, das es hier
echo   nicht gibt. Wird jetzt ersetzt, geht das dort Stehende
echo   verloren. Dein Ordner hier bleibt in jedem Fall unveraendert.
echo   ------------------------------------------------------------
echo.
set "ANTWORT="
set /p ANTWORT="   Inhalt auf GitHub durch diesen Stand ersetzen? Tippe JA und Enter: "
if /I not "%ANTWORT%"=="JA" (
  echo.
  echo   Abgebrochen. Es wurde nichts gesendet.
  pause
  exit /b 1
)

echo.
echo   Ersetze den Inhalt auf GitHub ...
git push origin HEAD:main --force
if errorlevel 1 (
  echo.
  echo   [FEHLER] Auch das hat nicht geklappt. Die Meldung steht oben.
  echo            Haeufigste Ursachen:
  echo              - keine Internetverbindung
  echo              - die Anmeldung bei GitHub fehlt oder ist abgelaufen
  echo            Fuehre einmal GITHUB-DIAGNOSE.bat aus.
  pause
  exit /b 1
)

:fertig
echo.
echo   [3/3] Nachpruefen ...
for /f "tokens=1" %%r in ('git ls-remote origin refs/heads/main 2^>nul') do set "FERN=%%r"
for /f "delims=" %%l in ('git rev-parse HEAD 2^>nul') do set "HIER=%%l"
echo         Hier:    %HIER%
echo         GitHub:  %FERN%
if /I "%HIER%"=="%FERN%" (
  echo.
  echo   ============================================================
  echo     Fertig. GitHub zeigt jetzt genau diesen Stand ^(%VERSION%^).
  echo     https://github.com/eichbergmarc-glitch/ai-orb-1.0
  echo   ============================================================
) else (
  echo.
  echo   [WARNUNG] GitHub zeigt einen anderen Stand als dieser Ordner.
  echo             Fuehre GITHUB-DIAGNOSE.bat aus und schick mir die
  echo             Datei logs\github-diagnose.txt.
)
echo.
pause
exit /b 0

:gitfehler
echo.
echo   [FEHLER] Das Sichern ist fehlgeschlagen. Die Meldung steht oben.
pause
exit /b 1
