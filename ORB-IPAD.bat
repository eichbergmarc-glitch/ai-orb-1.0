@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AI-Orb fuer das iPad

echo.
echo ======================================================================
echo   AI-ORB FUER DAS IPAD
echo ======================================================================
echo.

REM ===================================================== 1. Python vorhanden?
echo [1/5] Python ...
python --version >nul 2>nul
if errorlevel 1 (
  echo       Python ist nicht im Pfad. Ohne Python laeuft der Orb ohnehin nicht.
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo       %%v
echo.

REM ================================================== 2. Laeuft das Backend?
echo [2/5] Orb-Backend ...
powershell -NoProfile -Command "try{$null=Invoke-WebRequest 'http://127.0.0.1:8756/health' -TimeoutSec 3 -UseBasicParsing;exit 0}catch{exit 1}"
if errorlevel 1 (
  echo.
  echo       Das Backend antwortet nicht auf 127.0.0.1:8756.
  echo       Starte zuerst den Orb wie gewohnt und dann diese Datei erneut.
  echo.
  pause
  exit /b 1
)
echo       Laeuft.
echo.

REM ====================================================== 3. Tailscale da?
echo [3/5] Tailscale ...
where tailscale >nul 2>nul
if not errorlevel 1 goto tsangemeldet

echo       Nicht gefunden. Versuche die Installation ueber winget ...
where winget >nul 2>nul
if errorlevel 1 goto keinwinget
winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
set "PATH=%PATH%;%ProgramFiles%\Tailscale;%ProgramFiles(x86)%\Tailscale"
where tailscale >nul 2>nul
if errorlevel 1 goto keinwinget
echo       Installiert.
goto tsangemeldet

:keinwinget
echo.
echo       Automatische Installation nicht moeglich.
echo       Lade Tailscale von https://tailscale.com/download/windows
echo       Danach diese Datei erneut starten.
echo.
pause
exit /b 1

REM ---------------------------------------------------- Angemeldet?
:tsangemeldet
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "try{(tailscale status --json ^| ConvertFrom-Json).BackendState}catch{'?'}"`) do set "TSSTAND=%%a"
if /i "!TSSTAND!"=="Running" goto tsfertig

echo       Noch nicht angemeldet. Es oeffnet sich gleich ein Browserfenster -
echo       dort mit deinem Konto anmelden, danach geht es hier weiter.
echo.
tailscale up
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "try{(tailscale status --json ^| ConvertFrom-Json).BackendState}catch{'?'}"`) do set "TSSTAND=%%a"
if /i not "!TSSTAND!"=="Running" (
  echo.
  echo       Anmeldung nicht abgeschlossen. Bitte erneut versuchen.
  echo.
  pause
  exit /b 1
)

:tsfertig
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "try{(tailscale status --json ^| ConvertFrom-Json).Self.DNSName.TrimEnd('.')}catch{''}"`) do set "ORBHOST=%%a"
if "!ORBHOST!"=="" (
  echo       Angemeldet, aber der Name im Tailnet liess sich nicht lesen.
) else (
  echo       Angemeldet als !ORBHOST!
)
echo.

REM ============================================ 4. Port im Tailnet freigeben
echo [4/5] Port 8757 im Tailnet freigeben ...
tailscale serve --bg 8757 >nul 2>&1
if not errorlevel 1 goto servefertig
tailscale serve https / http://127.0.0.1:8757 >nul 2>&1
if not errorlevel 1 goto servefertig

echo.
echo       Das hat nicht geklappt. Fast immer fehlt dafuer nur ein Haken:
echo       Oeffne  https://login.tailscale.com/admin/dns
echo       und schalte unter "HTTPS Certificates" auf Enable.
echo       Danach diese Datei erneut starten.
echo.
echo       ^(Ohne HTTPS gibt iOS das Mikrofon nicht frei. Tippen ginge
echo        trotzdem - dafuer diese Datei mit  --offen  starten.^)
echo.
pause
exit /b 1

:servefertig
echo       Freigegeben.
echo.

REM ================================================== 5. Bruecke starten
echo [5/5] Bruecke starten ...
echo.
if "!ORBHOST!"=="" (
  python ipad\orb_ipad_server.py --port 8757
) else (
  python ipad\orb_ipad_server.py --port 8757 --adresse "https://!ORBHOST!"
)

if errorlevel 1 (
  echo.
  echo Der Start ist fehlgeschlagen.
  pause
)
endlocal
