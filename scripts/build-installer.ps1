<#
.SYNOPSIS
    Baut AI-Orb-Setup.exe (Phasen 41, 42, 60).

.DESCRIPTION
    Erzeugt aus dem Projekt eine einzige Installationsdatei, die alles
    mitbringt: Electron, den Python-Kern, die mitgelieferte Python-Runtime,
    die Sprachpakete, Icon, Startmenü-Eintrag und einen Uninstaller.

    Der Ablauf:

      1. Voraussetzungen prüfen (Node.js)
      2. Node-Pakete installieren
      3. Python-Runtime vorbereiten und in das Paket legen
      4. Oberfläche bauen und gegenprüfen
      5. Installationspaket schnüren
      6. Ergebnis prüfen

    Gebaut wird auf demselben Rechner, auf dem AI-Orb später läuft. Ein
    Windows-Installationspaket lässt sich nur unter Windows erzeugen; das
    ist keine Bequemlichkeitsentscheidung, sondern eine Eigenschaft des
    Formats.

.PARAMETER SkipVoice
    Ohne Sprachpakete bauen. Das Paket wird deutlich kleiner, AI-Orb
    spricht dann nur über die Windows-Sprachausgabe und hört nicht zu.

.PARAMETER SkipRuntime
    Die Python-Runtime nicht neu vorbereiten, falls sie schon liegt.

.PARAMETER Clean
    Alles neu bauen.
#>

[CmdletBinding()]
param(
    [switch]$SkipVoice,
    [switch]$SkipRuntime,
    [switch]$Clean
)

$ErrorActionPreference = "Continue"

$ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDirectory
Set-Location $ProjectRoot

$script:StepNumber = 0
function Write-Step {
    param([string]$Text)
    $script:StepNumber += 1
    Write-Host ""
    Write-Host "[$script:StepNumber/6] $Text" -ForegroundColor Cyan
}
function Write-Ok  { param([string]$Text) Write-Host "      $Text" -ForegroundColor Green }
function Write-Inf { param([string]$Text) Write-Host "      $Text" -ForegroundColor DarkGray }
function Write-Err { param([string]$Text) Write-Host "      $Text" -ForegroundColor Red }

# ---------------------------------------------------------------------------
#  Protokoll
# ---------------------------------------------------------------------------
#
#  Jede Ausgabe wird zusaetzlich in eine Datei geschrieben.
#
#  Der Grund: Ein Fehlschlag beim Schnueren des Pakets erzeugt hunderte
#  Zeilen, und die entscheidende steht mittendrin. Wer nur den roten Kasten
#  am Ende sieht, sieht das Ergebnis, aber nicht die Ursache - und der
#  Kasten ist dann eine Feststellung ohne Erkenntnis.
#
$script:LogFile = Join-Path $ProjectRoot "AI-Orb-Build-Log.txt"
"AI-Orb Build-Protokoll - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" |
    Set-Content -Path $script:LogFile -Encoding UTF8

function Write-Log {
    param([string]$Text = "")
    try { Add-Content -Path $script:LogFile -Value $Text -Encoding UTF8 } catch { }
}

function Show-Failure {
    param([string]$Title, [string[]]$Lines)
    Write-Host ""
    Write-Host "  ========================================================" -ForegroundColor Red
    Write-Host "   $Title" -ForegroundColor Red
    Write-Host "  ========================================================" -ForegroundColor Red
    Write-Host ""
    foreach ($line in $Lines) { Write-Host "   $line" }
    Write-Host ""
    Write-Host "   Vollstaendiges Protokoll:" -ForegroundColor DarkGray
    Write-Host "   $script:LogFile" -ForegroundColor DarkGray
    Write-Host ""

    Write-Log ""
    Write-Log "=== FEHLGESCHLAGEN: $Title ==="
    foreach ($line in $Lines) { Write-Log "   $line" }
}

