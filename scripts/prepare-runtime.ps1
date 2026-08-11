<#
.SYNOPSIS
    Legt die mitgelieferte Python-Runtime an (Phase 47).

.DESCRIPTION
    Die Vorgabe ist eindeutig: Der Benutzer soll Python nicht kennen oder
    bedienen müssen, und nach der Installation nie "python is not
    recognized" zu sehen bekommen. Deshalb bringt AI-Orb sein eigenes
    Python mit.

    Benutzt wird die "embeddable"-Fassung von python.org – dieselbe, die
    für genau diesen Zweck gedacht ist: ein vollständiger Interpreter in
    einem Ordner, ohne Installation, ohne Registrierungseinträge, ohne
    Einfluss auf ein bereits vorhandenes Python des Benutzers.

    Drei Schritte sind nötig, und der mittlere ist der, den man leicht
    übersieht:

      1. Die embeddable-Fassung herunterladen und entpacken.
      2. Die Datei python3xx._pth anpassen. Ohne diesen Schritt findet der
         Interpreter weder site-packages noch den Projektordner – er läuft,
         kann aber nichts importieren.
      3. pip nachrüsten und die Pakete installieren.

    Das Ergebnis liegt unter runtime\python\ und wird von electron-builder
    mit ins Installationspaket genommen.

.PARAMETER Version
    Die Python-Fassung. 3.11 ist die verlässlichste Wahl: neu genug für
    alles, was AI-Orb braucht, und alt genug, dass es für jedes Paket
    fertige Windows-Pakete gibt.

.PARAMETER SkipVoice
    Die Sprachpakete auslassen. Ergibt ein deutlich kleineres Paket,
    kostet aber Weckwort und Sprachausgabe.

.PARAMETER Force
    Eine vorhandene Runtime neu anlegen.
#>

[CmdletBinding()]
param(
    [string]$Version = "3.11.9",
    [switch]$SkipVoice,
    [switch]$Force
)

# Bewusst "Continue" und nicht "Stop".
#
# Mit "Stop" behandelt PowerShell jede Ausgabe eines aufgerufenen Programms
# auf der Fehlerausgabe als abbrechenden Fehler – auch dann, wenn sie
# erwartet ist. Ein Import-Test, der fehlschlagen *darf*, würde damit das
# ganze Skript beenden, obwohl er nur eine Frage beantworten sollte.
# Fehler werden hier stattdessen an jeder Stelle einzeln geprüft.
$ErrorActionPreference = "Continue"

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDirectory
Set-Location $ProjectRoot

$RuntimeDir = Join-Path $ProjectRoot "runtime\python"
$ShortVersion = ($Version -split "\.")[0] + ($Version -split "\.")[1]   # z. B. 311

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    [OK] $Text" -ForegroundColor Green }
function Write-Inf  { param([string]$Text) Write-Host "    $Text" -ForegroundColor DarkGray }
function Write-Err  { param([string]$Text) Write-Host "    [X]  $Text" -ForegroundColor Red }

<#
.SYNOPSIS
    Prüft, ob sich ein Python-Modul importieren lässt.

.DESCRIPTION
    Kapselt den Import-Test so, dass ein Fehlschlag ein Ergebnis ist und
    kein Abbruch. Die Ausgabe von Python wird eingefangen und
    zurückgegeben, damit im Fehlerfall die tatsächliche Ursache genannt
    werden kann statt nur "hat nicht geklappt".

.OUTPUTS
    Ein Objekt mit Ok (bool), Fehlend (string) und Ausgabe (string).
