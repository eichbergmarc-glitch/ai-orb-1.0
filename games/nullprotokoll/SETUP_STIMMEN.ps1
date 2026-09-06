<#
    NULLPROTOKOLL - Einrichtung der Sprachausgabe mit XTTS-v2

    XTTS-v2 klingt deutlich natuerlicher als eine klassische Sprachausgabe und
    kann eine Stimme aus einer kurzen Sprachprobe klonen. Dieses Skript richtet
    alles Noetige ein und rendert am Ende eine kurze Hoerprobe, damit du die
    Qualitaet beurteilen kannst, bevor der lange Lauf startet.

    Aufruf:   .\SETUP_STIMMEN.ps1
    Nur CPU:  .\SETUP_STIMMEN.ps1 -Cpu
    Ohne Hoerprobe:  .\SETUP_STIMMEN.ps1 -KeineProbe

    Rechtliches: XTTS-v2 steht unter der Coqui Public Model License und ist nur
    fuer nicht-kommerzielle Nutzung freigegeben. Klone ausschliesslich Stimmen,
    die dir gehoeren oder fuer die dir eine Erlaubnis vorliegt.
#>

[CmdletBinding()]
param(
    [switch]$Cpu,
    [switch]$KeineProbe,
    [int]$ProbeZeilen = 8
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

trap {
    Write-Host ''
    Write-Host 'FEHLER - die Einrichtung wurde abgebrochen.' -ForegroundColor Red
    Write-Host ("  Meldung: {0}" -f $_.Exception.Message) -ForegroundColor Red
    if ($_.InvocationInfo) {
        Write-Host ("  Zeile {0}: {1}" -f $_.InvocationInfo.ScriptLineNumber, $_.InvocationInfo.Line.Trim()) -ForegroundColor Red
    }
    Write-Host ("  Typ: {0}" -f $_.Exception.GetType().FullName) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host 'Schick mir setup_stimmen.log, dann sehe ich woran es liegt.' -ForegroundColor Yellow
    exit 1
}

Write-Host '--- Umgebung ---------------------------------------------'
Write-Host ("PowerShell : {0}" -f $PSVersionTable.PSVersion)
Write-Host ("Edition    : {0}" -f $PSVersionTable.PSEdition)
Write-Host ("Betriebssys: {0}" -f [System.Environment]::OSVersion.VersionString)
Write-Host ("Richtlinie : {0}" -f (Get-ExecutionPolicy))
Write-Host '----------------------------------------------------------'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Root) { $Root = (Get-Location).Path }
$Speech = Join-Path $Root '.tools\speech'
$VenvDir = Join-Path $Speech 'xtts-venv'
New-Item -ItemType Directory -Force -Path $Speech | Out-Null

function Write-Step  ([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Write-Note  ([string]$Text) { Write-Host "   $Text" -ForegroundColor DarkGray }
function Write-Good  ([string]$Text) { Write-Host "   $Text" -ForegroundColor Green }
function Write-Warn2 ([string]$Text) { Write-Host "   $Text" -ForegroundColor Yellow }

# ------------------------------------------------------------------ Python

Write-Step 'Python'
Write-Note 'XTTS braucht ein vollstaendiges Python; die eingebettete Fassung genuegt nicht.'

$Python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    try {
        $version = & $found.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($version -match '^3\.(9|10|11|12)$') {
            $Python = $found.Source
            Write-Good "Gefunden: $Python (Python $version)"
            break
        }
        Write-Note "$($found.Source) ist Python $version - nicht geeignet."
    }
    catch { }
}

if (-not $Python) {
    Write-Note 'Kein geeignetes Python gefunden, versuche die Installation.'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Note 'Installiere Python 3.12 ueber winget ...'
        & winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [System.Environment]::GetEnvironmentVariable('Path', 'User')
        $found = Get-Command python -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source; Write-Good "Python installiert: $Python" }
    }
    if (-not $Python) {
        Write-Warn2 'Bitte Python 3.12 von https://www.python.org/downloads/ installieren'
        Write-Warn2 'und dabei "Add python.exe to PATH" ankreuzen. Danach dieses Skript erneut starten.'
        exit 1
    }
}

# ------------------------------------------------------------------ ffmpeg

