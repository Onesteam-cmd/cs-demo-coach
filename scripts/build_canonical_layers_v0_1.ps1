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
Write-Host "=== 1) Build canonical round timeline ==="
& $Py ".\backend\layers\canonical_round_timeline_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 2) Build canonical trade layer ==="
& $Py ".\backend\layers\canonical_trade_layer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build canonical utility timeline ==="
& $Py ".\backend\layers\canonical_utility_timeline_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Check canonical layer files ==="

$Files = @(
    ".\data\layers\$MatchId\canonical_round_timeline_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_round_timeline_${Player}_v0_1.csv",
    ".\data\layers\$MatchId\canonical_trade_layer_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_trade_layer_${Player}_v0_1.csv",
    ".\data\layers\$MatchId\canonical_utility_timeline_v0_1.json",
    ".\data\layers\$MatchId\canonical_utility_timeline_v0_1.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
    }
}

Write-Host ""
Write-Host "=== CANONICAL LAYERS v0.1 COMPLETE ==="
Write-Host "Layer folder:"
Write-Host "  .\data\layers\$MatchId"
