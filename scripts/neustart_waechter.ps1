# ===========================================================================
#  Neustart-Waechter
# ===========================================================================
#  Laeuft dauerhaft im Hintergrund und schaut alle paar Sekunden nach, ob
#  im Projektordner eine Datei NEUSTART-BITTE.txt liegt. Liegt sie da,
#  wird sie geloescht, der Orb beendet, neu gebaut und wieder gestartet.
#
#  Der Sinn: Aenderungen am Code greifen erst nach einem Neustart. Wer
#  nicht am Rechner sitzt, kann keinen Doppelklick machen - aber eine
#  Datei in den Ordner legen kann auch jemand aus der Ferne.
#
#  Zwei Vorsichtsmassnahmen sind eingebaut:
#
#  Die Signaldatei wird zuerst geloescht, dann gehandelt. Andersherum
#  wuerde ein Fehler beim Beenden dazu fuehren, dass die Datei liegen
#  bleibt und der Waechter in einer Schleife immer wieder neu startet.
#
#  Und beendet werden nur Prozesse, die aus diesem Projektordner stammen.
#  Ein blindes "taskkill electron.exe" wuerde auch fremde Programme
#  treffen, die zufaellig auf Electron gebaut sind - davon gibt es viele.
#
#  Drei Auftraege nimmt der Waechter entgegen, alle als Datei im Ordner:
#
#    NEUSTART-BITTE.txt            Orb beenden, neu bauen, starten.
#    MIKROFON-PRUEFEN-BITTE.txt    Tonlage nachsehen, ohne Neustart.
#    SELBSTVERBESSERUNG-BITTE.txt  Den Nachtlauf jetzt starten.
#
#  Der Nachtlauf kann eine Dreiviertelstunde dauern. Er laeuft deshalb
#  nebenher; der Waechter wartet nicht auf ihn, sondern bleibt ansprechbar.
#  Solange einer laeuft, wird kein zweiter gestartet.
#
#  Und der Waechter erneuert sich selbst: Aendert sich diese Datei, startet
#  er sich neu. Sonst muesste jemand am Rechner sitzen, um eine Aenderung
#  am Waechter wirksam zu machen - und genau dafuer gibt es ihn ja nicht.
# ===========================================================================

$ErrorActionPreference = 'Continue'

$Projekt   = Split-Path -Parent $PSScriptRoot
$Signal    = Join-Path $Projekt 'NEUSTART-BITTE.txt'
$Protokoll = Join-Path $Projekt 'logs\waechter-protokoll.txt'
$Status    = Join-Path $Projekt 'WAECHTER-LAEUFT.txt'
$Starter   = Join-Path $Projekt 'ORB-STARTEN.bat'
$Pruefung  = Join-Path $Projekt 'MIKROFON-PRUEFEN-BITTE.txt'
$Bericht   = Join-Path $Projekt 'scripts\mikrofon_bericht.py'
$Verbessern = Join-Path $Projekt 'SELBSTVERBESSERUNG-BITTE.txt'
$Nachtlauf  = Join-Path $Projekt 'werkzeug\selbstverbesserung.py'
$Selbst     = $PSCommandPath
$Erneuern   = Join-Path $Projekt 'scripts\waechter-still.vbs'

# Der Stand dieser Datei beim Start. Aendert er sich, ist der Waechter
# veraltet und ersetzt sich durch die neue Fassung.
$EigenerStand = $null
try { $EigenerStand = (Get-Item $Selbst).LastWriteTimeUtc } catch { }

# Laeuft gerade ein Nachtlauf? Dann kein zweiter.
$LaufendeVerbesserung = $null

function ProjektPython() {
  $py = Join-Path $Projekt 'runtime\python\python.exe'
  if (Test-Path $py) { return $py }
  return 'python'
}

function Notiz([string]$Text) {
  $Zeile = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text
  Write-Host $Zeile
  try { Add-Content -Path $Protokoll -Value $Zeile -Encoding UTF8 } catch { }
}

