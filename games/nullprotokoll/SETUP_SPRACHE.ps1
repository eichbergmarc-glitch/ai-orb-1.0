<#
    NULLPROTOKOLL - Einrichtung der Sprachsteuerung und Sprachausgabe

    Holt einmalig alles, was fuer Sprache gebraucht wird, in den Ordner .tools\speech:

      whisper.cpp   erkennt deine gesprochenen Befehle, vollstaendig lokal
      Piper         spricht Gedanken, Juna, Samir und die Funkstimme vor
      ffmpeg        wandelt die gerenderten Zeilen nach OGG
      Python        nur falls noch keines installiert ist (eingebettete Fassung)

    Danach werden alle Sprachzeilen einmalig gerendert. Das dauert je nach
    Rechner 5 bis 20 Minuten und muss nur einmal geschehen.

    Aufruf in PowerShell im Projektordner:   .\SETUP_SPRACHE.ps1
    Groesseres Whisper-Modell:               .\SETUP_SPRACHE.ps1 -Model medium
    Nur Sprachausgabe, keine Erkennung:      .\SETUP_SPRACHE.ps1 -SkipWhisper
#>

[CmdletBinding()]
param(
    [ValidateSet('base', 'small', 'medium')]
    [string]$Model = 'small',
    [switch]$SkipWhisper,
    [switch]$SkipVoice,
    [switch]$Force
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
    Write-Host ''
    Write-Host 'Schick mir setup_sprache.log, dann sehe ich woran es liegt.' -ForegroundColor Yellow
    exit 1
}

Write-Host '--- Umgebung ---------------------------------------------'
Write-Host ("PowerShell : {0}" -f $PSVersionTable.PSVersion)
Write-Host ("Betriebssys: {0}" -f [System.Environment]::OSVersion.VersionString)
Write-Host ("Richtlinie : {0}" -f (Get-ExecutionPolicy))
Write-Host '----------------------------------------------------------'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Root) { $Root = (Get-Location).Path }
$Speech = Join-Path $Root '.tools\speech'
$Downloads = Join-Path $Speech 'download'
New-Item -ItemType Directory -Force -Path $Speech, $Downloads | Out-Null