<#
.SYNOPSIS
    Fuehrt ein Programm aus, protokolliert alles und gibt die Ausgabe zurueck.

.DESCRIPTION
    Sammelt stdout und stderr, schreibt beides ins Protokoll und zeigt es
    zugleich an. Der Rueckgabewert enthaelt den Beendigungscode und die
    Zeilen, die nach einem Fehler interessant sind.
#>
function Invoke-Logged {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @()
    )

    Write-Log ""
    Write-Log "--- $Command $($Arguments -join ' ') ---"

    $collected = New-Object System.Collections.Generic.List[string]

    & $Command @Arguments 2>&1 | ForEach-Object {
        $line = if ($_ -is [System.Management.Automation.ErrorRecord]) {
            $_.ToString()
        } else {
            [string]$_
        }
        $collected.Add($line)
        Write-Log $line
        Write-Host $line
    }

    $exit = $LASTEXITCODE

    # Die Zeilen heraussuchen, die eine Ursache benennen. electron-builder
    # stellt seiner eigentlichen Meldung ein Kreuzzeichen voran (U+2A2F),
    # alles davor ist Fortschrittsanzeige.
    #
    # Das Zeichen steht hier als ⨯ und nicht als Zeichen selbst:
    # Windows PowerShell liest eine .ps1-Datei ohne BOM als ANSI, und ein
    # Sonderzeichen im Quelltext waere dann ein anderes als gemeint. Die
    # Ausweichschreibweise ist haesslicher, aber sie ueberlebt den Transport.
    # (Der Backslash bleibt in PowerShell stehen - dort schuetzt das
    # Gravis-Zeichen, nicht der Backslash - und erreicht so die Regex.)
    $pattern = "\u2A2F|^\s*Error\b|error [A-Z]+\d|ENOENT|EPERM|EBUSY|EACCES|" +
               "[Cc]annot |[Ff]ailed|FEHLER|not found|Command failed"

    $interesting = $collected | Where-Object { $_ -match $pattern } | Select-Object -Last 12

    return [PSCustomObject]@{
        ExitCode    = $exit
        Lines       = $collected
        Interesting = $interesting
    }
}

Clear-Host
Write-Host ""
Write-Host "  ==========================================================" -ForegroundColor White
Write-Host "    AI-Orb-Setup.exe wird gebaut" -ForegroundColor White
Write-Host "  ==========================================================" -ForegroundColor White
Write-Host "    Projekt: $ProjectRoot" -ForegroundColor DarkGray
Write-Host "    Das dauert beim ersten Mal etwa 15 Minuten." -ForegroundColor DarkGray

# ============================================================================
# 1. Voraussetzungen
# ============================================================================

Write-Step "Voraussetzungen"

if ($env:OS -ne "Windows_NT") {
    Show-Failure "Nur unter Windows" @(
        "Ein Windows-Installationspaket laesst sich nur unter Windows bauen.",
        "Das ist eine Eigenschaft des Formats, keine Einschraenkung von AI-Orb."
    )
    exit 1
}

# Erst nachsehen, ob es node ueberhaupt gibt, und dann erst aufrufen.
#
# Ein Aufruf eines nicht vorhandenen Programms setzt $LASTEXITCODE nicht -
# die Variable behaelt den Wert des letzten wirklich gelaufenen Befehls.
# Wer nur $LASTEXITCODE prueft, bekommt bei fehlendem Node.js unter
# Umstaenden eine 0 zurueck und baut munter weiter, bis es spaeter kracht.
$NodeCommand = Get-Command node -ErrorAction SilentlyContinue

if (-not $NodeCommand) {
    Show-Failure "Node.js fehlt" @(
        "Zum Bauen wird Node.js gebraucht - fuer die fertige Anwendung nicht.",
        "",
        "Lade die LTS-Fassung: https://nodejs.org/",
        "Danach diese Datei erneut doppelklicken.",
        "",
        "Falls Node.js gerade erst installiert wurde: Dieses Fenster",
        "schliessen und neu oeffnen. Ein laufendes Fenster kennt den",
        "neuen Suchpfad noch nicht."
    )
    exit 1
}