function OrbBeenden() {
  $getroffen = 0
  foreach ($name in @('electron', 'python', 'pythonw', 'node')) {
    Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
      $pfad = ''
      try { $pfad = $_.Path } catch { }
      if ($pfad -and $pfad.StartsWith($Projekt, [System.StringComparison]::OrdinalIgnoreCase)) {
        Notiz ("  beende {0} (PID {1})" -f $name, $_.Id)
        try { Stop-Process -Id $_.Id -Force -ErrorAction Stop; $getroffen++ } catch { Notiz ("  liess sich nicht beenden: " + $_.Exception.Message) }
      }
    }
  }
  if ($getroffen -eq 0) { Notiz '  es lief nichts aus diesem Ordner' }
  return $getroffen
}

Notiz '=========================================================='
Notiz 'Waechter gestartet.'
Notiz ("Projekt:  " + $Projekt)
Notiz ("Signal:   " + $Signal)
Notiz '=========================================================='

if (-not (Test-Path $Starter)) {
  Notiz 'ORB-STARTEN.bat fehlt - der Waechter kann nichts starten. Abbruch.'
  Start-Sleep -Seconds 20
  exit 1
}

# Eine alte Signaldatei vom letzten Mal soll keinen Neustart ausloesen.
if (Test-Path $Signal) {
  Remove-Item $Signal -Force -ErrorAction SilentlyContinue
  Notiz 'Alte Signaldatei entfernt (kein Neustart daraus).'
}

$letzteMeldung = [DateTime]::MinValue