function Write-Step  ([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
function Write-Note  ([string]$Text) { Write-Host "   $Text" -ForegroundColor DarkGray }
function Write-Good  ([string]$Text) { Write-Host "   $Text" -ForegroundColor Green }
function Write-Warn2 ([string]$Text) { Write-Host "   $Text" -ForegroundColor Yellow }

function Get-Remote {
    <# Laedt die erste erreichbare der angegebenen Adressen. #>
    param([string[]]$Urls, [string]$Target, [string]$Label)

    if ((Test-Path $Target) -and -not $Force) {
        Write-Note "$Label ist bereits vorhanden."
        return $true
    }
    foreach ($url in $Urls) {
        try {
            Write-Note "Lade $Label ..."
            Invoke-WebRequest -Uri $url -OutFile $Target -UseBasicParsing -TimeoutSec 900
            if ((Get-Item $Target).Length -gt 1024) {
                Write-Good "$Label geladen."
                return $true
            }
            Remove-Item $Target -Force -ErrorAction SilentlyContinue
        }
        catch {
            Write-Note "Nicht erreichbar: $url"
        }
    }
    Write-Warn2 "$Label konnte nicht geladen werden."
    return $false
}

function Expand-Once {
    param([string]$Archive, [string]$Destination)
    if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-Archive -Path $Archive -DestinationPath $Destination -Force
}

function Find-Executable {
    param([string]$SearchRoot, [string[]]$Names)
    foreach ($name in $Names) {
        $hit = Get-ChildItem -Path $SearchRoot -Filter $name -Recurse -File -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

# ------------------------------------------------------------------ Python

Write-Step 'Python'
$Python = $null
foreach ($candidate in @('python', 'python3', 'py')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        try {
            $version = & $found.Source -c "import sys; print(sys.version_info[0])" 2>$null
            if ($version -eq '3') { $Python = $found.Source; break }
        }
        catch { }
    }
}
if ($Python) {
    Write-Good "Gefunden: $Python"
}
else {
    Write-Note 'Kein Python gefunden, hole die eingebettete Fassung.'
    $embedZip = Join-Path $Downloads 'python-embed.zip'
    $embedDir = Join-Path $Speech 'python'
    $ok = Get-Remote -Label 'Python (eingebettet)' -Target $embedZip -Urls @(
        'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip',
        'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
    )
    if ($ok) {
        Expand-Once -Archive $embedZip -Destination $embedDir
        $Python = Join-Path $embedDir 'python.exe'
        Write-Good "Eingebettetes Python bereit."
    }
    else {
        Write-Warn2 'Ohne Python koennen die Sprachzeilen nicht gerendert werden.'
        Write-Warn2 'Installiere Python von https://www.python.org/downloads/ und starte erneut.'
    }
}

# ------------------------------------------------------------------ ffmpeg

Write-Step 'ffmpeg'
$Ffmpeg = $null
$ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegCommand) { $Ffmpeg = $ffmpegCommand.Source }
if (-not $Ffmpeg) {
    $existing = Find-Executable -SearchRoot $Speech -Names @('ffmpeg.exe')
    if ($existing) { $Ffmpeg = $existing }
}
if ($Ffmpeg) {
    Write-Good "Gefunden: $Ffmpeg"
}
else {
    $ffZip = Join-Path $Downloads 'ffmpeg.zip'
    $ok = Get-Remote -Label 'ffmpeg' -Target $ffZip -Urls @(
        'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
        'https://github.com/GyanD/codexffmpeg/releases/latest/download/ffmpeg-release-essentials.zip'
    )
    if ($ok) {
        Expand-Once -Archive $ffZip -Destination (Join-Path $Speech 'ffmpeg')
        $Ffmpeg = Find-Executable -SearchRoot (Join-Path $Speech 'ffmpeg') -Names @('ffmpeg.exe')
        if ($Ffmpeg) { Write-Good 'ffmpeg bereit.' }
    }
    if (-not $Ffmpeg) {
        Write-Warn2 'Ohne ffmpeg werden WAV-Dateien statt OGG geschrieben (deutlich groesser).'
    }
}

# ------------------------------------------------------------------ Whisper

$WhisperServer = $null
$WhisperModel = $null
if (-not $SkipWhisper) {
    Write-Step 'Spracherkennung (whisper.cpp)'
    $whisperDir = Join-Path $Speech 'whisper'
    $WhisperServer = Find-Executable -SearchRoot $whisperDir -Names @('whisper-server.exe', 'server.exe')
    if ($WhisperServer -and -not $Force) {
        Write-Good "Bereits vorhanden: $WhisperServer"
    }
    else {
        $zip = Join-Path $Downloads 'whisper-bin.zip'
        $ok = Get-Remote -Label 'whisper.cpp (Windows)' -Target $zip -Urls @(
            'https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip',
            'https://github.com/ggerganov/whisper.cpp/releases/latest/download/whisper-bin-x64.zip'
        )
        if ($ok) {
            Expand-Once -Archive $zip -Destination $whisperDir
            $WhisperServer = Find-Executable -SearchRoot $whisperDir -Names @('whisper-server.exe', 'server.exe')
            if ($WhisperServer) { Write-Good "Server: $WhisperServer" }
            else { Write-Warn2 'Im Archiv wurde keine Server-Datei gefunden.' }
        }
        if (-not $WhisperServer) {
            Write-Warn2 'Lade die Windows-Binaerdateien manuell von'
            Write-Warn2 '  https://github.com/ggml-org/whisper.cpp/releases'
            Write-Warn2 "und entpacke sie nach $whisperDir"
        }
    }

    $modelDir = Join-Path $Speech 'models'
    New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
    $WhisperModel = Join-Path $modelDir "ggml-$Model.bin"
    $sizeHint = @{ base = '142 MB'; small = '466 MB'; medium = '1,5 GB' }[$Model]
    Write-Note "Modell ggml-$Model ($sizeHint)"
    $null = Get-Remote -Label "Whisper-Modell $Model" -Target $WhisperModel -Urls @(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$Model.bin",
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$Model.bin?download=true"
    )
    if (-not (Test-Path $WhisperModel)) { $WhisperModel = $null }
}

# ------------------------------------------------------------------ Piper

$Piper = $null
$VoicesDir = Join-Path $Speech 'voices'
if (-not $SkipVoice) {
    Write-Step 'Sprachausgabe (Piper)'
    $piperDir = Join-Path $Speech 'piper'
    $Piper = Find-Executable -SearchRoot $piperDir -Names @('piper.exe')
    if ($Piper -and -not $Force) {
        Write-Good "Bereits vorhanden: $Piper"
    }
    else {
        $zip = Join-Path $Downloads 'piper.zip'
        $ok = Get-Remote -Label 'Piper (Windows)' -Target $zip -Urls @(
            'https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip',
            'https://github.com/rhasspy/piper/releases/latest/download/piper_windows_amd64.zip'
        )
        if ($ok) {
            Expand-Once -Archive $zip -Destination $piperDir
            $Piper = Find-Executable -SearchRoot $piperDir -Names @('piper.exe')
            if ($Piper) { Write-Good "Piper: $Piper" }
        }
        if (-not $Piper) {
            Write-Warn2 'Piper konnte nicht geladen werden. Ohne Piper spricht das Spiel'
            Write-Warn2 'alle Zeilen ueber die Windows-Sprachausgabe - das funktioniert,'
            Write-Warn2 'klingt aber deutlich synthetischer.'
        }
    }

    New-Item -ItemType Directory -Force -Path $VoicesDir | Out-Null
    $voices = @(
        @{ Name = 'de_DE-kerstin-low';     Path = 'de/de_DE/kerstin/low' },
        @{ Name = 'de_DE-thorsten-medium'; Path = 'de/de_DE/thorsten/medium' },
        @{ Name = 'de_DE-ramona-low';      Path = 'de/de_DE/ramona/low' },
        @{ Name = 'de_DE-karlsson-low';    Path = 'de/de_DE/karlsson/low' },
        @{ Name = 'de_DE-pavoque-low';     Path = 'de/de_DE/pavoque/low' }
    )
    foreach ($voice in $voices) {
        $base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/$($voice.Path)/$($voice.Name)"
        $null = Get-Remote -Label "Stimme $($voice.Name)" -Target (Join-Path $VoicesDir "$($voice.Name).onnx") -Urls @("$base.onnx")
        $null = Get-Remote -Label "Stimme $($voice.Name) (Konfiguration)" -Target (Join-Path $VoicesDir "$($voice.Name).onnx.json") -Urls @("$base.onnx.json")
    }
}

# ------------------------------------------------------------------ Rendern

if ($Python -and $Piper -and -not $SkipVoice) {
    Write-Step 'Sprachzeilen rendern'
    Write-Note 'Das laeuft einmalig und kann einige Minuten dauern.'
    $arguments = @(
        (Join-Path $Root 'tools\render_voice.py'),
        '--project', $Root,
        '--piper', $Piper,
        '--voices', $VoicesDir
    )
    if ($Ffmpeg) { $arguments += @('--ffmpeg', $Ffmpeg) }
    if ($Force)  { $arguments += '--force' }
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "Rendern endete mit Code $LASTEXITCODE." }
}
elseif (-not $SkipVoice) {
    Write-Warn2 'Rendern uebersprungen: Python oder Piper fehlt.'
}

# ------------------------------------------------------------------ Abschluss

$config = [ordered]@{
    whisper_server = $WhisperServer
    whisper_model  = $WhisperModel
    whisper_port   = 8099
    piper          = $Piper
    voices         = $VoicesDir
    python         = $Python
    ffmpeg         = $Ffmpeg
    erzeugt        = (Get-Date).ToString('s')
}
$config | ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $Speech 'config.json') -Encoding UTF8