$NodeVersion = (& node --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $NodeVersion) {
    Show-Failure "Node.js antwortet nicht" @(
        "Gefunden wurde: $($NodeCommand.Source)",
        "Der Aufruf 'node --version' ist aber fehlgeschlagen.",
        "",
        "Meist hilft eine Neuinstallation von Node.js."
    )
    exit 1
}
Write-Ok "Node.js $NodeVersion"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Show-Failure "npm fehlt" @(
        "Node.js ist da, npm aber nicht. Das ist ungewoehnlich -",
        "normalerweise bringt Node.js npm mit.",
        "",
        "Am ehesten hilft: Node.js LTS von https://nodejs.org/ neu",
        "installieren und dabei die Voreinstellungen uebernehmen."
    )
    exit 1
}

if ($Clean) {
    Write-Inf "Alter Stand wird entfernt (-Clean)"
    foreach ($path in @("dist-installer", "desktop\electron\dist", "runtime")) {
        $full = Join-Path $ProjectRoot $path
        if (Test-Path $full) { Remove-Item -Recurse -Force $full }
    }
}

# ============================================================================
# 2. Node-Pakete
# ============================================================================

Write-Step "Node-Pakete"

$ElectronBuilder = Join-Path $ProjectRoot "node_modules\.bin\electron-builder.cmd"

if (-not (Test-Path $ElectronBuilder)) {
    Write-Inf "Werden installiert (einige Minuten)..."
    $Npm = Invoke-Logged -Command "npm" -Arguments @("install", "--no-audit", "--no-fund")
    if ($Npm.ExitCode -ne 0) {
        $detail = @()
        if ($Npm.Interesting) {
            $detail += "Das hat npm gemeldet:"
            $detail += ""
            foreach ($line in $Npm.Interesting) { $detail += "  $line" }
            $detail += ""
        }
        $detail += "Haeufigste Ursache: keine Internetverbindung."
        Show-Failure "npm install ist fehlgeschlagen" $detail
        exit 1
    }
}
Write-Ok "Vorhanden"

# ============================================================================
# 3. Python-Runtime
# ============================================================================

Write-Step "Python-Runtime"

$RuntimePython = Join-Path $ProjectRoot "runtime\python\python.exe"

if ($SkipRuntime -and (Test-Path $RuntimePython)) {
    Write-Ok "Uebersprungen (-SkipRuntime)"
}
else {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   (Join-Path $ProjectRoot "scripts\prepare-runtime.ps1"))
    if ($SkipVoice) { $arguments += "-SkipVoice" }
    if ($Clean)     { $arguments += "-Force" }

    $Runtime = Invoke-Logged -Command "powershell" -Arguments $arguments
    if ($Runtime.ExitCode -ne 0) {
        Show-Failure "Die Python-Runtime liess sich nicht vorbereiten" @(
            "Die Ursache steht oben.",
            "Ohne Runtime muesste der Benutzer Python selbst installieren -",
            "genau das soll das Installationspaket vermeiden."
        )
        exit 1
    }
}

if (-not (Test-Path $RuntimePython)) {
    Show-Failure "Die Runtime fehlt" @("Erwartet wurde: $RuntimePython")
    exit 1
}
Write-Ok "runtime\python bereit"

# ============================================================================
# 4. Oberflaeche
# ============================================================================

Write-Step "Oberflaeche wird gebaut"

$Compile = Invoke-Logged -Command "npm" -Arguments @("run", "build")
if ($Compile.ExitCode -ne 0) {
    $detail = @()
    if ($Compile.Interesting) {
        $detail += "Das hat der Uebersetzer gemeldet:"
        $detail += ""
        foreach ($line in $Compile.Interesting) { $detail += "  $line" }
    }
    else { $detail += "Die Fehlermeldung steht oben." }
    Show-Failure "Der Build ist fehlgeschlagen" $detail
    exit 1
}