#>
function Test-PythonImport {
    param([Parameter(Mandatory)][string[]]$Modules)

    $missing = @()
    $messages = @()

    foreach ($module in $Modules) {
        # Jedes Modul einzeln prüfen: Bei "import a, b" verrät die
        # Fehlermeldung nur das erste fehlende, und man sucht weiter.
        $output = & $PythonExe -c "import $module" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $missing += $module
            $text = ($output | Out-String).Trim()
            # Aus dem Traceback nur die letzte Zeile - die trägt den Grund.
            $lastLine = ($text -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
            if ($lastLine) { $messages += "$module - $lastLine" }
        }
    }

    return [PSCustomObject]@{
        Ok       = ($missing.Count -eq 0)
        Fehlend  = $missing
        Ausgabe  = ($messages -join "`n")
    }
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor White
Write-Host "  Python-Runtime fuer AI-Orb vorbereiten" -ForegroundColor White
Write-Host "=============================================================" -ForegroundColor White
Write-Inf "Fassung: $Version"
Write-Inf "Ziel:    $RuntimeDir"

# ---------------------------------------------------------------------------
# 1. Vorhandene Runtime
# ---------------------------------------------------------------------------

$PythonExe = Join-Path $RuntimeDir "python.exe"

if ((Test-Path $PythonExe) -and (-not $Force)) {
    if ((Test-PythonImport -Modules @("yaml")).Ok) {
        Write-Ok "Die Runtime ist bereits vorhanden und einsatzbereit."
        Write-Inf "Neu anlegen mit: -Force"
        exit 0
    }
    Write-Inf "Die vorhandene Runtime ist unvollstaendig - sie wird ergaenzt."
}

# ---------------------------------------------------------------------------
# 2. Herunterladen
# ---------------------------------------------------------------------------

Write-Step "Python wird geladen"

if ((Test-Path $RuntimeDir) -and $Force) {
    Remove-Item -Recurse -Force $RuntimeDir
}
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

$Url = "https://www.python.org/ftp/python/$Version/python-$Version-embed-amd64.zip"
$Archive = Join-Path $env:TEMP "python-$Version-embed.zip"

if (-not (Test-Path $Archive)) {
    Write-Inf "Von $Url"
    try {
        # Fortschrittsanzeige abschalten: Sie macht den Download in
        # PowerShell um ein Vielfaches langsamer.
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing -ErrorAction Stop
    }
    catch {
        Write-Err "Der Download ist fehlgeschlagen: $_"
        Write-Inf "Pruefe die Internetverbindung. Ohne Runtime laesst sich kein"
        Write-Inf "Installationspaket bauen."
        exit 1
    }
}

try {
    Expand-Archive -Path $Archive -DestinationPath $RuntimeDir -Force -ErrorAction Stop
}
catch {
    Write-Err "Das Archiv liess sich nicht entpacken: $_"
    Write-Inf "Moeglicherweise ist der Download unvollstaendig. Loesche"
    Write-Inf "  $Archive"
    Write-Inf "und versuche es erneut."
    exit 1
}

if (-not (Test-Path $PythonExe)) {
    Write-Err "Nach dem Entpacken fehlt python.exe."
    Write-Inf "Erwartet wurde: $PythonExe"
    exit 1
}
Write-Ok "Entpackt nach runtime\python"

# ---------------------------------------------------------------------------
# 3. Suchpfade freischalten
# ---------------------------------------------------------------------------

Write-Step "Suchpfade werden gesetzt"

# Die embeddable-Fassung hat den Import von site-packages ab Werk
# abgeschaltet. Ohne diese Zeilen findet der Interpreter kein einziges
# installiertes Paket - der haeufigste Fehler bei diesem Vorgehen.
$PthFile = Join-Path $RuntimeDir "python$ShortVersion._pth"

if (Test-Path $PthFile) {
    @"
python$ShortVersion.zip
.
Lib\site-packages

# Der Programmordner, zwei Ebenen ueber python.exe.
#
# Ohne diese Zeile scheitert "python -m backend.main" mit
# "No module named backend" - und zwar unabhaengig davon, aus welchem
# Verzeichnis man startet. Liegt naemlich eine ._pth-Datei vor, laeuft
# der Interpreter im isolierten Modus: Weder das aktuelle Verzeichnis
# noch PYTHONPATH werden beruecksichtigt. Der Suchpfad steht dann
# ausschliesslich hier.
#
# Die Angabe ist relativ zu dieser Datei und stimmt deshalb in beiden
# Faellen: im Quellordner (runtime\python -> Projektordner) wie in der
# Installation (resources\app\runtime\python -> resources\app).
..\..

# Ohne diese Zeile bleibt site-packages unsichtbar.
import site
"@ | Set-Content -Path $PthFile -Encoding ASCII
    Write-Ok "python$ShortVersion._pth angepasst"
}
else {
    Write-Err "python$ShortVersion._pth nicht gefunden - ist die Fassung richtig?"
    exit 1
}

# ---------------------------------------------------------------------------
# 4. pip nachruesten
# ---------------------------------------------------------------------------

Write-Step "pip wird eingerichtet"

$GetPip = Join-Path $env:TEMP "get-pip.py"
if (-not (Test-Path $GetPip)) {
    try {
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -UseBasicParsing -ErrorAction Stop
    }
    catch {
        Write-Err "get-pip.py liess sich nicht laden: $_"
        exit 1
    }
}

$PipSetup = & $PythonExe $GetPip --no-warn-script-location 2>&1

$PipVersion = & $PythonExe -m pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip liess sich nicht einrichten."
    Write-Inf ($PipSetup | Out-String).Trim()
    Write-Inf ($PipVersion | Out-String).Trim()
    exit 1
}
Write-Ok "pip bereit"

