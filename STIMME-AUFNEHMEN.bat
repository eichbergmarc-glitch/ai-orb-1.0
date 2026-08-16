@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title AI-Orb - Stimmprobe aufnehmen

echo ============================================================
echo   Stimmprobe fuer den Orb aufnehmen
echo ============================================================
echo.
echo   Der Orb soll mit DEINER Stimme sprechen. Dafuer braucht er
echo   eine kurze Aufnahme - etwa 20 Sekunden.
echo.
echo   Was eine gute Probe ausmacht:
echo     - ruhig und deutlich sprechen, so wie der Orb klingen soll
echo     - kein Radio, kein Fernseher, keine zweite Person im Raum
echo     - zusammenhaengend reden, nicht einzelne Woerter
echo.
echo   Lies zum Beispiel das hier vor:
echo.
echo     "Guten Morgen. Ich habe die Nachrichten fuer dich
echo      durchgesehen und drei Dinge gefunden, die dich
echo      interessieren koennten. Das Wichtigste zuerst: Der
echo      Termin am Donnerstag wurde verschoben."
echo.
echo ============================================================
echo.

cd /d "%~dp0"

set "PY=runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

set "ZIEL=%~dp0data\stimmprobe.wav"

echo   Aufnahme startet in 3 Sekunden ...
timeout /t 3 /nobreak >nul
echo.

"%PY%" -c "import sounddevice as sd, numpy as np, wave, sys; sd.default.samplerate=24000; sd.default.channels=1; print('   >>> JETZT SPRECHEN (20 Sekunden) <<<'); d=sd.rec(int(20*24000), dtype='float32'); sd.wait(); p=float(np.max(np.abs(d))); print(); print(f'   Aufnahme fertig. Aussteuerung: {p:.2f}'); sys.exit(2) if p<0.02 else None; d=d/max(p,1e-6)*0.85; w=wave.open(r'%ZIEL%','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes((d*32767).astype('<i2').tobytes()); w.close(); print('   Gespeichert.')"

if errorlevel 2 (
  echo.
  echo   [ZU LEISE] Es war fast nichts zu hoeren.
  echo              Pruefe, ob das richtige Mikrofon eingestellt ist,
  echo              und sprich naeher heran. Dann noch einmal starten.
  echo.
  pause
  exit /b 1
)
if errorlevel 1 (
  echo.
  echo   [FEHLER] Die Aufnahme hat nicht geklappt. Fehlt 'sounddevice'?
  echo            Der Orb bringt es normalerweise mit.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Fertig. Die Probe liegt hier:
echo.
echo     %ZIEL%
echo.
echo   So geht es weiter:
echo     1. Oeffne AI-Orb-Stimmserver.ipynb in Google Colab
echo     2. Lade diese Datei dort in Zelle 3 hoch
echo     3. Fuehre die Zellen aus - am Ende bekommst du eine Adresse
echo     4. Trage sie hier ein mit: STIMME-VERBINDEN.bat
echo ============================================================
echo.
pause
