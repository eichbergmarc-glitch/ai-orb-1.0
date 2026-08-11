<#
.SYNOPSIS
    Räumt die alte, skriptbasierte Installation auf.

.DESCRIPTION
    Bis Fassung 0.3.0 wurde AI-Orb über Skripte betrieben: eine
    Python-Umgebung im Projektordner, Node-Pakete daneben, ein Build,
    Patch-Pakete, Reparaturskripte. Ab 0.4.0 gibt es stattdessen eine
    Installationsdatei.

    Dieses Skript entfernt, was von der alten Arbeitsweise übrig ist –
    aber nur das. Deine Daten bleiben, sofern du nicht ausdrücklich etwas
    anderes verlangst.

    Diese Unterscheidung ist der ganze Zweck des Skripts. Ein "alles
    löschen" wäre in drei Zeilen geschrieben; die Sorgfalt liegt darin,
    zwischen Wegwerfbarem und Unersetzlichem zu trennen.

.PARAMETER IncludeData
    Auch die Benutzerdaten löschen: Erinnerungen, Wissensbasis, Knowledge
    Graph, Karteikarten, gelernte Positionen. Wird zweimal bestätigt.

.PARAMETER DryRun
    Nur zeigen, was geschehen würde.
#>

[CmdletBinding()]
param(
    [switch]$IncludeData,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDirectory
Set-Location $ProjectRoot

function Write-Ok  { param([string]$Text) Write-Host "      $Text" -ForegroundColor Green }
function Write-Inf { param([string]$Text) Write-Host "      $Text" -ForegroundColor DarkGray }
function Write-Keep{ param([string]$Text) Write-Host "      $Text" -ForegroundColor Cyan }
function Write-Warn2 { param([string]$Text) Write-Host "      $Text" -ForegroundColor Yellow }

Clear-Host
Write-Host ""
Write-Host "  ==========================================================" -ForegroundColor White
Write-Host "    AI-Orb - alte Installation aufraeumen" -ForegroundColor White
Write-Host "  ==========================================================" -ForegroundColor White
Write-Host "    Ordner: $ProjectRoot" -ForegroundColor DarkGray
if ($DryRun) {
    Write-Host "    PROBELAUF - es wird nichts geloescht" -ForegroundColor Yellow
}

# ===========================================================================
# 1. Laufende Prozesse
# ===========================================================================

Write-Host ""
Write-Host "[1/4] Laufende Prozesse" -ForegroundColor Cyan

$Running = @()
foreach ($name in @("AI-Orb", "electron", "python")) {
    $found = Get-Process -Name $name -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($ProjectRoot) }
    if ($found) { $Running += $found }
}

if ($Running.Count -gt 0) {
    Write-Warn2 "$($Running.Count) Prozess(e) von AI-Orb laufen noch."
    if (-not $DryRun) {
        foreach ($process in $Running) {
            try {
                $process.Kill()
                Write-Inf "beendet: $($process.ProcessName) (PID $($process.Id))"
            }
            catch {
                Write-Inf "liess sich nicht beenden: $($process.ProcessName)"
            }
        }
        Start-Sleep -Seconds 2
    }
    Write-Ok "Prozesse beendet"
}
else {
    Write-Ok "Es laeuft nichts"
}

# ===========================================================================
# 2. Wegwerfbares
# ===========================================================================

Write-Host ""
Write-Host "[2/4] Technische Zwischenstaende" -ForegroundColor Cyan

# Ordner, die sich jederzeit neu erzeugen lassen.
$DisposableFolders = @(
    ".venv",
    "node_modules",
    "desktop\electron\dist",
    "dist-installer",
    "logs",
    "upgrades",
    "runtime"
)

