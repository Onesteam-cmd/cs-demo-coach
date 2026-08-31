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
Write-Host "=== 1) Ensure coach priority v0.3 ==="
& ".\scripts\build_coach_priority_v0_3.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build coach action plan v0.2 ==="
& $Py ".\backend\verdict\coach_action_plan_v0_2.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check files ==="
$Files = @(
    ".\data\verdict\$MatchId\coach_action_plan_${Player}_v0_2.json",
    ".\data\verdict\$MatchId\coach_action_plan_${Player}_v0_2.csv",
    ".\data\reviews\$MatchId\coach_round_review_queue_${Player}_v0_2.csv"
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
Write-Host "=== COACH ACTION PLAN v0.2 COMPLETE ==="
