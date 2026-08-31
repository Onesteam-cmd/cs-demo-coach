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
Write-Host "=== 1) Ensure match package v0.7 ==="
& ".\scripts\build_match_package_v0_7.ps1" -MatchId $MatchId -Player $Player

Write-Host ""
Write-Host "=== 2) Build coach brief ==="
& $Py ".\backend\verdict\coach_brief_builder_v0_1.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 3) Build match package v0.8 ==="
& $Py ".\backend\package\match_package_builder_v0_8.py" `
    --match-id $MatchId `
    --player $Player `
    --data-dir "data"

Write-Host ""
Write-Host "=== 4) Check files ==="
$Files = @(
    ".\data\verdict\$MatchId\coach_brief_${Player}_v0_1.json",
    ".\data\verdict\$MatchId\coach_brief_${Player}_v0_1.csv",
    ".\data\package\$MatchId\match_package_${Player}_v0_8.json",
    ".\data\package\$MatchId\match_package_index_${Player}_v0_8.csv"
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
Write-Host "=== COACH BRIEF / MATCH PACKAGE v0.8 COMPLETE ==="
