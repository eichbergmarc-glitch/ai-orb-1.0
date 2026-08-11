# ============================================================================
#  diagnose.ps1 - stellt fest, warum AI-Orb sich nicht so verhaelt wie erwartet
# ============================================================================
#
#  Dieses Skript aendert nichts. Es sieht nach und schreibt auf.
#
#  Der Anlass: Drei sehr verschiedene Beschwerden - "der Orb ist zu gross",
#  "er reagiert nicht auf das Weckwort", "er antwortet nicht" - hatten
#  dieselbe Ursache, naemlich einen falsch aufgeloesten Programmordner. Von
#  aussen war das nicht zu sehen, weil ein Programm, das seine Konfiguration
#  nicht findet, nicht abstuerzt, sondern stillschweigend Vorgabewerte nimmt.
#
#  Deshalb beantwortet dieser Bericht zuerst die Frage, die man nicht sieht:
#  Wo sucht AI-Orb eigentlich, und liegt dort etwas?
#
# ----------------------------------------------------------------------------

param(
    # Ordner der Installation. Wird sonst selbst gesucht.
    [string]$Installation = ""
)

# "Continue" und nicht "Stop": Dieses Skript soll alles pruefen, was zu
# pruefen ist. Ein Befehl, der fehlschlaegt, ist hier ein Befund - kein
# Grund, den Rest des Berichts wegzulassen.
$ErrorActionPreference = "Continue"

$Report = New-Object System.Collections.Generic.List[string]

function Add-Line { param([string]$Text = "") $Report.Add($Text); Write-Host $Text }

function Add-Heading {
    param([string]$Text)
    Add-Line ""
    Add-Line ("=" * 74)
    Add-Line "  $Text"
    Add-Line ("=" * 74)
}

function Add-Result {
    param([string]$Label, [bool]$Ok, [string]$Detail = "")
    $mark = if ($Ok) { "[ok]  " } else { "[FEHLT]" }
    $line = "{0} {1}" -f $mark.PadRight(8), $Label
    if ($Detail) { $line += " - $Detail" }
    Add-Line $line
}

Add-Line "AI-ORB DIAGNOSE"
Add-Line ("Erstellt: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Add-Line ("Rechner:  " + $env:COMPUTERNAME + " / " + [System.Environment]::OSVersion.VersionString)

# ---------------------------------------------------------------------------
#  1. Wo ist AI-Orb?
# ---------------------------------------------------------------------------

Add-Heading "1. Programmordner"

$Candidates = @()
if ($Installation) { $Candidates += $Installation }
$Candidates += @(
    (Join-Path $env:LOCALAPPDATA "Programs\AI-Orb\resources\app"),
    (Join-Path $env:PROGRAMFILES "AI-Orb\resources\app"),
    # Der Quellordner: zwei Ebenen ueber diesem Skript.
    (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)),
    # Die ueblichen Ablageorte. Wird dieses Skript aus einem entpackten
    # Archiv heraus gestartet, fuehrt der Weg ueber die eigene Lage ins
    # Leere - dann hilft nur, an den bekannten Stellen nachzusehen.
    (Join-Path $env:USERPROFILE "Desktop\AI-Orb\AI-Orb"),
    (Join-Path $env:USERPROFILE "Desktop\AI-Orb"),
    (Join-Path $env:USERPROFILE "Documents\AI-Orb\AI-Orb"),
    (Join-Path $env:USERPROFILE "Documents\AI-Orb")
)

$AppRoot = $null
foreach ($candidate in $Candidates) {
    if ($candidate -and (Test-Path (Join-Path $candidate "backend\main.py"))) {
        $AppRoot = (Resolve-Path $candidate).Path
        break
    }
}

if (-not $AppRoot) {
    Add-Line "AI-Orb wurde nicht gefunden. Gesucht wurde in:"
    foreach ($candidate in $Candidates) { Add-Line "    $candidate" }
    Add-Line ""
    Add-Line "Ist AI-Orb installiert? Sonst dieses Skript aus dem Quellordner starten."
    $Report -join "`r`n" | Set-Content (Join-Path ([Environment]::GetFolderPath("Desktop")) "AI-Orb-Diagnose.txt") -Encoding UTF8
    exit 1
}

Add-Line "Programmordner: $AppRoot"

$Installed = Test-Path (Join-Path $AppRoot ".installiert")
Add-Line ("Betriebsart:    " + $(if ($Installed) { "installiert" } else { "Quellordner (tragbar)" }))

Add-Line ""
foreach ($item in @("config.yaml", "backend\main.py", "runtime\python\python.exe", "plugins", "skills")) {
    Add-Result $item (Test-Path (Join-Path $AppRoot $item))
}

# ---------------------------------------------------------------------------
#  2. Wo sind die Benutzerdaten?
# ---------------------------------------------------------------------------

Add-Heading "2. Benutzerdaten"

$UserDir = if ($Installed) { Join-Path $env:APPDATA "AI-Orb" } else { $AppRoot }
Add-Line "Benutzerordner: $UserDir"

$UserConfig = Join-Path $UserDir "config.yaml"
$ConfigInUse = if (Test-Path $UserConfig) { $UserConfig } else { Join-Path $AppRoot "config.yaml" }

Add-Line "Wirksame Konfiguration: $ConfigInUse"
Add-Line ""
Add-Line "Das ist die Datei, die du bearbeiten musst. Aenderungen an einer"
Add-Line "anderen config.yaml haben keine Wirkung."

if (Test-Path $ConfigInUse) {
    Add-Line ""
    foreach ($key in @("  scale:", "  width:", "  height:", "  theme:")) {
        $hit = Select-String -Path $ConfigInUse -Pattern ("^" + [regex]::Escape($key)) -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if ($hit) { Add-Line ("    " + $hit.Line.Trim()) }
    }
}

