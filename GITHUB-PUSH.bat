@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb auf GitHub schieben

REM ===========================================================================
REM  AI-Orb auf GitHub schieben  ->  eichbergmarc-glitch/ai-orb-1.0
REM ===========================================================================
REM  Geheimnisse (.env) und grosse Ordner (Runtime, Modelle, Browser-Profil,
REM  node_modules) werden AUSGESCHLOSSEN - sie bleiben nur auf deinem Rechner.
REM ===========================================================================

set "PROJEKT=%USERPROFILE%\AI-Orb"
set "REMOTE=https://github.com/eichbergmarc-glitch/ai-orb-1.0.git"

cd /d "%PROJEKT%" 2>nul || (echo   Ordner "%PROJEKT%" nicht gefunden. & pause & exit /b 1)

where git >nul 2>&1
if errorlevel 1 (
  echo   Git ist nicht installiert. Hole es von:
  echo     https://git-scm.com/download/win
  echo   danach diese Datei erneut starten.
  echo.
  pause
  exit /b 1
)

echo   Schutz: grosse und sensible Dinge vom Hochladen ausnehmen ...
call :ignorieren ".env"
call :ignorieren ".env.*"
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

if not exist ".git" ( git init >nul )
git branch -M main >nul 2>&1

REM Das GitHub-Ziel eintragen (oder auf die richtige Adresse setzen).
git remote get-url origin >nul 2>&1
if errorlevel 1 ( git remote add origin "%REMOTE%" ) else ( git remote set-url origin "%REMOTE%" )

REM ---------------------------------------------------------------------------
REM  Git-Identitaet: OHNE die schlaegt der Commit fehl - und genau daran lag
REM  es. Ist schon eine gesetzt (hier oder global), bleibt sie unangetastet.
REM ---------------------------------------------------------------------------
git config user.name  >nul 2>&1 || git config user.name  "Marc Eichberg"
git config user.email >nul 2>&1 || git config user.email "eichbergmarc@gmail.com"

REM Falls Geheimnisse/grosse Ordner frueher schon versioniert wurden: raus.
git rm --cached -r --ignore-unmatch .env "models" "runtime" "node_modules" "data" "logs" "audio" >nul 2>&1

echo   Stand festhalten ...
git add -A
git commit -m "AI-Orb 0.26.4 - Browsersteuerung, Suche/Diagnose, Offline-Modell, Kontingent-Rueckfall, Stimme" >nul 2>&1

REM Gibt es jetzt wirklich einen Commit? Wenn nicht, klar sagen, warum.
git rev-parse HEAD >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Es liess sich kein Commit erstellen. Das ist fast immer die fehlende
  echo   Git-Identitaet. Ich habe Name und E-Mail gerade gesetzt - bitte
  echo   starte diese Datei einfach NOCH EINMAL, dann klappt es.
  echo.
  pause
  exit /b 1
)

echo   Hochladen nach %REMOTE% ...
git push -u origin main
if not errorlevel 1 goto :fertig

echo.
echo   ------------------------------------------------------------------
echo   Der normale Push ging nicht durch.
echo.
echo   - Kommt ein Anmeldefenster von GitHub: anmelden, dann laeuft es.
echo   - Sonst liegt im Repo noch der ALTE Linux-Orb, der sich nicht
echo     zusammenfuehren laesst. Ich kann ihn durch den AKTUELLEN Stand
echo     ERSETZEN (der alte Inhalt auf GitHub wird ueberschrieben; dein
echo     Rechner bleibt unberuehrt).
echo.
set /p ANTWORT="   Bisherigen Repo-Inhalt ersetzen? Tippe JA und Enter: "
if /I not "%ANTWORT%"=="JA" (
  echo   Abgebrochen. Es wurde nichts ueberschrieben.
  pause
  exit /b 1
)

echo   Ersetze den Repo-Inhalt durch den aktuellen Stand ...
git push -u origin main --force
if errorlevel 1 (
  echo.
  echo   Auch das ging nicht durch. Meist fehlt noch die Anmeldung bei GitHub:
  echo   Beim Push sollte ein Browser-/Anmeldefenster kommen. Kommt keines,
  echo   fuehre einmal  GITHUB-DIAGNOSE.bat  aus - die schreibt die genaue
  echo   Fehlermeldung mit.
  echo.
  pause
  exit /b 1
)

:fertig
echo.
echo   ==========================================================
echo     Fertig. Der aktuelle Stand ist auf GitHub:
echo     https://github.com/eichbergmarc-glitch/ai-orb-1.0
echo   ==========================================================
echo.
pause
exit /b 0

:ignorieren
findstr /x /c:%~1 .gitignore >nul 2>&1
if errorlevel 1 echo %~1>> .gitignore
exit /b 0
