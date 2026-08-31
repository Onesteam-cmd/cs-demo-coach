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
Write-Host "=== 1) Ensure advantage profile ==="
& ".\scripts\build_advantage_profile_v0_1.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build match package v0.6 ==="
& $Py ".\backend\package\match_package_builder_v0_6.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check package files ==="
$Files = @(
    ".\data\package\$MatchId\match_package_${Player}_v0_6.json",
    ".\data\package\$MatchId\match_package_index_${Player}_v0_6.csv",
    ".\data\analysis\$MatchId\advantage_profile_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_round_state_${Player}_v0_1.json"
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
Write-Host "=== MATCH PACKAGE v0.6 LAYER COMPLETE ==="