# Gegenprobe: Enthaelt der Build wirklich den aktuellen Code? Ein stiller
# Fehlschlag an dieser Stelle faellt sonst erst dem Benutzer auf.
$Markers = @{
    (Join-Path $ProjectRoot "desktop\electron\dist\renderer\renderer.js") =
        @("reportOrbOffset", "MovementEngine", "uTurbulence")
    (Join-Path $ProjectRoot "desktop\electron\dist\electron\main.js") =
        @("startBackend", "SplashScreen", "moveOrbTo")
}

$Missing = @()
foreach ($file in $Markers.Keys) {
    if (-not (Test-Path $file)) {
        $Missing += (Split-Path $file -Leaf) + " fehlt"
        continue
    }
    $content = Get-Content $file -Raw
    foreach ($marker in $Markers[$file]) {
        if ($content -notmatch [regex]::Escape($marker)) {
            $Missing += (Split-Path $file -Leaf) + ": $marker"
        }
    }
}

if ($Missing.Count -gt 0) {
    Show-Failure "Der Build ist unvollstaendig" @(
        ($Missing -join "; "),
        "",
        "Loesche desktop\electron\dist und baue erneut."
    )
    exit 1
}
Write-Ok "Build geprueft"

# ============================================================================
# 5. Installationspaket
# ============================================================================

Write-Step "Installationspaket wird geschnuert"
Write-Inf "Das ist der laengste Schritt."

$Builder = Invoke-Logged -Command $ElectronBuilder -Arguments @("--win", "--publish", "never")
if ($Builder.ExitCode -ne 0) {
    $detail = @()
    if ($Builder.Interesting) {
        $detail += "Das hat electron-builder gemeldet:"
        $detail += ""
        foreach ($line in $Builder.Interesting) { $detail += "  $line" }
        $detail += ""
    }
    $detail += "Haeufigste Ursachen:"
    $detail += "  - AI-Orb laeuft noch (beenden und erneut versuchen)"
    $detail += "  - ein Virenschutz blockiert das Schreiben in dist-installer"
    $detail += "  - kein Platz auf der Festplatte (etwa 2 GB werden gebraucht)"
    $detail += "  - eine Datei aus extraResources fehlt (siehe Protokoll)"

    Show-Failure "electron-builder ist fehlgeschlagen" $detail
    exit 1
}

# ============================================================================
# 6. Ergebnis
# ============================================================================

Write-Step "Ergebnis"

$Setup = Join-Path $ProjectRoot "dist-installer\AI-Orb-Setup.exe"

if (-not (Test-Path $Setup)) {
    $found = Get-ChildItem (Join-Path $ProjectRoot "dist-installer") -Filter "*.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { $Setup = $found.FullName }
}

if (-not (Test-Path $Setup)) {
    Show-Failure "Es wurde keine Installationsdatei erzeugt" @(
        "Erwartet wurde: dist-installer\AI-Orb-Setup.exe"
    )
    exit 1
}

$SizeMb = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
Write-Ok "AI-Orb-Setup.exe ($SizeMb MB)"

Write-Host ""
Write-Host "  ==========================================================" -ForegroundColor Green
Write-Host "    Fertig" -ForegroundColor Green
Write-Host "  ==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "    $Setup" -ForegroundColor White
Write-Host ""
Write-Host "    Doppelklick darauf installiert AI-Orb. Danach steht es im"
Write-Host "    Startmenue unter 'AI-Orb'. Ein Klick, und der Orb erscheint."
Write-Host ""

# Den Ordner zeigen - dann muss niemand danach suchen.
Start-Process explorer.exe -ArgumentList "/select,`"$Setup`""

exit 0
