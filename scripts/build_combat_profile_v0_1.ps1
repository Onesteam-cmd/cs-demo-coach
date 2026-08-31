param(
    [string]$MatchId = "example_match",
    [string]$Player = "Player"
)

$ErrorActionPreference = "Stop"

Set-Location "."
pwd

$PythonCandidates = @(
    ".\.venv\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    "python"
)

$Py = $null
foreach ($Candidate in $PythonCandidates) {
    if ($Candidate -eq "python") {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) {
            $Py = "python"
            break
        }
    } elseif (Test-Path $Candidate) {
        $Py = $Candidate
        break
    }
}

if (-not $Py) {
    throw "Python не найден. Запусти из того же окружения, где работает analyze_demo.ps1."
}

Write-Host ""
Write-Host "=== 1) Ensure canonical round layer ==="
& ".\scripts\build_canonical_layers_v0_1.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build canonical combat events ==="
& $Py ".\backend\layers\canonical_combat_events_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build combat profile analyzer ==="
& $Py ".\backend\analyzers\combat_profile_analyzer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Check files ==="
$Files = @(
    ".\data\layers\$MatchId\canonical_combat_events_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_combat_kills_${Player}_v0_1.csv",
    ".\data\layers\$MatchId\canonical_combat_damages_${Player}_v0_1.csv",
    ".\data\analysis\$MatchId\combat_profile_${Player}_v0_1.json",
    ".\data\analysis\$MatchId\combat_profile_rounds_${Player}_v0_1.csv",
    ".\data\analysis\$MatchId\combat_profile_weapons_${Player}_v0_1.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
        throw "Missing output: $File"
    }
}

Write-Host ""
Write-Host "=== COMBAT PROFILE LAYER COMPLETE ==="