# ---------------------------------------------------------------------------
# 5. Pakete installieren
# ---------------------------------------------------------------------------

Write-Step "Pakete werden installiert"

& $PythonExe -m pip install --no-warn-script-location --disable-pip-version-check `
    -r (Join-Path $ProjectRoot "requirements.txt")

$Base = Test-PythonImport -Modules @("yaml")
if (-not $Base.Ok) {
    Write-Err "Die Grundpakete liessen sich nicht installieren."
    Write-Inf $Base.Ausgabe
    Write-Inf ""
    Write-Inf "Haeufigste Ursachen: keine Internetverbindung, oder eine"
    Write-Inf "Firewall blockiert pip."
    exit 1
}
Write-Ok "Grundpakete installiert"

if (-not $SkipVoice) {
    Write-Inf "Sprachpakete (etwa 500 MB, das dauert)..."
    & $PythonExe -m pip install --no-warn-script-location --disable-pip-version-check `
        -r (Join-Path $ProjectRoot "requirements-voice.txt")

    # Ein Fehlschlag hier ist kein Abbruchgrund: AI-Orb laeuft ohne
    # Sprachpakete weiter und spricht ueber die Windows-Sprachausgabe.
    # Deshalb wird geprueft, benannt - und weitergemacht.
    $Voice = Test-PythonImport -Modules @("sounddevice", "faster_whisper", "piper")

    if ($Voice.Ok) {
        Write-Ok "Sprachpakete installiert - Weckwort und Stimme sind dabei"
    }
    else {
        Write-Inf "Diese Sprachpakete fehlen: $($Voice.Fehlend -join ', ')"
        if ($Voice.Ausgabe) {
            foreach ($line in ($Voice.Ausgabe -split "`r?`n")) {
                if ($line.Trim()) { Write-Inf "  $line" }
            }
        }
        Write-Inf ""

        if ($Voice.Fehlend -contains "sounddevice" -or $Voice.Fehlend -contains "faster_whisper") {
            Write-Inf "Ohne diese reagiert AI-Orb nicht auf das Weckwort."
        }
        if ($Voice.Fehlend -contains "piper") {
            Write-Inf "Ohne Piper spricht AI-Orb ueber die Windows-Sprachausgabe."
        }
        Write-Inf "Der Bau laeuft weiter - nachruesten geht jederzeit."
    }
}
else {
    Write-Inf "Sprachpakete uebersprungen (-SkipVoice)"
}

# ---------------------------------------------------------------------------
# 6. Gegenprobe
# ---------------------------------------------------------------------------

Write-Step "Runtime wird geprueft"

# Das Skript wird in eine Datei geschrieben statt als Argument uebergeben:
# Der Projektpfad kann Leerzeichen und Sonderzeichen enthalten, die auf der
# Befehlszeile zu schwer auffindbaren Fehlern fuehren.
$CheckScript = Join-Path $env:TEMP "ai-orb-runtime-check.py"
@"
import sys
sys.path.insert(0, r'$ProjectRoot')
import backend.main
from backend import __version__
print('OK ' + __version__)
"@ | Set-Content -Path $CheckScript -Encoding UTF8

$CheckOutput = & $PythonExe $CheckScript 2>&1
$CheckExit = $LASTEXITCODE
Remove-Item $CheckScript -Force -ErrorAction SilentlyContinue

$CheckText = ($CheckOutput | Out-String).Trim()

if ($CheckExit -eq 0 -and $CheckText -match "OK\s+(\S+)") {
    Write-Ok "Das Backend laeuft mit der mitgelieferten Runtime (Fassung $($Matches[1]))"
}
else {
    Write-Err "Das Backend laeuft nicht mit der mitgelieferten Runtime."
    Write-Inf ""
    foreach ($line in ($CheckText -split "`r?`n")) {
        if ($line.Trim()) { Write-Inf $line }
    }
    Write-Inf ""
    Write-Inf "Neu anlegen mit: BUILD-INSTALLER.bat /neu"
    exit 1
}

$Size = [math]::Round((Get-ChildItem $RuntimeDir -Recurse -File |
    Measure-Object -Property Length -Sum).Sum / 1MB, 1)

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  Runtime bereit ($Size MB)" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Weiter mit: BUILD-INSTALLER.bat"
Write-Host ""
exit 0
