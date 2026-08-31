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
Write-Host "=== 1) Ensure decision layers ==="
& ".\scripts\build_decision_layers_v0_1.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build evidence priority engine ==="
& $Py ".\backend\verdict\evidence_priority_engine_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Check files ==="

$Files = @(
    ".\data\verdict\$MatchId\evidence_priority_${Player}_v0_1.json",
    ".\data\verdict\$MatchId\evidence_priority_${Player}_v0_1.csv"
)

foreach ($File in $Files) {
    if (Test-Path $File) {
        Get-Item $File | Select-Object FullName, Length, LastWriteTime
    } else {
        Write-Host "MISSING: $File"
    }
}

Write-Host ""
Write-Host "=== EVIDENCE PRIORITY LAYER COMPLETE ==="