while ($true) {

  # Lebenszeichen, damit von aussen sichtbar ist, dass der Waechter wacht.
  if (((Get-Date) - $letzteMeldung).TotalSeconds -ge 30) {
    $laufText = 'nein'
    if ($LaufendeVerbesserung -and -not $LaufendeVerbesserung.HasExited) { $laufText = 'ja' }
    try {
      Set-Content -Path $Status -Encoding UTF8 -Value @(
        'Der Neustart-Waechter laeuft.',
        ('Letztes Lebenszeichen: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
        '',
        'Neustart ausloesen:      Datei NEUSTART-BITTE.txt in diesen Ordner legen.',
        'Mikrofon nachsehen:      Datei MIKROFON-PRUEFEN-BITTE.txt hierher legen.',
        'Selbstverbesserung:      Datei SELBSTVERBESSERUNG-BITTE.txt hierher legen.',
        ('Nachtlauf laeuft gerade: ' + $laufText),
        '',
        'Was dabei passiert steht in logs\waechter-protokoll.txt',
        'Der Nachtlauf schreibt nach logs\selbstverbesserung.log'
      )
    } catch { }
    $letzteMeldung = Get-Date
  }

  # Ein Mikrofon-Bericht, ohne den Orb anzufassen. Nuetzlich aus der
  # Ferne: die Tonlage des Rechners aendert sich (Kopfhoerer ein- und
  # ausgesteckt, Windows-Freigaben), und dann will man nachsehen
  # koennen, ohne gleich alles neu zu starten.
  if (Test-Path $Pruefung) {
    Remove-Item $Pruefung -Force -ErrorAction SilentlyContinue
    Notiz 'Mikrofon-Bericht angefordert.'
    $py = Join-Path $Projekt 'runtime\python\python.exe'
    if (-not (Test-Path $py)) { $py = 'python' }
    try {
      & $py $Bericht 2>&1 | Out-Null
      Notiz 'Bericht steht in logs\mikrofon-bericht.txt'
    } catch {
      Notiz ('Bericht fehlgeschlagen: ' + $_.Exception.Message)
    }
  }

  # ---------------------------------------------------------------- Nachtlauf
  # Die Selbstverbesserung auf Zuruf. Sie laeuft nebenher: ein Lauf mit
  # Patches darf eine Dreiviertelstunde brauchen, und solange soll der
  # Waechter trotzdem auf einen Neustart reagieren koennen.
  if (Test-Path $Verbessern) {
    $wunsch = ''
    try { $wunsch = (Get-Content $Verbessern -Raw -ErrorAction SilentlyContinue) } catch { }
    Remove-Item $Verbessern -Force -ErrorAction SilentlyContinue

    if ($LaufendeVerbesserung -and -not $LaufendeVerbesserung.HasExited) {
      Notiz 'Selbstverbesserung angefordert - es laeuft schon eine. Uebergangen.'
    } elseif (-not (Test-Path $Nachtlauf)) {
      Notiz 'Selbstverbesserung angefordert - werkzeug\selbstverbesserung.py fehlt.'
    } else {
      # "nur-ziele" zeigt in Sekunden, woran gearbeitet wuerde, ohne das
      # Modell zu bemuehen. Alles andere ist der volle Lauf.
      $schalter = '--patches'
      if ($wunsch -and $wunsch -match 'nur-?ziele') { $schalter = '--ziele' }
      Notiz ('--- Selbstverbesserung angefordert (' + $schalter + ') ---')
      try {
        $LaufendeVerbesserung = Start-Process -FilePath (ProjektPython) `
          -ArgumentList @(('"' + $Nachtlauf + '"'), $schalter) `
          -WorkingDirectory $Projekt -WindowStyle Hidden -PassThru
        Notiz ('Gestartet (PID ' + $LaufendeVerbesserung.Id + '). Fortgang: logs\selbstverbesserung.log')
      } catch {
        Notiz ('Start fehlgeschlagen: ' + $_.Exception.Message)
        $LaufendeVerbesserung = $null
      }
    }
  }

  if ($LaufendeVerbesserung -and $LaufendeVerbesserung.HasExited) {
    Notiz ('Selbstverbesserung beendet (Rueckgabe ' + $LaufendeVerbesserung.ExitCode + ').')
    $LaufendeVerbesserung = $null
  }

  # ------------------------------------------------------------- Erneuerung
  # Wurde diese Datei geaendert, laeuft hier eine veraltete Fassung. Der
  # Waechter startet dann die neue und tritt ab. Waehrend eines Nachtlaufs
  # nicht - der Lauf ueberlebte den Wechsel zwar, aber niemand saehe mehr,
  # wann er fertig wird.
  if ($EigenerStand) {
    $jetzt = $null
    try { $jetzt = (Get-Item $Selbst).LastWriteTimeUtc } catch { }
    if ($jetzt -and $jetzt -ne $EigenerStand -and
        -not ($LaufendeVerbesserung -and -not $LaufendeVerbesserung.HasExited)) {
      Notiz 'Der Waechter wurde geaendert - neue Fassung uebernimmt.'
      try {
        if (Test-Path $Erneuern) {
          Start-Process -FilePath 'wscript.exe' -ArgumentList @('//B', $Erneuern) -WorkingDirectory $Projekt
        } else {
          Start-Process -FilePath 'powershell' -WindowStyle Hidden `
            -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File', $Selbst) -WorkingDirectory $Projekt
        }
        Notiz 'Uebergeben. Diese Fassung tritt ab.'
        exit 0
      } catch {
        Notiz ('Uebergabe fehlgeschlagen, bleibe in der alten Fassung: ' + $_.Exception.Message)
        $EigenerStand = $jetzt
      }
    }
  }

  if (Test-Path $Signal) {

    $grund = ''
    try { $grund = (Get-Content $Signal -Raw -ErrorAction SilentlyContinue) } catch { }
    Remove-Item $Signal -Force -ErrorAction SilentlyContinue

    Notiz ''
    Notiz '--- Neustart angefordert ---'
    if ($grund -and $grund.Trim()) { Notiz ('Grund: ' + $grund.Trim()) }

    OrbBeenden | Out-Null

    # Windows braucht einen Moment, bis Dateien des beendeten Prozesses
    # wieder frei sind. Ohne diese Pause scheitert der Bau gelegentlich
    # daran, dass dist\ noch gehalten wird.
    Start-Sleep -Seconds 3

    Notiz 'Starte ORB-STARTEN.bat (baut neu und startet).'
    try {
      Start-Process -FilePath $Starter -WorkingDirectory $Projekt
      Notiz 'Startbefehl abgesetzt. Der Fortgang steht in AI-Orb-Start-Log.txt'
    } catch {
      Notiz ('Start fehlgeschlagen: ' + $_.Exception.Message)
    }

    # Nicht sofort wieder lauschen - sonst kann eine Signaldatei, die
    # waehrend des Bauens ankommt, den halbfertigen Start abwuergen.
    Start-Sleep -Seconds 20
    Notiz '--- bereit fuer den naechsten Neustart ---'
    Notiz ''
  }

  Start-Sleep -Seconds 3
}
