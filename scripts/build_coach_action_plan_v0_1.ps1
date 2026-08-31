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
Write-Host "=== 1) Ensure coach priority v0.2 ==="
& ".\scripts\build_coach_priority_v0_2.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build coach action plan v0.1 ==="
& $Py ".\backend\verdict\coach_action_plan_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check files ==="

$Files = @(
    ".\data\verdict\$MatchId\coach_action_plan_${Player}_v0_1.json",
    ".\data\verdict\$MatchId\coach_action_plan_${Player}_v0_1.csv",
    ".\data\reviews\$MatchId\coach_round_review_queue_${Player}_v0_1.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
    }
}

Write-Host ""
Write-Host "=== COACH ACTION PLAN LAYER COMPLETE ==="
