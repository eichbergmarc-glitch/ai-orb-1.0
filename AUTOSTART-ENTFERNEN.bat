@echo off
chcp 65001 >nul
title AI-Orb - Neustart-Waechter aus dem Autostart nehmen

set "ZIEL=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AI-Orb Neustart-Waechter.lnk"

echo.
if exist "%ZIEL%" (
  del "%ZIEL%"
  echo   Aus dem Autostart entfernt.
) else (
  echo   Im Autostart lag nichts - nichts zu tun.
)
echo.
echo   Ein bereits laufender Waechter laeuft weiter, bis der
echo   Rechner neu gestartet wird.
echo.
pause