if ($WhisperServer -and $WhisperModel) {
    # Startprogramm mit fertig aufgeloesten Pfaden, damit STARTEN.bat kein JSON lesen muss.
    $launcher = @"
@echo off
title NULLPROTOKOLL - Spracherkennung
echo Spracherkennung laeuft auf 127.0.0.1:8099. Dieses Fenster bitte offen lassen.
"$WhisperServer" -m "$WhisperModel" -l de --port 8099 --host 127.0.0.1 -t 4 --no-timestamps
"@
    Set-Content -Path (Join-Path $Speech 'START_SPRACHE.bat') -Value $launcher -Encoding OEM
    Write-Good 'START_SPRACHE.bat geschrieben.'
}

Write-Step 'Fertig'
if ($WhisperServer -and $WhisperModel) {
    Write-Good 'Sprachsteuerung einsatzbereit. STARTEN.bat startet den Dienst automatisch mit.'
}
else {
    Write-Warn2 'Sprachsteuerung nicht vollstaendig. Das Spiel laeuft weiterhin mit Maus und Tastatur.'
}
$voiceCount = (Get-ChildItem -Path (Join-Path $Root 'assets\voice') -Recurse -Include *.ogg, *.wav -ErrorAction SilentlyContinue).Count
Write-Good "$voiceCount vorgerenderte Sprachdateien vorhanden."
Write-Host ''
