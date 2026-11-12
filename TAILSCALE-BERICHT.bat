@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI-Orb - Tailscale-Bericht
REM  Sammelt, was Tailscale ueber die Verbindung zum Handy weiss.
REM  Aendert nichts. Ergebnis: logs\tailscale-bericht.txt
if not exist logs mkdir logs
set "LOG=logs\tailscale-bericht.txt"
set "TS=tailscale"
where tailscale >nul 2>&1 || set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
echo Tailscale-Bericht %DATE% %TIME%> "%LOG%"
echo.>> "%LOG%"
echo === Geraete im Tailnet (status) ===>> "%LOG%"
"%TS%" status >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo === Weiterleitung fuer den Orb (serve status) ===>> "%LOG%"
"%TS%" serve status >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo === Name und Adresse dieses PCs ===>> "%LOG%"
"%TS%" ip -4 >> "%LOG%" 2>&1
"%TS%" status --json | findstr /i "DNSName HostName Online KeyExpiry MagicDNSSuffix CertDomains" >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo === Netzpruefung ===>> "%LOG%"
"%TS%" netcheck >> "%LOG%" 2>&1
echo.>> "%LOG%"
echo === Antwortet der Orb hier am PC? ===>> "%LOG%"
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 http://127.0.0.1:8756/).StatusCode } catch { $_.Exception.Message }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 https://desktop-6i52n9c.tailb73873.ts.net/).StatusCode } catch { $_.Exception.Message }" >> "%LOG%" 2>&1
echo.
echo   Fertig. Bericht: %LOG%
echo.
pause