# Dateien der alten, skriptbasierten Arbeitsweise.
$ObsoleteFiles = @(
    "REPARIEREN-UND-STARTEN.bat",
    "rebuild.bat",
    "install.bat",
    "install.ps1",
    "start.bat",
    "start.ps1",
    "scripts\repair.ps1",
    "scripts\rebuild.ps1",
    "scripts\stop-orb.ps1",
    "scripts\create-shortcut.ps1",
    "PATCH-ANWENDEN.md",
    "package-lock.json",
    "data\upgrade_state.json"
)

$FreedBytes = 0
$RemovedCount = 0

foreach ($folder in $DisposableFolders) {
    $full = Join-Path $ProjectRoot $folder
    if (-not (Test-Path $full)) { continue }

    $size = 0
    try {
        $size = (Get-ChildItem $full -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum
    } catch { }
    if (-not $size) { $size = 0 }

    if ($DryRun) {
        Write-Inf "wuerde entfernt: $folder ($([math]::Round($size / 1MB, 1)) MB)"
    }
    else {
        try {
            Remove-Item -Recurse -Force $full -ErrorAction Stop
            Write-Inf "entfernt: $folder ($([math]::Round($size / 1MB, 1)) MB)"
            $FreedBytes += $size
            $RemovedCount += 1
        }
        catch {
            Write-Warn2 "blieb liegen: $folder - $($_.Exception.Message)"
        }
    }
}

foreach ($file in $ObsoleteFiles) {
    $full = Join-Path $ProjectRoot $file
    if (-not (Test-Path $full)) { continue }

    if ($DryRun) {
        Write-Inf "wuerde entfernt: $file"
    }
    else {
        try {
            $size = (Get-Item $full).Length
            Remove-Item -Force $full -ErrorAction Stop
            Write-Inf "entfernt: $file"
            $FreedBytes += $size
            $RemovedCount += 1
        }
        catch {
            Write-Warn2 "blieb liegen: $file"
        }
    }
}

# Python-Zwischenstaende
$Caches = Get-ChildItem $ProjectRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
if ($Caches) {
    if ($DryRun) {
        Write-Inf "wuerden entfernt: $($Caches.Count) __pycache__-Ordner"
    }
    else {
        foreach ($cache in $Caches) {
            try { Remove-Item -Recurse -Force $cache.FullName -ErrorAction Stop } catch { }
        }
        Write-Inf "entfernt: $($Caches.Count) __pycache__-Ordner"
    }
}

Write-Ok "$RemovedCount Eintraege entfernt, $([math]::Round($FreedBytes / 1MB, 1)) MB frei"

# ===========================================================================
# 3. Startmenue-Eintraege der alten Fassung
# ===========================================================================

Write-Host ""
Write-Host "[3/4] Alte Startmenue-Eintraege" -ForegroundColor Cyan

$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\AI-Orb"

if (Test-Path $StartMenu) {
    if ($DryRun) {
        Write-Inf "wuerde entfernt: $StartMenu"
    }
    else {
        try {
            Remove-Item -Recurse -Force $StartMenu -ErrorAction Stop
            Write-Ok "Alte Verknuepfungen entfernt"
        }
        catch {
            Write-Warn2 "Die Verknuepfungen blieben liegen."
        }
    }
}
else {
    Write-Ok "Keine vorhanden"
}

# ===========================================================================
# 4. Benutzerdaten
# ===========================================================================

Write-Host ""
Write-Host "[4/4] Deine Daten" -ForegroundColor Cyan

$DataFolders = @("data", "models", "audio")
$UserFiles = @("config.yaml", ".env")

$DataSize = 0
foreach ($folder in $DataFolders) {
    $full = Join-Path $ProjectRoot $folder
    if (Test-Path $full) {
        try {
            $sum = (Get-ChildItem $full -Recurse -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
            if ($sum) { $DataSize += $sum }
        } catch { }
    }
}

if (-not $IncludeData) {
    Write-Keep "Bleiben erhalten ($([math]::Round($DataSize / 1MB, 1)) MB):"
    foreach ($folder in $DataFolders) {
        if (Test-Path (Join-Path $ProjectRoot $folder)) { Write-Keep "  $folder\" }
    }
    foreach ($file in $UserFiles) {
        if (Test-Path (Join-Path $ProjectRoot $file)) { Write-Keep "  $file" }
    }
    Write-Host ""
    Write-Inf "Die neue Fassung uebernimmt sie beim ersten Start selbst."
    Write-Inf "Wirklich alles loeschen: AUFRAEUMEN.bat /auch-daten"
}
else {
    Write-Warn2 "Es sollen auch deine Daten geloescht werden."
    Write-Host ""
    Write-Host "      Das betrifft:" -ForegroundColor Yellow
    Write-Host "        - Erinnerungen und Gespraeche" -ForegroundColor Yellow
    Write-Host "        - Wissensbasis und Wissensnetz" -ForegroundColor Yellow
    Write-Host "        - Karteikarten und Lernplaene" -ForegroundColor Yellow
    Write-Host "        - Einstellungen und Zugangsdaten" -ForegroundColor Yellow
    Write-Host "        - gelernte Orb-Positionen" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "      Umfang: $([math]::Round($DataSize / 1MB, 1)) MB" -ForegroundColor Yellow
    Write-Host ""

    if (-not $DryRun) {
        $answer = Read-Host "      Wirklich loeschen? Tippe LOESCHEN"
        if ($answer -ne "LOESCHEN") {
            Write-Host ""
            Write-Ok "Abgebrochen - deine Daten bleiben."
            $IncludeData = $false
        }
    }

    if ($IncludeData) {
        foreach ($folder in $DataFolders) {
            $full = Join-Path $ProjectRoot $folder
            if (-not (Test-Path $full)) { continue }
            if ($DryRun) { Write-Inf "wuerde entfernt: $folder\"; continue }
            try {
                Remove-Item -Recurse -Force $full -ErrorAction Stop
                Write-Inf "entfernt: $folder\"
            } catch { Write-Warn2 "blieb liegen: $folder\" }
        }
        foreach ($file in $UserFiles) {
            $full = Join-Path $ProjectRoot $file
            if (-not (Test-Path $full)) { continue }
            if ($DryRun) { Write-Inf "wuerde entfernt: $file"; continue }
            try {
                Remove-Item -Force $full -ErrorAction Stop
                Write-Inf "entfernt: $file"
            } catch { Write-Warn2 "blieb liegen: $file" }
        }

        # Auch die Daten einer bereits installierten Fassung.
        foreach ($path in @((Join-Path $env:APPDATA "AI-Orb"),
                            (Join-Path $env:LOCALAPPDATA "AI-Orb"))) {
            if (-not (Test-Path $path)) { continue }
            if ($DryRun) { Write-Inf "wuerde entfernt: $path"; continue }
            try {
                Remove-Item -Recurse -Force $path -ErrorAction Stop
                Write-Inf "entfernt: $path"
            } catch { Write-Warn2 "blieb liegen: $path" }
        }

        Write-Ok "Daten geloescht"
    }
}

# ===========================================================================
# Abschluss
# ===========================================================================

Write-Host ""
Write-Host "  ==========================================================" -ForegroundColor Green
if ($DryRun) {
    Write-Host "    Probelauf beendet - es wurde nichts geloescht" -ForegroundColor Green
}
else {
    Write-Host "    Aufgeraeumt" -ForegroundColor Green
}
Write-Host "  ==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "    So geht es weiter:"
Write-Host ""
Write-Host "      1. BUILD-INSTALLER.bat doppelklicken" -ForegroundColor White
Write-Host "         erzeugt AI-Orb-Setup.exe (etwa 15 Minuten)"
Write-Host ""
Write-Host "      2. AI-Orb-Setup.exe doppelklicken" -ForegroundColor White
Write-Host "         installiert AI-Orb samt allem, was es braucht"
Write-Host ""
Write-Host "      3. Startmenue -> AI-Orb" -ForegroundColor White
Write-Host "         ein Klick, und der Orb erscheint"
Write-Host ""

exit 0
