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
Write-Host "=== 1) Build canonical mechanics events ==="
& $Py ".\backend\layers\canonical_mechanics_events_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 2) Build mechanics problem analyzer ==="
& $Py ".\backend\analyzers\mechanics_problem_analyzer_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check files ==="

$Files = @(
    ".\data\layers\$MatchId\canonical_mechanics_events_${Player}_v0_1.json",
    ".\data\layers\$MatchId\canonical_mechanics_events_${Player}_v0_1.csv",
    ".\data\analysis\$MatchId\mechanics_problem_${Player}_v0_1.json",
    ".\data\analysis\$MatchId\mechanics_problem_${Player}_v0_1.csv"
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
Write-Host "=== MECHANICS LAYERS v0.1 COMPLETE ==="
