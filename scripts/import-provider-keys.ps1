param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [string]$EnvPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $EnvPath) {
    $EnvPath = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
}

if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw "Die Schluesseldatei wurde nicht gefunden: $SourcePath"
}

$labelToVariable = @{
    "openrouter" = "OPENROUTER_API_KEY"
    "grok"       = "XAI_API_KEY"
    "xai"        = "XAI_API_KEY"
    "openapi"    = "OPENAI_API_KEY"
    "openai"     = "OPENAI_API_KEY"
}

$lines = [System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $SourcePath))
$found = [ordered]@{}

for ($index = 0; $index -lt $lines.Length; $index++) {
    $label = $lines[$index].Trim().ToLowerInvariant().TrimEnd(':')
    if (-not $labelToVariable.ContainsKey($label)) {
        continue
    }

    for ($valueIndex = $index + 1; $valueIndex -lt $lines.Length; $valueIndex++) {
        $candidate = $lines[$valueIndex].Trim()
        if (-not $candidate) {
            continue
        }
        $candidateLabel = $candidate.ToLowerInvariant().TrimEnd(':')
        if ($labelToVariable.ContainsKey($candidateLabel)) {
            break
        }
        if ($candidate -match '^[A-Za-z_][A-Za-z0-9_]*=') {
            break
        }
        $found[$labelToVariable[$label]] = $candidate
        break
    }
}

$required = @("OPENROUTER_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY")
$missing = @($required | Where-Object { -not $found.Contains($_) })
if ($missing.Count -gt 0) {
    throw "Nicht alle Provider-Eintraege wurden gefunden: $($missing -join ', ')"
}

$envLines = [System.Collections.Generic.List[string]]::new()
if (Test-Path -LiteralPath $EnvPath) {
    $envLines.AddRange(
        [string[]][System.IO.File]::ReadAllLines((Resolve-Path -LiteralPath $EnvPath))
    )
}

foreach ($variable in $required) {
    $replacement = "$variable=$($found[$variable])"
    $replaced = $false
    for ($index = 0; $index -lt $envLines.Count; $index++) {
        if ($envLines[$index] -match "^\s*$([regex]::Escape($variable))\s*=") {
            $envLines[$index] = $replacement
            $replaced = $true
            break
        }
    }
    if (-not $replaced) {
        $envLines.Add($replacement)
    }
}

[System.IO.File]::WriteAllLines(
    $EnvPath,
    $envLines,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Importiert: $($required -join ', '). Schluesselwerte wurden nicht ausgegeben."