Write-Step 'ffmpeg'
$Ffmpeg = $null
$ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegCommand) { $Ffmpeg = $ffmpegCommand.Source }
if (-not $Ffmpeg) {
    $hit = Get-ChildItem -Path $Speech -Filter 'ffmpeg.exe' -Recurse -File -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($hit) { $Ffmpeg = $hit.FullName }
}
if (-not $Ffmpeg) {
    $ffZip = Join-Path $Speech 'ffmpeg.zip'
    foreach ($url in @(
        'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
        'https://github.com/GyanD/codexffmpeg/releases/latest/download/ffmpeg-release-essentials.zip'
    )) {
        try {
            Write-Note 'Lade ffmpeg ...'
            Invoke-WebRequest -Uri $url -OutFile $ffZip -UseBasicParsing -TimeoutSec 900
            Expand-Archive -Path $ffZip -DestinationPath (Join-Path $Speech 'ffmpeg') -Force
            Remove-Item $ffZip -Force -ErrorAction SilentlyContinue
            $hit = Get-ChildItem -Path (Join-Path $Speech 'ffmpeg') -Filter 'ffmpeg.exe' -Recurse -File |
                   Select-Object -First 1
            if ($hit) { $Ffmpeg = $hit.FullName }
            break
        }
        catch { Write-Note "Nicht erreichbar: $url" }
    }
}
if ($Ffmpeg) { Write-Good "ffmpeg: $Ffmpeg" }
else { Write-Warn2 'Ohne ffmpeg werden WAV-Dateien statt OGG geschrieben (deutlich groesser).' }

# ------------------------------------------------------------------ Grafikkarte

Write-Step 'Rechenwerk'
$UseCuda = $false
if (-not $Cpu) {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        try {
            $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
            if ($gpu) {
                $UseCuda = $true
                Write-Good "NVIDIA-Grafikkarte erkannt: $gpu"
                Write-Note 'Damit rendert XTTS ein Vielfaches schneller.'
            }
        }
        catch { }
    }
}
if (-not $UseCuda) {
    Write-Note 'Keine nutzbare NVIDIA-Grafikkarte - es wird auf der CPU gerechnet.'
    Write-Note 'Das funktioniert, dauert fuer alle Zeilen aber mehrere Stunden.'
}

# ------------------------------------------------------------------ Umgebung

Write-Step 'XTTS-Umgebung'
if (-not (Test-Path (Join-Path $VenvDir 'Scripts\python.exe'))) {
    Write-Note "Lege virtuelle Umgebung an: $VenvDir"
    & $Python -m venv $VenvDir
}
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Warn2 'Die virtuelle Umgebung konnte nicht angelegt werden.'
    exit 1
}

Write-Note 'Aktualisiere pip ...'
& $VenvPython -m pip install --upgrade pip --quiet

# Ab PyTorch 2.9 verlangt coqui-tts die Zusatzbibliothek torchcodec fuer die
# Audioausgabe. Deren Windows-Fassung braucht die FFmpeg-DLLs im System, die ein
# gewoehnliches ffmpeg.exe nicht mitbringt. Unterhalb von 2.9 benutzt coqui-tts
# weiterhin torchaudio - deutlich weniger bewegliche Teile, gleiche Qualitaet.
Write-Note "Installiere PyTorch 2.8 (etwa 2,5 GB, das dauert) ..."
if ($UseCuda) {
    & $VenvPython -m pip install "torch>=2.2,<2.9" "torchaudio<2.9" --index-url 'https://download.pytorch.org/whl/cu121'
}
else {
    # Auf Windows liefert PyPI bereits die CPU-Fassung.
    & $VenvPython -m pip install "torch>=2.2,<2.9" "torchaudio<2.9"
}
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'PyTorch konnte nicht installiert werden.'
    exit 1
}

Write-Note 'Installiere coqui-tts ...'
& $VenvPython -m pip install coqui-tts
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'coqui-tts konnte nicht installiert werden.'
    exit 1
}

