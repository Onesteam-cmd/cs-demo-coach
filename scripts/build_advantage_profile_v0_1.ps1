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
Write-Host "=== 1) Ensure match package v0.5 ==="
& ".\scripts\build_match_package_v0_5.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build canonical round state ==="
& $Py ".\backend\layers\canonical_round_state_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build advantage profile analyzer ==="
& $Py ".\backend\analyzers\advantage_profile_analyzer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Check files ==="
$Files = @(
    ".\data\layers\$MatchId\canonical_round_state_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_round_state_${Player}_v0_1.csv",
    ".\data\analysis\$MatchId\advantage_profile_${Player}_v0_1.json",
    ".\data\analysis\$MatchId\advantage_profile_${Player}_v0_1.csv"
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
Write-Host "=== ADVANTAGE PROFILE LAYER COMPLETE ==="
