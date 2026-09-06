# ===========================================================================
#  Den Neustart-Waechter erneuern
# ===========================================================================
#  Der Waechter laeuft unsichtbar. Eine Aenderung an seinem Programm greift
#  erst nach einem Neustart - und einfach einen zweiten dazuzustarten waere
#  schlecht: Dann reagieren zwei auf dieselbe Auftragsdatei, und ein
#  Nachtlauf koennte doppelt anlaufen.
#
#  Darum: erst alle Waechter DIESES Ordners beenden, dann genau einen neuen
#  starten. Beendet wird nur, was auch wirklich dieser Waechter ist - die
#  Befehlszeile muss sowohl das Skript als auch diesen Ordner nennen.
# ===========================================================================

$ErrorActionPreference = 'Continue'
$Projekt = Split-Path -Parent $PSScriptRoot
$Skript  = Join-Path $Projekt 'scripts\neustart_waechter.ps1'
$Still   = Join-Path $Projekt 'scripts\waechter-still.vbs'

Write-Host ''
Write-Host ('  Ordner: ' + $Projekt)
Write-Host ''

$alte = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -and
    $_.CommandLine -like '*neustart_waechter.ps1*' -and
    $_.CommandLine -like ('*' + $Projekt + '*')
  })

if ($alte.Count -eq 0) {
  Write-Host '  Es lief kein Waechter aus diesem Ordner.'
} else {
  foreach ($a in $alte) {
    Write-Host ('  Beende alten Waechter (PID ' + $a.ProcessId + ')')
    Stop-Process -Id $a.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
}

if (-not (Test-Path $Skript)) {
  Write-Host '  scripts\neustart_waechter.ps1 fehlt - nichts zu starten.'
  exit 1
}

try {
  if (Test-Path $Still) {
    Start-Process -FilePath 'wscript.exe' -ArgumentList @('//B', $Still) -WorkingDirectory $Projekt
  } else {
    Start-Process -FilePath 'powershell' -WindowStyle Hidden -WorkingDirectory $Projekt `
      -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Skript)
  }
  Write-Host '  Neuer Waechter gestartet (unsichtbar).'
} catch {
  Write-Host ('  Start fehlgeschlagen: ' + $_.Exception.Message)
  exit 1
}

Write-Host ''
Write-Host '  In spaetestens 30 Sekunden nennt WAECHTER-LAEUFT.txt'
Write-Host '  alle drei Auftraege, die der Waechter annimmt.'
Write-Host ''
exit 0