# coqui-tts fordert nur "transformers>=4.57" ohne Obergrenze. pip zieht damit
# die 5er-Reihe, in der isin_mps_friendly entfernt wurde - eine Funktion, die
# coqui-tts intern noch importiert. Ohne diese Grenze bricht der erste Aufruf
# mit "cannot import name 'isin_mps_friendly'" ab.
Write-Note 'Setze transformers und torch auf vertraegliche Fassungen ...'
& $VenvPython -m pip install "transformers>=4.57,<5" "torch>=2.2,<2.9" "torchaudio<2.9"
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'transformers konnte nicht angepasst werden.'
    exit 1
}

Write-Note 'Pruefe, ob XTTS wirklich geladen werden kann ...'
# Die Ausgabe geht in eine Datei statt in eine Variable: bei
# $ErrorActionPreference = 'Stop' macht PowerShell aus jeder stderr-Zeile eines
# fremden Programms einen abbrechenden Fehler und behaelt nur die erste Zeile -
# genau dadurch ging der eigentliche Traceback vorher verloren.
$checkLog = Join-Path $Speech 'xtts_check.txt'
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $VenvPython -c "from TTS.api import TTS; print('XTTS_IMPORT_OK')" > $checkLog 2>&1
$checkCode = $LASTEXITCODE
$ErrorActionPreference = $previousPreference

$checkText = if (Test-Path $checkLog) { Get-Content $checkLog -Raw } else { '' }
if ($checkCode -eq 0 -and $checkText -match 'XTTS_IMPORT_OK') {
    Write-Good 'XTTS laesst sich laden.'
}
else {
    Write-Warn2 'XTTS laesst sich nicht laden. Vollstaendige Ausgabe:'
    Write-Host ''
    Write-Host $checkText
    Write-Host ''
    Write-Warn2 'Installierte Fassungen:'
    $ErrorActionPreference = 'Continue'
    & $VenvPython -m pip list 2>&1 |
        Select-String -Pattern 'transformers|coqui|torch|tokenizers|numpy|huggingface' |
        ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
    $ErrorActionPreference = $previousPreference
    exit 1
}
Write-Good 'Umgebung steht.'

# ------------------------------------------------------------------ Startprogramm

$renderCall = "`"$VenvPython`" `"$Root\tools\render_voice_xtts.py`" --project `"$Root`""
if ($Ffmpeg) { $renderCall += " --ffmpeg `"$Ffmpeg`"" }
if ($Cpu)    { $renderCall += " --cpu" }

$batch = @"
@echo off
title NULLPROTOKOLL - Stimmen rendern
set COQUI_TOS_AGREED=1
echo Rendert alle Sprachzeilen. Der Lauf ist wiederaufnehmbar - ein Abbruch
echo mit Strg+C kostet nichts, beim naechsten Start geht es weiter.
echo.
$renderCall %*
echo.
pause
"@
Set-Content -Path (Join-Path $Root 'STIMMEN_RENDERN.bat') -Value $batch -Encoding OEM
Write-Good 'STIMMEN_RENDERN.bat geschrieben.'

# ------------------------------------------------------------------ Hoerprobe

if (-not $KeineProbe) {
    Write-Step 'Hoerprobe'
    Write-Note "Rendert $ProbeZeilen Zeilen je Rolle. Beim ersten Mal wird das Modell geladen (~1,8 GB)."
    $env:COQUI_TOS_AGREED = '1'
    $probeArgs = @(
        (Join-Path $Root 'tools\render_voice_xtts.py'),
        '--project', $Root,
        '--limit', $ProbeZeilen
    )
    if ($Ffmpeg) { $probeArgs += @('--ffmpeg', $Ffmpeg) }
    if ($Cpu)    { $probeArgs += '--cpu' }
    & $VenvPython @probeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "Die Hoerprobe endete mit Fehlercode $LASTEXITCODE - es wurde nichts gerendert."
        Write-Warn2 'Die Ursache steht in den Zeilen darueber.'
        exit 1
    }
}

Write-Step 'Fertig'
Write-Good 'Hoer dir die Dateien in assets\voice\ an.'
Write-Note 'Passt die Stimme, dann alle Zeilen rendern mit:   .\STIMMEN_RENDERN.bat'
Write-Note 'Andere Stimme gewuenscht? tools\voice_config.json anpassen.'
Write-Note 'Eigene Stimme klonen? Sprachprobe nach tools\stimmproben\ legen,'
Write-Note 'siehe tools\stimmproben\LIESMICH.md.'
Write-Host ''