# ---------------------------------------------------------------------------
#  3. Der Python-Kern
# ---------------------------------------------------------------------------

Add-Heading "3. Python-Kern"

$Python = Join-Path $AppRoot "runtime\python\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $AppRoot ".venv\Scripts\python.exe"
}

if (-not (Test-Path $Python)) {
    Add-Line "Kein mitgeliefertes Python gefunden - das ist die Ursache, wenn"
    Add-Line "AI-Orb ueberhaupt nicht antwortet. Neu installieren."
}
else {
    Add-Line "Interpreter: $Python"
    $version = (& $Python --version 2>&1 | Out-String).Trim()
    Add-Line "Fassung:     $version"

    # Kann der Kern sein eigenes Paket finden? Das ist die Frage, an der
    # eine embeddable-Runtime scheitert, wenn der Suchpfad nicht stimmt.
    Add-Line ""
    Push-Location $AppRoot
    $import = (& $Python -c "import backend; print('ok')" 2>&1 | Out-String).Trim()
    Pop-Location

    if ($import -match "ok") {
        Add-Result "import backend" $true
    }
    else {
        Add-Result "import backend" $false
        Add-Line ""
        Add-Line "    Der Kern findet sein eigenes Paket nicht. Ohne das startet"
        Add-Line "    nichts - kein Weckwort, keine Antworten."
        Add-Line "    Meldung:"
        foreach ($line in ($import -split "`r?`n")) { if ($line.Trim()) { Add-Line ("      " + $line.Trim()) } }
    }

    Add-Line ""
    Add-Line "Pakete:"
    foreach ($module in @("yaml", "sounddevice", "faster_whisper", "piper", "numpy")) {
        $probe = (& $Python -c "import $module" 2>&1 | Out-String).Trim()
        $present = ($LASTEXITCODE -eq 0)
        $note = if ($module -eq "yaml") { "notwendig" } else { "fuer Sprache" }
        Add-Result $module $present $note
    }
}

# ---------------------------------------------------------------------------
#  4. Die Startpruefung des Kerns
# ---------------------------------------------------------------------------

Add-Heading "4. Startpruefung"

if (Test-Path $Python) {
    Push-Location $AppRoot
    $check = (& $Python -m backend.main --check 2>&1 | Out-String)
    Pop-Location

    foreach ($line in ($check -split "`r?`n")) {
        if ($line.Trim()) { Add-Line $line.TrimEnd() }
    }
}
else {
    Add-Line "Uebersprungen - kein Interpreter."
}

# ---------------------------------------------------------------------------
#  5. Sprachmodelle
# ---------------------------------------------------------------------------

Add-Heading "5. Antwortgeber"

$Claude = Get-Command claude -ErrorAction SilentlyContinue
if ($Claude) {
    Add-Result "Claude Code CLI" $true $Claude.Source
    Add-Line ""
    Add-Line "    Ob du angemeldet bist, zeigt 'claude' im Terminal."
}
else {
    Add-Result "Claude Code CLI" $false "nicht im Suchpfad"
    Add-Line ""
    Add-Line "    Ohne diese antwortet AI-Orb nur ueber Ollama."
}

$Ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $Ollama) {
    foreach ($guess in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:PROGRAMFILES "Ollama\ollama.exe"))) {
        if (Test-Path $guess) { $Ollama = [PSCustomObject]@{ Source = $guess }; break }
    }
}
Add-Result "Ollama" ($null -ne $Ollama) $(if ($Ollama) { $Ollama.Source } else { "nicht gefunden" })

# ---------------------------------------------------------------------------
#  6. Mikrofon
# ---------------------------------------------------------------------------

Add-Heading "6. Mikrofon"

$MicPolicy = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone" -ErrorAction SilentlyContinue
if ($MicPolicy -and $MicPolicy.Value) {
    Add-Result "Windows-Freigabe" ($MicPolicy.Value -eq "Allow") $MicPolicy.Value
}
else {
    Add-Line "Freigabe nicht auslesbar. Nachsehen unter:"
    Add-Line "Einstellungen -> Datenschutz und Sicherheit -> Mikrofon"
}

$Devices = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
           Where-Object { $_.PNPClass -eq "AudioEndpoint" -or $_.Name -match "Mikrofon|Microphone" }
if ($Devices) {
    Add-Line ""
    Add-Line "Gefundene Geraete:"
    foreach ($device in ($Devices | Select-Object -First 8)) { Add-Line ("    " + $device.Name) }
}

# ---------------------------------------------------------------------------
#  7. Protokolle
# ---------------------------------------------------------------------------

Add-Heading "7. Letzte Protokollzeilen"

$LogDir = Join-Path $UserDir "logs"
if (Test-Path $LogDir) {
    $latest = Get-ChildItem $LogDir -Filter "*.log" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        Add-Line "Aus $($latest.Name):"
        Add-Line ""
        foreach ($line in (Get-Content $latest.FullName -Tail 40 -ErrorAction SilentlyContinue)) {
            Add-Line ("    " + $line)
        }
    }
    else { Add-Line "Noch keine Protokolldatei - der Kern ist nie gestartet." }
}
else { Add-Line "Kein Protokollordner unter $LogDir" }

# ---------------------------------------------------------------------------

$Target = Join-Path ([Environment]::GetFolderPath("Desktop")) "AI-Orb-Diagnose.txt"
$Report -join "`r`n" | Set-Content -Path $Target -Encoding UTF8

Add-Heading "Fertig"
Add-Line "Der Bericht liegt auf dem Desktop: AI-Orb-Diagnose.txt"
Add-Line "Schick ihn mir, dann muss keiner von uns raten."

Write-Host ""
Read-Host "Zum Schliessen Eingabetaste druecken"
