@echo off
REM ===========================================================================
REM  AI-Orb - Installationsdatei bauen
REM ===========================================================================
REM  Diese Datei erzeugt AI-Orb-Setup.exe.
REM  Einfach doppelklicken - es ist nichts einzugeben.
REM
REM  Danach genuegt ein Doppelklick auf AI-Orb-Setup.exe, und AI-Orb ist
REM  installiert: mit eigener Python-Runtime, Electron, Sprachpaketen,
REM  Startmenue-Eintrag und Uninstaller. Der Benutzer braucht danach weder
REM  Python noch Node.js noch eine Kommandozeile.
REM
REM  Beim ersten Mal dauert das etwa 15 Minuten und laedt rund 700 MB.
REM  Gebraucht werden dafuer: Node.js und eine Internetverbindung.
REM
REM  Zusaetzliche Schalter:
REM    /ohne-sprache    Ohne Sprachpakete bauen (kleineres Paket, aber
REM                     kein Weckwort und nur Windows-Sprachausgabe)
REM    /schnell         Vorhandene Python-Runtime wiederverwenden
REM    /neu             Alles von Grund auf neu bauen
REM ===========================================================================

setlocal
cd /d "%~dp0"
title AI-Orb-Setup.exe bauen

set PS_ARGS=

:parse
if "%~1"=="" goto run
if /i "%~1"=="/ohne-sprache" set PS_ARGS=%PS_ARGS% -SkipVoice
if /i "%~1"=="/schnell"      set PS_ARGS=%PS_ARGS% -SkipRuntime
if /i "%~1"=="/neu"          set PS_ARGS=%PS_ARGS% -Clean
shift
goto parse

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-installer.ps1" %PS_ARGS%
set BUILD_RESULT=%errorlevel%

if not "%BUILD_RESULT%"=="0" (
    echo.
    echo ==========================================================
    echo   Der Bau ist fehlgeschlagen.
    echo   Die Ursache steht oben im Klartext.
    echo ==========================================================
    echo.
    pause
    exit /b 1
)

echo.
pause
endlocal
