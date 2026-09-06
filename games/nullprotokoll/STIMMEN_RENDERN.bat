@echo off
title NULLPROTOKOLL - Stimmen rendern
set COQUI_TOS_AGREED=1
echo Rendert alle Sprachzeilen. Der Lauf ist wiederaufnehmbar - ein Abbruch
echo mit Strg+C kostet nichts, beim naechsten Start geht es weiter.
echo.
"C:\Users\info\AI-Orb\games\nullprotokoll\.tools\speech\xtts-venv\Scripts\python.exe" "C:\Users\info\AI-Orb\games\nullprotokoll\tools\render_voice_xtts.py" --project "C:\Users\info\AI-Orb\games\nullprotokoll" --ffmpeg "C:\Users\info\AI-Orb\games\nullprotokoll\.tools\speech\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe" %*
echo.
pause
